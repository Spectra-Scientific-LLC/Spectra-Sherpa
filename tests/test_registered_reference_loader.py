from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.reference_materialization import MaterializedReferenceProjection
from spectra_sherpa.app.lib.sherpa_dataset import DatasetSourceIdentity, SherpaDataset, TargetContext
from spectra_sherpa.app.services.dag.nodes.data.loaders import _load_registry_asset
from spectra_sherpa.io.types import IngestionResult, SourceMember, SpectralAsset


def _dataset(*, target: bool) -> SherpaDataset:
    return SherpaDataset(
        X=np.asarray([[1.0, 2.0], [3.0, 4.0]]),
        feature_axis=SpectralAxis(values=np.asarray([1000.0, 1100.0]), title="Wavelength", units="nm"),
        sample_axis=SampleAxis(labels=["A", "B"]),
        target=np.asarray([10.0, 11.0]) if target else None,
        target_context=(
            TargetContext(target_type="continuous", target_names=["Moisture"], selected_target="Moisture")
            if target
            else None
        ),
        source_identity=DatasetSourceIdentity(source_format="eigenvector-dso", object_name="spectra"),
    )


def test_registered_sidecar_projects_exact_member_without_replacing_generic_ingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    member = tmp_path / "qualified.mat"
    member.write_bytes(b"qualified-member")
    portable = {
        "projection_id": "fixture-projection-v1",
        "member_sha256": "a" * 64,
        "member_size_bytes": len(b"qualified-member"),
    }
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.registered_reference_storage.read_registered_reference_sidecar",
        lambda _path: portable,
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.reference_materialization.materialize_reference_member",
        lambda _path, _projection_id: MaterializedReferenceProjection(
            dataset=_dataset(target=True), portable_reference=portable
        ),
    )
    monkeypatch.setattr(
        "spectra_sherpa.io.ingest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("generic ingest must not double-read")),
    )

    loaded = _load_registry_asset(member, asset_id="fixture-projection-v1")

    assert loaded.selected_asset_id == "fixture-projection-v1"
    assert loaded.dataset.target.tolist() == [10.0, 11.0]
    assert loaded.source_members[0].sha256 == "a" * 64


def test_nonreference_customer_mat_uses_generic_native_reader_even_when_dso(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    customer = tmp_path / "renamed-customer-dso.mat"
    customer.write_bytes(b"ordinary-paid-user-dso")
    dataset = _dataset(target=False)
    dataset.feature_axis = FeatureAxis(labels=["F1", "F2"], title="Feature")
    observed: list[Path] = []

    def _ingest(path: Path, **_kwargs) -> IngestionResult:
        observed.append(Path(path))
        return IngestionResult(
            format_id="matlab",
            variant="mat-v5-dso",
            parser_id="spectrasherpa.matlab",
            parser_version="3",
            source_members=(SourceMember(name=customer.name, sha256="b" * 64, size_bytes=customer.stat().st_size),),
            assets=(SpectralAsset(asset_id="customer_dso", dataset=dataset, dimension_roles=("sample", "feature")),),
        )

    monkeypatch.setattr(
        "spectra_sherpa.app.lib.registered_reference_storage.read_registered_reference_sidecar",
        lambda _path: None,
    )
    monkeypatch.setattr("spectra_sherpa.io.ingest", _ingest)

    loaded = _load_registry_asset(customer, asset_id="customer_dso")

    assert observed == [customer]
    assert loaded.selected_asset_id == "customer_dso"
    assert loaded.dataset.source_identity.source_format == "eigenvector-dso"
