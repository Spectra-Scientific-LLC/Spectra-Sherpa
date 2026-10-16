"""v0.6.0 model recovery never invents missing signal authority."""

import numpy as np
import pytest

from spectra_sherpa.app.lib.fitted_state import FastICAExtract
from spectra_sherpa.app.lib.pca import PCAExtract
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import PLSDANode
from spectra_sherpa.app.services.dag.nodes.classification.plsda_state import (
    ARTIFACT_SERIALIZER,
    V060_ARTIFACT_SERIALIZER,
    V060_FITTED_STATE_SERIALIZER,
    SherpaPLSDAArtifact,
)
from spectra_sherpa.app.services.dag.nodes.modeling.load_apply_node import _apply_model_artifact
from spectra_sherpa.app.services.execution_runtime import ApplicationModelArtifactReplay
from spectra_sherpa.app.services.legacy_model_application import (
    LEGACY_WARNING,
    LegacyAcknowledgementRequired,
    require_legacy_application_acknowledgement,
)
from spectra_sherpa.app.services.model_application import (
    VerifiedModelSnapshot,
    apply_model_to_dataset,
    preflight_model_application,
)
from spectra_sherpa.core.axis_semantics import axis_semantics
from spectra_sherpa.core.model_artifact import ORDINARY_MODEL_ARTIFACT_AUTHORITY


def _dataset() -> SherpaDataset:
    matrix = np.array(
        [[0.1, 0.2, 0.4], [0.2, 0.3, 0.5], [0.9, 0.8, 0.7], [0.8, 0.7, 0.6], [0.3, 0.2, 0.1], [0.7, 0.9, 0.8]],
        dtype=float,
    )
    return SherpaDataset(X=matrix, feature_axis=SpectralAxis(values=np.array([900.0, 1200.0, 1600.0]), units="cm-1"))


def _v060_plsda():
    dataset = _dataset()
    labels = np.asarray(["a", "a", "b", "b", "a", "b"])
    state = PLSDANode("fit", {"n_components": 1, "scale": False}).fit_fitted_state(dataset, labels)
    state["serializer"] = V060_FITTED_STATE_SERIALIZER
    state["metadata"]["serializer"] = V060_ARTIFACT_SERIALIZER
    state["metadata"].pop("input_identity")
    state["metadata"].pop("screening")
    restored = SherpaPLSDAArtifact.from_fitted_state(state)
    manifest, arrays = restored.to_artifact()
    manifest["serializer"] = V060_ARTIFACT_SERIALIZER
    manifest["artifact_uid"] = "v060-plsda"
    manifest["artifact_authority"] = ORDINARY_MODEL_ARTIFACT_AUTHORITY
    manifest.pop("input_identity")
    manifest.pop("screening")
    return dataset, manifest, arrays


def test_v060_plsda_requires_acknowledgement_and_exact_typed_axis():
    dataset, manifest, arrays = _v060_plsda()
    with pytest.raises(LegacyAcknowledgementRequired, match="predates fitted signal identity"):
        require_legacy_application_acknowledgement(manifest, arrays, dataset, acknowledged=False)
    assert require_legacy_application_acknowledgement(manifest, arrays, dataset, acknowledged=True) == LEGACY_WARNING
    with pytest.raises(LegacyAcknowledgementRequired):
        _apply_model_artifact(manifest, arrays, dataset, model_id="v060-plsda", replay=ApplicationModelArtifactReplay())
    applied = _apply_model_artifact(
        manifest,
        arrays,
        dataset,
        model_id="v060-plsda",
        replay=ApplicationModelArtifactReplay(),
        acknowledge_legacy_input_uncertainty=True,
    )
    assert len(applied["labels"]) == dataset.shape[0]
    assert applied["metadata"]["legacy_exploratory_warning"] == LEGACY_WARNING
    changed = SherpaDataset(
        X=dataset.X, feature_axis=SpectralAxis(values=np.array([900.0, 1201.0, 1600.0]), units="cm-1")
    )
    with pytest.raises(ValueError, match="feature identity differs"):
        require_legacy_application_acknowledgement(manifest, arrays, changed, acknowledged=True)


@pytest.mark.parametrize(
    "model_type,serializer",
    [
        ("pca", "spectrasherpa.model-artifact.pca/3"),
        ("fastica", "spectrasherpa.model-artifact.fastica/1"),
    ],
)
def test_v060_numeric_axis_requires_exact_values_even_after_ack(model_type, serializer):
    dataset = _dataset()
    quantity = axis_semantics(axis_class="SpectralAxis", title=None, units="cm-1").quantity
    manifest = {
        "model_type": model_type,
        "serializer": serializer,
        "n_features": 3,
        "feature_axis_class": "SpectralAxis",
        "feature_axis": [900.0, 1200.0, 1600.0],
        "feature_axis_units": "cm-1",
        "feature_axis_quantity": quantity.value if quantity else None,
    }
    with pytest.raises(LegacyAcknowledgementRequired):
        require_legacy_application_acknowledgement(manifest, {}, dataset, acknowledged=False)
    assert require_legacy_application_acknowledgement(manifest, {}, dataset, acknowledged=True) == LEGACY_WARNING
    changed = SherpaDataset(
        X=dataset.X, feature_axis=SpectralAxis(values=np.array([900.0, 1200.0001, 1600.0]), units="cm-1")
    )
    with pytest.raises(ValueError, match="coordinates differ"):
        require_legacy_application_acknowledgement(manifest, {}, changed, acknowledged=True)
    manifest.pop("feature_axis")
    with pytest.raises(ValueError, match="no complete retained numeric feature axis"):
        require_legacy_application_acknowledgement(manifest, {}, dataset, acknowledged=True)


@pytest.mark.parametrize("model_type", ["pca", "fastica"])
def test_v060_transform_replays_with_warning_only_after_acknowledgement(model_type):
    dataset = _dataset()
    if model_type == "pca":
        extract = PCAExtract(
            scores=np.zeros((6, 2)),
            loadings=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
            explained_variance_ratio=np.array([0.7, 0.3]),
            explained_variance=np.array([2.0, 1.0]),
            n_components=2,
            mean=np.zeros(3),
        )
    else:
        extract = FastICAExtract(
            components=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
            mean=np.zeros(3),
            mixing=np.array([[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]),
            n_components=2,
            n_features=3,
            algorithm="parallel",
            fun="logcosh",
            whiten="unit-variance",
            random_seed=0,
        )
    manifest, arrays = extract.to_artifact()
    quantity = axis_semantics(axis_class="SpectralAxis", title=None, units="cm-1").quantity
    manifest.update(
        artifact_uid=f"v060-{model_type}",
        artifact_authority=ORDINARY_MODEL_ARTIFACT_AUTHORITY,
        feature_axis_class="SpectralAxis",
        feature_axis=[900.0, 1200.0, 1600.0],
        feature_axis_units="cm-1",
        feature_axis_quantity=quantity.value if quantity else None,
    )
    with pytest.raises(LegacyAcknowledgementRequired):
        _apply_model_artifact(
            manifest, arrays, dataset, model_id=f"v060-{model_type}", replay=ApplicationModelArtifactReplay()
        )
    applied = _apply_model_artifact(
        manifest,
        arrays,
        dataset,
        model_id=f"v060-{model_type}",
        replay=ApplicationModelArtifactReplay(),
        acknowledge_legacy_input_uncertainty=True,
    )
    np.testing.assert_allclose(applied["transformed"], extract.transform(dataset.X))
    assert applied["metadata"]["legacy_exploratory_warning"] == LEGACY_WARNING
    with pytest.raises(LegacyAcknowledgementRequired):
        preflight_model_application(dataset, manifest, arrays)
    _, warnings, _ = preflight_model_application(dataset, manifest, arrays, acknowledge_legacy_input_uncertainty=True)
    assert LEGACY_WARNING in warnings


def test_current_plsda_with_missing_identity_cannot_use_legacy_acknowledgement():
    dataset, manifest, arrays = _v060_plsda()
    manifest["serializer"] = ARTIFACT_SERIALIZER
    with pytest.raises(ValueError, match="closed schema"):
        _apply_model_artifact(
            manifest,
            arrays,
            dataset,
            model_id="v060-plsda",
            replay=ApplicationModelArtifactReplay(),
            acknowledge_legacy_input_uncertainty=True,
        )


@pytest.mark.asyncio
async def test_legacy_warning_survives_retained_application_response():
    dataset, manifest, arrays = _v060_plsda()
    snapshot = VerifiedModelSnapshot("v060-plsda", manifest, arrays)
    with pytest.raises(ValueError, match="predates fitted signal identity"):
        await apply_model_to_dataset("v060-plsda", dataset, verified_snapshot=snapshot)
    response = await apply_model_to_dataset(
        "v060-plsda",
        dataset,
        verified_snapshot=snapshot,
        acknowledge_legacy_input_uncertainty=True,
    )
    assert response["predictions"]
    assert LEGACY_WARNING in response["warnings"]
    assert response["metadata"]["legacy_exploratory_acknowledged"] is True


def test_legacy_acknowledgement_does_not_admit_hosted_application(monkeypatch):
    from spectra_sherpa.app.services import legacy_model_application

    dataset, manifest, arrays = _v060_plsda()
    monkeypatch.setattr(legacy_model_application, "is_local", lambda: False)
    with pytest.raises(ValueError, match="only in local OSS"):
        require_legacy_application_acknowledgement(manifest, arrays, dataset, acknowledged=True)
