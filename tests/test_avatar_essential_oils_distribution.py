from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import struct
import sys
import types
import zipfile
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).parents[3]
TOOL_PATH = REPO_ROOT / "packages" / "spectra-sherpa" / "tools" / "avatar_essential_oils_distribution.py"
SPEC = importlib.util.spec_from_file_location("avatar_essential_oils_distribution", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


@pytest.fixture(autouse=True)
def _isolate_spectrochempy_module_state() -> Any:
    retained = {
        name: module
        for name, module in tuple(sys.modules.items())
        if name == "spectrochempy" or name.startswith("spectrochempy.")
    }
    for name in retained:
        sys.modules.pop(name, None)
    try:
        yield
    finally:
        for name in tuple(sys.modules):
            if name == "spectrochempy" or name.startswith("spectrochempy."):
                sys.modules.pop(name, None)
        sys.modules.update(retained)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    rows: list[dict[str, Any]] = []
    definition_rows: list[dict[str, Any]] = []
    projections: dict[str, dict[str, Any]] = {}
    for block in (1, 2, 3):
        for order in range(1, 12):
            specimen = f"S{order:02d}"
            sample = f"{specimen}__B{block}"
            name = f"{sample}.spa"
            content = f"synthetic-SPA:{sample}\n".encode()
            (source_dir / name).write_bytes(content)
            values_sha = _sha(f"values:{sample}".encode())
            axis_sha = _sha(b"axis")
            row = {
                "distribution_filename": name,
                "curated_sha256": _sha(content),
                "size_bytes": len(content),
                "sample_id": sample,
                "specimen_id": specimen,
                "block": block,
                "acquisition_order": order,
                "evidence_status": "pending_exact_citation" if specimen == "S01" else "not_applicable",
                "format_id": "omnic",
                "variant": "spa-single-spectrum",
                "parser_id": "spectrasherpa.omnic",
                "parser_version": "1",
                "asset_id": "spectrum",
                "shape": [1, 1868],
                "axis_units": "cm-1",
                "feature_axis_order": "strictly_descending",
                "value_units": "absorbance",
                "values_sha256": values_sha,
                "axis_sha256": axis_sha,
            }
            rows.append(row)
            projections[name] = {
                field: row[field]
                for field in (
                    "format_id",
                    "variant",
                    "parser_id",
                    "parser_version",
                    "asset_id",
                    "shape",
                    "axis_units",
                    "value_units",
                    "values_sha256",
                    "axis_sha256",
                )
            }
            annotations = {
                "sample_id": sample,
                "specimen_id": specimen,
                "block": block,
                "acquisition_order": order,
                "curated_filename": name,
                "curated_sha256": _sha(content),
                "evidence_status": row["evidence_status"],
                "evidence_citation_id": None,
            }
            definition_rows.append(
                {
                    "file_name": f"raw/{name}",
                    "sha256": _sha(content),
                    "asset_id": "spectrum",
                    "source_row_index": 0,
                    "sample_id": sample,
                    "annotations": annotations,
                }
            )

    manifest = {
        "schema_version": "spectrasherpa-avatar-essential-oils-public-manifest/2",
        "dataset_id": TOOL.DATASET_ID,
        "dataset_version": 1,
        "claim_boundary": "Parser and workflow validation only; no authenticity or population claim.",
        "files": rows,
    }
    definition = {
        "schema_version": "spectrasherpa-collection-definition/1",
        "collection": {"dataset_id": "avatar-essential-oils/1:canonical-phase4"},
        "columns": list(definition_rows[0]["annotations"]),
        "rows": definition_rows,
    }
    manifest_path = tmp_path / "manifest.json"
    definition_path = tmp_path / "definition.json"
    _write_json(manifest_path, manifest)
    _write_json(definition_path, definition)
    authority = {
        "schema_version": TOOL.RELEASE_AUTHORITY_SCHEMA,
        "dataset_id": TOOL.DATASET_ID,
        "dataset_version": 1,
        "dataset_title": TOOL.DATASET_TITLE,
        "status": "approved_for_unpublished_distribution_candidate",
        "license": TOOL.LICENSE,
        "license_url": TOOL.LICENSE_URL,
        "license_authorization_sha256": TOOL.LICENSE_AUTHORIZATION_SHA256,
        "source_manifest_sha256": _sha(manifest_path.read_bytes()),
        "collection_definition_sha256": _sha(definition_path.read_bytes()),
        "creator_display_name": "Example Data Creator",
        "licensor_display_name": "Example Data Licensor",
        "canonical_attribution_statement": "Example Data Creator (2026), Lavender Essential Oil FTIR Corpus v1.",
        "citation_policy": {
            "status": "no_external_publication_citations_applicable",
            "basis": "original_unpublished_laboratory_dataset",
            "statement": "This is an original unpublished laboratory dataset; no external publication citations apply.",
            "external_publication_citation_count": 0,
        },
        "citations": [],
        "privacy_review": {
            "status": "passed",
            "reviewed_on": "2026-08-26",
            "reviewer_role": "dataset rights holder",
            "supplier_crosswalk_absent": True,
            "supplier_identity_absent": True,
            "supplier_identifying_metadata_absent": True,
            "private_paths_and_ids_absent": True,
            "non_oil_references_absent": True,
        },
        "limitations": [
            "Technical acquisition replicates only; not a population study.",
            "Labels do not establish botanical authenticity or future-lot performance.",
        ],
    }
    authority_path = tmp_path / "authority.json"
    _write_json(authority_path, authority)
    monkeypatch.setattr(TOOL, "_native_projection", lambda name, _content: dict(projections[name]))
    return {
        "source_dir": source_dir,
        "manifest_path": manifest_path,
        "definition_path": definition_path,
        "authority_path": authority_path,
        "authority": authority,
    }


def _build(tmp_path: Path, fixture: dict[str, Any], name: str = "avatar.zip") -> tuple[Path, dict[str, Any]]:
    archive = tmp_path / name
    receipt = TOOL.build_distribution(
        source_manifest_path=fixture["manifest_path"],
        collection_definition_path=fixture["definition_path"],
        release_authority_path=fixture["authority_path"],
        source_dir=fixture["source_dir"],
        output_path=archive,
    )
    return archive, receipt


def test_avatar_distribution_is_deterministic_closed_and_correction_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    first, receipt = _build(tmp_path, fixture, "first.zip")
    second, repeated = _build(tmp_path, fixture, "second.zip")

    assert first.read_bytes() == second.read_bytes()
    assert receipt == repeated
    assert receipt["status"] == "unpublished_distribution_candidate_validated"
    assert receipt["dataset_title"] == TOOL.DATASET_TITLE
    assert receipt["creator_display_name"] == "Example Data Creator"
    assert receipt["licensor_display_name"] == "Example Data Licensor"
    assert receipt["external_publication_citation_count"] == 0
    assert receipt["privacy_review_complete"] is True
    assert receipt["member_count"] == 41
    assert receipt["correction"] == "None"
    assert receipt["raw_publication_performed"] is False
    if os.name != "nt":
        assert stat_mode(first) == 0o600

    with zipfile.ZipFile(first) as archive:
        assert len(archive.infolist()) == 41
        assert all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist())
        manifest = json.loads(archive.read(f"{TOOL.PACKAGE_ROOT}/manifest.json"))
        assert manifest["acquisition_method"]["correction"] == "None"
        assert manifest["counts"] == {"files": 33, "specimens": 11, "blocks": 3}
        resolved = json.loads(archive.read(f"{TOOL.PACKAGE_ROOT}/collection-definition.json"))
        cited = [row for row in resolved["rows"] if row["annotations"]["specimen_id"] == "S01"]
        assert {row["annotations"]["evidence_status"] for row in cited} == {
            "original_lab_dataset_no_external_publication_citation"
        }
        assert {row["annotations"]["evidence_citation_id"] for row in cited} == {None}


def test_archive_identity_is_independent_of_current_parser_source_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    first_authority = {
        "distribution_tool_sha256": "1" * 64,
        "native_module_count": 20,
        "native_module_projection_sha256": "2" * 64,
    }
    second_authority = {
        "distribution_tool_sha256": "3" * 64,
        "native_module_count": 21,
        "native_module_projection_sha256": "4" * 64,
    }
    monkeypatch.setattr(TOOL, "_implementation_authority", lambda: dict(first_authority))
    first, first_receipt = _build(tmp_path, fixture, "implementation-first.zip")
    monkeypatch.setattr(TOOL, "_implementation_authority", lambda: dict(second_authority))
    second, second_receipt = _build(tmp_path, fixture, "implementation-second.zip")

    assert first.read_bytes() == second.read_bytes()
    assert first_receipt["archive_sha256"] == second_receipt["archive_sha256"]
    assert first_receipt["implementation_authority"] == first_authority
    assert second_receipt["implementation_authority"] == second_authority
    with zipfile.ZipFile(first) as archive:
        manifest = json.loads(archive.read(f"{TOOL.PACKAGE_ROOT}/manifest.json"))
    assert manifest["schema_version"] == TOOL.PACKAGE_MANIFEST_SCHEMA
    assert "implementation_authority" not in manifest


def test_source_preflight_is_nonpublishing_and_names_exact_pending_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    receipt = TOOL.preflight_sources(
        source_manifest_path=fixture["manifest_path"],
        collection_definition_path=fixture["definition_path"],
        source_dir=fixture["source_dir"],
    )
    assert receipt["status"] == "source_science_admitted_release_authority_pending"
    assert receipt["file_count"] == 33
    assert receipt["specimen_count"] == 11
    assert receipt["blocks"] == [1, 2, 3]
    assert receipt["historical_pending_citation_specimen_ids"] == ["S01"]
    assert receipt["archive_created"] is False
    assert receipt["required_release_authorities"] == [
        "creator_display_name",
        "licensor_display_name",
        "canonical_attribution_statement",
        "laboratory_origin_no_external_publication_citations",
        "repeated_privacy_and_package_content_review",
    ]


def test_source_preflight_refuses_a_process_that_already_loaded_spectrochempy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    sys.modules["spectrochempy"] = types.ModuleType("spectrochempy")
    with pytest.raises(TOOL.DistributionError, match="must remain unloaded"):
        TOOL.preflight_sources(
            source_manifest_path=fixture["manifest_path"],
            collection_definition_path=fixture["definition_path"],
            source_dir=fixture["source_dir"],
        )


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda authority: authority.__setitem__("creator_display_name", "pending"), "placeholder"),
        (lambda authority: authority.__setitem__("citations", [{"invented": True}]), "must not manufacture"),
        (
            lambda authority: authority["privacy_review"].__setitem__("supplier_identity_absent", False),
            "supplier_identity_absent",
        ),
        (
            lambda authority: authority["citation_policy"].__setitem__("external_publication_citation_count", 1),
            "exact integer zero",
        ),
    ],
)
def test_release_authority_refuses_incomplete_legal_scientific_or_privacy_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: Any,
    message: str,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    mutation(fixture["authority"])
    _write_json(fixture["authority_path"], fixture["authority"])
    with pytest.raises(TOOL.DistributionError, match=message):
        _build(tmp_path, fixture)


def test_private_review_candidate_requires_truthful_pending_privacy_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    fixture["authority"]["status"] = "approved_for_private_package_review"
    fixture["authority"]["privacy_review"] = {
        "status": "pending_candidate_content_review",
        "reviewed_on": None,
        "reviewer_role": None,
        "supplier_crosswalk_absent": None,
        "supplier_identity_absent": None,
        "supplier_identifying_metadata_absent": None,
        "private_paths_and_ids_absent": None,
        "non_oil_references_absent": None,
    }
    _write_json(fixture["authority_path"], fixture["authority"])
    _archive, receipt = _build(tmp_path, fixture)
    assert receipt["status"] == "private_package_review_candidate_validated"
    assert receipt["privacy_review_complete"] is False

    fixture["authority"]["privacy_review"]["supplier_identity_absent"] = True
    _write_json(fixture["authority_path"], fixture["authority"])
    with pytest.raises(TOOL.DistributionError, match="exact pending privacy review"):
        _build(tmp_path, fixture, "mixed-privacy.zip")


def test_release_authority_refuses_duplicate_keys_even_with_valid_last_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    original = fixture["authority_path"].read_text()
    fixture["authority_path"].write_text(
        original.replace('"license": "CC-BY-4.0"', '"license": "CC0-1.0",\n  "license": "CC-BY-4.0"')
    )
    with pytest.raises(TOOL.DistributionError, match="duplicate key"):
        _build(tmp_path, fixture)


def test_source_inventory_and_source_bytes_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    extra = fixture["source_dir"] / "extra.spa"
    extra.write_bytes(b"extra")
    with pytest.raises(TOOL.DistributionError, match="extra"):
        _build(tmp_path, fixture, "extra.zip")
    extra.unlink()

    source = fixture["source_dir"] / "S01__B1.spa"
    source.write_bytes(b"changed-source")
    with pytest.raises(TOOL.DistributionError, match="frozen manifest"):
        _build(tmp_path, fixture, "changed.zip")


def test_source_symlink_and_existing_output_refuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    source = fixture["source_dir"] / "S01__B1.spa"
    target = tmp_path / "target.spa"
    target.write_bytes(source.read_bytes())
    source.unlink()
    try:
        source.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(TOOL.DistributionError, match="linked"):
        _build(tmp_path, fixture, "linked.zip")

    source.unlink()
    source.write_bytes(target.read_bytes())
    output = tmp_path / "existing.zip"
    output.write_bytes(b"retain")
    with pytest.raises(TOOL.DistributionError, match="already exists"):
        _build(tmp_path, fixture, "existing.zip")
    assert output.read_bytes() == b"retain"


def _rewrite_archive(path: Path, mutation: Any) -> None:
    with zipfile.ZipFile(path) as source:
        rows = [(info.filename, source.read(info)) for info in source.infolist()]
    mutation(rows)
    replacement = path.with_suffix(".mutated")
    with zipfile.ZipFile(replacement, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in rows:
            info = zipfile.ZipInfo(name, TOOL.ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    os.replace(replacement, path)


def test_archive_source_and_metadata_mutations_refuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    source_archive, _receipt = _build(tmp_path, fixture, "source-mutation.zip")

    def mutate_source(rows: list[tuple[str, bytes]]) -> None:
        for index, (name, content) in enumerate(rows):
            if name.endswith("/data/S01__B1.spa"):
                rows[index] = (name, b"X" + content[1:])
                return

    _rewrite_archive(source_archive, mutate_source)
    with pytest.raises(TOOL.DistributionError, match="frozen identity"):
        TOOL.validate_distribution(
            archive_path=source_archive,
            source_manifest_path=fixture["manifest_path"],
            collection_definition_path=fixture["definition_path"],
            release_authority_path=fixture["authority_path"],
        )

    metadata_archive, _receipt = _build(tmp_path, fixture, "metadata-mutation.zip")

    def mutate_metadata(rows: list[tuple[str, bytes]]) -> None:
        for index, (name, content) in enumerate(rows):
            if name.endswith("/ATTRIBUTION.md"):
                rows[index] = (name, content + b"Changed\n")
                return

    _rewrite_archive(metadata_archive, mutate_metadata)
    with pytest.raises(TOOL.DistributionError, match="reconstructed closed package"):
        TOOL.validate_distribution(
            archive_path=metadata_archive,
            source_manifest_path=fixture["manifest_path"],
            collection_definition_path=fixture["definition_path"],
            release_authority_path=fixture["authority_path"],
        )


def test_forged_low_eocd_count_refuses_before_zipfile_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    archive, _receipt = _build(tmp_path, fixture)
    content = bytearray(archive.read_bytes())
    eocd = content.rfind(b"PK\x05\x06")
    assert eocd >= 0
    struct.pack_into("<HH", content, eocd + 8, 1, 1)
    archive.write_bytes(content)
    monkeypatch.setattr(TOOL.zipfile, "ZipFile", lambda *_args, **_kwargs: pytest.fail("ZipFile reached"))
    with pytest.raises(TOOL.DistributionError, match="member count"):
        TOOL.validate_distribution(
            archive_path=archive,
            source_manifest_path=fixture["manifest_path"],
            collection_definition_path=fixture["definition_path"],
            release_authority_path=fixture["authority_path"],
        )


def test_public_metadata_refuses_private_paths_and_supplier_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    fixture["authority"]["limitations"].append("Private path /Users/example/supplier_crosswalk.json")
    _write_json(fixture["authority_path"], fixture["authority"])
    with pytest.raises(TOOL.DistributionError, match="privacy-bearing"):
        _build(tmp_path, fixture)


def test_raw_source_privacy_scan_and_repository_output_guard_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    source = fixture["source_dir"] / "S01__B1.spa"
    private_content = b"operator=/Users/scientist/private/sample.spa"
    source.write_bytes(private_content)
    manifest = json.loads(fixture["manifest_path"].read_text())
    definition = json.loads(fixture["definition_path"].read_text())
    manifest["files"][0]["curated_sha256"] = _sha(private_content)
    manifest["files"][0]["size_bytes"] = len(private_content)
    definition["rows"][0]["sha256"] = _sha(private_content)
    definition["rows"][0]["annotations"]["curated_sha256"] = _sha(private_content)
    _write_json(fixture["manifest_path"], manifest)
    _write_json(fixture["definition_path"], definition)
    fixture["authority"]["source_manifest_sha256"] = _sha(fixture["manifest_path"].read_bytes())
    fixture["authority"]["collection_definition_sha256"] = _sha(fixture["definition_path"].read_bytes())
    _write_json(fixture["authority_path"], fixture["authority"])
    with pytest.raises(TOOL.DistributionError, match="raw source .* privacy-bearing"):
        _build(tmp_path, fixture)

    with pytest.raises(TOOL.DistributionError, match="outside the repository"):
        TOOL._write_new_private(REPO_ROOT / "avatar-essential-oils-v1.zip", b"not-written")
    assert not (REPO_ROOT / "avatar-essential-oils-v1.zip").exists()
