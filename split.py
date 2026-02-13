#!/usr/bin/env python3
"""Split summaries into per-category files based on analysis output.

Usage:
    python split.py output/                              # reads analysis.md + latest summaries, writes categories/
    python split.py output/ --analysis custom.md         # custom analysis file
    python split.py output/ -o ./my_categories/          # custom output directory
"""

import argparse
import re
import sys
from pathlib import Path

URL_PATTERN = re.compile(r"https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]+")

SEP = r"\s*[-\u2014\u2013]{1,3}\s*"
CATEGORIZATION_PATTERN = re.compile(
    r"\*\*(.+?)\*\*" + SEP + r"(.+?)" + SEP + r".+?" + SEP +
    r"(https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]+)"
)


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


def extract_url_from_section(section: str) -> str | None:
    """Extract the URL from a section's **URL:** metadata line."""
    m = re.search(r"\*\*URL:\*\*\s*(https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]+)", section)
    return m.group(1) if m else None


def slugify_category(name: str) -> str:
    """Convert a category name to a filename-safe slug.

    "Resume & Applications" -> "resume_and_applications"
    """
    s = name.replace("&", "and")
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s)
    s = s.strip("_").lower()
    return s


def parse_categorizations(analysis_text: str) -> dict[str, str]:
    """Parse analysis output into {url: category} mapping."""
    result = {}
    for m in CATEGORIZATION_PATTERN.finditer(analysis_text):
        category = m.group(2).strip()
        url = m.group(3)
        result[url] = category
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Split summaries into per-category files based on analysis output."
    )
    parser.add_argument("input_dir", help="Folder containing summaries and analysis")
    parser.add_argument("--analysis", default=None,
                        help="Path to analysis output (default: <input_dir>/analysis.md)")
    parser.add_argument("-o", "--output-dir", default=None,
                        help="Output directory for category files (default: <input_dir>/categories/)")
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

    # Parse categorizations from analysis
    analysis_text = analysis_path.read_text(encoding="utf-8")
    url_to_category = parse_categorizations(analysis_text)
    if not url_to_category:
        print("No categorization lines found in analysis file. Nothing to split.")
        return 1

    # Parse summaries into sections
    text = summaries_path.read_text(encoding="utf-8")
    sections = parse_sections(text)

    # Group sections by category
    categories: dict[str, list[str]] = {}
    summary_urls = set()
    for section in sections:
        url = extract_url_from_section(section)
        if url:
            summary_urls.add(url)
        category = url_to_category.get(url, "Uncategorized") if url else "Uncategorized"
        categories.setdefault(category, []).append(section)

    # Write category files
    out_dir = Path(args.output_dir) if args.output_dir else input_dir / "categories"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'Category':<30} {'File':<40} {'Count':>5}")
    print("-" * 77)
    for category, cat_sections in sorted(categories.items()):
        slug = slugify_category(category)
        filename = f"{slug}.md"
        out_path = out_dir / filename
        out_path.write_text("\n---\n".join(cat_sections) + "\n", encoding="utf-8")
        print(f"{category:<30} {filename:<40} {len(cat_sections):>5}")

    print(f"\nWrote {len(categories)} category files to {out_dir}/")

    # Warn about URLs in analysis not found in summaries
    analysis_urls = set(url_to_category.keys())
    missing = analysis_urls - summary_urls
    if missing:
        print(f"\nWarning: {len(missing)} URL(s) in analysis not found in summaries:")
        for url in sorted(missing):
            print(f"  {url}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
