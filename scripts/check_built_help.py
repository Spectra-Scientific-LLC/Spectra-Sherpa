#!/usr/bin/env python3
"""Validate existing METHOD_TOPICS and node help references against built HTML.

Build first with python -m mkdocs build --strict, then run
python scripts/check_built_help.py --site-dir site. No network requests or writes.
Uses the committed registry projection embedded in generated node reference
sections; requires only Python's standard library. The generator's --check
checks that projection against the live registry in the full-runtime job.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

if __name__ == "__main__":
    sys.dont_write_bytecode = True

from generate_node_reference import BEGIN, END, HELP_METADATA, ROOT, help_reference, replace_section


def generated_help_rows(root: Path) -> list[dict]:
    """Read generator-owned help metadata, never a separately maintained census."""
    rows = []
    seen: set[str] = set()
    for path in sorted((root / "docs/nodes").rglob("*.md")):
        source = path.read_text(encoding="utf-8")
        if BEGIN not in source and END not in source and HELP_METADATA not in source:
            continue
        replace_section(source, "", path)  # Validate marker cardinality and ordering.
        section = source.split(BEGIN, 1)[1].split(END, 1)[0]
        matches = re.findall(re.escape(HELP_METADATA) + r"(.+?) -->", section)
        if len(matches) != 1 or source.count(HELP_METADATA) != 1:
            raise ValueError(f"{path}: expected exactly one generated node-help metadata record.")
        metadata = json.loads(matches[0])
        reference = path.relative_to(root).as_posix()
        if not isinstance(metadata, dict) or set(metadata) != {"help_reference", "node_types"}:
            raise ValueError(f"{path}: invalid generated node-help metadata.")
        if metadata["help_reference"] != reference:
            raise ValueError(f"{path}: generated help_reference does not match its containing page.")
        nodes = metadata["node_types"]
        if not isinstance(nodes, list) or not nodes:
            raise ValueError(f"{path}: generated node list must be nonempty.")
        for node in nodes:
            if not isinstance(node, str) or not re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", node) or node in seen:
                raise ValueError(f"{path}: invalid or duplicate generated node identity: {node!r}")
            seen.add(node)
            row = {"node_type": node, "execution_contract": {"payload": {"help_reference": reference}}}
            help_reference(row)
            rows.append(row)
    if not rows:
        raise ValueError("No generated node-help metadata. Run: python scripts/generate_node_reference.py")
    return rows


def method_topics(source: str) -> dict[str, str]:
    """Read the one existing TS literal; reject unsupported syntax, never skip it.

    This intentionally accepts the authority's current string-only object shape.
    A future computed/spread value must teach this reader how to evaluate it.
    """
    blocks = re.findall(r"\bexport\s+const\s+METHOD_TOPICS\s*=\s*\{(.*?)\}\s*as\s+const\s*;", source, re.S)
    if len(blocks) != 1:
        raise ValueError("Expected exactly one literal METHOD_TOPICS object in frontend/src/utils/documentation.ts.")
    entry = re.compile(r'\s*([A-Za-z_$][\w$]*)\s*:\s*("(?:[^"\\]|\\.)*")\s*(?:,|$)')
    topics: dict[str, str] = {}
    remaining = blocks[0]
    while remaining.strip():
        match = entry.match(remaining)
        if match is None:
            raise ValueError("Unsupported METHOD_TOPICS syntax; update the reader, not a second topic registry.")
        key, value = match.groups()
        if key in topics:
            raise ValueError(f"Duplicate METHOD_TOPICS key: {key}")
        topics[key] = json.loads(value)
        remaining = remaining[match.end() :]
    if not topics:
        raise ValueError("METHOD_TOPICS must not be empty.")
    return topics


class Anchors(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.names: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if value is not None and (key == "id" or (tag == "a" and key == "name")):
                self.names.add(value)


def built_target(site_dir: Path, url: str) -> tuple[Path, str]:
    parsed = urlsplit(url)
    path = unquote(parsed.path)
    relative = PurePosixPath(path)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or path.startswith("/")
        or "\\" in path
        or ".." in relative.parts
        or not path
    ):
        raise ValueError(f"Expected a safe site-relative help URL, got {url!r}")
    if path.endswith("/"):
        relative /= "index.html"
    elif relative.suffix != ".html":
        raise ValueError(f"Help URL must name a directory or HTML document: {url!r}")
    target = site_dir.joinpath(*relative.parts)
    if not target.resolve().is_relative_to(site_dir.resolve()):
        raise ValueError(f"Help URL escapes the built site: {url!r}")
    return target, unquote(parsed.fragment)


def check_built_help(site_dir: Path, topics: dict[str, str], rows: list[dict]) -> list[str]:
    links = [(f"METHOD_TOPICS.{key}", url) for key, url in topics.items()]
    failures: list[str] = []
    for row in rows:
        try:
            reference = help_reference(row)
            # Same projection as nodeHelp.ts: docs/nodes/foo.md -> nodes/foo/.
            links.append((row["node_type"], reference.removeprefix("docs/").removesuffix(".md") + "/"))
        except ValueError as error:
            failures.append(str(error))
    if not rows:
        failures.append("No registered node help references were supplied.")
    anchors: dict[Path, set[str]] = {}
    for owner, url in links:
        try:
            target, fragment = built_target(site_dir, url)
            if not target.is_file():
                raise ValueError(f"missing built HTML: {target}")
            if fragment:
                if target not in anchors:
                    parser = Anchors()
                    parser.feed(target.read_text(encoding="utf-8"))
                    parser.close()
                    anchors[target] = parser.names
                if fragment not in anchors[target]:
                    raise ValueError(f"missing HTML anchor #{fragment} in {target}")
        except (ValueError, OSError) as error:
            failures.append(f"{owner} ({url}): {error}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir", type=Path, default=ROOT / "site", help="Existing MkDocs output directory.")
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    if not args.site_dir.is_dir():
        parser.exit(1, f"Built site does not exist: {args.site_dir}\nRun: python -m mkdocs build --strict\n")
    try:
        topics = method_topics((ROOT / "frontend/src/utils/documentation.ts").read_text(encoding="utf-8"))
        rows = generated_help_rows(ROOT)
        failures = check_built_help(args.site_dir, topics, rows)
    except (ValueError, OSError) as error:
        failures = [str(error)]
    if failures:
        print("\n".join(failures), file=sys.stderr)
        print(
            "Fix the destination or its authoritative METHOD_TOPICS/help_reference, rebuild with "
            "`python -m mkdocs build --strict`, then rerun this checker against that output directory.",
            file=sys.stderr,
        )
        return 1
    print(f"Built help valid: {len(topics)} method topics and {len(rows)} node references.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
