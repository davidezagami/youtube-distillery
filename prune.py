#!/usr/bin/env python3
"""Remove outlier videos from summaries.md based on analysis output.

Usage:
    python prune.py andylacivita/                          # reads analysis.md, writes summaries_v2.md
    python prune.py andylacivita/ --analysis outliers.md   # custom analysis file
    python prune.py andylacivita/ --overwrite              # overwrite summaries.md in place
    python prune.py andylacivita/ -o cleaned.md            # explicit output path
"""

import argparse
import re
import sys
from pathlib import Path

URL_PATTERN = re.compile(r"https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]+")


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


def extract_outlier_urls(analysis_text: str) -> set[str]:
    """Extract all YouTube URLs from the analysis output."""
    return set(URL_PATTERN.findall(analysis_text))


def parse_sections(text: str) -> list[str]:
    """Split summaries.md on '\\n---\\n' separator, dropping empty sections."""
    parts = text.split("\n---\n")
    return [s.strip() for s in parts if s.strip()]


def extract_url_from_section(section: str) -> str | None:
    """Extract the URL from a section's **URL:** metadata line."""
    m = re.search(r"\*\*URL:\*\*\s*(https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]+)", section)
    return m.group(1) if m else None


def next_version_path(base_path: Path) -> Path:
    """Find the next available summaries_vN.md path."""
    parent = base_path.parent
    stem = base_path.stem  # "summaries"
    suffix = base_path.suffix  # ".md"
    version = 2
    while (parent / f"{stem}_v{version}{suffix}").exists():
        version += 1
    return parent / f"{stem}_v{version}{suffix}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove outlier videos from summaries.md based on analysis output."
    )
    parser.add_argument("input_dir", help="Folder containing summaries.md")
    parser.add_argument("--analysis", default=None,
                        help="Path to analysis output (default: <input_dir>/analysis.md)")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite summaries.md in place")
    parser.add_argument("-o", "--output", default=None,
                        help="Explicit output path")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    summaries_path = find_latest_summaries(input_dir)
    if not summaries_path.exists():
        print(f"Error: no summaries.md found in {input_dir}")
        return 1
    print(f"Using {summaries_path.name}")

    analysis_path = Path(args.analysis) if args.analysis else input_dir / "analysis.md"
    if not analysis_path.exists():
        print(f"Error: analysis file not found: {analysis_path}")
        return 1

    # Extract outlier URLs from analysis
    analysis_text = analysis_path.read_text(encoding="utf-8")
    outlier_urls = extract_outlier_urls(analysis_text)
    if not outlier_urls:
        print("No outlier URLs found in analysis file. Nothing to prune.")
        return 0

    # Parse and filter summaries
    text = summaries_path.read_text(encoding="utf-8")
    sections = parse_sections(text)
    kept = [s for s in sections if extract_url_from_section(s) not in outlier_urls]
    removed = len(sections) - len(kept)

    # Determine output path
    if args.output:
        out_path = Path(args.output)
    elif args.overwrite:
        out_path = summaries_path
    else:
        out_path = next_version_path(summaries_path)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n---\n".join(kept) + "\n", encoding="utf-8")
    print(f"Removed {removed} outliers ({len(kept)} remaining). Written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
