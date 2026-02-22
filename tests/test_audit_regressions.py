"""Regression tests for bugs found during mutable-container audit.

All 10 tests should PASS:
- TestQualityMetricsMutableDefault (2): Pydantic V2 list default isolation
- TestDatasetManifestMutableDefault (2): Pydantic V2 list default isolation
- TestExtraDictIsolation (4): deep-copy on init/from_dict, .extra/.meta intentionally mutable
- TestSerializerAxisMutation (1): to_dict() creates fresh dict per call
- TestDiagnosticsInputMutation (1): outlier detection no longer mutates input

Run with:
    cd spectra-sherpa && python -m pytest tests/test_audit_regressions.py -v --no-cov
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import (
    DatasetManifest,
    EvaluationResult,
    QualityMetrics,
    SherpaDataset,
    SpectralAxis,
)

# ═══════════════════════════════════════════════════════════════════════════
# Group 1: Mutable defaults on Pydantic models
# ═══════════════════════════════════════════════════════════════════════════


class TestQualityMetricsMutableDefault:
    """Guard: QualityMetrics.evaluations gets a fresh list per instance.
    Pydantic V2 handles list defaults correctly.
    """

    def test_independent_instances_do_not_share_evaluations_list(self):
        q1 = QualityMetrics()
        q2 = QualityMetrics()
        assert (
            q1.evaluations is not q2.evaluations
        ), "Two QualityMetrics() instances share the same evaluations list object"

    def test_append_to_one_does_not_affect_other(self):
        q1 = QualityMetrics()
        q2 = QualityMetrics()
        ev = EvaluationResult(evaluation_id="test", model_type="PCA")
        q1.add_evaluation(ev)
        assert len(q2.evaluations) == 0, "Adding evaluation to q1 leaked into q2 via shared mutable default"


class TestDatasetManifestMutableDefault:
    """Guard: DatasetManifest.state_effects gets a fresh list per instance.
    Pydantic V2 handles list defaults correctly.
    """

    def test_independent_instances_do_not_share_state_effects(self):
        m1 = DatasetManifest(dataset_id="a", shape=(3, 10))
        m2 = DatasetManifest(dataset_id="b", shape=(5, 20))
        assert (
            m1.state_effects is not m2.state_effects
        ), "Two DatasetManifest instances share the same state_effects list object"

    def test_mutate_one_does_not_affect_other(self):
        m1 = DatasetManifest(dataset_id="a", shape=(3, 10))
        m2 = DatasetManifest(dataset_id="b", shape=(5, 20))
        m1.state_effects.append("normalized")
        assert (
            "normalized" not in m2.state_effects
        ), "Mutating m1.state_effects leaked into m2 via shared mutable default"


# ═══════════════════════════════════════════════════════════════════════════
# Group 2: Extra dict copy isolation
# ═══════════════════════════════════════════════════════════════════════════


class TestExtraDictIsolation:
    """Extra dict boundary isolation.

    .extra and .meta intentionally return the mutable internal dict —
    70+ call sites do `dataset.meta["key"] = value` across the codebase.

    What IS protected: __init__ and from_dict deep-copy the extra parameter
    so the caller's dict and the dataset's dict are independent objects.
    """

    def test_extra_and_meta_are_same_object(self):
        """By design: .extra and .meta are the same mutable dict."""
        ds = SherpaDataset(X=np.zeros((3, 10)))
        assert ds.extra is ds.meta

    def test_meta_mutation_is_visible_via_get_extra(self):
        """By design: internal code can mutate via .meta["key"] = value."""
        ds = SherpaDataset(X=np.zeros((3, 10)))
        ds.meta["user.key"] = "value"
        assert ds.get_extra("user.key") == "value"

    def test_init_deep_copies_extra_dict(self):
        caller_dict = {"user.key": {"nested": [1, 2, 3]}}
        ds = SherpaDataset(X=np.zeros((3, 10)), extra=caller_dict)
        caller_dict["user.key"]["nested"].append(999)
        assert (
            999 not in ds.get_extra("user.key")["nested"]
        ), "__init__ doesn't deep-copy extra — caller mutation leaks into dataset"

    def test_from_dict_deep_copies_extra(self):
        ds_original = SherpaDataset(X=np.zeros((3, 10)))
        ds_original.set_extra("user.key", {"nested": [1, 2, 3]})
        wire = ds_original.to_dict()

        ds_restored = SherpaDataset.from_dict(wire)
        # Mutate the wire dict's extra after deserialization
        wire["extra"]["user.key"]["nested"].append(999)
        assert (
            999 not in ds_restored.get_extra("user.key")["nested"]
        ), "from_dict doesn't deep-copy extra — wire dict mutation leaks into restored dataset"


# ═══════════════════════════════════════════════════════════════════════════
# Group 3: DAG node mutation side-effects
# ═══════════════════════════════════════════════════════════════════════════


class TestSerializerAxisMutation:
    """Guard: serialize.py works on a fresh to_dict() result per call,
    so it never contaminates other consumers.
    """

    def test_serialize_does_not_mutate_shared_to_dict_result(self):
        from spectra_sherpa.app.services.dag.serialize import (
            _serialize_sherpa_dataset,
        )

        ds = SherpaDataset(
            X=np.zeros((3, 50)),
            spectral_axis=SpectralAxis(values=np.linspace(400, 4000, 50), units="dimensionless"),
        )
        shared_dict = ds.to_dict()
        original_x_units = shared_dict["spectral_axis"]["units"]

        result = _serialize_sherpa_dataset(ds)

        x_units_in_result = result.get("x_axis", {}).get("units", "NOT_FOUND")
        assert x_units_in_result == "", f"Expected dimensionless → '' in serialized output, got '{x_units_in_result}'"

        assert (
            shared_dict["spectral_axis"]["units"] == original_x_units
        ), "Serializer mutated a dict that another consumer could be holding"


class TestDiagnosticsInputMutation:
    """Fixed: OutlierDetectionNode no longer mutates input dataset quality.
    The evaluation is returned in the result dict for the consumer to attach.
    """

    @pytest.mark.asyncio
    async def test_outlier_detection_does_not_mutate_input_quality(self):
        """Outlier detection must not modify the source dataset."""
        from sklearn.decomposition import PCA

        from spectra_sherpa.app.services.dag.nodes.diagnostics import (
            OutlierDetectionNode,
        )

        np.random.seed(42)
        X = np.random.randn(20, 10)
        input_ds = SherpaDataset(X=X)

        assert len(input_ds.quality.evaluations) == 0

        pca = PCA(n_components=3)
        scores = pca.fit_transform(X)

        pca_model = {
            "model": pca,
            "scores": scores,
            "loadings": pca.components_,
            "n_components": 3,
            "n_observations": 20,
            "explained_variance": pca.explained_variance_,
            "_internal": {
                "input_data": X,
                "input_data_ds": input_ds,
            },
            "metadata": {"type": "PCAModel"},
        }

        node = OutlierDetectionNode(node_id="test_outlier")
        node.parameters = {"confidence_level": 0.95}
        await node.execute(pca_model=pca_model)

        assert len(input_ds.quality.evaluations) == 0, (
            "OutlierDetectionNode mutated input dataset's quality — "
            f"found {len(input_ds.quality.evaluations)} evaluation(s) "
            "that were injected as a side-effect"
        )
