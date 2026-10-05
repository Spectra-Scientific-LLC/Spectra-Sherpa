#!/usr/bin/env python3
"""Generate the canonical DAG node release-readiness audit.

The assessment source is deliberately human-reviewed. This generator makes
that judgement complete and auditable: every registered node must appear once,
every evidence reference must exist, and the emitted report is bound to the
current contract census and project-repair map.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_ASSESSMENT_SCHEMA = "spectra-canonical-node-readiness-assessments/3"
_DUPLICATION_SCHEMA = "spectra-canonical-node-near-duplicate-families/1"
_REPORT_SCHEMA = "spectra-canonical-node-readiness-audit/2"
_CONFIDENCE = {"high", "medium", "low"}
_CRITICALITY = {"p0", "p1", "p2", "none"}
_FAULT_PATTERNS = {
    "artifact_replay_gap",
    "axis_unit_shape_guard_gap",
    "deprecated_or_ignored_parameter",
    "evidence_qualification_gap",
    "execution_projection_divergence",
    "fitted_lifecycle_gap",
    "fold_leakage_risk",
    "incomplete_sample_accounting",
    "incomplete_typed_ports",
    "insufficient_tests",
    "known_scientific_defect",
    "missing_consumer_proof",
    "missing_execution_contract",
    "missing_explicit_policy",
    "missing_performance_proof",
    "missing_scientific_reference",
    "nondeterministic_behavior",
    "silent_fallback",
    "superseded_duplicate",
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_portable_text_file(path: Path) -> str:
    """Bind logical UTF-8 text independently of checkout line endings."""

    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"{path} must contain a JSON object")
    return value


def _qualification_authority() -> Any:
    path = Path(__file__).with_name("qualify_canonical_node_baseline.py")
    spec = importlib.util.spec_from_file_location("spectra_canonical_node_qualification", path)
    _require(spec is not None and spec.loader is not None, "canonical-node qualification authority is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_assessment(
    assessment: dict[str, Any],
    *,
    repository_root: Path,
    paired_evidence_ref: str | None,
) -> None:
    expected = {
        "node_type",
        "stars",
        "confidence",
        "criticality",
        "summary",
        "fault_patterns",
        "next_star_blocker",
        "evidence_refs",
    }
    _require(set(assessment) == expected, f"assessment fields must be exactly {sorted(expected)}")
    node_type = assessment["node_type"]
    _require(isinstance(node_type, str) and node_type, "node_type must be a non-empty string")
    stars = assessment["stars"]
    _require(type(stars) is int and 1 <= stars <= 5, f"{node_type}: stars must be an integer from 1 to 5")
    _require(assessment["confidence"] in _CONFIDENCE, f"{node_type}: invalid confidence")
    _require(assessment["criticality"] in _CRITICALITY, f"{node_type}: invalid criticality")
    _require(
        isinstance(assessment["summary"], str) and assessment["summary"].strip(),
        f"{node_type}: summary is required",
    )
    patterns = assessment["fault_patterns"]
    _require(isinstance(patterns, list), f"{node_type}: fault_patterns must be a list")
    _require(len(patterns) == len(set(patterns)), f"{node_type}: duplicate fault pattern")
    _require(set(patterns) <= _FAULT_PATTERNS, f"{node_type}: unknown fault patterns {set(patterns) - _FAULT_PATTERNS}")
    if stars == 5:
        _require(
            assessment["next_star_blocker"] == "none",
            f"{node_type}: a five-star node must have next_star_blocker='none'",
        )
        _require(assessment["criticality"] == "none", f"{node_type}: a five-star node cannot retain criticality")
        _require(not patterns, f"{node_type}: a five-star node cannot retain fault patterns")
    else:
        _require(
            isinstance(assessment["next_star_blocker"], str)
            and assessment["next_star_blocker"].strip()
            and assessment["next_star_blocker"] != "none",
            f"{node_type}: a rating below five requires the exact next-star blocker",
        )
    refs = assessment["evidence_refs"]
    _require(isinstance(refs, list) and refs, f"{node_type}: evidence_refs are required")
    if stars == 5:
        _require(paired_evidence_ref is not None, f"{node_type}: five-star rating requires paired qualification")
        _require(paired_evidence_ref in refs, f"{node_type}: five-star evidence must cite the paired qualification")
    for ref in refs:
        _require(isinstance(ref, str) and ref, f"{node_type}: evidence ref must be a string")
        path_text = ref.split("::", 1)[0]
        if path_text == ref and ref.rsplit(":", 1)[-1].isdigit():
            path_text = ref.rsplit(":", 1)[0]
        _require((repository_root / path_text).exists(), f"{node_type}: missing evidence ref {ref}")


def _render_markdown(report: dict[str, Any]) -> str:
    aggregates = report["aggregates"]
    if aggregates["stars"]["5"] == aggregates["total_nodes"]:
        interpretation = [
            "All active canonical nodes have demonstrated the complete release path:",
            "scientific authority, one execution truth, closed contracts, evidence-producing",
            "consumers, representative performance, and exact-tree qualification on Darwin",
            "and Linux with identical test identities and scientific runtime versions.",
            "",
            "The continuing control is fail-closed: changes to node science, data contracts,",
            "or the locked scientific runtime invalidate the retained qualification and require",
            "a new exact-tree platform pair before five-star status can be regenerated.",
        ]
    else:
        interpretation = [
            "No five-star rating was awarded because the audited tree has not yet",
            "demonstrated the complete release path for any node: scientific authority,",
            "one execution truth, closed contracts, evidence-producing consumers,",
            "representative performance, and current cross-platform qualification.",
            "This does not mean every node is scientifically unusable. The four-star",
            "nodes are the strongest current candidates and principally lack final",
            "consumer/performance qualification.",
            "",
            "The repair order implied by the evidence is:",
            "",
            "1. Correct known P1 scientific defects and silent fallbacks before producing new campaign evidence.",
            "2. Remove superseded duplicate node identities after migrating their consumers.",
            "3. Collapse live, generated, fit, fold, application, and replay projections onto one authority.",
            "4. Close typed ports, execution policy, fitted-state, and sample-accounting contracts.",
            "5. Earn four and five stars through real project consumers, performance ceilings, "
            "and cross-platform qualification.",
        ]
    lines = [
        "# Canonical DAG Node Release-Readiness Audit",
        "",
        f"Audit date: {report['audit_date']}",
        "",
        f"Baseline commit: `{report['baseline_commit']}`",
        "",
        f"Registry digest: `{report['registry_digest']}`",
        "",
        "This is a release-readiness audit, not a ranking of scientific importance.",
        "A node receives only the evidence demonstrated in the audited tree; planned",
        "repairs do not earn stars. The scale is defined in",
        "`docs/lesson/canonical-dag-node-repair-lessons.md` (PR #578).",
        "",
        "## Summary",
        "",
        f"- Nodes audited: **{aggregates['total_nodes']}**",
        f"- Known P0 nodes: **{aggregates['criticality']['p0']}**",
        f"- Known P1 nodes: **{aggregates['criticality']['p1']}**",
        f"- Five-star release-ready nodes: **{aggregates['stars']['5']}**",
        f"- One- and two-star repair priority: **{aggregates['priority_nodes']}**",
        f"- Observable near-duplicate families: **{aggregates['near_duplicates']['total_unique_pairs']}**",
        f"- Verification-critical duplicate families: **{aggregates['near_duplicates']['verification_critical']}**",
        "",
        "### Star distribution",
        "",
        "| Stars | Meaning | Nodes |",
        "|---:|---|---:|",
        f"| 1 | Unsafe, defective, duplicate, or non-canonical | {aggregates['stars']['1']} |",
        f"| 2 | Executable prototype with material contract gaps | {aggregates['stars']['2']} |",
        f"| 3 | Locally credible; release path incomplete | {aggregates['stars']['3']} |",
        f"| 4 | Canonical candidate missing final qualification | {aggregates['stars']['4']} |",
        f"| 5 | Canonical DAG node ready for release | {aggregates['stars']['5']} |",
        "",
        "### Interpretation and immediate priorities",
        "",
        *interpretation,
        "",
        "## Cross-node fault patterns",
        "",
        "| Pattern | Affected nodes |",
        "|---|---:|",
    ]
    for pattern, count in aggregates["fault_patterns"].items():
        lines.append(f"| `{pattern}` | {count} |")
    lines.extend(
        [
            "",
            "## Node-by-node table",
            "",
            "| Node | Family | Stars | Criticality | Confidence | Current finding | Next-star blocker |",
            "|---|---|---:|---|---|---|---|",
        ]
    )
    for row in report["nodes"]:
        summary = row["summary"].replace("|", "\\|").replace("\n", " ")
        blocker = row["next_star_blocker"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{row['node_type']}` | {row['family']} | {row['stars']} | "
            f"{row['criticality']} | {row['confidence']} | {summary} | {blocker} |"
        )
    lines.extend(["", "## Detailed evidence", ""])
    for row in report["nodes"]:
        lines.extend(
            [
                f"### `{row['node_type']}` — {row['stars']} star{'s' if row['stars'] != 1 else ''}",
                "",
                row["summary"],
                "",
                f"- Family: `{row['family']}`",
                f"- Criticality: `{row['criticality']}`",
                f"- Confidence: `{row['confidence']}`",
                f"- Contract complete: `{str(row['contract_complete']).lower()}`",
                f"- Lifecycle: `{row['lifecycle_kind']}`",
                f"- Retention decision: `{row['retention_decision']}`",
                f"- Fault patterns: {', '.join(f'`{p}`' for p in row['fault_patterns']) or 'none'}",
                "- Near-duplicate families: "
                + (
                    ", ".join(
                        f"`{entry['family_id']}` ({entry['classification']}, "
                        f"{', '.join(f'`{name}`' for name in entry['functions'])})"
                        for entry in row["near_duplicate_families"]
                    )
                    or "none"
                ),
                f"- Next-star blocker: {row['next_star_blocker']}",
                "- Evidence:",
            ]
        )
        lines.extend(f"  - `{ref}`" for ref in row["evidence_refs"])
        lines.append("")
    lines.extend(
        [
            "## Reproduction",
            "",
            "```bash",
            "env -u PYTHONPATH \\",
            '  PYTHONPATH="$PWD/packages/spectra-sherpa/src:$PWD/packages/spectra-server/src" \\',
            "  python packages/spectra-sherpa/tools/generate_node_readiness_audit.py",
            "```",
            "",
            f"Report digest: `{report['report_digest']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail unless the checked-in JSON and Markdown reports match the assessment source",
    )
    arguments = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[3]
    evidence_dir = repository_root / "docs/evidence"
    assessment_path = evidence_dir / "canonical-node-readiness-assessments.json"
    census_path = evidence_dir / "m4-node-contract-census.json"
    repair_map_path = evidence_dir / "canonical-node-project-repair-map.json"
    duplication_path = evidence_dir / "canonical-node-near-duplicate-families.json"
    manifest_path = evidence_dir / "canonical-node-qualification-manifest.json"

    source = _load_json(assessment_path)
    census = _load_json(census_path)
    repair_map = _load_json(repair_map_path)
    duplication = _load_json(duplication_path)
    _require(source.get("schema_version") == _ASSESSMENT_SCHEMA, "unexpected assessment schema")
    _require(source.get("registry_digest") == census.get("registry_digest"), "assessment registry digest is stale")
    retired_node_types = source.get("retired_node_types")
    retired_registry_digest = source.get("retired_registry_digest")
    _require(
        isinstance(retired_node_types, list)
        and retired_node_types == sorted(set(retired_node_types))
        and all(isinstance(node_type, str) for node_type in retired_node_types),
        "retired assessment node types are not closed and sorted",
    )
    _require(
        isinstance(retired_registry_digest, str) and len(retired_registry_digest) == 64,
        "retired assessment registry digest is invalid",
    )
    _require(repair_map.get("registry_digest") == census.get("registry_digest"), "repair map and census disagree")
    _require(duplication.get("schema_version") == _DUPLICATION_SCHEMA, "unexpected near-duplicate schema")
    duplicate_pairs = duplication.get("pairs")
    duplicate_annotations = duplication.get("node_annotations")
    duplicate_counts = duplication.get("classification_counts")
    _require(isinstance(duplicate_pairs, list), "near-duplicate pairs must be a list")
    _require(isinstance(duplicate_annotations, dict), "near-duplicate node annotations must be an object")
    _require(isinstance(duplicate_counts, dict), "near-duplicate classification counts must be an object")
    _require(
        duplication.get("total_unique_pairs") == len(duplicate_pairs),
        "near-duplicate pair count is inconsistent",
    )
    _require(
        duplicate_counts.get("verification_critical") == 0,
        "verification-critical duplicated logic must be shared before readiness publication",
    )

    paired = source.get("paired_qualification")
    pair: dict[str, Any] | None = None
    paired_evidence_ref: str | None = None
    if paired is not None:
        _require(isinstance(paired, dict), "paired qualification authority must be an object")
        _require(
            set(paired) == {"macos_receipt", "ubuntu_receipt", "pair_receipt", "product_projection", "pair_digest"},
            "paired qualification fields are incomplete",
        )
        for key in ("macos_receipt", "ubuntu_receipt", "pair_receipt", "product_projection"):
            _require(isinstance(paired[key], str), f"paired qualification {key} must be a path")
            _require((repository_root / paired[key]).is_file(), f"paired qualification {key} is missing")
        qualification = _qualification_authority()
        pair = qualification.validate_retained_pair(repository_root, _load_json(manifest_path))
        _require(pair["pair_digest"] == paired["pair_digest"], "assessment pair digest is stale")
        _require(pair["source_revision"] == source["baseline_commit"], "assessment baseline is not qualified revision")
        _require(paired["pair_receipt"] == qualification._RETAINED_PAIR, "assessment cites another pair receipt")
        _require(
            paired["product_projection"] == qualification._RETAINED_PRODUCT_PROJECTION,
            "assessment cites another product projection",
        )
        paired_evidence_ref = paired["pair_receipt"]

    census_by_node = {row["node_type"]: row for row in census["nodes"]}
    map_by_node = {row["node_type"]: row for row in repair_map["nodes"]}
    assessment_rows = source.get("nodes")
    _require(isinstance(assessment_rows, list), "assessment nodes must be a list")
    for row in assessment_rows:
        _require(isinstance(row, dict), "every assessment must be an object")
        _validate_assessment(
            row,
            repository_root=repository_root,
            paired_evidence_ref=paired_evidence_ref,
        )
    assessment_by_node = {row["node_type"]: row for row in assessment_rows}
    _require(len(assessment_by_node) == len(assessment_rows), "duplicate node assessment")
    expected_nodes = set(census_by_node)
    _require(
        set(duplicate_annotations) <= expected_nodes,
        f"near-duplicate annotations contain unknown nodes: {sorted(set(duplicate_annotations) - expected_nodes)}",
    )
    _require(set(map_by_node) == expected_nodes, "repair map node set differs from census")
    _require(
        set(assessment_by_node) == expected_nodes | set(retired_node_types),
        f"assessment node mismatch: missing={sorted(expected_nodes - set(assessment_by_node))}, "
        f"extra={sorted(set(assessment_by_node) - expected_nodes - set(retired_node_types))}",
    )
    _require(
        all(
            "superseded_duplicate" in assessment_by_node[node_type]["fault_patterns"]
            for node_type in retired_node_types
        ),
        "retired assessment rows are not explicitly superseded",
    )
    _require(
        all(
            ("missing_explicit_policy" in assessment_by_node[node_type]["fault_patterns"])
            == (not bool(census_by_node[node_type].get("policy", {}).get("explicit")))
            for node_type in expected_nodes
        ),
        "assessment explicit-policy findings disagree with the registry census",
    )
    managed_nodes = {
        node_type
        for node_type, row in census_by_node.items()
        if row.get("managed_optimization_profile", {}).get("eligible") is True
    }
    _require(
        all(census_by_node[node_type]["execution_contract"]["payload"]["citations"] for node_type in managed_nodes),
        "every managed optimization operation must bind at least one scientific reference",
    )
    _require(
        all(
            "missing_scientific_reference" not in assessment_by_node[node_type]["fault_patterns"]
            and "execution_projection_divergence" not in assessment_by_node[node_type]["fault_patterns"]
            for node_type in managed_nodes
        ),
        "managed optimization assessments may not retain citation or execution-projection gaps",
    )

    rows: list[dict[str, Any]] = []
    for node_type in sorted(expected_nodes):
        assessment = assessment_by_node[node_type]
        census_row = census_by_node[node_type]
        map_row = map_by_node[node_type]
        rows.append(
            {
                **assessment,
                "family": map_row["family"],
                "contract_complete": census_row["contract_complete"],
                "contract_status": census_row["catalog_classification"]["contract_status"],
                "lifecycle_kind": census_row["catalog_classification"]["lifecycle_kind"],
                "typed_port_status": census_row["catalog_classification"]["typed_port_status"],
                "retention_decision": map_row["retention_decision"],
                "repair_gaps": map_row["repair_gaps"],
                "consumer_bindings": map_row["consumer_bindings"],
                "near_duplicate_families": duplicate_annotations.get(node_type, []),
            }
        )

    star_counts = Counter(str(row["stars"]) for row in rows)
    criticality_counts = Counter(row["criticality"] for row in rows)
    pattern_counts = Counter(pattern for row in rows for pattern in row["fault_patterns"])
    family_stars: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        family_stars[row["family"]][str(row["stars"])] += 1

    source_artifacts = {
        "assessment_sha256": _sha256_portable_text_file(assessment_path),
        "census_sha256": _sha256_portable_text_file(census_path),
        "repair_map_sha256": _sha256_portable_text_file(repair_map_path),
        "near_duplicate_families_sha256": _sha256_portable_text_file(duplication_path),
    }
    if pair is not None:
        assert isinstance(paired, dict)
        source_artifacts.update(
            {
                "qualification_macos_sha256": _sha256_portable_text_file(repository_root / paired["macos_receipt"]),
                "qualification_ubuntu_sha256": _sha256_portable_text_file(repository_root / paired["ubuntu_receipt"]),
                "qualification_pair_sha256": _sha256_portable_text_file(repository_root / paired["pair_receipt"]),
                "qualification_product_projection_sha256": _sha256_portable_text_file(
                    repository_root / paired["product_projection"]
                ),
            }
        )

    report: dict[str, Any] = {
        "schema_version": _REPORT_SCHEMA,
        "audit_date": source["audit_date"],
        "baseline_commit": source["baseline_commit"],
        "registry_digest": census["registry_digest"],
        "retired_assessment": {
            "node_types": retired_node_types,
            "registry_digest": retired_registry_digest,
        },
        "source_artifacts": source_artifacts,
        "aggregates": {
            "total_nodes": len(rows),
            "stars": {str(star): star_counts[str(star)] for star in range(1, 6)},
            "criticality": {key: criticality_counts[key] for key in sorted(_CRITICALITY)},
            "priority_nodes": star_counts["1"] + star_counts["2"],
            "fault_patterns": dict(sorted(pattern_counts.items(), key=lambda item: (-item[1], item[0]))),
            "family_stars": {
                family: {str(star): counts[str(star)] for star in range(1, 6)}
                for family, counts in sorted(family_stars.items())
            },
            "near_duplicates": {
                "total_unique_pairs": len(duplicate_pairs),
                "total_families": duplication.get("total_families", 0),
                "affected_nodes": len(duplicate_annotations),
                **{key: duplicate_counts.get(key, 0) for key in sorted(duplicate_counts)},
            },
        },
        "nodes": rows,
    }
    if pair is not None:
        report["paired_qualification"] = pair
    report["report_digest"] = hashlib.sha256(_canonical_bytes(report)).hexdigest()
    generated = {
        evidence_dir / "canonical-node-readiness-audit.json": (json.dumps(report, indent=2, sort_keys=True) + "\n"),
        evidence_dir / "canonical-node-readiness-audit.md": _render_markdown(report),
    }
    if arguments.check:
        for path, expected in generated.items():
            _require(path.is_file(), f"missing generated report: {path}")
            _require(
                path.read_text(encoding="utf-8") == expected,
                f"generated report is stale: {path}",
            )
        return
    for path, content in generated.items():
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
