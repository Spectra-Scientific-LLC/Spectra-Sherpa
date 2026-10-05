#!/usr/bin/env python3
"""Generate/check the closed census of production axis constructors.

The census does not forbid fresh axis construction. It makes every production
constructor and its supplied-field shape reviewable, and turns an added,
removed, or moved reconstruction path into an explicit generated-artifact
change. This is the structural backstop for DSO axis-field preservation.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = ROOT / "packages/spectra-sherpa/src/spectra_sherpa"
OUTPUT = ROOT / "docs/evidence/dataset-axis-constructor-census.json"
SCHEMA_VERSION = "spectrasherpa-dataset-axis-constructor-census/2"
AXIS_CONSTRUCTORS = frozenset(
    {
        "AxisInfo",
        "FeatureAxis",
        "FrequencyAxis",
        "MZAxis",
        "PotentialAxis",
        "SampleAxis",
        "SpatialAxis",
        "SpectralAxis",
        "TimeAxis",
    }
)
PRESERVATION_FIELDS = frozenset(
    {
        "alternate_label_sets",
        "alternate_scales",
        "alternate_title_sets",
        "class_sets",
        "classes",
        "exclusion_reasons",
        "include_mask",
        "labels",
        "primary_class_set_name",
        "primary_label_name",
        "primary_scale_name",
        "primary_title_name",
        "sample_table",
        "selection_scores",
        "title",
        "units",
        "values",
    }
)


@dataclass(frozen=True)
class AxisConstructorCall:
    file: str
    scope: str
    constructor: str
    line: int
    column: int
    positional_arguments: int
    keyword_arguments: tuple[str, ...]
    preservation_sensitive: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "scope": self.scope,
            "constructor": self.constructor,
            "line": self.line,
            "column": self.column,
            "positional_arguments": self.positional_arguments,
            "keyword_arguments": list(self.keyword_arguments),
            "preservation_sensitive": self.preservation_sensitive,
        }


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _mentions_preservation_field(node: ast.AST) -> bool:
    return any(
        (isinstance(item, ast.Attribute) and item.attr in PRESERVATION_FIELDS)
        or (isinstance(item, ast.Constant) and item.value in PRESERVATION_FIELDS)
        for item in ast.walk(node)
    )


class _ConstructorVisitor(ast.NodeVisitor):
    def __init__(self, relative: str) -> None:
        self.relative = relative
        self.scope: list[str] = []
        self.calls: list[AxisConstructorCall] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self.visit_FunctionDef(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        constructor = _call_name(node.func)
        if constructor in AXIS_CONSTRUCTORS:
            keywords = tuple(sorted(keyword.arg or "**" for keyword in node.keywords))
            sensitive = any(_mentions_preservation_field(argument) for argument in node.args)
            sensitive = sensitive or any(_mentions_preservation_field(keyword.value) for keyword in node.keywords)
            self.calls.append(
                AxisConstructorCall(
                    file=self.relative,
                    scope=".".join(self.scope) or "<module>",
                    constructor=constructor,
                    line=node.lineno,
                    column=node.col_offset,
                    positional_arguments=len(node.args),
                    keyword_arguments=keywords,
                    preservation_sensitive=sensitive,
                )
            )
        self.generic_visit(node)


def census(source_root: Path = SOURCE_ROOT, *, repository_root: Path = ROOT) -> dict[str, Any]:
    calls: list[AxisConstructorCall] = []
    source_files = sorted(source_root.rglob("*.py"))
    for path in source_files:
        relative = path.resolve().relative_to(repository_root.resolve()).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        visitor = _ConstructorVisitor(relative)
        visitor.visit(tree)
        calls.extend(visitor.calls)
    records = [item.to_dict() for item in sorted(calls, key=lambda item: (item.file, item.line, item.column))]
    projection = {
        "schema_version": SCHEMA_VERSION,
        "source_root": source_root.resolve().relative_to(repository_root.resolve()).as_posix(),
        "source_file_count": len(source_files),
        "constructor_call_count": len(records),
        "preservation_sensitive_call_count": sum(bool(item["preservation_sensitive"]) for item in records),
        "calls": records,
    }
    encoded = json.dumps(
        stable_projection(projection), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return {**projection, "census_sha256": hashlib.sha256(encoded).hexdigest()}


def stable_projection(value: Any) -> Any:
    """Remove source locations while retaining duplicate call occurrences."""

    if isinstance(value, dict):
        return {key: stable_projection(item) for key, item in sorted(value.items()) if key not in {"line", "column"}}
    if isinstance(value, list):
        projected = [stable_projection(item) for item in value]
        if all(isinstance(item, dict) for item in projected):
            return sorted(projected, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
        return projected
    return value


def render(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    expected = render(census())
    if args.check:
        if not args.output.is_file():
            raise SystemExit("dataset axis constructor census is stale; regenerate it before review")
        checked = json.loads(args.output.read_text(encoding="utf-8"))
        generated = json.loads(expected)
        if stable_projection(checked) != stable_projection(generated):
            raise SystemExit("dataset axis constructor census is stale; regenerate it before review")
        print("Dataset axis constructor census: PASS")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(expected)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
