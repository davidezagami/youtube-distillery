#!/usr/bin/env python3
"""Chunked analysis of summaries via Claude.

Splits summaries.md into batches, sends each batch with the same prompt,
and concatenates the responses.

Usage:
    python analyze.py andylacivita/ --prompt-file find_outliers.txt
    python analyze.py andylacivita/ --prompt-file categorize.txt --batch-size 15 -o results.md
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import anthropic


def find_latest_summaries(input_dir: Path) -> Path:
    """Find the highest-versioned summaries file, falling back to summaries.md."""
    base = input_dir / "summaries.md"
    latest = base
    version = 2
    while (candidate := input_dir / f"summaries_v{version}.md").exists():
        latest = candidate
        version += 1
    if not latest.exists():
        return base  # let caller handle the missing-file error
    return latest


def parse_sections(text: str) -> list[str]:
    """Split summaries.md on '\\n---\\n' separator, dropping empty sections."""
    parts = text.split("\n---\n")
    return [s.strip() for s in parts if s.strip()]


def batch_sections(sections: list[str], batch_size: int) -> list[str]:
    """Group sections into batches, rejoining each with the original separator."""
    batches = []
    for i in range(0, len(sections), batch_size):
        chunk = sections[i : i + batch_size]
        batches.append("\n\n---\n\n".join(chunk))
    return batches


async def analyze_one(
    client: anthropic.AsyncAnthropic,
    model: str,
    prompt: str,
    batch: str,
    semaphore: asyncio.Semaphore,
) -> str:
    """Send one batch to Claude and return the response text."""
    max_retries = 5
    for attempt in range(max_retries):
        async with semaphore:
            try:
                response = await client.messages.create(
                    model=model,
                    max_tokens=4096,
                    messages=[
                        {
                            "role": "user",
                            "content": f"{prompt}\n\n{batch}",
                        }
                    ],
                )
                return response.content[0].text
            except anthropic.RateLimitError:
                if attempt == max_retries - 1:
                    raise
                wait = 2 ** attempt * 10  # 10s, 20s, 40s, 80s, 160s
                print(f"  Rate limited, retrying in {wait}s...")
                await asyncio.sleep(wait)


async def analyze_all(
    batches: list[str],
    client: anthropic.AsyncAnthropic,
    model: str,
    prompt: str,
    concurrency: int,
) -> list[str]:
    """Process all batches concurrently, returning responses in order."""
    semaphore = asyncio.Semaphore(concurrency)
    total = len(batches)
    results: list[str | None] = [None] * total

    async def process(idx: int, batch: str) -> None:
        results[idx] = await analyze_one(client, model, prompt, batch, semaphore)
        print(f"  [{idx + 1}/{total}] Batch done")

    tasks = [process(i, b) for i, b in enumerate(batches)]
    await asyncio.gather(*tasks)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a chunked analysis over summaries.md using Claude."
    )
    parser.add_argument("input_dir", help="Folder containing summaries.md")
    parser.add_argument("--prompt-file", required=True,
                        help="Path to a text file with the analysis prompt")
    parser.add_argument("--batch-size", type=int, default=20,
                        help="Max summaries per API request (default: 20)")
    parser.add_argument("-o", "--output", default=None,
                        help="Output file (default: <input_dir>/analysis.md)")
    parser.add_argument("--anthropic-key",
                        help="Anthropic API key (or ANTHROPIC_API_KEY env)")
    parser.add_argument("--model", default=None,
                        help="Anthropic model (or ANTHROPIC_MODEL env)")
    parser.add_argument("--concurrency", type=int, default=5,
                        help="Max parallel API calls (default: 5)")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    summaries_path = find_latest_summaries(input_dir)
    if not summaries_path.exists():
        print(f"Error: no summaries.md found in {input_dir}")
        return 1
    print(f"Using {summaries_path.name}")

    prompt_path = Path(args.prompt_file)
    if not prompt_path.exists():
        print(f"Error: prompt file not found: {prompt_path}")
        return 1

    api_key = args.anthropic_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: provide an Anthropic API key via --anthropic-key or ANTHROPIC_API_KEY env var")
        return 1

    model = args.model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    output_path = Path(args.output) if args.output else input_dir / "analysis.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    text = summaries_path.read_text(encoding="utf-8")
    sections = parse_sections(text)

    if not sections:
        print("No summary sections found in summaries.md.")
        return 0

    batches = batch_sections(sections, args.batch_size)
    print(f"Analyzing {len(sections)} summaries in {len(batches)} batches "
          f"with {model} (concurrency={args.concurrency})...\n")

    client = anthropic.AsyncAnthropic(api_key=api_key)
    results = asyncio.run(
        analyze_all(batches, client, model, prompt, args.concurrency)
    )

    output_path.write_text("\n\n---\n\n".join(results) + "\n", encoding="utf-8")
    print(f"\nDone. Results written to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
