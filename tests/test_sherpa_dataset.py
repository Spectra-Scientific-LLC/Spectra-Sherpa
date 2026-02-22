"""Tests for SherpaDataset, Pydantic models, adapters, and DatasetSummarizer.

Run with:
    cd spectra-sherpa && python -m pytest tests/test_sherpa_dataset.py -v --no-cov
"""

from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import (
    EFFECT_BASELINE_CORRECTED,
    EFFECT_MEAN_CENTERED,
    EFFECT_NORMALIZED,
    EFFECT_SCALED,
    EFFECT_SCATTER_CORRECTED,
    EFFECT_SMOOTHED,
    AxisInfo,
    BranchInfo,
    DatasetManifest,
    DatasetState,
    DomainContext,
    EvaluationResult,
    InferredDomain,
    Provenance,
    ProvenanceEntry,
    QualityMetrics,
    SampleAxis,
    SherpaDataset,
    SpectralAxis,
    TargetContext,
)

# ═══════════════════════════════════════════════════════════════════════════
# AxisInfo (base)
# ═══════════════════════════════════════════════════════════════════════════


class TestAxisInfo:
    def test_defaults(self):
        ai = AxisInfo()
        assert ai.values is None
        assert ai.labels is None
        assert ai.units is None
        assert ai.title is None

    def test_data_property(self):
        vals = np.array([1.0, 2.0, 3.0])
        ai = AxisInfo(values=vals)
        assert ai.data is ai.values

    def test_length_from_values(self):
        ai = AxisInfo(values=np.arange(5))
        assert ai.length == 5
        assert len(ai) == 5

    def test_length_from_labels(self):
        ai = AxisInfo(labels=["a", "b"])
        assert ai.length == 2

    def test_length_zero(self):
        ai = AxisInfo()
        assert ai.length == 0

    def test_shape(self):
        ai = AxisInfo(values=np.zeros(3))
        assert ai.shape == (3,)

    def test_shape_none(self):
        ai = AxisInfo()
        assert ai.shape == ()

    def test_copy_independent(self):
        ai = AxisInfo(values=np.array([1.0, 2.0]), labels=["a", "b"], units="nm", title="x")
        cp = ai.copy()
        assert cp is not ai
        cp.values[0] = 999.0
        assert ai.values[0] == 1.0
        cp.labels[0] = "z"
        assert ai.labels[0] == "a"


# ═══════════════════════════════════════════════════════════════════════════
# SpectralAxis
# ═══════════════════════════════════════════════════════════════════════════


class TestSpectralAxis:
    def test_axis_type_wavenumber(self):
        sa = SpectralAxis(values=np.arange(100), units="cm-1")
        assert sa.axis_type == "wavenumber"

    def test_axis_type_wavelength_nm(self):
        sa = SpectralAxis(values=np.arange(100), units="nm")
        assert sa.axis_type == "wavelength_nm"

    def test_axis_type_wavelength_um(self):
        sa = SpectralAxis(values=np.arange(100), units="µm")
        assert sa.axis_type == "wavelength_um"

    def test_axis_type_none_for_unknown(self):
        sa = SpectralAxis(values=np.arange(100), units="ppm")
        assert sa.axis_type is None

    def test_axis_type_none_when_no_units(self):
        sa = SpectralAxis(values=np.arange(100))
        assert sa.axis_type is None

    def test_range(self):
        sa = SpectralAxis(values=np.array([400.0, 800.0, 1200.0, 4000.0]))
        assert sa.range == (400.0, 4000.0)

    def test_range_none_when_no_values(self):
        sa = SpectralAxis()
        assert sa.range is None

    def test_select_region(self):
        sa = SpectralAxis(values=np.array([100.0, 200.0, 300.0, 400.0, 500.0]))
        mask = sa.select_region(200, 400)
        np.testing.assert_array_equal(mask, [False, True, True, True, False])

    def test_select_region_order_independent(self):
        sa = SpectralAxis(values=np.array([100.0, 200.0, 300.0]))
        mask1 = sa.select_region(100, 200)
        mask2 = sa.select_region(200, 100)
        np.testing.assert_array_equal(mask1, mask2)

    def test_select_region_no_values_raises(self):
        sa = SpectralAxis()
        with pytest.raises(ValueError, match="no values"):
            sa.select_region(0, 100)

    def test_copy_returns_spectral_axis(self):
        sa = SpectralAxis(values=np.array([1.0, 2.0]), units="cm-1", title="wn")
        cp = sa.copy()
        assert isinstance(cp, SpectralAxis)
        assert cp.units == "cm-1"


# ═══════════════════════════════════════════════════════════════════════════
# SampleAxis
# ═══════════════════════════════════════════════════════════════════════════


class TestSampleAxis:
    def test_n_included_all(self):
        sa = SampleAxis(values=np.arange(5))
        assert sa.n_included == 5

    def test_n_included_with_mask(self):
        sa = SampleAxis(
            values=np.arange(5),
            include_mask=np.array([True, True, False, True, False]),
        )
        assert sa.n_included == 3

    def test_exclude(self):
        sa = SampleAxis(values=np.arange(3))
        sa.exclude([1], reason="outlier")
        assert sa.include_mask is not None
        np.testing.assert_array_equal(sa.include_mask, [True, False, True])
        assert sa.exclusion_reasons[1] == "outlier"

    def test_include(self):
        sa = SampleAxis(
            values=np.arange(3),
            include_mask=np.array([True, False, True]),
            exclusion_reasons=[None, "outlier", None],
        )
        sa.include([1])
        np.testing.assert_array_equal(sa.include_mask, [True, True, True])
        assert sa.exclusion_reasons[1] is None

    def test_sample_table(self):
        sa = SampleAxis(values=np.arange(3))
        sa.set_column("batch", ["A", "A", "B"])
        assert sa.get_column("batch") == ["A", "A", "B"]
        assert sa.get_column("missing") is None

    def test_copy_independent(self):
        sa = SampleAxis(
            values=np.arange(3),
            labels=["a", "b", "c"],
            classes=np.array(["X", "Y", "X"], dtype=object),
            include_mask=np.array([True, True, False]),
            sample_table={"batch": ["A", "B", "C"]},
        )
        cp = sa.copy()
        assert isinstance(cp, SampleAxis)
        cp.values[0] = 999
        assert sa.values[0] == 0
        cp.sample_table["batch"][0] = "Z"
        assert sa.sample_table["batch"][0] == "A"

    def test_set_column_length_mismatch(self):
        """set_column rejects values with wrong length."""
        sa = SampleAxis(values=np.arange(3))
        with pytest.raises(ValueError, match="length"):
            sa.set_column("batch", ["A"])

    def test_exclude_out_of_bounds(self):
        """exclude rejects out-of-range indices."""
        sa = SampleAxis(values=np.arange(3))
        with pytest.raises(IndexError):
            sa.exclude([5])

    def test_include_out_of_bounds(self):
        """include rejects out-of-range indices."""
        sa = SampleAxis(
            values=np.arange(3),
            include_mask=np.array([True, False, True]),
        )
        with pytest.raises(IndexError):
            sa.include([10])


# ═══════════════════════════════════════════════════════════════════════════
# DomainContext + InferredDomain
# ═══════════════════════════════════════════════════════════════════════════


class TestDomainContext:
    def test_defaults(self):
        dc = DomainContext()
        assert dc.technique is None
        assert dc.sample_type is None
        assert dc.inferred is None

    def test_with_technique(self):
        dc = DomainContext(technique="IR", sample_type="polymer")
        assert dc.technique == "IR"
        assert dc.sample_type == "polymer"

    def test_with_inferred(self):
        inf = InferredDomain(technique="NIR", confidence=0.8, source="axis_range", reasoning="test")
        dc = DomainContext(inferred=inf)
        assert dc.inferred.technique == "NIR"
        assert dc.inferred.confidence == 0.8


class TestTargetContext:
    def test_defaults(self):
        tc = TargetContext()
        assert tc.target_type is None
        assert tc.n_classes is None

    def test_categorical(self):
        tc = TargetContext(
            target_type="categorical",
            target_name="Species",
            n_classes=3,
            class_names=["setosa", "versicolor", "virginica"],
        )
        assert tc.target_type == "categorical"
        assert tc.n_classes == 3

    def test_continuous(self):
        tc = TargetContext(
            target_type="continuous",
            target_name="Protein",
            target_units="mg/L",
        )
        assert tc.target_units == "mg/L"


# ═══════════════════════════════════════════════════════════════════════════
# Provenance + ProvenanceEntry
# ═══════════════════════════════════════════════════════════════════════════


class TestProvenanceEntry:
    def test_creation(self):
        pe = ProvenanceEntry(op_id="preprocess.snv", parameters={"a": 1})
        assert pe.op_id == "preprocess.snv"
        assert pe.parameters == {"a": 1}

    def test_immutable(self):
        pe = ProvenanceEntry(op_id="test")
        with pytest.raises(Exception):
            pe.op_id = "changed"

    def test_state_effects(self):
        pe = ProvenanceEntry(
            op_id="preprocess.snv",
            state_effects=[EFFECT_NORMALIZED, EFFECT_SCATTER_CORRECTED],
        )
        assert EFFECT_NORMALIZED in pe.state_effects
        assert EFFECT_SCATTER_CORRECTED in pe.state_effects

    def test_state_effects_is_tuple(self):
        """state_effects is coerced to tuple for true immutability."""
        pe = ProvenanceEntry(op_id="test", state_effects=["a", "b"])
        assert isinstance(pe.state_effects, tuple)
        assert pe.state_effects == ("a", "b")

    def test_parameters_deep_copied(self):
        """Mutating the original dict does not affect the entry."""
        params = {"a": 1, "nested": {"b": 2}}
        pe = ProvenanceEntry(op_id="test", parameters=params)
        params["a"] = 99
        params["nested"]["b"] = 99
        assert pe.parameters["a"] == 1
        assert pe.parameters["nested"]["b"] == 2

    def test_parameters_mapping_is_immutable(self):
        pe = ProvenanceEntry(op_id="test", parameters={"a": 1, "nested": {"b": 2}})
        # frozen=True prevents assignment on the model itself
        # Pydantic V2 raises ValidationError (not TypeError) for frozen models
        with pytest.raises(Exception):
            pe.op_id = "changed"  # type: ignore[misc]
        # Parameters are deep-copied at construction, so the model holds its own copy.
        # Verify the values are correct and isolated from the source dict.
        assert pe.parameters["a"] == 1
        assert pe.parameters["nested"]["b"] == 2

    def test_provenance_copy_isolation(self):
        """Mutating a copied provenance does not affect the original."""
        prov = Provenance()
        prov.append("op1", {"a": {"b": 1}})
        copy = prov.copy()
        copy.append("op2", {"b": 2})
        with pytest.raises(TypeError):
            copy[0].parameters["a"]["b"] = 2  # type: ignore[index]
        assert len(prov) == 1
        assert len(copy) == 2


class TestProvenance:
    def test_empty(self):
        prov = Provenance()
        assert len(prov) == 0
        assert not prov
        assert prov.operations == []

    def test_append(self):
        prov = Provenance()
        prov.append("preprocess.snv", {"param": 1}, state_effects=[EFFECT_NORMALIZED])
        assert len(prov) == 1
        assert prov[0].op_id == "preprocess.snv"
        assert prov[0].timestamp  # auto-generated

    def test_iteration(self):
        prov = Provenance()
        prov.append("step1", {})
        prov.append("step2", {})
        ops = [e.op_id for e in prov]
        assert ops == ["step1", "step2"]

    def test_all_effects(self):
        prov = Provenance()
        prov.append("a", {}, state_effects=[EFFECT_NORMALIZED])
        prov.append("b", {}, state_effects=[EFFECT_SCALED, EFFECT_NORMALIZED])
        effects = prov.all_effects
        assert effects == frozenset({EFFECT_NORMALIZED, EFFECT_SCALED})

    def test_has_effect(self):
        prov = Provenance()
        prov.append("a", {}, state_effects=[EFFECT_SMOOTHED])
        assert prov.has_effect(EFFECT_SMOOTHED)
        assert not prov.has_effect(EFFECT_SCALED)

    def test_has_operation(self):
        prov = Provenance()
        prov.append("preprocess.snv", {})
        assert prov.has_operation("preprocess.")
        assert not prov.has_operation("model.")

    def test_to_list_from_list_roundtrip(self):
        prov = Provenance()
        prov.append("op1", {"x": 1}, state_effects=["eff1"])
        prov.append("op2", {"y": 2})
        data = prov.to_list()
        restored = Provenance.from_list(data)
        assert len(restored) == 2
        assert restored[0].op_id == "op1"
        assert restored[0].state_effects == ("eff1",)
        assert restored[1].op_id == "op2"

    def test_from_list_legacy_format(self):
        """Legacy format uses 'operation' key instead of 'op_id'."""
        data = [{"operation": "normalize.snv", "parameters": {}}]
        prov = Provenance.from_list(data)
        assert prov[0].op_id == "normalize.snv"

    def test_copy_independent(self):
        prov = Provenance()
        prov.append("step1", {})
        cp = prov.copy()
        cp.append("step2", {})
        assert len(prov) == 1
        assert len(cp) == 2


# ═══════════════════════════════════════════════════════════════════════════
# DatasetState
# ═══════════════════════════════════════════════════════════════════════════


class TestDatasetState:
    def test_raw_state(self):
        prov = Provenance()
        state = DatasetState.from_provenance(prov)
        assert state.processing_stage == "raw"
        assert state.effects == frozenset()
        assert state.n_steps == 0

    def test_preprocessed_state(self):
        prov = Provenance()
        prov.append("snv", {}, state_effects=[EFFECT_NORMALIZED])
        state = DatasetState.from_provenance(prov)
        assert state.processing_stage == "preprocessed"
        assert state.is_normalized
        assert not state.is_scaled

    def test_modeled_state(self):
        prov = Provenance()
        prov.append("snv", {}, state_effects=[EFFECT_NORMALIZED])
        prov.append("pls", {}, state_effects=["modeled"])
        state = DatasetState.from_provenance(prov)
        assert state.processing_stage == "modeled"

    def test_immutable(self):
        state = DatasetState(processing_stage="raw", effects=frozenset(), n_steps=0)
        with pytest.raises(Exception):
            state.processing_stage = "preprocessed"

    def test_convenience_properties(self):
        prov = Provenance()
        prov.append(
            "a", {}, state_effects=[EFFECT_BASELINE_CORRECTED, EFFECT_SMOOTHED, EFFECT_MEAN_CENTERED, EFFECT_SCALED]
        )
        state = DatasetState.from_provenance(prov)
        assert state.is_baseline_corrected
        assert state.is_smoothed
        assert state.is_mean_centered
        assert state.is_scaled


# ═══════════════════════════════════════════════════════════════════════════
# QualityMetrics + EvaluationResult
# ═══════════════════════════════════════════════════════════════════════════


class TestQualityMetrics:
    def test_empty(self):
        qm = QualityMetrics()
        assert qm.snr is None
        assert qm.evaluations == []
        assert qm.latest is None

    def test_add_evaluation(self):
        qm = QualityMetrics()
        ev = EvaluationResult(
            evaluation_id="ev1",
            model_type="PLS",
            r2=0.95,
            rmse=0.1,
        )
        qm.add_evaluation(ev)
        assert len(qm.evaluations) == 1
        assert qm.latest is ev
        assert qm.latest.r2 == 0.95

    def test_multiple_evaluations(self):
        qm = QualityMetrics()
        ev1 = EvaluationResult(evaluation_id="ev1", model_type="PLS", r2=0.90)
        ev2 = EvaluationResult(evaluation_id="ev2", model_type="PLS", r2=0.95, fold=1)
        qm.add_evaluation(ev1)
        qm.add_evaluation(ev2)
        assert qm.latest is ev2
        assert qm.latest.fold == 1


class TestEvaluationResult:
    def test_immutable(self):
        ev = EvaluationResult(evaluation_id="ev1")
        with pytest.raises(Exception):
            ev.model_type = "PLS"

    def test_regression_metrics(self):
        ev = EvaluationResult(
            evaluation_id="ev1",
            model_type="PLS",
            r2=0.95,
            rmse=0.1,
            mae=0.08,
            n_components=5,
        )
        assert ev.r2 == 0.95
        assert ev.n_components == 5

    def test_classification_metrics(self):
        cm = [[10.0, 2.0], [1.0, 12.0]]
        ev = EvaluationResult(
            evaluation_id="ev1",
            model_type="KNN",
            accuracy=0.88,
            confusion_matrix=cm,
        )
        assert ev.accuracy == 0.88
        assert ev.confusion_matrix == cm

    def test_outlier_metrics(self):
        ev = EvaluationResult(
            evaluation_id="ev1",
            outlier_indices=[2, 5, 8],
            outlier_percentage=12.5,
            t2_limit=3.5,
            q_limit=1.2,
        )
        assert ev.outlier_indices == [2, 5, 8]
        assert ev.t2_limit == 3.5


# ═══════════════════════════════════════════════════════════════════════════
# BranchInfo + DatasetManifest
# ═══════════════════════════════════════════════════════════════════════════


class TestBranchInfo:
    def test_creation(self):
        bi = BranchInfo(
            label="snv_branch",
            parent_dataset_id="abc123",
            parent_provenance_index=3,
            content_hash="deadbeef",
        )
        assert bi.label == "snv_branch"
        assert bi.content_hash == "deadbeef"

    def test_immutable(self):
        bi = BranchInfo(label="x", parent_dataset_id="y", parent_provenance_index=0, content_hash="z")
        with pytest.raises(Exception):
            bi.label = "changed"


class TestDatasetManifest:
    def test_from_dataset(self):
        ds = SherpaDataset(
            X=np.zeros((3, 5)),
            title="test",
            domain=DomainContext(technique="IR"),
        )
        ds.provenance.append("step1", {}, state_effects=[EFFECT_NORMALIZED])
        m = ds.manifest
        assert isinstance(m, DatasetManifest)
        assert m.dataset_id == ds.dataset_id
        assert m.shape == (3, 5)
        assert m.title == "test"
        assert m.technique == "IR"
        assert m.n_provenance_steps == 1
        assert EFFECT_NORMALIZED in m.state_effects


# ═══════════════════════════════════════════════════════════════════════════
# SherpaDataset — Construction + Shape Invariants
# ═══════════════════════════════════════════════════════════════════════════


class TestSherpaDatasetConstruction:
    def test_2d_array(self):
        ds = SherpaDataset(X=np.array([[1, 2], [3, 4]]))
        assert ds.shape == (2, 2)
        assert ds.X.dtype == np.float64

    def test_1d_promoted_to_2d(self):
        ds = SherpaDataset(X=np.array([1, 2, 3]))
        assert ds.ndim == 2
        assert ds.shape == (1, 3)

    def test_list_of_lists(self):
        ds = SherpaDataset(X=[[1, 2], [3, 4]])
        assert ds.shape == (2, 2)

    def test_defaults(self):
        ds = SherpaDataset(X=np.zeros((2, 3)))
        assert ds.spectral_axis is None
        assert ds.sample_axis is None
        assert ds.target is None
        assert ds.backend == "numpy"
        assert ds.title is None
        assert ds.units is None
        assert len(ds.provenance) == 0
        assert ds.state.processing_stage == "raw"
        assert ds.dataset_id  # UUID assigned

    def test_data_alias(self):
        ds = SherpaDataset(X=np.ones((2, 3)))
        assert ds.data is ds.X


class TestShapeInvariants:
    def test_spectral_axis_mismatch_raises(self):
        with pytest.raises(ValueError, match="spectral_axis length"):
            SherpaDataset(
                X=np.zeros((3, 5)),
                spectral_axis=SpectralAxis(values=np.arange(10)),  # 10 != 5
            )

    def test_sample_axis_mismatch_raises(self):
        with pytest.raises(ValueError, match="sample_axis length"):
            SherpaDataset(
                X=np.zeros((3, 5)),
                sample_axis=SampleAxis(values=np.arange(10)),  # 10 != 3
            )

    def test_target_mismatch_raises(self):
        with pytest.raises(ValueError, match="target length"):
            SherpaDataset(
                X=np.zeros((3, 5)),
                target=np.array([0, 1]),  # 2 != 3
            )

    def test_sample_axis_classes_mismatch_raises(self):
        with pytest.raises(ValueError, match="classes length"):
            SherpaDataset(
                X=np.zeros((3, 5)),
                sample_axis=SampleAxis(
                    values=np.arange(3),
                    classes=np.array(["A", "B"]),  # 2 != 3
                ),
            )

    def test_sample_axis_include_mask_mismatch_raises(self):
        with pytest.raises(ValueError, match="include_mask length"):
            SherpaDataset(
                X=np.zeros((3, 5)),
                sample_axis=SampleAxis(
                    values=np.arange(3),
                    include_mask=np.array([True, False]),  # 2 != 3
                ),
            )

    def test_spectral_axis_setter_validates(self):
        ds = SherpaDataset(X=np.zeros((3, 5)))
        with pytest.raises(ValueError, match="spectral_axis length"):
            ds.spectral_axis = SpectralAxis(values=np.arange(10))

    def test_sample_axis_setter_validates(self):
        ds = SherpaDataset(X=np.zeros((3, 5)))
        with pytest.raises(ValueError, match="sample_axis length"):
            ds.sample_axis = SampleAxis(values=np.arange(10))

    def test_target_setter_validates(self):
        ds = SherpaDataset(X=np.zeros((3, 5)))
        with pytest.raises(ValueError, match="target length"):
            ds.target = np.array([0, 1])

    def test_post_init_sample_axis_assignment_validates(self):
        ds = SherpaDataset(
            X=np.zeros((3, 5)),
            sample_axis=SampleAxis(values=np.arange(3), labels=["a", "b", "c"]),
        )
        ax = ds.sample_axis
        with pytest.raises(ValueError, match="expected length"):
            ax.include_mask = np.array([True, False])  # type: ignore[assignment]
        assert ds.sample_axis.include_mask is None

    def test_post_init_sample_table_assignment_validates(self):
        ds = SherpaDataset(
            X=np.zeros((3, 5)),
            sample_axis=SampleAxis(values=np.arange(3), labels=["a", "b", "c"]),
        )
        ax = ds.sample_axis
        with pytest.raises(ValueError, match="length"):
            ax.set_column("batch", [1, 2])  # type: ignore[union-attr]
        assert ds.sample_axis.sample_table is None

    def test_valid_axes_accepted(self):
        ds = SherpaDataset(
            X=np.zeros((3, 5)),
            spectral_axis=SpectralAxis(values=np.arange(5)),
            sample_axis=SampleAxis(values=np.arange(3)),
            target=np.array([0, 1, 2]),
        )
        assert ds.spectral_axis.length == 5
        assert ds.sample_axis.length == 3
        assert len(ds.target) == 3

    def test_empty_axis_accepted(self):
        """An axis with no values (length 0) is always accepted."""
        ds = SherpaDataset(
            X=np.zeros((3, 5)),
            spectral_axis=SpectralAxis(title="empty"),
        )
        assert ds.spectral_axis.title == "empty"


# ═══════════════════════════════════════════════════════════════════════════
# SherpaDataset — Axis Access + N-Dimensional
# ═══════════════════════════════════════════════════════════════════════════


class TestAxisAccess:
    def test_spectral_axis_property(self):
        sa = SpectralAxis(values=np.arange(5), units="cm-1")
        ds = SherpaDataset(X=np.zeros((3, 5)), spectral_axis=sa)
        assert ds.spectral_axis is not sa
        assert isinstance(ds.axis(-1), SpectralAxis)
        np.testing.assert_array_equal(ds.axis(-1).values, sa.values)

    def test_sample_axis_property(self):
        sa = SampleAxis(values=np.arange(3), labels=["a", "b", "c"])
        ds = SherpaDataset(X=np.zeros((3, 5)), sample_axis=sa)
        assert ds.sample_axis is not sa
        assert isinstance(ds.axis(0), SampleAxis)
        np.testing.assert_array_equal(ds.axis(0).values, sa.values)

    def test_axis_unknown_dim(self):
        ds = SherpaDataset(X=np.zeros((3, 5)))
        assert ds.axis(2) is None


# ═══════════════════════════════════════════════════════════════════════════
# SherpaDataset — Domain, Provenance, Quality, State
# ═══════════════════════════════════════════════════════════════════════════


class TestDomainProvenanceQuality:
    def test_domain_default(self):
        ds = SherpaDataset(X=np.zeros((2, 3)))
        assert ds.domain.technique is None

    def test_domain_set(self):
        ds = SherpaDataset(X=np.zeros((2, 3)))
        ds.domain = DomainContext(technique="Raman")
        assert ds.domain.technique == "Raman"

    def test_provenance_is_source_of_truth(self):
        ds = SherpaDataset(X=np.zeros((2, 3)))
        ds.provenance.append("snv", {}, state_effects=[EFFECT_NORMALIZED])
        assert ds.state.is_normalized
        assert ds.state.processing_stage == "preprocessed"

    def test_state_always_fresh(self):
        ds = SherpaDataset(X=np.zeros((2, 3)))
        state1 = ds.state
        assert state1.n_steps == 0
        ds.provenance.append("op", {})
        state2 = ds.state
        assert state2.n_steps == 1
        # state1 is a snapshot, not affected by the append
        assert state1.n_steps == 0

    def test_quality_add_evaluation(self):
        ds = SherpaDataset(X=np.zeros((2, 3)))
        ev = EvaluationResult(evaluation_id="ev1", model_type="PLS", r2=0.95)
        ds.quality.add_evaluation(ev)
        assert ds.quality.latest.r2 == 0.95


# ═══════════════════════════════════════════════════════════════════════════
# SherpaDataset — Extra Metadata (namespaced)
# ═══════════════════════════════════════════════════════════════════════════


class TestExtraMetadata:
    def test_set_get(self):
        ds = SherpaDataset(X=np.zeros((2, 3)))
        ds.set_extra("mypackage.key", "value")
        assert ds.get_extra("mypackage.key") == "value"

    def test_get_default(self):
        ds = SherpaDataset(X=np.zeros((2, 3)))
        assert ds.get_extra("missing.key") is None
        assert ds.get_extra("missing.key", "default") == "default"

    def test_non_namespaced_raises(self):
        ds = SherpaDataset(X=np.zeros((2, 3)))
        with pytest.raises(ValueError, match="namespaced"):
            ds.set_extra("noprefix", "value")

    def test_reserved_prefix_raises(self):
        ds = SherpaDataset(X=np.zeros((2, 3)))
        with pytest.raises(ValueError, match="reserved"):
            ds.set_extra("sherpa.internal", "value")
        with pytest.raises(ValueError, match="reserved"):
            ds.set_extra("system.config", "value")


# ═══════════════════════════════════════════════════════════════════════════
# SherpaDataset — Equality + Fingerprint
# ═══════════════════════════════════════════════════════════════════════════


class TestEquality:
    def test_data_equality(self):
        a = SherpaDataset(X=np.array([[1.0, 2.0]]))
        b = SherpaDataset(X=np.array([[1.0, 2.0]]))
        assert a == b
        assert a.equals(b, mode="data")

    def test_data_inequality(self):
        a = SherpaDataset(X=np.array([[1.0, 2.0]]))
        b = SherpaDataset(X=np.array([[1.0, 3.0]]))
        assert a != b

    def test_metadata_equality(self):
        a = SherpaDataset(X=np.array([[1.0]]), title="A", units="abs", domain=DomainContext(technique="IR"))
        b = SherpaDataset(X=np.array([[9.0]]), title="A", units="abs", domain=DomainContext(technique="IR"))
        assert a.equals(b, mode="metadata")

    def test_metadata_inequality(self):
        a = SherpaDataset(X=np.array([[1.0]]), title="A")
        b = SherpaDataset(X=np.array([[1.0]]), title="B")
        assert not a.equals(b, mode="metadata")

    def test_full_equality(self):
        a = SherpaDataset(X=np.array([[1.0]]), title="A", domain=DomainContext(technique="IR"))
        b = SherpaDataset(X=np.array([[1.0]]), title="A", domain=DomainContext(technique="IR"))
        assert a.equals(b, mode="full")

    def test_full_inequality_data(self):
        a = SherpaDataset(X=np.array([[1.0]]), title="A")
        b = SherpaDataset(X=np.array([[2.0]]), title="A")
        assert not a.equals(b, mode="full")

    def test_full_inequality_metadata(self):
        a = SherpaDataset(X=np.array([[1.0]]), title="A")
        b = SherpaDataset(X=np.array([[1.0]]), title="B")
        assert not a.equals(b, mode="full")

    def test_tolerance(self):
        a = SherpaDataset(X=np.array([[1.0]]))
        b = SherpaDataset(X=np.array([[1.0 + 1e-10]]))
        assert a.equals(b, atol=1e-8)

    def test_fingerprint(self):
        a = SherpaDataset(X=np.array([[1.0, 2.0]]))
        b = SherpaDataset(X=np.array([[1.0, 2.0]]))
        assert a.fingerprint == b.fingerprint
        c = SherpaDataset(X=np.array([[1.0, 3.0]]))
        assert a.fingerprint != c.fingerprint

    def test_eq_not_implemented_for_non_dataset(self):
        ds = SherpaDataset(X=np.zeros((2, 3)))
        assert ds.__eq__("not a dataset") is NotImplemented


# ═══════════════════════════════════════════════════════════════════════════
# SherpaDataset — Copy
# ═══════════════════════════════════════════════════════════════════════════


class TestSherpaDatasetCopy:
    def _make_ds(self):
        return SherpaDataset(
            X=np.array([[1.0, 2.0], [3.0, 4.0]]),
            spectral_axis=SpectralAxis(values=np.array([10.0, 20.0]), units="nm"),
            sample_axis=SampleAxis(values=np.array([0.0, 1.0]), labels=["s1", "s2"]),
            target=np.array([0, 1]),
            domain=DomainContext(technique="IR"),
            backend="numpy",
            title="original",
            units="absorbance",
        )

    def test_copy_returns_new_instance(self):
        ds = self._make_ds()
        cp = ds.copy()
        assert cp is not ds

    def test_copy_new_dataset_id(self):
        ds = self._make_ds()
        cp = ds.copy()
        assert cp.dataset_id != ds.dataset_id

    def test_copy_X_independent(self):
        ds = self._make_ds()
        cp = ds.copy()
        cp._X[0, 0] = 999.0
        assert ds.X[0, 0] == 1.0

    def test_copy_spectral_axis_independent(self):
        ds = self._make_ds()
        cp = ds.copy()
        cp.spectral_axis.values[0] = 999.0
        assert ds.spectral_axis.values[0] == 10.0

    def test_copy_sample_axis_independent(self):
        ds = self._make_ds()
        cp = ds.copy()
        cp.sample_axis.labels[0] = "CHANGED"
        assert ds.sample_axis.labels[0] == "s1"

    def test_copy_target_independent(self):
        ds = self._make_ds()
        cp = ds.copy()
        cp._target[0] = 999
        assert ds.target[0] == 0

    def test_copy_provenance_independent(self):
        ds = self._make_ds()
        ds.provenance.append("step1", {})
        cp = ds.copy()
        cp.provenance.append("step2", {})
        assert len(ds.provenance) == 1
        assert len(cp.provenance) == 2

    def test_copy_preserves_scalars(self):
        ds = self._make_ds()
        cp = ds.copy()
        assert cp.backend == "numpy"
        assert cp.title == "original"
        assert cp.units == "absorbance"
        assert cp.domain.technique == "IR"


# ═══════════════════════════════════════════════════════════════════════════
# SherpaDataset — __getitem__
# ═══════════════════════════════════════════════════════════════════════════


class TestSherpaDatasetGetitem:
    def _make_ds(self):
        X = np.arange(20, dtype=float).reshape(4, 5)
        return SherpaDataset(
            X=X,
            spectral_axis=SpectralAxis(values=np.array([100, 200, 300, 400, 500], dtype=float)),
            sample_axis=SampleAxis(values=np.arange(4, dtype=float), labels=["s0", "s1", "s2", "s3"]),
            target=np.array([0, 1, 0, 1]),
            title="indexed",
        )

    def test_bool_mask(self):
        ds = self._make_ds()
        mask = np.array([True, False, True, False])
        result = ds[mask]
        assert result.shape == (2, 5)
        np.testing.assert_array_equal(result.X[0], ds.X[0])
        np.testing.assert_array_equal(result.X[1], ds.X[2])

    def test_bool_mask_slices_sample_axis(self):
        ds = self._make_ds()
        mask = np.array([True, False, True, False])
        result = ds[mask]
        assert result.sample_axis.labels == ["s0", "s2"]

    def test_bool_mask_preserves_spectral_axis(self):
        ds = self._make_ds()
        mask = np.array([True, False, True, False])
        result = ds[mask]
        np.testing.assert_array_equal(result.spectral_axis.values, ds.spectral_axis.values)

    def test_bool_mask_slices_target(self):
        ds = self._make_ds()
        mask = np.array([False, True, False, True])
        result = ds[mask]
        np.testing.assert_array_equal(result.target, [1, 1])

    def test_int_index(self):
        ds = self._make_ds()
        result = ds[2]
        assert result.shape == (1, 5)
        np.testing.assert_array_equal(result.X[0], ds.X[2])

    def test_int_index_slices_sample_axis(self):
        ds = self._make_ds()
        result = ds[1]
        assert result.sample_axis.labels == ["s1"]

    def test_tuple_col_slice(self):
        ds = self._make_ds()
        result = ds[:, 1:4]
        assert result.shape == (4, 3)

    def test_tuple_col_slice_spectral_axis(self):
        ds = self._make_ds()
        result = ds[:, 1:3]
        np.testing.assert_array_equal(result.spectral_axis.values, [200, 300])

    def test_preserves_domain_and_provenance(self):
        ds = self._make_ds()
        ds.domain = DomainContext(technique="IR")
        ds.provenance.append("step1", {})
        result = ds[0]
        assert result.domain.technique == "IR"
        assert len(result.provenance) == 1

    # -- Regression: plain slice (P0 fix) ------------------------------------

    def test_plain_slice(self):
        """ds[1:3] must slice rows and sample axis correctly."""
        ds = self._make_ds()
        result = ds[1:3]
        assert result.shape == (2, 5)
        np.testing.assert_array_equal(result.X[0], ds.X[1])
        np.testing.assert_array_equal(result.X[1], ds.X[2])

    def test_plain_slice_sample_axis(self):
        ds = self._make_ds()
        result = ds[1:3]
        assert result.sample_axis is not None
        assert result.sample_axis.labels == ["s1", "s2"]

    def test_plain_slice_preserves_spectral_axis(self):
        ds = self._make_ds()
        result = ds[1:3]
        assert result.spectral_axis is not None
        np.testing.assert_array_equal(result.spectral_axis.values, ds.spectral_axis.values)

    def test_plain_slice_target(self):
        ds = self._make_ds()
        result = ds[1:3]
        np.testing.assert_array_equal(result.target, [1, 0])

    # -- Regression: column scalar indexing (P0 fix) -------------------------

    def test_column_scalar_index(self):
        """ds[:, 0] must work without axis validation errors."""
        ds = self._make_ds()
        result = ds[:, 0]
        assert result.shape == (4, 1)

    def test_column_scalar_index_spectral_axis(self):
        """ds[:, 0] spectral axis must be 1-d with 1 element."""
        ds = self._make_ds()
        result = ds[:, 0]
        assert result.spectral_axis is not None
        assert result.spectral_axis.length == 1
        np.testing.assert_array_equal(result.spectral_axis.values, [100])

    def test_column_scalar_with_row_slice(self):
        """ds[0:2, 0] must slice both dimensions."""
        ds = self._make_ds()
        result = ds[0:2, 0]
        assert result.shape == (2, 1)

    def test_row_scalar_col_slice(self):
        """ds[0, 1:4] must work."""
        ds = self._make_ds()
        result = ds[0, 1:4]
        assert result.shape == (1, 3)


# ═══════════════════════════════════════════════════════════════════════════
# SherpaDataset — Branching
# ═══════════════════════════════════════════════════════════════════════════


class TestBranching:
    def test_branch_creates_new_id(self):
        ds = SherpaDataset(X=np.zeros((3, 5)))
        branched = ds.branch("snv_path")
        assert branched.dataset_id != ds.dataset_id

    def test_branch_info(self):
        ds = SherpaDataset(X=np.zeros((3, 5)))
        ds.provenance.append("step1", {})
        branched = ds.branch("snv_path")
        bi = branched.branch_info
        assert bi is not None
        assert bi.label == "snv_path"
        assert bi.parent_dataset_id == ds.dataset_id
        assert bi.parent_provenance_index == 1
        assert len(bi.content_hash) == 64  # full sha256

    def test_branch_data_independent(self):
        ds = SherpaDataset(X=np.array([[1.0, 2.0]]))
        branched = ds.branch("test")
        branched._X[0, 0] = 999.0
        assert ds.X[0, 0] == 1.0

    def test_compare_branches(self):
        ds = SherpaDataset(X=np.zeros((3, 5)))
        a = ds.branch("path_a")
        b = ds.branch("path_b")
        a.provenance.append("snv", {}, state_effects=[EFFECT_NORMALIZED])
        b.provenance.append("msc", {}, state_effects=[EFFECT_SCATTER_CORRECTED])
        diff = SherpaDataset.compare_branches(a, b)
        assert diff["a_label"] == "path_a"
        assert diff["b_label"] == "path_b"
        assert EFFECT_NORMALIZED in diff["effects_only_in_a"]
        assert EFFECT_SCATTER_CORRECTED in diff["effects_only_in_b"]


# ═══════════════════════════════════════════════════════════════════════════
# SherpaDataset — Serialization (to_dict / from_dict)
# ═══════════════════════════════════════════════════════════════════════════


class TestSherpaDatasetSerialization:
    def _make_ds(self):
        ds = SherpaDataset(
            X=np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]),
            spectral_axis=SpectralAxis(values=np.array([100.0, 200.0, 300.0]), units="cm-1", title="wavenumber"),
            sample_axis=SampleAxis(values=np.array([0.0, 1.0]), labels=["s1", "s2"], title="samples"),
            target=np.array([0, 1]),
            domain=DomainContext(technique="IR"),
            backend="numpy",
            title="Test",
            units="absorbance",
        )
        ds.provenance.append("snv", {"param": 1}, state_effects=[EFFECT_NORMALIZED])
        return ds

    def test_type_field(self):
        d = self._make_ds().to_dict()
        assert d["type"] == "SherpaDataset"
        assert d["version"] == "1.0"

    def test_shape_and_data(self):
        d = self._make_ds().to_dict()
        assert d["shape"] == [2, 3]
        assert d["n_samples"] == 2
        assert d["n_features"] == 3
        assert d["data"] == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]

    def test_spectral_axis_uses_data_key(self):
        d = self._make_ds().to_dict()
        assert "data" in d["spectral_axis"]
        assert d["spectral_axis"]["data"] == [100.0, 200.0, 300.0]

    def test_domain_serialized(self):
        d = self._make_ds().to_dict()
        assert d["domain"]["technique"] == "IR"

    def test_provenance_serialized(self):
        d = self._make_ds().to_dict()
        assert len(d["provenance"]) == 1
        assert d["provenance"][0]["op_id"] == "snv"

    def test_state_serialized(self):
        d = self._make_ds().to_dict()
        assert d["state"]["processing_stage"] == "preprocessed"

    def test_metadata_block_for_frontend(self):
        d = self._make_ds().to_dict()
        assert "metadata" in d
        assert d["metadata"]["data_type"] == "IR"
        assert d["metadata"]["is_spectra"] is True

    def test_nan_sanitized(self):
        ds = SherpaDataset(X=np.array([[1.0, float("nan")]]))
        d = ds.to_dict()
        assert d["data"][0][0] == 1.0
        assert d["data"][0][1] is None

    def test_round_trip(self):
        original = self._make_ds()
        d = original.to_dict()
        restored = SherpaDataset.from_dict(d)
        np.testing.assert_array_almost_equal(restored.X, original.X)
        assert restored.shape == original.shape
        assert restored.title == original.title
        assert restored.units == original.units
        assert restored.backend == original.backend
        assert restored.domain.technique == "IR"
        assert len(restored.provenance) == 1
        assert restored.provenance[0].op_id == "snv"

    def test_round_trip_target(self):
        ds = SherpaDataset(X=np.zeros((3, 2)), target=np.array([0, 1, 2]))
        d = ds.to_dict()
        restored = SherpaDataset.from_dict(d)
        np.testing.assert_array_equal(restored.target, [0, 1, 2])

    def test_round_trip_branch(self):
        ds = SherpaDataset(X=np.zeros((3, 2)))
        branched = ds.branch("test_branch")
        d = branched.to_dict()
        restored = SherpaDataset.from_dict(d)
        assert restored.branch_info is not None
        assert restored.branch_info.label == "test_branch"

    def test_from_dict_rejects_wrong_type(self):
        with pytest.raises(ValueError, match="Expected type='SherpaDataset'"):
            SherpaDataset.from_dict({"type": "NDDataset", "data": [[1.0]]})

    def test_round_trip_extra(self):
        ds = SherpaDataset(X=np.zeros((2, 3)), extra={"my.key": "value"})
        d = ds.to_dict()
        restored = SherpaDataset.from_dict(d)
        assert restored.get_extra("my.key") == "value"


# ═══════════════════════════════════════════════════════════════════════════
# SherpaDataset — __repr__
# ═══════════════════════════════════════════════════════════════════════════


class TestSherpaDatasetRepr:
    def test_repr(self):
        ds = SherpaDataset(
            X=np.zeros((3, 5)),
            domain=DomainContext(technique="IR"),
            backend="scp",
            title="MyData",
        )
        r = repr(ds)
        assert "SherpaDataset" in r
        assert "shape=(3, 5)" in r
        assert "technique='IR'" in r
        assert "backend='scp'" in r
        assert "title='MyData'" in r


# ═══════════════════════════════════════════════════════════════════════════
# DatasetSummarizer
# ═══════════════════════════════════════════════════════════════════════════


class TestDatasetSummarizer:
    @pytest.fixture
    def summarizer(self):
        from spectra_sherpa.app.lib.dataset_summarizer import DatasetSummarizer

        return DatasetSummarizer()

    @pytest.fixture
    def sample_ds(self):
        ds = SherpaDataset(
            X=np.random.rand(10, 100),
            spectral_axis=SpectralAxis(values=np.linspace(400, 4000, 100), units="cm-1", title="wavenumber"),
            sample_axis=SampleAxis(
                values=np.arange(10, dtype=float),
                labels=[f"sample_{i}" for i in range(10)],
            ),
            target=np.random.rand(10),
            target_context=TargetContext(target_type="continuous", target_name="Protein"),
            domain=DomainContext(technique="IR", sample_type="polymer"),
            title="Test IR Data",
            units="absorbance",
        )
        ds.provenance.append(
            "preprocess.snv",
            {"normalize": True},
            state_effects=[EFFECT_NORMALIZED, EFFECT_SCATTER_CORRECTED],
        )
        ds.quality.add_evaluation(
            EvaluationResult(
                evaluation_id="ev1",
                model_type="PLS",
                r2=0.95,
                rmse=0.05,
            )
        )
        return ds

    def test_tier0(self, summarizer, sample_ds):
        text = summarizer.summarize(sample_ds, tier=0)
        assert "Test IR Data" in text
        assert "10 samples" in text
        assert "100 features" in text
        assert "IR" in text

    def test_tier1(self, summarizer, sample_ds):
        text = summarizer.summarize(sample_ds, tier=1)
        assert "preprocessed" in text
        assert EFFECT_NORMALIZED in text
        assert "cm-1" in text or "wavenumber" in text

    def test_tier2(self, summarizer, sample_ds):
        text = summarizer.summarize(sample_ds, tier=2)
        assert "Provenance" in text
        assert "preprocess.snv" in text
        assert "normalize" in text

    def test_tier3(self, summarizer, sample_ds):
        text = summarizer.summarize(sample_ds, tier=3)
        assert "PLS" in text
        assert "R2" in text or "0.95" in text

    def test_max_tokens_truncation(self, summarizer, sample_ds):
        text = summarizer.summarize(sample_ds, tier=3, max_tokens=10)
        assert len(text) <= 10 * 4 + 20  # ~4 chars/token + truncation message

    def test_to_structured_tier0(self, summarizer, sample_ds):
        d = summarizer.to_structured(sample_ds, tier=0)
        assert d["dataset_id"] == sample_ds.dataset_id
        assert d["shape"] == [10, 100]
        assert d["domain"]["technique"] == "IR"
        assert "state" not in d

    def test_to_structured_tier1(self, summarizer, sample_ds):
        d = summarizer.to_structured(sample_ds, tier=1)
        assert d["state"]["processing_stage"] == "preprocessed"
        assert d["spectral_axis"]["units"] == "cm-1"
        assert d["target"]["type"] == "continuous"

    def test_to_structured_tier3(self, summarizer, sample_ds):
        d = summarizer.to_structured(sample_ds, tier=3)
        assert "quality" in d
        assert d["quality"]["n_evaluations"] == 1
        assert "data_statistics" in d
        assert "mean" in d["data_statistics"]

    def test_to_mcp_resource(self, summarizer, sample_ds):
        resource = summarizer.to_mcp_resource(sample_ds)
        assert "manifest" in resource
        assert "preview" in resource
        assert "provenance" in resource
        assert resource["manifest"]["dataset_id"] == sample_ds.dataset_id


# ═══════════════════════════════════════════════════════════════════════════
# Adapters — numpy
# ═══════════════════════════════════════════════════════════════════════════


class TestNumpyAdapter:
    def test_from_numpy_basic(self):
        from spectra_sherpa.app.lib.adapters.numpy_adapter import from_numpy

        ds = from_numpy(np.array([[1.0, 2.0], [3.0, 4.0]]))
        assert ds.shape == (2, 2)
        assert ds.backend == "numpy"

    def test_from_numpy_wavenumbers(self):
        from spectra_sherpa.app.lib.adapters.numpy_adapter import from_numpy

        ds = from_numpy(
            np.zeros((3, 5)),
            wavenumbers=np.linspace(400, 4000, 5),
            technique="IR",
            title="Test",
        )
        assert ds.spectral_axis is not None
        assert ds.spectral_axis.units == "cm-1"
        assert ds.spectral_axis.axis_type == "wavenumber"
        assert ds.domain.technique == "IR"
        assert ds.title == "Test"

    def test_from_numpy_wavelengths(self):
        from spectra_sherpa.app.lib.adapters.numpy_adapter import from_numpy

        ds = from_numpy(
            np.zeros((3, 5)),
            wavelengths=np.linspace(700, 2500, 5),
        )
        assert ds.spectral_axis.units == "nm"

    def test_from_numpy_both_raises(self):
        from spectra_sherpa.app.lib.adapters.numpy_adapter import from_numpy

        with pytest.raises(ValueError, match="not both"):
            from_numpy(
                np.zeros((3, 5)),
                wavenumbers=np.arange(5),
                wavelengths=np.arange(5),
            )

    def test_from_numpy_with_target(self):
        from spectra_sherpa.app.lib.adapters.numpy_adapter import from_numpy

        ds = from_numpy(
            np.zeros((3, 5)),
            target=np.array([0, 1, 2]),
            target_name="Species",
            target_type="categorical",
        )
        np.testing.assert_array_equal(ds.target, [0, 1, 2])
        assert ds.target_context.target_name == "Species"

    def test_to_numpy(self):
        from spectra_sherpa.app.lib.adapters.numpy_adapter import from_numpy, to_numpy

        ds = from_numpy(
            np.array([[1.0, 2.0], [3.0, 4.0]]),
            wavenumbers=np.array([100.0, 200.0]),
            target=np.array([0, 1]),
            sample_labels=["s1", "s2"],
        )
        result = to_numpy(ds)
        np.testing.assert_array_equal(result["X"], [[1.0, 2.0], [3.0, 4.0]])
        np.testing.assert_array_equal(result["wavenumbers"], [100.0, 200.0])
        np.testing.assert_array_equal(result["target"], [0, 1])
        assert result["sample_labels"] == ["s1", "s2"]


# ═══════════════════════════════════════════════════════════════════════════
# Adapters — sklearn
# ═══════════════════════════════════════════════════════════════════════════


class TestSklearnAdapter:
    def _make_bunch(self):
        return SimpleNamespace(
            data=np.array([[5.1, 3.5], [4.9, 3.0], [7.0, 3.2]]),
            target=np.array([0, 0, 1]),
            feature_names=["sepal_length", "sepal_width"],
            target_names=["setosa", "versicolor"],
            DESCR="A test dataset",
        )

    def test_from_sklearn(self):
        from spectra_sherpa.app.lib.adapters.sklearn_adapter import from_sklearn

        ds = from_sklearn(self._make_bunch(), name="iris")
        assert isinstance(ds, SherpaDataset)
        assert ds.shape == (3, 2)
        assert ds.backend == "sklearn"
        assert ds.title == "iris"

    def test_spectral_axis_labels(self):
        from spectra_sherpa.app.lib.adapters.sklearn_adapter import from_sklearn

        ds = from_sklearn(self._make_bunch())
        assert ds.spectral_axis is not None
        assert ds.spectral_axis.labels == ["sepal_length", "sepal_width"]

    def test_target(self):
        from spectra_sherpa.app.lib.adapters.sklearn_adapter import from_sklearn

        ds = from_sklearn(self._make_bunch())
        np.testing.assert_array_equal(ds.target, [0, 0, 1])

    def test_target_context_inferred(self):
        from spectra_sherpa.app.lib.adapters.sklearn_adapter import from_sklearn

        ds = from_sklearn(self._make_bunch(), name="iris")
        assert ds.target_context.target_type == "categorical"
        assert ds.target_context.n_classes == 2
        assert ds.target_context.class_names == ["setosa", "versicolor"]

    def test_extra_metadata(self):
        from spectra_sherpa.app.lib.adapters.sklearn_adapter import from_sklearn

        ds = from_sklearn(self._make_bunch(), name="iris")
        assert ds.get_extra("sklearn.target_names") == ["setosa", "versicolor"]
        assert ds.get_extra("sklearn.dataset_name") == "iris"
        assert ds.get_extra("sklearn.description") is not None


# ═══════════════════════════════════════════════════════════════════════════
# Adapters — scp (mocked)
# ═══════════════════════════════════════════════════════════════════════════


class TestSCPAdapter:
    def _make_mock_nddataset(self):
        """Create a mock NDDataset with the expected interface."""
        x_coord = SimpleNamespace(
            data=np.linspace(400, 4000, 50),
            units="cm^-1",
            title="wavenumber",
            labels=None,
        )
        y_coord = SimpleNamespace(
            data=np.arange(3, dtype=float),
            units=None,
            title="samples",
            labels=np.array(["s1", "s2", "s3"]),
        )
        return SimpleNamespace(
            data=np.random.rand(3, 50),
            x=x_coord,
            y=y_coord,
            title="Mock IR Data",
            units="absorbance",
            meta={"custom": "value", "processing_history": [{"operation": "load"}]},
        )

    def test_from_nddataset(self):
        from spectra_sherpa.app.lib.adapters.scp_adapter import from_nddataset

        mock = self._make_mock_nddataset()
        ds = from_nddataset(mock)
        assert isinstance(ds, SherpaDataset)
        assert ds.shape == (3, 50)
        assert ds.backend == "scp"
        assert ds.title == "Mock IR Data"

    def test_from_nddataset_spectral_axis(self):
        from spectra_sherpa.app.lib.adapters.scp_adapter import from_nddataset

        mock = self._make_mock_nddataset()
        ds = from_nddataset(mock)
        assert ds.spectral_axis is not None
        assert ds.spectral_axis.units == "cm^-1"

    def test_from_nddataset_sample_axis(self):
        from spectra_sherpa.app.lib.adapters.scp_adapter import from_nddataset

        mock = self._make_mock_nddataset()
        ds = from_nddataset(mock)
        assert ds.sample_axis is not None
        assert ds.sample_axis.labels == ["s1", "s2", "s3"]

    def test_from_nddataset_provenance(self):
        from spectra_sherpa.app.lib.adapters.scp_adapter import from_nddataset

        mock = self._make_mock_nddataset()
        ds = from_nddataset(mock)
        assert len(ds.provenance) == 1
        assert ds.provenance[0].op_id == "load"

    def test_from_nddataset_extra(self):
        from spectra_sherpa.app.lib.adapters.scp_adapter import from_nddataset

        mock = self._make_mock_nddataset()
        ds = from_nddataset(mock)
        assert ds.get_extra("scp.custom") == "value"

    def test_from_nddataset_domain_inference(self):
        from spectra_sherpa.app.lib.adapters.scp_adapter import from_nddataset

        mock = self._make_mock_nddataset()
        ds = from_nddataset(mock)
        # Should infer IR from wavenumber range
        assert ds.domain.inferred is not None
        assert ds.domain.inferred.technique == "IR"
        assert ds.domain.inferred.confidence > 0


# ═══════════════════════════════════════════════════════════════════════════
# Pydantic schema generation
# ═══════════════════════════════════════════════════════════════════════════


class TestPydanticSchemas:
    """Verify model_json_schema() works for MCP tool discovery."""

    def test_domain_context_schema(self):
        schema = DomainContext.model_json_schema()
        assert "properties" in schema
        assert "technique" in schema["properties"]

    def test_provenance_entry_schema(self):
        schema = ProvenanceEntry.model_json_schema()
        assert "properties" in schema
        assert "op_id" in schema["properties"]
        assert "state_effects" in schema["properties"]

    def test_dataset_manifest_schema(self):
        schema = DatasetManifest.model_json_schema()
        assert "properties" in schema
        assert "dataset_id" in schema["properties"]

    def test_target_context_schema(self):
        schema = TargetContext.model_json_schema()
        assert "properties" in schema
        assert "target_type" in schema["properties"]

    def test_evaluation_result_schema(self):
        schema = EvaluationResult.model_json_schema()
        assert "properties" in schema
        assert "r2" in schema["properties"]

    # -- Regression: axis models with ndarray fields (P0 fix) ----------------

    def test_axis_info_schema(self):
        """AxisInfo.model_json_schema() must not raise PydanticInvalidForJsonSchema."""
        schema = AxisInfo.model_json_schema()
        assert "properties" in schema
        assert "values" in schema["properties"]

    def test_spectral_axis_schema(self):
        schema = SpectralAxis.model_json_schema()
        assert "properties" in schema
        assert "values" in schema["properties"]

    def test_sample_axis_schema(self):
        schema = SampleAxis.model_json_schema()
        assert "properties" in schema
        assert "values" in schema["properties"]
        assert "classes" in schema["properties"]
        assert "include_mask" in schema["properties"]


# ═══════════════════════════════════════════════════════════════════════════
# scp_roundtrip() — envelope pattern tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSCPRoundtrip:
    """Test the scp_roundtrip() envelope function.

    Uses mock NDDataset (SimpleNamespace) so tests work without SCP installed.
    The mock simulates the to_nddataset → fn → from_nddataset cycle by
    patching the adapter functions.
    """

    def _make_rich_dataset(self) -> SherpaDataset:
        """Create a SherpaDataset with all metadata fields populated."""
        spectral = SpectralAxis(
            values=np.linspace(400, 4000, 50),
            units="cm^-1",
            title="wavenumber",
        )
        sample = SampleAxis(
            values=np.arange(3, dtype=float),
            labels=["s1", "s2", "s3"],
            title="samples",
            classes=np.array(["A", "B", "A"], dtype=object),
            include_mask=np.array([True, True, False]),
            exclusion_reasons=[None, None, "outlier"],
            sample_table={"concentration": [1.0, 2.0, 3.0]},
        )
        prov = Provenance()
        prov.append("data.source", {"file": "test.csv"})
        quality = QualityMetrics(snr=42.0)
        quality.add_evaluation(EvaluationResult(evaluation_id="eval-1", model_type="PCA", n_components=3))
        domain = DomainContext(technique="IR", sample_type="liquid")
        target_ctx = TargetContext(target_type="continuous", target_name="moisture")

        return SherpaDataset(
            X=np.random.default_rng(42).standard_normal((3, 50)),
            spectral_axis=spectral,
            sample_axis=sample,
            target=np.array([1.0, 2.0, 3.0]),
            target_context=target_ctx,
            domain=domain,
            provenance=prov,
            quality=quality,
            backend="numpy",
            title="Test IR Spectra",
            units="absorbance",
            extra={"user.note": "important", "scp.custom": "value"},
        )

    def _roundtrip_with_mock(self, ds, fn_effect=None, **kwargs):
        """Run scp_roundtrip with patched adapter functions.

        Simulates the to_nddataset → fn → from_nddataset cycle using
        a mock NDDataset. Optionally applies fn_effect to the data.
        """
        from unittest.mock import patch

        from spectra_sherpa.app.lib.adapters import scp_adapter

        def mock_to_nddataset(sherpa_ds):
            """Simulate to_nddataset: produce a mock NDDataset."""
            x_coord = SimpleNamespace(
                data=sherpa_ds.spectral_axis.values.copy() if sherpa_ds.spectral_axis else None,
                units=sherpa_ds.spectral_axis.units if sherpa_ds.spectral_axis else None,
                title=sherpa_ds.spectral_axis.title if sherpa_ds.spectral_axis else None,
                labels=None,
            )
            y_coord = SimpleNamespace(
                data=sherpa_ds.sample_axis.values.copy() if sherpa_ds.sample_axis else None,
                units=sherpa_ds.sample_axis.units if sherpa_ds.sample_axis else None,
                title=sherpa_ds.sample_axis.title if sherpa_ds.sample_axis else None,
                labels=(
                    np.array(sherpa_ds.sample_axis.labels)
                    if sherpa_ds.sample_axis and sherpa_ds.sample_axis.labels
                    else None
                ),
            )
            # Simulate what fn_effect does to the data
            data = sherpa_ds.X.copy()
            if fn_effect is not None:
                data = fn_effect(data)
            return SimpleNamespace(
                data=data,
                x=x_coord,
                y=y_coord,
                title=sherpa_ds.title or "",
                units=sherpa_ds.units or "",
                meta={"processing_history": sherpa_ds.provenance.to_list()},
            )

        with (
            patch.object(scp_adapter, "to_nddataset", side_effect=mock_to_nddataset),
            patch.object(scp_adapter, "require_scp"),
        ):
            return scp_adapter.scp_roundtrip(ds, lambda ndd: None, **kwargs)

    def test_roundtrip_preserves_provenance(self):
        ds = self._make_rich_dataset()
        original_len = len(ds.provenance)

        result = self._roundtrip_with_mock(ds, op_id="test.op", parameters={"key": "val"})

        # Original provenance carried forward + 1 new step
        assert len(result.provenance) == original_len + 1
        assert result.provenance[0].op_id == "data.source"
        assert result.provenance[-1].op_id == "test.op"

    def test_roundtrip_preserves_target(self):
        ds = self._make_rich_dataset()
        result = self._roundtrip_with_mock(ds, op_id="test.op")

        np.testing.assert_array_equal(result.target, ds.target)

    def test_roundtrip_preserves_target_context(self):
        ds = self._make_rich_dataset()
        result = self._roundtrip_with_mock(ds, op_id="test.op")

        assert result.target_context.target_type == "continuous"
        assert result.target_context.target_name == "moisture"

    def test_roundtrip_preserves_quality(self):
        ds = self._make_rich_dataset()
        result = self._roundtrip_with_mock(ds, op_id="test.op")

        assert result.quality.snr == 42.0
        assert len(result.quality.evaluations) == 1
        assert result.quality.evaluations[0].model_type == "PCA"

    def test_roundtrip_preserves_domain(self):
        ds = self._make_rich_dataset()
        result = self._roundtrip_with_mock(ds, op_id="test.op")

        assert result.domain.technique == "IR"
        assert result.domain.sample_type == "liquid"

    def test_roundtrip_preserves_extra(self):
        ds = self._make_rich_dataset()
        result = self._roundtrip_with_mock(ds, op_id="test.op")

        assert result.get_extra("user.note") == "important"
        # scp.custom also survives (may come from both snapshot and from_nddataset)
        assert result.get_extra("scp.custom") == "value"

    def test_roundtrip_preserves_sample_axis_extras(self):
        ds = self._make_rich_dataset()
        result = self._roundtrip_with_mock(ds, op_id="test.op")

        sa = result.sample_axis
        assert sa is not None
        np.testing.assert_array_equal(sa.classes, np.array(["A", "B", "A"], dtype=object))
        np.testing.assert_array_equal(sa.include_mask, np.array([True, True, False]))
        assert sa.exclusion_reasons == [None, None, "outlier"]
        assert sa.sample_table == {"concentration": [1.0, 2.0, 3.0]}

    def test_roundtrip_adds_provenance_step(self):
        ds = self._make_rich_dataset()
        result = self._roundtrip_with_mock(
            ds,
            op_id="baseline.rubberband",
            parameters={"method": "rubberband"},
            state_effects=["baseline_corrected"],
            node_id="node-123",
        )

        last = result.provenance[-1]
        assert last.op_id == "baseline.rubberband"
        assert dict(last.parameters) == {"method": "rubberband"}
        assert "baseline_corrected" in last.state_effects
        assert last.node_id == "node-123"

    def test_roundtrip_preserves_title_and_units(self):
        ds = self._make_rich_dataset()
        result = self._roundtrip_with_mock(ds, op_id="test.op")

        assert result.title == "Test IR Spectra"
        assert result.units == "absorbance"

    def test_roundtrip_inplace_op(self):
        """fn returning None (in-place SCP methods) must work."""
        ds = self._make_rich_dataset()
        # fn_effect simulates an in-place mutation (e.g. baseline shift)
        result = self._roundtrip_with_mock(
            ds,
            fn_effect=lambda data: data - np.mean(data, axis=1, keepdims=True),
            op_id="test.inplace",
        )
        assert result.shape == ds.shape
        assert len(result.provenance) == len(ds.provenance) + 1
