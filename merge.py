#!/usr/bin/env python3
"""Cross-channel category merge.

Reads per-channel category files, asks Claude to propose a unified taxonomy,
then concatenates content into merged category files.

Usage:
    python merge.py output/ -o output/_merged/
    python merge.py output/ -o output/_merged/ --min-categories 5 --max-categories 10
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import anthropic

DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")


def filename_to_label(filename: str) -> str:
    """Convert a snake_case filename to a human-readable label."""
    stem = Path(filename).stem
    return stem.replace("_", " ").title()


def label_to_filename(label: str) -> str:
    """Convert a human-readable label to a snake_case filename."""
    slug = label.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
    return slug + ".md"


def collect_categories(output_dir: Path, exclude: list[str] | None = None) -> dict[str, list[dict]]:
    """Walk output/<channel>/categories/*.md and return {channel: [{label, path}, ...]}."""
    exclude = set(exclude or [])
    channels = {}
    for entry in sorted(output_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_") or entry.name in exclude:
            continue
        cat_dir = entry / "categories"
        if not cat_dir.is_dir():
            continue
        cats = []
        for f in sorted(cat_dir.glob("*.md")):
            cats.append({"label": filename_to_label(f.name), "path": f})
        if cats:
            channels[entry.name] = cats
    return channels


def build_merge_prompt(channels: dict[str, list[dict]], min_cats: int, max_cats: int) -> str:
    """Build the prompt for the LLM merge call."""
    lines = [
        "You are given per-channel video category names from multiple YouTube channels.",
        "All channels cover career/job-search advice but each has its own category scheme.",
        "",
        "Your task:",
        f"1. Propose a UNIFIED taxonomy of {min_cats}-{max_cats} categories that covers all content.",
        "2. Map every input category to exactly one unified category.",
        "3. Keep channel-specific niches (e.g. consulting case interviews) as their own category",
        "   if they don't fit naturally elsewhere.",
        "4. Merge categories with strong semantic overlap (e.g. 'Resume and LinkedIn Optimization'",
        "   and 'Resume and Application Strategy' → single category).",
        "",
        "Input categories by channel:",
        "",
    ]
    for channel, cats in channels.items():
        lines.append(f"### {channel}")
        for c in cats:
            lines.append(f"- {c['label']}")
        lines.append("")

    lines.extend([
        "Output ONLY valid JSON (no markdown fences) with this structure:",
        '{',
        '  "unified_categories": ["Category Name 1", "Category Name 2", ...],',
        '  "mapping": {',
        '    "channel_name": {',
        '      "Original Category Label": "Unified Category Name",',
        '      ...',
        '    },',
        '    ...',
        '  }',
        '}',
    ])
    return "\n".join(lines)


def call_llm(prompt: str, api_key: str | None, model: str) -> dict:
    """Send the merge prompt to Claude and parse JSON response."""
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


def do_merge(
    output_dir: Path,
    merged_dir: Path,
    channels: dict[str, list[dict]],
    taxonomy: dict,
):
    """Create unified category files by appending source content."""
    merged_dir.mkdir(parents=True, exist_ok=True)
    mapping = taxonomy["mapping"]

    # Create empty files for each unified category
    unified_files = {}
    for cat_name in taxonomy["unified_categories"]:
        fname = label_to_filename(cat_name)
        fpath = merged_dir / fname
        unified_files[cat_name] = fpath
        # Write header
        fpath.write_text(f"# {cat_name}\n\n")

    # Append each channel's category content
    for channel, cats in channels.items():
        chan_mapping = mapping.get(channel, {})
        for cat in cats:
            unified_name = chan_mapping.get(cat["label"])
            if not unified_name:
                print(f"  WARNING: No mapping for {channel}/{cat['label']}, skipping")
                continue
            target = unified_files.get(unified_name)
            if not target:
                print(f"  WARNING: Unified category '{unified_name}' not found, skipping")
                continue

            content = cat["path"].read_text()
            with open(target, "a") as f:
                f.write(f"\n------------------------------------\n\n## Source: {channel}\n\n")
                f.write(content)
                f.write("\n")

    # Print summary
    print(f"\nUnified taxonomy ({len(taxonomy['unified_categories'])} categories):")
    for cat_name in taxonomy["unified_categories"]:
        fpath = unified_files[cat_name]
        # Count video entries (lines starting with '# ' that aren't the header)
        lines = fpath.read_text().splitlines()
        # Count source sections
        sources = sum(1 for l in lines if l.startswith("## Source:"))
        print(f"  {cat_name} ({sources} channel contributions)")


def main():
    parser = argparse.ArgumentParser(description="Merge per-channel categories into a unified taxonomy.")
    parser.add_argument("output_dir", help="Root output directory containing channel folders")
    parser.add_argument("-o", "--output", default=None, help="Merged output directory (default: <output_dir>/_merged)")
    parser.add_argument("--anthropic-key", default=None, help="Anthropic API key")
    parser.add_argument("--model", default=None, help="Model to use")
    parser.add_argument("--min-categories", type=int, default=5, help="Minimum unified categories (default: 5)")
    parser.add_argument("--max-categories", type=int, default=10, help="Maximum unified categories (default: 10)")
    parser.add_argument("--dry-run", action="store_true", help="Show prompt and taxonomy without writing files")
    parser.add_argument("--taxonomy-file", default=None, help="Use existing taxonomy JSON instead of calling LLM")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    merged_dir = Path(args.output) if args.output else output_dir / "_merged"
    model = args.model or DEFAULT_MODEL

    channels = collect_categories(output_dir)
    if not channels:
        print("No channels with categories found.")
        return 1

    total = sum(len(cats) for cats in channels.values())
    print(f"Found {total} categories across {len(channels)} channels:")
    for ch, cats in channels.items():
        print(f"  {ch}: {', '.join(c['label'] for c in cats)}")
    print()

    if args.taxonomy_file:
        taxonomy = json.loads(Path(args.taxonomy_file).read_text())
        print(f"Loaded taxonomy from {args.taxonomy_file}")
    else:
        prompt = build_merge_prompt(channels, args.min_categories, args.max_categories)

        if args.dry_run:
            print("=== PROMPT ===")
            print(prompt)
            print()

        print("Calling LLM for unified taxonomy...")
        taxonomy = call_llm(prompt, args.anthropic_key, model)

        # Save taxonomy for reproducibility
        tax_path = merged_dir if not args.dry_run else output_dir
        tax_path.mkdir(parents=True, exist_ok=True)
        tax_file = tax_path / "taxonomy.json"
        tax_file.write_text(json.dumps(taxonomy, indent=2))
        print(f"Taxonomy saved to {tax_file}")

    if args.dry_run:
        print("\n=== TAXONOMY ===")
        print(json.dumps(taxonomy, indent=2))
        return 0

    do_merge(output_dir, merged_dir, channels, taxonomy)

    # Save taxonomy in merged dir too
    (merged_dir / "taxonomy.json").write_text(json.dumps(taxonomy, indent=2))
    print(f"\nMerged files written to {merged_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
