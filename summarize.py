#!/usr/bin/env python3
"""Batch transcript summarizer using Claude.

Reads transcripts produced by channeltool.py and generates a single markdown
file with a Claude-generated summary for each video.  Progress is saved after
each video so interrupted runs can be resumed.

Usage:
    python summarize.py andylacivita/
    python summarize.py andylacivita/ -o summaries.md --concurrency 10
    python summarize.py andylacivita/ --prompt-file my_prompt.txt
"""

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

import math

import anthropic

DEFAULT_PROMPT = (
    "Summarize the following video transcript concisely. "
    "Focus on the key points, actionable advice, and main takeaways. "
    "Use bullet points where appropriate. Keep the summary to 1-2 paragraphs."
)


def load_prompt(path: str | None) -> str:
    """Read summarization prompt from a file, or return the built-in default."""
    if path is None:
        return DEFAULT_PROMPT
    return Path(path).read_text(encoding="utf-8").strip()


def compute_bullet_count(duration_seconds: int) -> int:
    """Compute bullet point count from video duration.

    Roughly one bullet per 1.5 minutes, minimum 10.
    """
    return max(10, math.ceil(duration_seconds / 90))


def render_prompt(template: str, video: dict) -> str:
    """Render a prompt template with per-video parameters.

    Supports {bullet_count} placeholder. If no placeholders are present,
    the template is returned as-is.
    """
    bullet_count = compute_bullet_count(video.get("duration", 600))
    try:
        return template.format(bullet_count=bullet_count)
    except KeyError:
        return template


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from the markdown body.

    Returns (metadata_dict, body). If no frontmatter is found the metadata
    dict is empty and body is the full text.
    """
    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    raw = text[4:end]  # between opening --- and closing ---
    meta: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"')

    body = text[end + 4:].lstrip("\n")
    return meta, body


def parse_completed_ids(output_path: Path) -> set[str]:
    """Read an existing summaries file and return video IDs already present."""
    if not output_path.exists():
        return set()
    text = output_path.read_text(encoding="utf-8")
    return set(re.findall(r"\*\*URL:\*\* https://www\.youtube\.com/watch\?v=([A-Za-z0-9_-]+)", text))


def format_one(video: dict, summary: str) -> str:
    """Format a single video section."""
    return (
        f"# {video['title']}\n"
        f"**Date:** {video['upload_date']} | "
        f"**URL:** {video['url']}\n\n"
        f"{summary}\n\n"
        f"---\n\n"
    )


async def summarize_one(
    client: anthropic.AsyncAnthropic,
    model: str,
    prompt: str,
    title: str,
    body: str,
    semaphore: asyncio.Semaphore,
) -> str:
    """Send a single transcript to Claude and return the summary text."""
    max_retries = 5
    for attempt in range(max_retries):
        async with semaphore:
            try:
                response = await client.messages.create(
                    model=model,
                    max_tokens=2048,
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                f"{prompt}\n\n"
                                f"Video title: {title}\n\n"
                                f"Transcript:\n{body}"
                            ),
                        }
                    ],
                )
                return response.content[0].text
            except anthropic.RateLimitError:
                if attempt == max_retries - 1:
                    raise
                wait = 2 ** attempt * 10  # 10s, 20s, 40s, 80s, 160s
                print(f"    Rate limited, retrying in {wait}s...")
                await asyncio.sleep(wait)


async def summarize_all(
    videos: list[dict],
    input_dir: Path,
    output_path: Path,
    client: anthropic.AsyncAnthropic,
    model: str,
    prompt_template: str,
    concurrency: int,
) -> int:
    """Summarize all videos concurrently, appending each result to output_path.

    Returns the number of summaries written.
    """
    semaphore = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()
    total = len(videos)
    completed = 0

    async def process(video: dict) -> None:
        nonlocal completed
        transcript_path = input_dir / video["transcript_file"]
        text = transcript_path.read_text(encoding="utf-8")
        _meta, body = parse_frontmatter(text)
        prompt = render_prompt(prompt_template, video)
        summary = await summarize_one(client, model, prompt, video["title"], body, semaphore)

        async with write_lock:
            with open(output_path, "a", encoding="utf-8") as f:
                f.write(format_one(video, summary))
            completed += 1
            print(f"  [{completed}/{total}] {video['title']}")

    tasks = [process(v) for v in videos]
    await asyncio.gather(*tasks)
    return completed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize video transcripts using Claude."
    )
    parser.add_argument("input_dir", help="Folder containing index.json and transcripts/")
    parser.add_argument("-o", "--output", default=None,
                        help="Output markdown file (default: <input_dir>/summaries.md)")
    parser.add_argument("--prompt-file", default=None,
                        help="Path to a text file with the summarization prompt")
    parser.add_argument("--anthropic-key",
                        help="Anthropic API key (or ANTHROPIC_API_KEY env)")
    parser.add_argument("--model", default=None,
                        help="Anthropic model (or ANTHROPIC_MODEL env)")
    parser.add_argument("--concurrency", type=int, default=5,
                        help="Max parallel API calls (default: 5)")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    index_path = input_dir / "index.json"
    if not index_path.exists():
        print(f"Error: no index.json found in {input_dir}")
        return 1

    api_key = args.anthropic_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: provide an Anthropic API key via --anthropic-key or ANTHROPIC_API_KEY env var")
        return 1

    model = args.model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
    prompt = load_prompt(args.prompt_file)
    output_path = Path(args.output) if args.output else input_dir / "summaries.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    index = json.loads(index_path.read_text(encoding="utf-8"))
    videos = [
        v for v in index.get("videos", [])
        if v.get("status") == "transcribed" and v.get("transcript_file")
    ]

    if not videos:
        print("No transcribed videos found in the index.")
        return 0

    # Sort newest first
    videos.sort(key=lambda v: v.get("upload_date", ""), reverse=True)

    # Skip already-summarized videos
    done_ids = parse_completed_ids(output_path)
    if done_ids:
        videos = [v for v in videos if v["id"] not in done_ids]
        print(f"Resuming: {len(done_ids)} already done, {len(videos)} remaining.")

    if not videos:
        print("All videos already summarized.")
        return 0

    print(f"Summarizing {len(videos)} transcripts with {model} (concurrency={args.concurrency})...\n")

    client = anthropic.AsyncAnthropic(api_key=api_key)
    written = asyncio.run(
        summarize_all(videos, input_dir, output_path, client, model, prompt, args.concurrency)
    )

    print(f"\nDone. {written} summaries appended to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
