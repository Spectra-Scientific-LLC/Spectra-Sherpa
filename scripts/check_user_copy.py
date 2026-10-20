#!/usr/bin/env python3
"""Bounded copy ratchet: static Vue text/attributes and workflow-guide prose only."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs/developers/user-copy-baseline.json"
# Exact product phrases, not scientific terms, symbols, identifiers or API names.
RULES = {
    "execute-workflow": (r"\bexecute workflow\b", "Run workflow"),
    "data-portfolio": (r"\bdata portfolios?\b", "Dataset / datasets"),
    "scientific-summary": (r"\bshort scientific summary\b", "Short summary"),
}
ATTRIBUTES = {"label", "title", "header", "placeholder", "aria-label", "alt"}


class CopyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ignored = 0
        self.fragments: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "code", "pre"}:
            self.ignored += 1
        if not self.ignored:
            self.fragments.extend(value for key, value in attrs if key in ATTRIBUTES and value)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "code", "pre"} and self.ignored:
            self.ignored -= 1

    def handle_data(self, data):
        if not self.ignored:
            self.fragments.append(re.sub(r"{{.*?}}", "", data, flags=re.S))


def copy_fragments(source: str, suffix: str) -> list[str]:
    if suffix == ".vue":
        parser = CopyParser()
        parser.feed(source)
        return parser.fragments
    source = re.sub(r"(?ms)^(```|~~~).*?^\1[^\n]*$", "", source)
    source = re.sub(r"`[^`]*`|<!--.*?-->|\]\([^)]*\)", "", source, flags=re.S)
    return [source]


def inventory(root: Path) -> dict[str, dict[str, int]]:
    result = {}
    paths = sorted((root / "frontend/src").rglob("*.vue")) + sorted((root / "docs/workflows").rglob("*.md"))
    for path in paths:
        counts: Counter[str] = Counter()
        for text in copy_fragments(path.read_text(encoding="utf-8"), path.suffix):
            for rule, (pattern, _) in RULES.items():
                counts[rule] += len(re.findall(pattern, text, flags=re.I))
        if any(counts.values()):
            result[path.relative_to(root).as_posix()] = {key: value for key, value in counts.items() if value}
    return result


def failures(current: dict, baseline: dict) -> list[str]:
    messages = []
    for path, counts in current.items():
        for rule, count in counts.items():
            if count > baseline.get(path, {}).get(rule, 0):
                messages.append(f"{path}: {rule}: {count} occurrences; use {RULES[rule][1]!r}")
    # Removal must shrink the baseline too; it cannot leave future growth credit.
    for path, counts in baseline.items():
        for rule, count in counts.items():
            if count > current.get(path, {}).get(rule, 0):
                messages.append(f"{path}: remove resolved {rule} baseline entries")
    return messages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Explicit reviewed inventory update; never run automatically in CI",
    )
    args = parser.parse_args()
    current = inventory(ROOT)
    if args.write_baseline:
        BASELINE.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    problems = failures(current, baseline)
    for problem in problems:
        print(problem)
    if problems:
        print("Correct new copy; shrink resolved baseline entries. Do not raise the baseline to pass CI.")
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
