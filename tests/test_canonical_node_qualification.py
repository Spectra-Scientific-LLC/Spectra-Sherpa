"""Integrity tests for the all-node paired-platform qualification authority."""

from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_TOOL_PATH = _REPOSITORY_ROOT / "packages/spectra-sherpa/tools/qualify_canonical_node_baseline.py"
_MANIFEST_PATH = _REPOSITORY_ROOT / "docs/evidence/canonical-node-qualification-manifest.json"
_MACOS_RECEIPT_PATH = _REPOSITORY_ROOT / "docs/evidence/canonical-node-qualification-macos.json"
_UBUNTU_RECEIPT_PATH = _REPOSITORY_ROOT / "docs/evidence/canonical-node-qualification-ubuntu.json"
_PAIR_RECEIPT_PATH = _REPOSITORY_ROOT / "docs/evidence/canonical-node-paired-qualification.json"
_PRODUCT_PROJECTION_PATH = _REPOSITORY_ROOT / "docs/evidence/canonical-node-qualified-product-projection.json"
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github/workflows/canonical-node-qualification.yml"


def _load_tool() -> dict[str, object]:
    return runpy.run_path(str(_TOOL_PATH), run_name="canonical_node_qualification_test")


def test_checked_qualification_manifest_is_current_and_total() -> None:
    result = subprocess.run(
        [sys.executable, str(_TOOL_PATH), "check", "--manifest", str(_MANIFEST_PATH)],
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["node_count"] == 101
    assert len(manifest["nodes"]) == 101
    assert len({row["node_type"] for row in manifest["nodes"]}) == 101
    assert all(row["consumer_test_id"] for row in manifest["nodes"])
    assert all(row["evidence_files"] for row in manifest["nodes"])
    assert "test_paths" not in manifest
    assert "test_selectors" not in manifest
    assert [batch["batch_id"] for batch in manifest["test_batches"]] == [
        "native-opus-clean-room",
        "canonical-node-evidence",
    ]
    selectors = [selector for batch in manifest["test_batches"] for selector in batch["selectors"]]
    assert len(selectors) == len(set(selectors))


def test_file_load_qualification_executes_public_native_conformance_without_private_custody() -> None:
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    batches = {batch["batch_id"]: batch["selectors"] for batch in manifest["test_batches"]}
    clean_room = batches["native-opus-clean-room"]
    selectors = [selector for values in batches.values() for selector in values]

    assert (
        "packages/spectra-sherpa/tests/test_native_omnic_ingestion.py::"
        "test_external_exact_hash_omnic_reference_science_when_available"
    ) in selectors
    assert "packages/spectra-sherpa/tests/test_native_opus_qualification.py" in selectors
    assert clean_room == ["packages/spectra-sherpa/tests/test_native_opus_qualification.py"]
    assert "packages/spectra-sherpa/tests/test_native_vendor_conformance_guards.py" in selectors
    assert not any("private_nxr_kinetics" in selector for selector in selectors)

    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "tools/provision_external_vendor_conformance.py" in workflow
    assert "SPECTRA_REQUIRE_EXTERNAL_VENDOR_CORPUS=1" in workflow
    job_configuration = workflow.split("    steps:", 1)[0]
    assert "${{ runner.temp }}" not in job_configuration
    assert "MPLCONFIGDIR=$RUNNER_TEMP/matplotlib" in workflow
    assert 'poetry install --with dev --extras "scp nist" --no-root' in workflow
    assert "poetry run pip install --no-deps --no-cache-dir --force-reinstall --editable ." in workflow


def test_retained_pair_reproduces_and_remains_bound_to_current_node_product(monkeypatch) -> None:
    tool = _load_tool()
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    assessments = json.loads(
        (_REPOSITORY_ROOT / "docs/evidence/canonical-node-readiness-assessments.json").read_text(encoding="utf-8")
    )
    if "paired_qualification" not in assessments:
        # A changed product is intentionally four-star until the manifest is
        # executed on both platforms. Old retained receipts remain historical
        # files, but are not current authority and must not validate this manifest.
        assert manifest == tool["build_manifest"](_REPOSITORY_ROOT)
        with pytest.raises(
            tool["QualificationError"],
            match="does not cover 91 nodes|binds another manifest",
        ):
            tool["validate_retained_pair"](_REPOSITORY_ROOT, manifest)
        return

    pair = tool["validate_retained_pair"](_REPOSITORY_ROOT, manifest)
    checked_pair = json.loads(_PAIR_RECEIPT_PATH.read_text(encoding="utf-8"))
    macos = json.loads(_MACOS_RECEIPT_PATH.read_text(encoding="utf-8"))
    ubuntu = json.loads(_UBUNTU_RECEIPT_PATH.read_text(encoding="utf-8"))

    assert pair == checked_pair
    assert pair["source_revision"] == assessments["baseline_commit"]
    assert len(pair["source_tree"]) == 40
    assert pair["node_count"] == 91
    assert pair["passed_test_count"] > 0
    assert pair["platform_receipts"] == {
        "Darwin": macos["receipt_digest"],
        "Linux": ubuntu["receipt_digest"],
    }
    assert macos["platform"]["system"] == "Darwin"
    assert ubuntu["platform"]["system"] == "Linux"

    monkeypatch.setitem(tool["validate_retained_pair"].__globals__, "_git_commit_available", lambda *_: False)
    assert tool["validate_retained_pair"](_REPOSITORY_ROOT, manifest) == checked_pair
    projection = json.loads(_PRODUCT_PROJECTION_PATH.read_text(encoding="utf-8"))
    assert projection["pair_digest"] == pair["pair_digest"]
    assert projection["source_revision"] == pair["source_revision"]


def test_node_science_projection_excludes_independently_qualified_non_node_surfaces() -> None:
    tool = _load_tool()
    projection = tool["_current_product_projection"](
        _REPOSITORY_ROOT,
        json.loads(_PAIR_RECEIPT_PATH.read_text(encoding="utf-8")),
    )
    excluded = projection["excluded_non_node_surfaces"]
    assert excluded == [
        "packages/spectra-sherpa/src/spectra_sherpa/static/**",
        "packages/spectra-sherpa/src/spectra_sherpa/sdk/__init__.py",
        "packages/spectra-sherpa/src/spectra_sherpa/sdk/canonical_public_fixture.py",
    ]

    pathspecs = tool["_qualified_product_pathspecs"]()
    result = subprocess.run(
        ["git", "ls-files", "--", *pathspecs],
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    projected = set(result.stdout.splitlines())
    assert "packages/spectra-sherpa/src/spectra_sherpa/sdk/data.py" in projected
    assert "packages/spectra-sherpa/src/spectra_sherpa/sdk/__init__.py" not in projected
    assert "packages/spectra-sherpa/src/spectra_sherpa/sdk/canonical_public_fixture.py" not in projected
    assert not any(path.startswith("packages/spectra-sherpa/src/spectra_sherpa/static/") for path in projected)


def test_pair_verifier_requires_two_platforms_and_identical_test_identity(tmp_path: Path) -> None:
    tool = _load_tool()
    digest = tool["_digest"]
    verify_pair = tool["verify_pair"]
    error = tool["QualificationError"]

    def receipt(system: str, passed_digest: str) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": "spectra-canonical-node-platform-receipt/1",
            "source_revision": "a" * 40,
            "source_tree": "b" * 40,
            "manifest_digest": "c" * 64,
            "registry_digest": "d" * 64,
            "project_map_digest": "e" * 64,
            "node_count": 91,
            "qualified_node_types": [f"node.{index:02d}" for index in range(91)],
            "platform": {"system": system, "release": "test", "machine": "test", "python": "3.11.0"},
            "scientific_runtime": {
                "h5py": "3.16.0",
                "numpy": "1.26.4",
                "pandas": "2.3.2",
                "scikit-learn": "1.9.0",
                "scipy": "1.17.1",
                "spectrochempy": "0.8.1",
            },
            "tests": {
                "batches": [
                    {
                        "batch_id": "native-opus-clean-room",
                        "passed": 18,
                        "passed_test_ids_sha256": "1" * 64,
                    },
                    {
                        "batch_id": "canonical-node-evidence",
                        "passed": 105,
                        "passed_test_ids_sha256": "2" * 64,
                    },
                ],
                "passed": 123,
                "failed": 0,
                "errors": 0,
                "skipped": 0,
                "passed_test_ids_sha256": passed_digest,
            },
            "completed_at": "2026-09-02T00:00:00+00:00",
        }
        value["receipt_digest"] = digest(value)
        return value

    mac_path = tmp_path / "mac.json"
    linux_path = tmp_path / "linux.json"
    output_path = tmp_path / "pair.json"
    mac_path.write_text(json.dumps(receipt("Darwin", "f" * 64)), encoding="utf-8")
    linux_path.write_text(json.dumps(receipt("Linux", "f" * 64)), encoding="utf-8")

    pair = verify_pair(mac_path, linux_path, output_path)
    assert pair["node_count"] == 91
    assert set(pair["platform_receipts"]) == {"Darwin", "Linux"}

    linux_path.write_text(json.dumps(receipt("Linux", "0" * 64)), encoding="utf-8")
    with pytest.raises(error, match="different test identities"):
        verify_pair(mac_path, linux_path, output_path)
