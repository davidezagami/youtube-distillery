"""Shared local LLM provider helpers for pipeline scripts."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


DEFAULT_CODEX_MODEL = "gpt-5.3-codex"
CODEX_REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
CODEX_VERBOSITIES = ("low", "medium", "high")


def resolve_codex_model(cli_model: str | None, legacy_env: str | None = None) -> str:
    """Resolve the Codex model from CLI, shared env, optional legacy env, or default."""
    return (
        cli_model
        or os.getenv("CODEX_MODEL")
        or (os.getenv(legacy_env) if legacy_env else None)
        or DEFAULT_CODEX_MODEL
    )


def add_codex_arguments(parser: argparse.ArgumentParser) -> None:
    """Add shared codex-exec provider flags to an argparse parser."""
    parser.add_argument(
        "--codex-command",
        default=os.getenv("CODEX_COMMAND", "codex"),
        help="codex executable to run for --provider codex-exec (default: codex)",
    )
    parser.add_argument(
        "--codex-reasoning-effort",
        choices=CODEX_REASONING_EFFORTS,
        default=os.getenv("CODEX_REASONING_EFFORT", "low"),
        help="codex exec model_reasoning_effort override (default: low)",
    )
    parser.add_argument(
        "--codex-verbosity",
        choices=CODEX_VERBOSITIES,
        default=os.getenv("CODEX_VERBOSITY", "low"),
        help="codex exec model_verbosity override (default: low)",
    )
    parser.add_argument(
        "--codex-timeout",
        type=int,
        default=int(os.getenv("CODEX_TIMEOUT", "900")),
        help="Seconds to wait for each codex exec call (default: 900)",
    )


@dataclass
class CodexExecRunner:
    """Run local non-interactive codex exec calls and return the final message."""

    command: str
    model: str
    reasoning_effort: str
    verbosity: str
    timeout: int
    output_prefix: str = "codex-exec-"

    def __post_init__(self) -> None:
        if shutil.which(self.command) is None:
            raise FileNotFoundError(f"codex command not found: {self.command}")

    def _command(self, output_path: Path) -> list[str]:
        return [
            self.command,
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "-m",
            self.model,
            "-c",
            f'model_reasoning_effort="{self.reasoning_effort}"',
            "-c",
            'model_reasoning_summary="none"',
            "-c",
            f'model_verbosity="{self.verbosity}"',
            "-c",
            'web_search="disabled"',
            "-c",
            "features.shell_tool=false",
            "-c",
            "hide_agent_reasoning=true",
            "--output-last-message",
            str(output_path),
            "-",
        ]

    def _make_output_path(self) -> Path:
        output_file = tempfile.NamedTemporaryFile(
            prefix=self.output_prefix, suffix=".md", delete=False
        )
        output_path = Path(output_file.name)
        output_file.close()
        return output_path

    @staticmethod
    def _failure_details(stdout: bytes, stderr: bytes) -> str:
        details = "\n".join(
            part
            for part in (
                stderr.decode("utf-8", errors="replace").strip(),
                stdout.decode("utf-8", errors="replace").strip(),
            )
            if part
        )
        if len(details) > 4000:
            details = details[-4000:]
        return details

    def _read_output(self, output_path: Path, label: str) -> str:
        output = output_path.read_text(encoding="utf-8").strip()
        if not output:
            raise RuntimeError(f"codex exec produced empty output for: {label}")
        return output

    def run(self, prompt: str, label: str = "request") -> str:
        """Run one synchronous codex exec call."""
        output_path = self._make_output_path()
        try:
            try:
                completed = subprocess.run(
                    self._command(output_path),
                    input=prompt.encode("utf-8"),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=self.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"codex exec timed out after {self.timeout}s for: {label}"
                ) from exc

            if completed.returncode != 0:
                details = self._failure_details(completed.stdout, completed.stderr)
                raise RuntimeError(
                    f"codex exec failed with exit code {completed.returncode} for: {label}\n{details}"
                )

            return self._read_output(output_path, label)
        finally:
            output_path.unlink(missing_ok=True)

    async def arun(self, prompt: str, label: str = "request") -> str:
        """Run one asynchronous codex exec call."""
        output_path = self._make_output_path()
        try:
            process = await asyncio.create_subprocess_exec(
                *self._command(output_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(prompt.encode("utf-8")),
                    timeout=self.timeout,
                )
            except asyncio.TimeoutError as exc:
                process.kill()
                await process.communicate()
                raise RuntimeError(
                    f"codex exec timed out after {self.timeout}s for: {label}"
                ) from exc

            if process.returncode != 0:
                details = self._failure_details(stdout, stderr)
                raise RuntimeError(
                    f"codex exec failed with exit code {process.returncode} for: {label}\n{details}"
                )

            return self._read_output(output_path, label)
        finally:
            output_path.unlink(missing_ok=True)
