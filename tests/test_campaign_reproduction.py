"""Local reproduction separates imported identity from fresh scientific results."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.services import campaign_reproduction as service
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.sdk.canonical_public_fixture import CanonicalPublicFixture
from spectra_sherpa.sdk.validate import make_split_plan
from tests.test_campaign_folder_watch import campaign  # noqa: F401
from tests.test_canonical_project_import import _REVIEW_ANCHORS, _REVIEW_PACKAGE


@pytest.mark.parametrize("changed", [False, True])
def test_reproduction_checks_science_independently(monkeypatch, changed):
    X = np.arange(96, dtype=float).reshape(12, 8)
    y = X[:, 0] * 0.3 + X[:, 1] * 0.1
    if changed:
        X, y = X[::-1].copy(), y[::-1].copy()
    split = make_split_plan(len(X), n_splits=3)
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(
            X=X,
            target=y,
            feature_axis=SpectralAxis(values=np.arange(8, dtype=float), units="cm-1"),
            domain=DomainContext(technique="NIR", measurement_mode="reflectance"),
            target_context=TargetContext(target_type="continuous", target_units="percent"),
        ),
        custody_id="public-fixture",
        dataset_ref_digest="a" * 64,
        split_plan_digest=split.digest,
    )
    paths = []

    def supplied_reference(path, package, *, projection_id):
        assert path.read_bytes() == b"local-only-fixture"
        assert projection_id == "test-projection"
        paths.append(path)
        return CanonicalPublicFixture(capability, split)

    monkeypatch.setattr(service, "load_registered_reference_fixture", supplied_reference)
    result = service.reproduce_reference_upload(
        package_bytes=_REVIEW_PACKAGE.archive,
        fixture_bytes=b"local-only-fixture",
        keys_bytes=json.dumps(_REVIEW_ANCHORS.as_dict()).encode(),
        projection_id="test-projection",
        expected_package_sha256=_REVIEW_PACKAGE.application.archive_sha256,
        max_bytes=10 * 1024 * 1024,
    )
    assert result["integrity_verified"]["status"] == "passed"
    assert result["publisher_authenticated"]["status"] == "passed"
    for key in ("validation_reproduced", "application_reproduced"):
        assert result[key]["status"] == ("not_run" if changed else "passed")
    assert not paths[0].exists()


def test_wrong_project_package_refused_before_fixture_load(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("must not decode data for an unrelated package")

    monkeypatch.setattr(service, "load_registered_reference_fixture", unexpected)
    with pytest.raises(ValueError, match="does not match"):
        service.reproduce_reference_upload(
            package_bytes=_REVIEW_PACKAGE.archive,
            fixture_bytes=b"unused",
            keys_bytes=b"{}",
            projection_id="unused",
            expected_package_sha256="0" * 64,
            max_bytes=10 * 1024 * 1024,
        )


@pytest.mark.asyncio
async def test_reproduction_route_uses_owned_imported_identity(campaign, auth_client, monkeypatch):  # noqa: F811
    imported, record, _ = campaign
    calls = []

    def reproduce(**kwargs):
        calls.append(kwargs)
        return {"validation_reproduced": {"status": "not_run", "reason": "fixture_mismatch"}}

    monkeypatch.setattr(service, "reproduce_reference_upload", reproduce)
    files = {
        "package": ("x.sherpa", b"package"),
        "fixture": ("x.zip", b"fixture"),
        "publisher_keys": ("keys.json", b"{}"),
    }
    response = await auth_client.post(
        f"/api/v1/projects/{imported.project_id}/reproduce-campaign", files=files, data={"projection_id": "test"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["validation_reproduced"]["status"] == "not_run"
    assert calls[0]["expected_package_sha256"] == record.package_sha256
    missing = await auth_client.post(
        "/api/v1/projects/999999/reproduce-campaign", files=files, data={"projection_id": "test"}
    )
    assert missing.status_code == 404
    assert len(calls) == 1
    from spectra_sherpa.app.api.v1.routes import projects

    monkeypatch.setattr(projects, "app_config", SimpleNamespace(mode="enterprise"))
    hosted = await auth_client.post(
        f"/api/v1/projects/{imported.project_id}/reproduce-campaign", files=files, data={"projection_id": "test"}
    )
    assert hosted.status_code == 403
    assert len(calls) == 1
