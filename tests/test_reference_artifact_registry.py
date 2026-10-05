from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from spectra_sherpa.app.lib.reference_artifacts import (
    REFERENCE_ARTIFACT_REGISTRY_PATH,
    ReferenceArtifactRegistryError,
    load_reference_artifact_registry,
    reference_artifact_registry_digest,
    registered_projection_acquisition,
)


def _payload() -> dict:
    return json.loads(REFERENCE_ARTIFACT_REGISTRY_PATH.read_text(encoding="utf-8"))


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_registry_binds_current_corn_artifact_and_projection() -> None:
    registry = load_reference_artifact_registry()
    artifact = registry.artifact("eigenvector-corn-archive-v1").as_dict()
    projection = registry.projection("public-corn-m5-moisture-v1").as_dict()

    assert artifact["expected_size_bytes"] == 1_094_488
    assert artifact["sha256"] == "8a2d1a03648b6ad334caaafa5d8377bf945ba1477a5082c4963d705d07cca795"
    assert artifact["members"] == [
        {
            "path": "corn.mat",
            "expected_size_bytes": 1_445_616,
            "sha256": "e28fd4be274a54ca57b1f2c67ef5a8bf4981f8314bcc73e4c64836fe658c46b5",
        }
    ]
    assert projection["artifact_id"] == artifact["artifact_id"]
    assert projection["native_reader_contract"] == "spectrasherpa.matlab-dso/1"
    assert projection["scientific_sha256"] == "27007609c7a8f53d144e235eaeb61829b4f306e33a129980a08f882a800f040e"
    assert projection["analysis"] == {
        "primary_role": "X_spectra",
        "modality": "spectra",
        "technique": "NIR",
        "target_type": "continuous",
        "target_fields": ["Moisture"],
        "identity_fields": [],
        "group_fields": [],
        "ordered_samples": False,
    }


def test_projection_acquisition_resolves_bytes_from_one_authority() -> None:
    acquisition = registered_projection_acquisition("public-corn-m5-moisture-v1")

    assert acquisition == {
        "artifact_id": "eigenvector-corn-archive-v1",
        "download_url": "https://eigenvector.com/wp-content/uploads/2019/06/corn.mat_.zip",
        "archive_expected_size_bytes": 1_094_488,
        "archive_sha256": "8a2d1a03648b6ad334caaafa5d8377bf945ba1477a5082c4963d705d07cca795",
        "redistribution": "upstream_only_not_redistributed",
        "member_path": "corn.mat",
        "member_expected_size_bytes": 1_445_616,
        "member_sha256": "e28fd4be274a54ca57b1f2c67ef5a8bf4981f8314bcc73e4c64836fe658c46b5",
    }


def test_registry_digest_is_canonical_and_detached() -> None:
    payload = _payload()
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    registry = load_reference_artifact_registry()
    detached = registry.artifacts[0].as_dict()
    detached["title"] = "mutated"

    assert reference_artifact_registry_digest() == expected
    assert registry.artifacts[0].as_dict()["title"] != "mutated"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p["artifacts"][0].update(expected_size_bytes=0), "expected_size_bytes"),
        (lambda p: p["artifacts"][0].update(sha256="0" * 63), "SHA-256"),
        (
            lambda p: p["artifacts"][0].update(download_url="https://example.com/corn.zip"),
            "provider-controlled HTTPS",
        ),
        (lambda p: p["artifacts"][0]["members"][0].update(path="../corn.mat"), "bounded relative member"),
        (lambda p: p["projections"][0].update(artifact_id="missing"), "unknown artifact"),
        (lambda p: p["projections"][0].update(qualification_status="pending"), "only qualified"),
        (
            lambda p: p["projections"][0]["analysis"].update(primary_role="X_features"),
            "role and modality disagree",
        ),
        (
            lambda p: p["projections"][1]["analysis"].update(target_fields=["Wrong target"]),
            "target authority disagrees",
        ),
    ],
)
def test_registry_refuses_unsafe_or_unqualified_authority(tmp_path: Path, mutate, message: str) -> None:
    payload = _payload()
    mutate(payload)
    with pytest.raises(ReferenceArtifactRegistryError, match=message):
        load_reference_artifact_registry(_write(tmp_path, payload))


def test_registry_refuses_filename_or_other_extra_authority(tmp_path: Path) -> None:
    payload = _payload()
    payload["artifacts"][0]["filename"] = "corn.mat_.zip"
    with pytest.raises(ReferenceArtifactRegistryError, match="fields differ"):
        load_reference_artifact_registry(_write(tmp_path, payload))


def test_registry_unknown_lookup_fails_closed() -> None:
    registry = load_reference_artifact_registry()
    with pytest.raises(ReferenceArtifactRegistryError, match="unknown qualified reference artifact"):
        registry.artifact("corn")
    with pytest.raises(ReferenceArtifactRegistryError, match="unknown qualified reference projection"):
        registry.projection("m5")
