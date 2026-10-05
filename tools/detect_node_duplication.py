#!/usr/bin/env python3
"""Inventory near-duplicate canonical DAG node functions.

The report is an observability contract, not a blanket failure gate.
Similarity is not itself a defect: generated exporters and small predicates
are expected to repeat, while duplicated verification logic at a fitted-state
trust boundary is not. The checked evidence records one canonical row per
unique pair, classifies its risk, and projects the families back onto every
affected registered node.

Usage:
    python tools/detect_node_duplication.py
    python tools/detect_node_duplication.py --write-evidence PATH
    python tools/detect_node_duplication.py --check-evidence PATH
    python tools/detect_node_duplication.py --check
"""

from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NODES_ROOT = Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "services" / "dag" / "nodes"
EVIDENCE_SCHEMA = "spectra-canonical-node-near-duplicate-families/1"
MIN_STATEMENTS = 6
MAX_STATEMENTS = 150
SIMILARITY_THRESHOLD = 0.80
QUICK_RATIO_FLOOR = SIMILARITY_THRESHOLD - 0.05

_PLUMBING_FUNCTIONS = {
    "_is_numeric_array",
    "_optional_text",
    "supports_python_export",
}
_STRUCTURAL_FUNCTIONS = {
    "apply_fitted_state",
    "fit_fitted_state",
    "generate_python",
}
_VERIFICATION_MARKERS = (
    "contract_digest",
    "fitted_state_envelope",
    "verify_fitted_state",
    "verify_state_envelope",
)


@dataclass(frozen=True)
class FunctionUnit:
    file: Path
    family: str
    qualname: str
    fingerprint: str
    statement_count: int
    node_types: tuple[str, ...]

    @property
    def function_name(self) -> str:
        return self.qualname.rsplit(".", 1)[-1]


@dataclass(frozen=True)
class DuplicateFinding:
    left: FunctionUnit
    right: FunctionUnit
    similarity: float
    classification: str


_NODE_CODE = {
    "If": "I",
    "For": "F",
    "While": "W",
    "Try": "T",
    "Return": "R",
    "Call": "C",
    "Assign": "A",
    "AugAssign": "G",
    "AnnAssign": "N",
    "Compare": "M",
    "BoolOp": "B",
    "BinOp": "O",
    "UnaryOp": "U",
    "Raise": "X",
    "With": "H",
    "ListComp": "L",
    "DictComp": "D",
    "SetComp": "S",
    "GeneratorExp": "E",
    "Lambda": "Y",
    "Attribute": "@",
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _fingerprint(node: ast.AST) -> str:
    names: dict[str, int] = {}
    tokens: list[str] = []
    for child in ast.walk(node):
        kind = type(child).__name__
        if isinstance(child, (ast.Name, ast.arg)):
            identifier = child.id if isinstance(child, ast.Name) else child.arg
            tokens.append(f"v{names.setdefault(identifier, len(names))}")
        elif kind in _NODE_CODE:
            tokens.append(_NODE_CODE[kind])
    return "".join(tokens)


def _node_types(tree: ast.AST) -> tuple[str, ...]:
    values: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "node_type" and isinstance(keyword.value, ast.Constant):
                value = keyword.value.value
                if isinstance(value, str) and value:
                    values.add(value)
    return tuple(sorted(values))


def _class_node_types(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    return {node.name: _node_types(node) for node in tree.body if isinstance(node, ast.ClassDef) and _node_types(node)}


class _FunctionCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope: list[str] = []
        self.functions: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        qualname = ".".join((*self.scope, node.name))
        self.functions.append((qualname, node))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        qualname = ".".join((*self.scope, node.name))
        self.functions.append((qualname, node))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()


def _iter_functions(path: Path, nodes_root: Path) -> list[FunctionUnit]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []
    family = path.relative_to(nodes_root).parts[0] if path.parent != nodes_root else "."
    registered_node_types = _node_types(tree)
    node_types_by_class = _class_node_types(tree)
    collector = _FunctionCollector()
    collector.visit(tree)
    units: list[FunctionUnit] = []
    for qualname, node in collector.functions:
        statement_count = sum(1 for _ in ast.walk(node))
        if not (MIN_STATEMENTS <= statement_count <= MAX_STATEMENTS):
            continue
        owning_class = qualname.split(".", 1)[0] if "." in qualname else None
        units.append(
            FunctionUnit(
                file=path,
                family=family,
                qualname=qualname,
                fingerprint=_fingerprint(node),
                statement_count=statement_count,
                node_types=node_types_by_class.get(owning_class, registered_node_types),
            )
        )
    return units


def _classification(left: FunctionUnit, right: FunctionUnit) -> str:
    names = {left.function_name, right.function_name}
    joined = " ".join(sorted(names)).lower()
    if any(marker in joined for marker in _VERIFICATION_MARKERS):
        return "verification_critical"
    if names <= _PLUMBING_FUNCTIONS or (
        left.function_name == right.function_name and left.function_name in _PLUMBING_FUNCTIONS
    ):
        return "plumbing"
    if names & _STRUCTURAL_FUNCTIONS or "managed_parameters" in joined:
        return "structural_sibling"
    return "structural_sibling"


def _unit_key(unit: FunctionUnit, root: Path) -> tuple[str, str]:
    return unit.file.relative_to(root).as_posix(), unit.qualname


def find_duplicates(root: Path) -> list[DuplicateFinding]:
    units: list[FunctionUnit] = []
    for file in sorted(root.rglob("*.py")):
        units.extend(_iter_functions(file, root))

    by_family: dict[str, list[FunctionUnit]] = {}
    for unit in units:
        by_family.setdefault(unit.family, []).append(unit)

    deduplicated: dict[tuple[tuple[str, str], tuple[str, str]], DuplicateFinding] = {}
    for family_units in by_family.values():
        for index, left in enumerate(family_units):
            matcher = difflib.SequenceMatcher(None, autojunk=False)
            matcher.set_seq2(left.fingerprint)
            for right in family_units[index + 1 :]:
                if left.file == right.file:
                    continue
                if (
                    abs(left.statement_count - right.statement_count) / max(left.statement_count, right.statement_count)
                    > 0.3
                ):
                    continue
                matcher.set_seq1(right.fingerprint)
                if matcher.quick_ratio() < QUICK_RATIO_FLOOR:
                    continue
                similarity = matcher.ratio()
                if similarity < SIMILARITY_THRESHOLD:
                    continue
                canonical_left, canonical_right = sorted((left, right), key=lambda unit: _unit_key(unit, root))
                pair_key = (_unit_key(canonical_left, root), _unit_key(canonical_right, root))
                finding = DuplicateFinding(
                    left=canonical_left,
                    right=canonical_right,
                    similarity=similarity,
                    classification=_classification(canonical_left, canonical_right),
                )
                existing = deduplicated.get(pair_key)
                if existing is None or finding.similarity > existing.similarity:
                    deduplicated[pair_key] = finding
    return sorted(
        deduplicated.values(),
        key=lambda item: (
            item.classification,
            _unit_key(item.left, root),
            _unit_key(item.right, root),
        ),
    )


def _side(unit: FunctionUnit, root: Path) -> dict[str, Any]:
    return {
        "file": unit.file.relative_to(root).as_posix(),
        "function": unit.qualname,
        "node_types": list(unit.node_types),
        "statement_count": unit.statement_count,
    }


def _side_identity(side: dict[str, Any]) -> tuple[str, str]:
    return str(side["file"]), str(side["function"])


def _connected_families(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    families: list[dict[str, Any]] = []
    for classification in ("verification_critical", "structural_sibling", "plumbing"):
        classified = [pair for pair in pairs if pair["classification"] == classification]
        adjacency: dict[tuple[str, str], set[tuple[str, str]]] = {}
        sides: dict[tuple[str, str], dict[str, Any]] = {}
        for pair in classified:
            left = _side_identity(pair["left"])
            right = _side_identity(pair["right"])
            adjacency.setdefault(left, set()).add(right)
            adjacency.setdefault(right, set()).add(left)
            sides[left] = pair["left"]
            sides[right] = pair["right"]
        unseen = set(adjacency)
        while unseen:
            seed = min(unseen)
            stack = [seed]
            members: set[tuple[str, str]] = set()
            while stack:
                current = stack.pop()
                if current in members:
                    continue
                members.add(current)
                unseen.discard(current)
                stack.extend(adjacency[current] - members)
            member_rows = [sides[identity] for identity in sorted(members)]
            family_pairs = [
                pair
                for pair in classified
                if _side_identity(pair["left"]) in members and _side_identity(pair["right"]) in members
            ]
            family_id = hashlib.sha256(
                _canonical_bytes({"classification": classification, "members": sorted(members)})
            ).hexdigest()[:16]
            families.append(
                {
                    "family_id": family_id,
                    "classification": classification,
                    "pair_count": len(family_pairs),
                    "minimum_similarity": min(pair["similarity"] for pair in family_pairs),
                    "maximum_similarity": max(pair["similarity"] for pair in family_pairs),
                    "members": member_rows,
                }
            )
            for pair in family_pairs:
                pair["family_id"] = family_id
    return sorted(families, key=lambda item: (item["classification"], item["family_id"]))


def build_evidence(root: Path = NODES_ROOT) -> dict[str, Any]:
    findings = find_duplicates(root)
    pairs: list[dict[str, Any]] = []
    for finding in findings:
        left = _side(finding.left, root)
        right = _side(finding.right, root)
        identity = {
            "left": [left["file"], left["function"]],
            "right": [right["file"], right["function"]],
        }
        pair_id = hashlib.sha256(_canonical_bytes(identity)).hexdigest()[:16]
        pair = {
            "pair_id": pair_id,
            "classification": finding.classification,
            "similarity": round(finding.similarity, 6),
            "left": left,
            "right": right,
        }
        pairs.append(pair)
    families = _connected_families(pairs)
    node_annotations: dict[str, list[dict[str, Any]]] = {}
    for family in families:
        node_functions: dict[str, set[str]] = {}
        for member in family["members"]:
            for node_type in member["node_types"]:
                node_functions.setdefault(node_type, set()).add(member["function"])
        for node_type, functions in node_functions.items():
            node_annotations.setdefault(node_type, []).append(
                {
                    "family_id": family["family_id"],
                    "classification": family["classification"],
                    "functions": sorted(functions),
                    "counterpart_node_types": sorted(set(node_functions) - {node_type}),
                    "pair_count": family["pair_count"],
                }
            )
    for node_family_annotations in node_annotations.values():
        node_family_annotations.sort(key=lambda item: (item["classification"], item["family_id"]))
    source_hash = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        source_hash.update(path.relative_to(root).as_posix().encode("utf-8"))
        source_hash.update(b"\0")
        source_hash.update(path.read_text(encoding="utf-8").encode("utf-8"))
        source_hash.update(b"\0")
    counts = Counter(pair["classification"] for pair in pairs)
    report: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA,
        "scanner": {
            "minimum_ast_nodes": MIN_STATEMENTS,
            "maximum_ast_nodes": MAX_STATEMENTS,
            "similarity_threshold": SIMILARITY_THRESHOLD,
        },
        "node_source_tree_sha256": source_hash.hexdigest(),
        "total_unique_pairs": len(pairs),
        "total_families": len(families),
        "classification_counts": {
            key: counts[key] for key in ("verification_critical", "structural_sibling", "plumbing")
        },
        "pairs": pairs,
        "families": families,
        "node_annotations": {key: node_annotations[key] for key in sorted(node_annotations)},
    }
    report["report_digest"] = hashlib.sha256(_canonical_bytes(report)).hexdigest()
    return report


def _render_human(report: dict[str, Any]) -> str:
    lines = [
        f"{report['total_unique_pairs']} unique near-duplicate function pair(s) "
        f"(threshold={SIMILARITY_THRESHOLD}).",
    ]
    for classification in ("verification_critical", "structural_sibling", "plumbing"):
        rows = [pair for pair in report["pairs"] if pair["classification"] == classification]
        lines.extend(("", f"[{classification}] {len(rows)}"))
        for pair in rows:
            lines.append(
                f"  {pair['pair_id']} family={pair['family_id']} {pair['similarity']:.2f} "
                f"{pair['left']['file']}::{pair['left']['function']} <-> "
                f"{pair['right']['file']}::{pair['right']['function']}"
            )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when verification-critical duplication remains")
    parser.add_argument("--write-evidence", type=Path, help="write the canonical JSON evidence")
    parser.add_argument("--check-evidence", type=Path, help="fail unless canonical JSON evidence is current")
    arguments = parser.parse_args()

    report = build_evidence()
    print(_render_human(report))
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if arguments.write_evidence is not None:
        arguments.write_evidence.parent.mkdir(parents=True, exist_ok=True)
        arguments.write_evidence.write_text(serialized, encoding="utf-8")
    if arguments.check_evidence is not None:
        if not arguments.check_evidence.is_file():
            print(f"Missing near-duplicate evidence: {arguments.check_evidence}", file=sys.stderr)
            return 1
        if arguments.check_evidence.read_text(encoding="utf-8") != serialized:
            print(f"Stale near-duplicate evidence: {arguments.check_evidence}", file=sys.stderr)
            return 1
    if arguments.check and report["classification_counts"]["verification_critical"]:
        print("Verification-critical near-duplicate logic remains.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
