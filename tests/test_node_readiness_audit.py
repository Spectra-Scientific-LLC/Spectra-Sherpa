"""Keep the canonical DAG node readiness audit complete and reproducible."""

from __future__ import annotations

import hashlib
import json
import runpy
import subprocess
import sys
from collections import Counter
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_ASSESSMENTS_PATH = _REPOSITORY_ROOT / "docs/evidence/canonical-node-readiness-assessments.json"
_AUDIT_PATH = _REPOSITORY_ROOT / "docs/evidence/canonical-node-readiness-audit.json"
_REPORT_PATH = _REPOSITORY_ROOT / "docs/evidence/canonical-node-readiness-audit.md"
_CENSUS_PATH = _REPOSITORY_ROOT / "docs/evidence/m4-node-contract-census.json"
_REPAIR_MAP_PATH = _REPOSITORY_ROOT / "docs/evidence/canonical-node-project-repair-map.json"
_DUPLICATION_PATH = _REPOSITORY_ROOT / "docs/evidence/canonical-node-near-duplicate-families.json"
_QUALIFICATION_MANIFEST_PATH = _REPOSITORY_ROOT / "docs/evidence/canonical-node-qualification-manifest.json"
_MACOS_RECEIPT_PATH = _REPOSITORY_ROOT / "docs/evidence/canonical-node-qualification-macos.json"
_UBUNTU_RECEIPT_PATH = _REPOSITORY_ROOT / "docs/evidence/canonical-node-qualification-ubuntu.json"
_PAIR_RECEIPT_PATH = _REPOSITORY_ROOT / "docs/evidence/canonical-node-paired-qualification.json"
_PRODUCT_PROJECTION_PATH = _REPOSITORY_ROOT / "docs/evidence/canonical-node-qualified-product-projection.json"
_GENERATOR_PATH = _REPOSITORY_ROOT / "packages/spectra-sherpa/tools/generate_node_readiness_audit.py"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_checked_readiness_report_is_the_deterministic_generator_output() -> None:
    result = subprocess.run(
        [sys.executable, str(_GENERATOR_PATH), "--check"],
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_source_artifact_digest_is_independent_of_checkout_line_endings(tmp_path: Path) -> None:
    generator = runpy.run_path(str(_GENERATOR_PATH))
    digest = generator["_sha256_portable_text_file"]
    logical_text = '{\n  "schema_version": "example/1"\n}\n'
    lf_path = tmp_path / "lf.json"
    crlf_path = tmp_path / "crlf.json"
    lf_path.write_bytes(logical_text.encode("utf-8"))
    crlf_path.write_bytes(logical_text.replace("\n", "\r\n").encode("utf-8"))

    expected = hashlib.sha256(logical_text.encode("utf-8")).hexdigest()
    assert digest(lf_path) == expected
    assert digest(crlf_path) == expected


def test_readiness_report_covers_every_registered_node_exactly_once() -> None:
    assessments = _load(_ASSESSMENTS_PATH)
    audit = _load(_AUDIT_PATH)
    census = _load(_CENSUS_PATH)
    repair_map = _load(_REPAIR_MAP_PATH)

    assessed_types = [row["node_type"] for row in assessments["nodes"]]
    audited_types = [row["node_type"] for row in audit["nodes"]]
    census_types = [row["node_type"] for row in census["nodes"]]
    mapped_types = [row["node_type"] for row in repair_map["nodes"]]

    retired = set(assessments["retired_node_types"])
    assert len(assessed_types) == len(set(assessed_types))
    assert retired == {
        "classification.predict",
        "data.my_dataset",
        "data.source",
        "diagnostics.holdout_evaluation",
        "model.pls",
        "model.pls_predict",
        "selection.sample_partition",
    }
    assert audited_types == sorted(audited_types)
    assert set(assessed_types) == set(census_types) | retired
    assert set(audited_types) == set(census_types) == set(mapped_types)
    assert audit["retired_assessment"] == {
        "node_types": sorted(retired),
        "registry_digest": assessments["retired_registry_digest"],
    }
    assert audit["registry_digest"] == census["registry_digest"] == repair_map["registry_digest"]


def test_readiness_aggregates_and_report_digest_are_self_consistent() -> None:
    audit = _load(_AUDIT_PATH)
    rows = audit["nodes"]
    stars = Counter(str(row["stars"]) for row in rows)
    criticality = Counter(row["criticality"] for row in rows)
    patterns = Counter(pattern for row in rows for pattern in row["fault_patterns"])

    assert audit["aggregates"]["total_nodes"] == len(rows)
    assert audit["aggregates"]["stars"] == {str(star): stars[str(star)] for star in range(1, 6)}
    assert audit["aggregates"]["criticality"] == {key: criticality[key] for key in ("none", "p0", "p1", "p2")}
    assert audit["aggregates"]["fault_patterns"] == dict(sorted(patterns.items(), key=lambda item: (-item[1], item[0])))
    unsigned = {key: value for key, value in audit.items() if key != "report_digest"}
    assert audit["report_digest"] == _canonical_digest(unsigned)


def test_every_active_node_is_five_star_only_through_the_retained_platform_pair() -> None:
    assessments = _load(_ASSESSMENTS_PATH)
    audit = _load(_AUDIT_PATH)
    manifest = _load(_QUALIFICATION_MANIFEST_PATH)
    macos = _load(_MACOS_RECEIPT_PATH)
    ubuntu = _load(_UBUNTU_RECEIPT_PATH)
    pair = _load(_PAIR_RECEIPT_PATH)
    product_projection = _load(_PRODUCT_PROJECTION_PATH)

    retired = set(assessments["retired_node_types"])
    active_assessments = [row for row in assessments["nodes"] if row["node_type"] not in retired]
    retired_assessments = [row for row in assessments["nodes"] if row["node_type"] in retired]
    pair_ref = str(_PAIR_RECEIPT_PATH.relative_to(_REPOSITORY_ROOT))

    assert len(active_assessments) == len(audit["nodes"]) == manifest["node_count"] == 101
    assert len(retired_assessments) == 7
    assert all(row["stars"] == 1 for row in retired_assessments)
    assert all("superseded_duplicate" in row["fault_patterns"] for row in retired_assessments)

    if "paired_qualification" not in assessments:
        assert "paired_qualification" not in audit
        assert audit["aggregates"]["stars"] == {"1": 0, "2": 0, "3": 0, "4": 101, "5": 0}
        assert audit["aggregates"]["criticality"] == {"none": 101, "p0": 0, "p1": 0, "p2": 0}
        assert audit["aggregates"]["fault_patterns"] == {"evidence_qualification_gap": 101}
        assert all(row["stars"] == 4 for row in active_assessments)
        assert all(row["fault_patterns"] == ["evidence_qualification_gap"] for row in active_assessments)
        assert all(pair_ref not in row["evidence_refs"] for row in active_assessments)
        return

    assert audit["aggregates"]["stars"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 91}
    assert audit["aggregates"]["criticality"] == {"none": 91, "p0": 0, "p1": 0, "p2": 0}
    assert audit["aggregates"]["fault_patterns"] == {}
    assert all(row["stars"] == 5 for row in active_assessments)
    assert all(row["criticality"] == "none" for row in active_assessments)
    assert all(row["fault_patterns"] == [] for row in active_assessments)
    assert all(row["next_star_blocker"] == "none" for row in active_assessments)
    assert all(pair_ref in row["evidence_refs"] for row in active_assessments)

    qualified_types = sorted(pair["qualified_node_types"])
    assert qualified_types == sorted(row["node_type"] for row in active_assessments)
    assert qualified_types == sorted(row["node_type"] for row in audit["nodes"])
    assert pair["node_count"] == 91
    assert pair["passed_test_count"] > 0
    assert pair["source_revision"] == assessments["baseline_commit"] == audit["baseline_commit"]
    assert pair["manifest_digest"] == manifest["manifest_digest"]
    assert pair["pair_digest"] == assessments["paired_qualification"]["pair_digest"]
    assert product_projection["pair_digest"] == pair["pair_digest"]
    assert product_projection["source_revision"] == pair["source_revision"]
    assert product_projection["file_count"] > 0
    assert audit["paired_qualification"] == pair
    assert pair["platform_receipts"] == {
        "Darwin": macos["receipt_digest"],
        "Linux": ubuntu["receipt_digest"],
    }
    for receipt in (macos, ubuntu):
        assert receipt["source_revision"] == pair["source_revision"]
        assert receipt["source_tree"] == pair["source_tree"]
        assert receipt["manifest_digest"] == pair["manifest_digest"]
        assert receipt["scientific_runtime"] == macos["scientific_runtime"]
        assert receipt["tests"]["passed"] == pair["passed_test_count"]
        assert receipt["tests"]["failed"] == 0
        assert receipt["tests"]["errors"] == 0
        assert receipt["tests"]["skipped"] == 0
        assert receipt["tests"]["passed_test_ids_sha256"] == pair["passed_test_ids_sha256"]


def test_readiness_projects_the_checked_near_duplicate_families_per_node() -> None:
    audit = _load(_AUDIT_PATH)
    duplication = _load(_DUPLICATION_PATH)
    expected = duplication["node_annotations"]

    assert duplication["classification_counts"]["verification_critical"] == 0
    assert audit["aggregates"]["near_duplicates"] == {
        "affected_nodes": len(expected),
        **duplication["classification_counts"],
        "total_families": duplication["total_families"],
        "total_unique_pairs": duplication["total_unique_pairs"],
    }
    for row in audit["nodes"]:
        assert row["near_duplicate_families"] == expected.get(row["node_type"], [])


def test_human_report_has_summary_table_and_one_section_per_node() -> None:
    audit = _load(_AUDIT_PATH)
    report = _REPORT_PATH.read_text(encoding="utf-8")

    assert "## Summary" in report
    assert "## Node-by-node table" in report
    assert "## Detailed evidence" in report
    assert report.count("\n### `") == len(audit["nodes"])
    for row in audit["nodes"]:
        node_type = row["node_type"]
        assert f"| `{node_type}` |" in report
        assert f"### `{node_type}` — {row['stars']} star" in report
