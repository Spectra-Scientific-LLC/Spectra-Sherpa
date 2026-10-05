"""Tests for the public, data-separated canonical reproduction fixture."""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import TargetContext
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.sdk.canonical_public_fixture import (
    CanonicalPublicFixtureError,
    load_canonical_public_fixture,
    load_registered_reference_fixture,
)
from spectra_sherpa.sdk.canonical_reproduction import reproduce_canonical_project
from tests.test_canonical_reproduction import _build_package, _classification_fixture, _fixture


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _write_fixture(path, *, shifted: bool = False) -> None:
    fixture, _split = _fixture(shifted=shifted)
    np.savez(
        path,
        X=np.asarray(fixture.arrays["X"]),
        y=np.asarray(fixture.arrays["target"]),
        wavelengths=np.arange(fixture.arrays["X"].shape[1], dtype=float),
    )


def test_public_npz_rebuilds_exact_oss_reproduction_capability(tmp_path) -> None:
    package = asyncio.run(_build_package())
    source = tmp_path / "public-fixture.npz"
    _write_fixture(source)

    fixture = load_canonical_public_fixture(source, package.archive, custody_id="public-fixture")
    report = reproduce_canonical_project(package.archive, fixture=fixture.capability, split_plan=fixture.split_plan)

    assert report.payload["integrity_verified"]["status"] == "passed"
    assert report.payload["validation_reproduced"]["status"] == "passed"
    assert report.payload["application_reproduced"]["status"] == "passed"


def test_public_npz_preserves_string_class_labels_for_exact_reproduction(tmp_path) -> None:
    package = asyncio.run(_build_package(classification=True))
    fixture_capability, _split = _classification_fixture()
    source = tmp_path / "public-classification-fixture.npz"
    np.savez(
        source,
        X=np.asarray(fixture_capability.arrays["X"]),
        y=np.asarray(fixture_capability.arrays["target"]),
        wavelengths=np.arange(fixture_capability.arrays["X"].shape[1], dtype=float),
    )

    fixture = load_canonical_public_fixture(
        source,
        package,
        custody_id="public-classification-fixture",
    )
    report = reproduce_canonical_project(package, fixture=fixture.capability, split_plan=fixture.split_plan)

    assert fixture.capability.arrays["target"].dtype.kind == "U"
    assert report.payload["integrity_verified"]["status"] == "passed"
    assert report.payload["validation_reproduced"]["status"] == "passed"
    assert report.payload["application_reproduced"]["status"] == "passed"


def test_public_npz_cannot_substitute_different_science(tmp_path) -> None:
    package = asyncio.run(_build_package())
    source = tmp_path / "changed-fixture.npz"
    _write_fixture(source, shifted=True)

    fixture = load_canonical_public_fixture(source, package, custody_id="public-fixture")
    report = reproduce_canonical_project(package, fixture=fixture.capability, split_plan=fixture.split_plan)

    assert report.payload["integrity_verified"]["status"] == "passed"
    assert report.payload["validation_reproduced"] == {
        "status": "not_run",
        "reason": "fixture_or_split_identity_mismatch",
    }


def test_provider_acquired_registered_reference_rebuilds_hosted_campaign_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from spectra_sherpa.app.lib import reference_materialization

    campaign_id = "canonical-campaign-001"
    package = asyncio.run(_build_package(custody_id=f"campaign-{campaign_id}"))
    capability, _split = _fixture(custody_id=f"campaign-{campaign_id}")
    source = tmp_path / "provider-download.zip"
    source.write_bytes(b"provider-owned-reference")
    monkeypatch.setattr(
        reference_materialization,
        "materialize_reference_projection",
        lambda path, projection_id: (
            pytest.fail("wrong provider artifact")
            if path != source or projection_id != "eigenvector.test.projection"
            else SimpleNamespace(dataset=capability.to_dataset())
        ),
    )

    fixture = load_registered_reference_fixture(
        source,
        package,
        projection_id="eigenvector.test.projection",
    )
    report = reproduce_canonical_project(package, fixture=fixture.capability, split_plan=fixture.split_plan)

    assert fixture.capability.evidence_summary()["custody_id"] == f"campaign-{campaign_id}"
    assert report.payload["validation_reproduced"]["status"] == "passed"
    assert report.payload["application_reproduced"]["status"] == "passed"


def test_provider_acquired_package_projection_uses_its_named_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from spectra_sherpa.app.lib import reference_materialization

    campaign_id = "canonical-campaign-001"
    package = asyncio.run(_build_package(custody_id=f"campaign-{campaign_id}"))
    capability, _split = _fixture(custody_id=f"campaign-{campaign_id}")
    source = tmp_path / "provider-download.zip"
    source.write_bytes(b"provider-owned-reference")
    dataset = capability.to_dataset()
    expected = np.asarray(dataset.target).copy()
    dataset.target = np.column_stack((expected, expected + 100.0))
    dataset.target_context = TargetContext(
        target_type="continuous",
        target_names=["Moisture", "Oil"],
        selected_target=None,
    )
    monkeypatch.setattr(
        reference_materialization,
        "materialize_reference_projection",
        lambda path, projection_id: (
            pytest.fail("wrong provider artifact")
            if path != source or projection_id != "eigenvector.test.projection"
            else SimpleNamespace(dataset=dataset)
        ),
    )
    projection = SimpleNamespace(as_dict=lambda: {"target_name": "Moisture"})
    registry = SimpleNamespace(projection=lambda projection_id: projection)
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.reference_artifacts.load_reference_artifact_registry",
        lambda: registry,
    )

    fixture = load_registered_reference_fixture(
        source,
        package,
        projection_id="eigenvector.test.projection",
    )
    report = reproduce_canonical_project(package, fixture=fixture.capability, split_plan=fixture.split_plan)

    assert report.payload["validation_reproduced"]["status"] == "passed"
    assert report.payload["application_reproduced"]["status"] == "passed"


def test_public_npz_requires_the_producer_recorded_custody_binding(tmp_path) -> None:
    package = asyncio.run(_build_package())
    source = tmp_path / "public-fixture.npz"
    _write_fixture(source)

    fixture = load_canonical_public_fixture(source, package, custody_id="different-public-fixture")
    report = reproduce_canonical_project(package, fixture=fixture.capability, split_plan=fixture.split_plan)

    assert report.payload["integrity_verified"]["status"] == "passed"
    assert report.payload["validation_reproduced"] == {
        "status": "not_run",
        "reason": "fixture_or_split_identity_mismatch",
    }


def test_public_npz_requires_the_producer_recorded_axis_binding(tmp_path) -> None:
    package = asyncio.run(_build_package())
    source = tmp_path / "public-fixture.npz"
    _write_fixture(source)

    fixture = load_canonical_public_fixture(
        source,
        package,
        custody_id="public-fixture",
        spectral_axis_units="nm",
    )
    report = reproduce_canonical_project(package, fixture=fixture.capability, split_plan=fixture.split_plan)

    assert report.payload["integrity_verified"]["status"] == "passed"
    assert report.payload["validation_reproduced"] == {
        "status": "not_run",
        "reason": "fixture_or_split_identity_mismatch",
    }


def test_public_npz_rejects_extra_or_object_members_before_execution(tmp_path) -> None:
    package = asyncio.run(_build_package())
    source = tmp_path / "invalid-fixture.npz"
    np.savez(source, X=np.ones((12, 8)), y=np.ones(12), unexpected=np.ones(1))

    with pytest.raises(CanonicalPublicFixtureError, match="members are closed"):
        load_canonical_public_fixture(source, package, custody_id="public-fixture")
