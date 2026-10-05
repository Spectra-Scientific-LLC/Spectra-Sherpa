from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from spectra_sherpa.app.lib import registered_reference_storage as storage


def _portable() -> dict[str, object]:
    return {
        "schema_version": "spectra-sherpa-external-reference/1",
        "projection_id": "fixture-projection-v1",
        "artifact_id": "fixture-artifact-v1",
        "artifact_size_bytes": 100,
        "artifact_sha256": "a" * 64,
        "member_path": "fixture.mat",
        "member_size_bytes": 10,
        "member_sha256": "b" * 64,
        "native_reader_contract": "spectrasherpa.matlab-dso/1",
        "scientific_sha256": "c" * 64,
        "provider": "Fixture Provider",
        "provider_page": "https://example.test/provider",
        "download_url": "https://example.test/file.zip",
        "redistribution": "upstream_only_not_redistributed",
    }


def test_sidecar_is_path_free_atomic_and_revalidated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    member = tmp_path / "qualified.mat"
    member.write_bytes(b"qualified")
    portable = _portable()
    monkeypatch.setattr(storage, "portable_reference_manifest", lambda _projection_id: dict(portable))

    sidecar = storage.write_registered_reference_sidecar(member, portable)
    admitted = storage.read_registered_reference_sidecar(member)

    assert admitted == portable
    if os.name != "nt":  # Windows uses the containing profile ACL.
        assert sidecar.stat().st_mode & 0o777 == 0o600
    serialized = sidecar.read_text()
    assert str(tmp_path) not in serialized
    assert member.name not in serialized
    assert not list(tmp_path.glob(f".{sidecar.name}.*"))


def test_ordinary_file_without_sidecar_is_not_reclassified(tmp_path: Path) -> None:
    ordinary = tmp_path / "customer-dataset.mat"
    ordinary.write_bytes(b"ordinary")

    assert storage.read_registered_reference_sidecar(ordinary) is None


def test_tampered_sidecar_refuses_against_active_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    member = tmp_path / "qualified.mat"
    member.write_bytes(b"qualified")
    portable = _portable()
    monkeypatch.setattr(storage, "portable_reference_manifest", lambda _projection_id: dict(portable))
    sidecar = storage.write_registered_reference_sidecar(member, portable)
    payload = json.loads(sidecar.read_text())
    payload["portable_reference"]["member_sha256"] = "d" * 64
    sidecar.write_text(json.dumps(payload))

    with pytest.raises(storage.RegisteredReferenceStorageError, match="active registry"):
        storage.read_registered_reference_sidecar(member)


def test_sidecar_symlink_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    member = tmp_path / "qualified.mat"
    member.write_bytes(b"qualified")
    portable = _portable()
    monkeypatch.setattr(storage, "portable_reference_manifest", lambda _projection_id: dict(portable))
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text("{}")
    storage.registered_reference_sidecar_path(member).symlink_to(elsewhere)

    with pytest.raises(storage.RegisteredReferenceStorageError, match="non-symlink"):
        storage.read_registered_reference_sidecar(member)


def test_sidecar_cleanup_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    member = tmp_path / "qualified.mat"
    member.write_bytes(b"qualified")
    portable = _portable()
    monkeypatch.setattr(storage, "portable_reference_manifest", lambda _projection_id: dict(portable))
    sidecar = storage.write_registered_reference_sidecar(member, portable)

    storage.remove_registered_reference_sidecar(member)
    storage.remove_registered_reference_sidecar(member)

    assert not sidecar.exists()


@pytest.mark.parametrize(
    "projection_id,scope",
    [
        ("public-corn-m5-moisture-v1", "registered_projection"),
        ("public-corn-mp5-moisture-v1", "registered_projection"),
        ("public-corn-mp6-moisture-v1", "registered_projection"),
        ("public-diesel-d4052-v1", "prepared_d4052_gatest_projection"),
    ],
)
def test_legacy_scope_is_read_from_registry_without_rewriting_sidecar(
    tmp_path: Path, projection_id: str, scope: str
) -> None:
    member = tmp_path / "qualified.mat"
    member.write_bytes(b"qualified")
    expected = storage.portable_reference_manifest(projection_id)
    sidecar = storage.write_registered_reference_sidecar(member, expected)
    payload = json.loads(sidecar.read_text())
    del payload["portable_reference"]["source_scope"]
    sidecar.write_text(json.dumps(payload))
    original = sidecar.read_bytes()

    admitted = storage.read_registered_reference_sidecar(member)

    assert admitted == expected
    assert admitted["source_scope"] == scope
    assert sidecar.read_bytes() == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_scope", None),
        ("source_scope", "unreviewed"),
        ("member_sha256", "0" * 64),
        ("artifact_sha256", "0" * 64),
        ("scientific_sha256", "0" * 64),
        ("analysis_profile", {}),
        ("schema_version", "spectra-sherpa-external-reference/1"),
        ("unexpected_field", "unreviewed"),
    ],
)
def test_legacy_scope_does_not_relax_other_registry_checks(tmp_path: Path, field: str, value: object) -> None:
    member = tmp_path / "qualified.mat"
    member.write_bytes(b"qualified")
    portable = storage.portable_reference_manifest("public-corn-m5-moisture-v1")
    sidecar = storage.write_registered_reference_sidecar(member, portable)
    payload = json.loads(sidecar.read_text())
    del payload["portable_reference"]["source_scope"]
    payload["portable_reference"][field] = value
    sidecar.write_text(json.dumps(payload))

    with pytest.raises(storage.RegisteredReferenceStorageError, match="active registry"):
        storage.read_registered_reference_sidecar(member)


def test_legacy_scope_does_not_allow_another_missing_field(tmp_path: Path) -> None:
    member = tmp_path / "qualified.mat"
    member.write_bytes(b"qualified")
    portable = storage.portable_reference_manifest("public-corn-m5-moisture-v1")
    sidecar = storage.write_registered_reference_sidecar(member, portable)
    payload = json.loads(sidecar.read_text())
    del payload["portable_reference"]["source_scope"]
    del payload["portable_reference"]["member_sha256"]
    sidecar.write_text(json.dumps(payload))

    with pytest.raises(storage.RegisteredReferenceStorageError, match="active registry"):
        storage.read_registered_reference_sidecar(member)


def test_new_sidecars_still_require_current_scope(tmp_path: Path) -> None:
    member = tmp_path / "qualified.mat"
    member.write_bytes(b"qualified")
    portable = storage.portable_reference_manifest("public-corn-m5-moisture-v1")
    del portable["source_scope"]

    with pytest.raises(storage.RegisteredReferenceStorageError, match="active registry"):
        storage.write_registered_reference_sidecar(member, portable)
    assert not storage.registered_reference_sidecar_path(member).exists()


def test_batch_prediction_reuses_exact_registered_spectral_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spectra_sherpa.app.lib import reference_materialization
    from spectra_sherpa.app.services.batch_predict import load_single_file

    member = tmp_path / "corn-mp5.mat"
    member.write_bytes(b"fixture")
    projection_id = "public-corn-mp5-moisture-v1"
    portable = storage.portable_reference_manifest(projection_id)
    storage.write_registered_reference_sidecar(member, portable)
    projected_spectra = object()
    monkeypatch.setattr(
        reference_materialization,
        "materialize_reference_member",
        lambda path, requested: reference_materialization.MaterializedReferenceProjection(
            dataset=projected_spectra,
            portable_reference=portable,
        ),
    )

    assert load_single_file(member, asset_id=projection_id) is projected_spectra
    with pytest.raises(ValueError, match="requested asset differs"):
        load_single_file(member, asset_id="mp5spec")

    changed = {**portable, "scientific_sha256": "0" * 64}
    monkeypatch.setattr(
        reference_materialization,
        "materialize_reference_member",
        lambda path, requested: reference_materialization.MaterializedReferenceProjection(
            dataset=projected_spectra,
            portable_reference=changed,
        ),
    )
    with pytest.raises(ValueError, match="identity changed"):
        load_single_file(member, asset_id=projection_id)
