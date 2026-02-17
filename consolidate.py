#!/usr/bin/env python3
"""Consolidate merged category files by removing redundant content across video summaries.

Uses chunked consolidation for large files, single-pass for small ones.

Usage:
    python consolidate.py output/_merged/salary_negotiation_and_compensation.md
    python consolidate.py output/_merged/                     # all categories
    python consolidate.py output/_merged/ -o output/_consolidated/
    python consolidate.py output/_merged/career_development_and_professional_growth.md --chunk-tokens 15000
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import functools

import anthropic

# Force unbuffered prints
print = functools.partial(print, flush=True)

DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")
DEFAULT_CHUNK_TOKENS = 20_000  # approx tokens per chunk
DEFAULT_MAX_TOKENS = 32_768
CHARS_PER_TOKEN = 4  # rough estimate
SINGLE_PASS_THRESHOLD = 30_000  # tokens; below this, no chunking needed


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def split_into_summaries(text: str) -> list[str]:
    """Split a merged category file into individual video summaries.

    Each summary starts with a '---' separator followed by '## Source: channel'.
    The first section (the category header) is discarded.
    """
    # Split on any horizontal rule (--- or longer dashes)
    parts = re.split(r"\n-{36}\n", text)
    summaries = []
    for part in parts:
        part = part.strip()
        if not part or part.startswith("# ") and "\n" not in part:
            # Category header line only
            continue
        if part.startswith("# ") and "## Source:" in part:
            # Category header + first source in same block
            idx = part.index("## Source:")
            part = part[idx:]
        summaries.append(part)
    return summaries


def chunk_summaries(summaries: list[str], chunk_tokens: int) -> list[list[str]]:
    """Group summaries into balanced chunks that fit under the token limit.

    Instead of greedy bin-packing (which leaves a small runt last chunk),
    compute the ideal number of chunks and distribute evenly.
    """
    import math

    total_tokens = sum(estimate_tokens(s) for s in summaries)
    num_chunks = math.ceil(total_tokens / chunk_tokens)
    if num_chunks < 1:
        num_chunks = 1
    target = total_tokens / num_chunks

    chunks = []
    current_chunk = []
    current_tokens = 0

    for summary in summaries:
        summary_tokens = estimate_tokens(summary)
        # Always put at least one summary per chunk
        if current_chunk and current_tokens + summary_tokens > target:
            chunks.append(current_chunk)
            current_chunk = []
            current_tokens = 0
        current_chunk.append(summary)
        current_tokens += summary_tokens

    if current_chunk:
        # Fold tiny remainders into the last chunk instead of creating a runt
        if chunks and current_tokens < target * 0.3:
            chunks[-1].extend(current_chunk)
        else:
            chunks.append(current_chunk)
    return chunks


CONSOLIDATE_PROMPT = """\
You are given summaries from multiple YouTube videos about: {category}

These summaries contain bulleted/numbered advice, tactics, and insights from different creators.
There is significant overlap — many videos cover the same advice in different words.

Your task:
1. Consolidate into a single, well-organized reference document.
2. REMOVE redundant advice that appears across multiple videos. If 5 videos all say
   "research the company before your interview," that becomes ONE bullet, not five.
3. PRESERVE every unique insight, specific script/phrase, concrete example, or distinctive
   perspective — even if only one video mentions it.
4. When creators give CONFLICTING advice, note the disagreement briefly
   (e.g., "Some advise X while others recommend Y because Z").
5. Organize by sub-topic with clear headers.
6. Use concise bullet points. No fluff, no preamble, no meta-commentary.

Output ONLY the consolidated reference document in markdown."""

MERGE_PROMPT = """\
You are given {n} separately consolidated reference sections about: {category}

These sections were produced independently and contain some overlap with each other.

Your task:
1. Merge into a single, final reference document.
2. Remove any remaining redundancies across sections.
3. Preserve all unique content.
4. Organize logically with clear sub-topic headers.
5. Use concise bullet points. No fluff, no preamble, no meta-commentary.

Output ONLY the final consolidated reference document in markdown."""


def call_llm(prompt: str, content: str, api_key: str | None, model: str, max_tokens: int = DEFAULT_MAX_TOKENS, retries: int = 3) -> str:
    """Send a consolidation request to Claude using streaming, with retries."""
    client = anthropic.Anthropic(api_key=api_key)
    for attempt in range(1, retries + 1):
        try:
            result_parts = []
            stop_reason = None
            with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "user", "content": f"{prompt}\n\n---\n\n{content}"},
                ],
            ) as stream:
                for text in stream.text_stream:
                    result_parts.append(text)
                stop_reason = stream.get_final_message().stop_reason
            if stop_reason == "max_tokens":
                print(f"\n  ERROR: Output truncated (hit {max_tokens} token limit). "
                      f"Re-run with --max-tokens {max_tokens * 2} to get full output.")
                sys.exit(1)
            return "".join(result_parts).strip()
        except Exception as e:
            if attempt < retries:
                wait = attempt * 5
                print(f"\n  WARN: API error ({e}), retrying in {wait}s (attempt {attempt}/{retries})...", end=" ", flush=True)
                time.sleep(wait)
            else:
                print(f"\n  ERROR: API failed after {retries} attempts: {e}")
                raise


def consolidate_file(
    filepath: Path,
    output_dir: Path,
    api_key: str | None,
    model: str,
    chunk_tokens: int,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    dry_run: bool = False,
) -> Path | None:
    """Consolidate a single merged category file."""
    text = filepath.read_text()
    category_name = filepath.stem.replace("_", " ").title()

    summaries = split_into_summaries(text)
    total_tokens = estimate_tokens(text)

    print(f"\n{'='*60}")
    print(f"Category: {category_name}")
    print(f"  {len(summaries)} video summaries, ~{total_tokens:,} tokens")

    if not summaries:
        print("  No summaries found, skipping.")
        return None

    output_path = output_dir / filepath.name

    if total_tokens <= SINGLE_PASS_THRESHOLD:
        # Single pass
        print("  Strategy: single pass (fits in context)")
        if dry_run:
            print("  [DRY RUN] Would consolidate in one call.")
            return None

        prompt = CONSOLIDATE_PROMPT.format(category=category_name)
        result = call_llm(prompt, text, api_key, model, max_tokens)
        result_tokens = estimate_tokens(result)
        print(f"  Result: ~{result_tokens:,} tokens ({result_tokens/total_tokens*100:.0f}% of original)")

    else:
        # Chunked consolidation
        chunks = chunk_summaries(summaries, chunk_tokens)
        print(f"  Strategy: chunked ({len(chunks)} chunks of ~{chunk_tokens:,} tokens)")

        if dry_run:
            for i, chunk in enumerate(chunks):
                ct = sum(estimate_tokens(s) for s in chunk)
                print(f"    Chunk {i+1}: {len(chunk)} summaries, ~{ct:,} tokens")
            print(f"  [DRY RUN] Would consolidate in {len(chunks)} + 1 calls.")
            return None

        # Phase 1: consolidate each chunk
        chunk_results = []
        for i, chunk in enumerate(chunks):
            chunk_text = "\n\n---\n\n".join(chunk)
            ct = estimate_tokens(chunk_text)
            print(f"  Chunk {i+1}/{len(chunks)}: {len(chunk)} summaries, ~{ct:,} tokens ...", end=" ", flush=True)

            prompt = CONSOLIDATE_PROMPT.format(category=category_name)
            result = call_llm(prompt, chunk_text, api_key, model, max_tokens)
            rt = estimate_tokens(result)
            print(f"→ ~{rt:,} tokens")
            chunk_results.append(result)
            time.sleep(1)  # rate limit courtesy

        # Phase 2: merge chunk results
        merge_sections = chunk_results
        merged_input = "\n\n---\n\n".join(
            f"## Section {i+1}\n\n{r}" for i, r in enumerate(merge_sections)
        )
        merge_tokens = estimate_tokens(merged_input)
        print(f"  Final merge: {len(merge_sections)} sections, ~{merge_tokens:,} tokens ...", end=" ", flush=True)

        if merge_tokens > SINGLE_PASS_THRESHOLD * 2:
            # Chunk results are still too big — do another round
            print(f"\n  WARNING: Merge input is large (~{merge_tokens:,} tokens). Doing recursive merge...")
            sub_chunks = chunk_summaries(chunk_results, chunk_tokens)
            sub_results = []
            for i, sub in enumerate(sub_chunks):
                sub_text = "\n\n---\n\n".join(f"## Section {j+1}\n\n{s}" for j, s in enumerate(sub))
                st = estimate_tokens(sub_text)
                print(f"    Sub-merge {i+1}/{len(sub_chunks)}: ~{st:,} tokens ...", end=" ", flush=True)
                prompt = MERGE_PROMPT.format(n=len(sub), category=category_name)
                r = call_llm(prompt, sub_text, api_key, model, max_tokens)
                rt = estimate_tokens(r)
                print(f"→ ~{rt:,} tokens")
                sub_results.append(r)
                time.sleep(1)

            merge_sections = sub_results
            merged_input = "\n\n---\n\n".join(
                f"## Section {i+1}\n\n{r}" for i, r in enumerate(merge_sections)
            )
            merge_tokens = estimate_tokens(merged_input)
            print(f"  Final merge (after recursive): ~{merge_tokens:,} tokens ...", end=" ", flush=True)

        prompt = MERGE_PROMPT.format(n=len(merge_sections), category=category_name)
        result = call_llm(prompt, merged_input, api_key, model, max_tokens)
        result_tokens = estimate_tokens(result)
        print(f"→ ~{result_tokens:,} tokens ({result_tokens/total_tokens*100:.0f}% of original)")

    # Write output
    output_dir.mkdir(parents=True, exist_ok=True)
    # Add header with stats
    header = (
        f"# {category_name}\n\n"
        f"*Consolidated from {len(summaries)} video summaries "
        f"(~{total_tokens:,} → ~{estimate_tokens(result):,} tokens, "
        f"{estimate_tokens(result)/total_tokens*100:.0f}% of original)*\n\n"
    )
    output_path.write_text(header + result)
    print(f"  Written to {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Consolidate merged category files.")
    parser.add_argument("input", help="A single .md file or directory of merged category files")
    parser.add_argument("-o", "--output", default=None, help="Output directory (default: <input_dir>/../_consolidated)")
    parser.add_argument("--anthropic-key", default=None, help="Anthropic API key")
    parser.add_argument("--model", default=None, help="Model to use")
    parser.add_argument("--chunk-tokens", type=int, default=DEFAULT_CHUNK_TOKENS, help=f"Tokens per chunk (default: {DEFAULT_CHUNK_TOKENS})")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, help=f"Max output tokens per LLM call (default: {DEFAULT_MAX_TOKENS})")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without making API calls")
    parser.add_argument("--skip-existing", action="store_true", help="Skip files that already exist in output")
    args = parser.parse_args()

    model = args.model or DEFAULT_MODEL
    input_path = Path(args.input)

    if input_path.is_file():
        files = [input_path]
        default_output = input_path.parent.parent / "_consolidated"
    elif input_path.is_dir():
        files = sorted(input_path.glob("*.md"))
        # Exclude taxonomy.json and similar
        files = [f for f in files if f.suffix == ".md"]
        default_output = input_path.parent / "_consolidated"
    else:
        print(f"Error: {input_path} not found.")
        return 1

    output_dir = Path(args.output) if args.output else default_output

    if not files:
        print("No .md files found.")
        return 1

    print(f"Will consolidate {len(files)} file(s) → {output_dir}/")

    for filepath in files:
        if args.skip_existing and (output_dir / filepath.name).exists():
            print(f"\nSkipping {filepath.name} (already exists)")
            continue
        consolidate_file(filepath, output_dir, args.anthropic_key, model, args.chunk_tokens, args.max_tokens, args.dry_run)

    print(f"\nDone!")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
