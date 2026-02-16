#!/usr/bin/env python3
"""Build a categorize prompt by injecting discovered categories into a template.

Usage:
    python build_prompt.py output/Farah_Sharghi/analysis.md
    python build_prompt.py output/Farah_Sharghi/analysis.md --template categorize_template.txt -o categorize_run.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def extract_categories(text: str) -> list[str]:
    """Extract lines starting with '- ' from analysis output."""
    return [m.group(0) for m in re.finditer(r"^- .+", text, re.MULTILINE)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inject discovered categories into a prompt template."
    )
    parser.add_argument("analysis", help="Path to analysis.md with discovered categories")
    parser.add_argument("--template", default="categorize_template.txt",
                        help="Template file with {categories} placeholder (default: categorize_template.txt)")
    parser.add_argument("-o", "--output", default="categorize_run.txt",
                        help="Output prompt file (default: categorize_run.txt)")
    args = parser.parse_args()

    analysis_path = Path(args.analysis)
    if not analysis_path.exists():
        print(f"Error: {analysis_path} not found")
        return 1

    template_path = Path(args.template)
    if not template_path.exists():
        print(f"Error: {template_path} not found")
        return 1

    categories = extract_categories(analysis_path.read_text(encoding="utf-8"))
    if not categories:
        print(f"Error: no categories found in {analysis_path} (expected lines starting with '- ')")
        return 1

    template = template_path.read_text(encoding="utf-8")
    prompt = template.replace("{categories}", "\n".join(categories))

    Path(args.output).write_text(prompt, encoding="utf-8")
    print(f"Found {len(categories)} categories:")
    for c in categories:
        print(f"  {c}")
    print(f"\nPrompt written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
