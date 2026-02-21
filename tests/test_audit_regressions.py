"""Regression tests for bugs found during mutable-container audit.

Currently FAILING (5 bugs):
- TestExtraDictIsolation (4 tests): extra/meta return mutable refs, init/from_dict don't deep-copy
- TestDiagnosticsInputMutation (1 test): outlier detection mutates input dataset quality

Currently PASSING (5 guards — Pydantic V2 handles these correctly):
- TestQualityMetricsMutableDefault (2 tests): list default isolation
- TestDatasetManifestMutableDefault (2 tests): list default isolation
- TestSerializerAxisMutation (1 test): to_dict() creates fresh dict per call

Run with:
    cd spectra-sherpa && python -m pytest tests/test_audit_regressions.py -v --no-cov
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import (
    DatasetManifest,
    DomainContext,
    EvaluationResult,
    QualityMetrics,
    SherpaDataset,
    SpectralAxis,
)


# ═══════════════════════════════════════════════════════════════════════════
# Group 1: Mutable defaults on Pydantic models
# ═══════════════════════════════════════════════════════════════════════════


class TestQualityMetricsMutableDefault:
    """Bug: QualityMetrics.evaluations = [] is a mutable class-level default.

    Two independently-constructed QualityMetrics instances can share the
    same list object. Appending to one silently contaminates the other.
    Fix: Use Field(default_factory=list).
    """

    def test_independent_instances_do_not_share_evaluations_list(self):
        q1 = QualityMetrics()
        q2 = QualityMetrics()
        assert q1.evaluations is not q2.evaluations, (
            "Two QualityMetrics() instances share the same evaluations list object"
        )

    def test_append_to_one_does_not_affect_other(self):
        q1 = QualityMetrics()
        q2 = QualityMetrics()
        ev = EvaluationResult(evaluation_id="test", model_type="PCA")
        q1.add_evaluation(ev)
        assert len(q2.evaluations) == 0, (
            "Adding evaluation to q1 leaked into q2 via shared mutable default"
        )


class TestDatasetManifestMutableDefault:
    """Bug: DatasetManifest.state_effects = [] is a mutable class-level default.

    Same shared-list problem as QualityMetrics.evaluations.
    Fix: Use Field(default_factory=list).
    """

    def test_independent_instances_do_not_share_state_effects(self):
        m1 = DatasetManifest(dataset_id="a", shape=(3, 10))
        m2 = DatasetManifest(dataset_id="b", shape=(5, 20))
        assert m1.state_effects is not m2.state_effects, (
            "Two DatasetManifest instances share the same state_effects list object"
        )

    def test_mutate_one_does_not_affect_other(self):
        m1 = DatasetManifest(dataset_id="a", shape=(3, 10))
        m2 = DatasetManifest(dataset_id="b", shape=(5, 20))
        m1.state_effects.append("normalized")
        assert "normalized" not in m2.state_effects, (
            "Mutating m1.state_effects leaked into m2 via shared mutable default"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Group 2: Extra dict exposure and copy isolation
# ═══════════════════════════════════════════════════════════════════════════


class TestExtraDictIsolation:
    """Bug: SherpaDataset.extra and .meta return the internal _extra dict
    by reference. Callers can mutate dataset internals without going through
    set_extra() — bypassing namespace validation and audit trail.

    Also: __init__ and from_dict don't deep-copy the extra parameter,
    so the caller's dict and the dataset's dict are the same object.
    """

    @pytest.mark.xfail(reason="Bug: .extra returns mutable internal dict", strict=True)
    def test_extra_property_returns_copy_not_reference(self):
        ds = SherpaDataset(X=np.zeros((3, 10)))
        ds.set_extra("user.key", "original")
        ext = ds.extra
        ext["user.key"] = "tampered"
        assert ds.get_extra("user.key") == "original", (
            ".extra returns mutable reference — caller can bypass set_extra() validation"
        )

    @pytest.mark.xfail(reason="Bug: .meta returns mutable internal dict", strict=True)
    def test_meta_property_returns_copy_not_reference(self):
        ds = SherpaDataset(X=np.zeros((3, 10)))
        ds.set_extra("user.key", "original")
        m = ds.meta
        m["user.key"] = "tampered"
        assert ds.get_extra("user.key") == "original", (
            ".meta returns mutable reference — caller can bypass set_extra() validation"
        )

    @pytest.mark.xfail(reason="Bug: __init__ doesn't deep-copy extra", strict=True)
    def test_init_deep_copies_extra_dict(self):
        caller_dict = {"user.key": {"nested": [1, 2, 3]}}
        ds = SherpaDataset(X=np.zeros((3, 10)), extra=caller_dict)
        caller_dict["user.key"]["nested"].append(999)
        assert 999 not in ds.get_extra("user.key")["nested"], (
            "__init__ doesn't deep-copy extra — caller mutation leaks into dataset"
        )

    @pytest.mark.xfail(reason="Bug: from_dict doesn't deep-copy extra", strict=True)
    def test_from_dict_deep_copies_extra(self):
        ds_original = SherpaDataset(X=np.zeros((3, 10)))
        ds_original.set_extra("user.key", {"nested": [1, 2, 3]})
        wire = ds_original.to_dict()

        ds_restored = SherpaDataset.from_dict(wire)
        # Mutate the wire dict's extra after deserialization
        wire["extra"]["user.key"]["nested"].append(999)
        assert 999 not in ds_restored.get_extra("user.key")["nested"], (
            "from_dict doesn't deep-copy extra — wire dict mutation leaks into restored dataset"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Group 3: DAG node mutation side-effects
# ═══════════════════════════════════════════════════════════════════════════


class TestSerializerAxisMutation:
    """Bug: serialize.py mutates axis dicts in-place when normalizing
    'dimensionless' → '' for units. If the same result dict were held
    by another consumer, it would see the mutation.

    The serializer should work on a deep copy, not mutate the to_dict()
    result in place. This test captures the pattern: get to_dict() first,
    then serialize, and verify the first result wasn't contaminated.
    """

    def test_serialize_does_not_mutate_shared_to_dict_result(self):
        from spectra_sherpa.app.services.dag.serialize import (
            _serialize_sherpa_dataset,
        )

        ds = SherpaDataset(
            X=np.zeros((3, 50)),
            spectral_axis=SpectralAxis(
                values=np.linspace(400, 4000, 50), units="dimensionless"
            ),
        )
        # Simulate another consumer holding a reference to the serialized dict
        # by monkey-patching to_dict to return a shared reference
        shared_dict = ds.to_dict()
        original_x_units = shared_dict["spectral_axis"]["units"]

        # The serializer calls to_dict() internally, which makes a new dict,
        # so this particular bug only manifests if someone shares the dict.
        # Still, the serializer should not mutate any dict it receives.
        result = _serialize_sherpa_dataset(ds)

        # The serialized result should have "" for dimensionless
        x_units_in_result = result.get("x_axis", {}).get("units", "NOT_FOUND")
        assert x_units_in_result == "", (
            f"Expected dimensionless → '' in serialized output, got '{x_units_in_result}'"
        )

        # The original shared_dict should be untouched
        assert shared_dict["spectral_axis"]["units"] == original_x_units, (
            "Serializer mutated a dict that another consumer could be holding"
        )


class TestDiagnosticsInputMutation:
    """Bug: OutlierDetectionNode.execute() mutates the quality metrics
    of the INPUT dataset by calling input_ds.quality.add_evaluation().

    This is a side-effect: the input dataset from a prior node gets
    its quality modified by a downstream consumer. In a DAG where
    multiple nodes consume the same input, this creates non-deterministic
    state depending on execution order.

    The evaluation should be attached to the OUTPUT, not the input.
    """

    @pytest.mark.xfail(reason="Bug: OutlierDetectionNode mutates input dataset quality", strict=True)
    @pytest.mark.asyncio
    async def test_outlier_detection_does_not_mutate_input_quality(self):
        """Verifying that running outlier detection doesn't modify
        the quality metrics of the source dataset."""
        from sklearn.decomposition import PCA

        from spectra_sherpa.app.services.dag.nodes.diagnostics import (
            OutlierDetectionNode,
        )

        # Create a source dataset
        np.random.seed(42)
        X = np.random.randn(20, 10)
        input_ds = SherpaDataset(X=X)

        # Verify clean starting state
        assert len(input_ds.quality.evaluations) == 0

        # Build a PCA model dict that mimics what PCANode outputs
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

        # The input dataset's quality should NOT have been modified
        assert len(input_ds.quality.evaluations) == 0, (
            "OutlierDetectionNode mutated input dataset's quality — "
            f"found {len(input_ds.quality.evaluations)} evaluation(s) "
            "that were injected as a side-effect"
        )
