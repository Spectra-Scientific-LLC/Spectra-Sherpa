"""Phase 2: Domain Population + Quality Metrics tests."""

from __future__ import annotations

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import (
    DomainContext,
    EvaluationResult,
    InferredDomain,
    SherpaDataset,
    SpectralAxis,
)
from spectra_sherpa.app.services.dag.io_contracts import attach_evaluation, build_dataset_like
from spectra_sherpa.app.services.dag.meta_helpers import (
    detect_data_quantity,
    detect_spectral_technique,
    detect_x_axis_type,
    get_spectral_info,
)
from spectra_sherpa.app.services.dag.nodes.data import DataSourceNode

# ---------------------------------------------------------------------------
# Slice 1: Detection functions with SherpaDataset
# ---------------------------------------------------------------------------


class TestDetectXAxisType:
    def test_wavenumber(self):
        ds = SherpaDataset(
            X=np.zeros((3, 100)),
            spectral_axis=SpectralAxis(values=np.linspace(400, 4000, 100), units="cm-1"),
        )
        assert detect_x_axis_type(ds) == "wavenumber"

    def test_wavelength_nm(self):
        ds = SherpaDataset(
            X=np.zeros((3, 100)),
            spectral_axis=SpectralAxis(values=np.linspace(800, 2500, 100), units="nm"),
        )
        assert detect_x_axis_type(ds) == "wavelength_nm"

    def test_wavelength_um(self):
        ds = SherpaDataset(
            X=np.zeros((3, 50)),
            spectral_axis=SpectralAxis(values=np.linspace(1, 25, 50), units="μm"),
        )
        assert detect_x_axis_type(ds) == "wavelength_um"

    def test_no_axis_returns_none(self):
        ds = SherpaDataset(X=np.zeros((3, 100)))
        assert detect_x_axis_type(ds) is None

    def test_axis_no_units_returns_none(self):
        ds = SherpaDataset(
            X=np.zeros((3, 100)),
            spectral_axis=SpectralAxis(values=np.arange(100)),
        )
        assert detect_x_axis_type(ds) is None


class TestDetectSpectralTechnique:
    def test_ir_from_wavenumber_range(self):
        ds = SherpaDataset(
            X=np.zeros((3, 100)),
            spectral_axis=SpectralAxis(values=np.linspace(400, 4000, 100), units="cm-1"),
        )
        assert detect_spectral_technique(ds) == "IR"

    def test_nir_from_wavenumber_range(self):
        ds = SherpaDataset(
            X=np.zeros((3, 100)),
            spectral_axis=SpectralAxis(values=np.linspace(4000, 10000, 100), units="cm-1"),
        )
        assert detect_spectral_technique(ds) == "NIR"

    def test_nir_from_wavelength(self):
        ds = SherpaDataset(
            X=np.zeros((3, 100)),
            spectral_axis=SpectralAxis(values=np.linspace(800, 2500, 100), units="nm"),
        )
        assert detect_spectral_technique(ds) == "NIR"

    def test_uv_vis_from_wavelength(self):
        ds = SherpaDataset(
            X=np.zeros((3, 100)),
            spectral_axis=SpectralAxis(values=np.linspace(200, 800, 100), units="nm"),
        )
        assert detect_spectral_technique(ds) == "UV-Vis"

    def test_authoritative_domain_overrides_inference(self):
        ds = SherpaDataset(
            X=np.zeros((3, 100)),
            spectral_axis=SpectralAxis(values=np.linspace(400, 4000, 100), units="cm-1"),
            domain=DomainContext(technique="Raman"),
        )
        # Axis says IR, but domain says Raman — domain wins
        assert detect_spectral_technique(ds) == "Raman"

    def test_raman_from_title(self):
        ds = SherpaDataset(
            X=np.zeros((3, 100)),
            spectral_axis=SpectralAxis(values=np.linspace(200, 3500, 100), units="cm-1"),
            title="Raman Spectra of Polymers",
        )
        assert detect_spectral_technique(ds) == "Raman"

    def test_no_axis_returns_none(self):
        ds = SherpaDataset(X=np.zeros((3, 100)))
        assert detect_spectral_technique(ds) is None

    def test_domain_technique_only(self):
        ds = SherpaDataset(
            X=np.zeros((3, 100)),
            domain=DomainContext(technique="NIR"),
        )
        assert detect_spectral_technique(ds) == "NIR"


class TestDetectDataQuantity:
    def test_absorbance_from_units(self):
        ds = SherpaDataset(X=np.zeros((3, 100)), units="absorbance")
        assert detect_data_quantity(ds) == "Absorbance"

    def test_transmittance_from_units(self):
        ds = SherpaDataset(X=np.zeros((3, 100)), units="transmittance")
        assert detect_data_quantity(ds) == "Transmittance"

    def test_from_domain_data_quantity(self):
        ds = SherpaDataset(
            X=np.zeros((3, 100)),
            domain=DomainContext(data_quantity="Reflectance"),
        )
        assert detect_data_quantity(ds) == "Reflectance"

    def test_domain_overrides_units(self):
        ds = SherpaDataset(
            X=np.zeros((3, 100)),
            units="absorbance",
            domain=DomainContext(data_quantity="Reflectance"),
        )
        assert detect_data_quantity(ds) == "Reflectance"

    def test_no_info_returns_none(self):
        ds = SherpaDataset(X=np.zeros((3, 100)))
        assert detect_data_quantity(ds) is None


class TestGetSpectralInfo:
    def test_full_info(self):
        ds = SherpaDataset(
            X=np.zeros((5, 200)),
            spectral_axis=SpectralAxis(values=np.linspace(400, 4000, 200), units="cm-1"),
            units="absorbance",
        )
        info = get_spectral_info(ds)
        assert info["technique"] == "IR"
        assert info["data_quantity"] == "Absorbance"
        assert info["x_axis_type"] == "wavenumber"
        assert info["shape"] == (5, 200)
        assert info["n_samples"] == 5
        assert info["n_features"] == 200
        assert info["x_range"] == (400.0, 4000.0)
        assert info["x_units"] == "cm-1"
        assert info["data_units"] == "absorbance"

    def test_minimal_info(self):
        ds = SherpaDataset(X=np.zeros((2, 10)))
        info = get_spectral_info(ds)
        assert info["technique"] is None
        assert info["shape"] == (2, 10)
        assert "x_range" not in info


# ---------------------------------------------------------------------------
# Slice 2: Domain population
# ---------------------------------------------------------------------------


class TestDomainPopulation:
    def test_domain_from_constructor(self):
        ds = SherpaDataset(
            X=np.zeros((10, 401)),
            spectral_axis=SpectralAxis(values=np.linspace(750, 1550, 401), units="nm"),
            domain=DomainContext(technique="NIR", expected_units="nm"),
        )
        assert ds.domain.technique == "NIR"
        assert ds.domain.expected_units == "nm"

    def test_inferred_domain(self):
        ds = SherpaDataset(
            X=np.zeros((5, 50)),
            domain=DomainContext(
                technique="IR",
                inferred=InferredDomain(
                    technique="IR",
                    confidence=0.8,
                    source="axis_range",
                    reasoning="Wavenumber 400-4000 cm-1 suggests IR",
                ),
            ),
        )
        assert ds.domain.technique == "IR"
        assert ds.domain.inferred is not None
        assert ds.domain.inferred.confidence == 0.8

    def test_data_source_promotes_instrument_and_measurement_mode(self):
        node = DataSourceNode(node_id="phase2-domain-node", parameters={})
        ds = SherpaDataset(
            X=np.zeros((4, 6)),
            extra={
                "scp.instrument_metadata": {
                    "manufacturer": "Bruker",
                    "model": "ALPHA",
                },
                "scp.sample_info": {
                    "sampling_technique": "atr",
                },
            },
        )
        enriched = node._apply_domain_context_hints(
            ds,
            source="file",
            sklearn_dataset="iris",
            eigenvector_dataset=None,
        )
        assert enriched.domain.instrument == "Bruker ALPHA"
        assert enriched.domain.measurement_mode == "ATR"


# ---------------------------------------------------------------------------
# Slice 3: Domain + quality propagation
# ---------------------------------------------------------------------------


class TestDomainPropagation:
    def test_build_dataset_like_preserves_domain(self):
        src = SherpaDataset(
            X=np.ones((5, 10)),
            domain=DomainContext(technique="NIR", sample_type="grain"),
        )
        result = build_dataset_like(np.zeros((5, 10)), src)
        assert result.domain.technique == "NIR"
        assert result.domain.sample_type == "grain"

    def test_copy_preserves_domain(self):
        ds = SherpaDataset(
            X=np.ones((5, 10)),
            domain=DomainContext(technique="IR", data_quantity="Absorbance"),
        )
        copy = ds.copy()
        assert copy.domain.technique == "IR"
        assert copy.domain.data_quantity == "Absorbance"

    def test_slicing_preserves_domain(self):
        ds = SherpaDataset(
            X=np.ones((5, 10)),
            domain=DomainContext(technique="IR"),
        )
        sliced = ds[0:3]
        assert sliced.domain.technique == "IR"


class TestQualityWiring:
    def test_attach_evaluation(self):
        ds = SherpaDataset(X=np.zeros((5, 10)))
        ev = EvaluationResult(
            evaluation_id="test1",
            model_type="PCA",
            outlier_indices=[2],
            outlier_percentage=20.0,
        )
        attach_evaluation(ds, ev)
        assert len(ds.quality.evaluations) == 1
        assert ds.quality.latest.model_type == "PCA"
        assert ds.quality.latest.outlier_percentage == 20.0

    def test_multiple_evaluations(self):
        ds = SherpaDataset(X=np.zeros((5, 10)))
        ev1 = EvaluationResult(evaluation_id="ev1", model_type="PCA")
        ev2 = EvaluationResult(evaluation_id="ev2", model_type="PLS", r2=0.95)
        attach_evaluation(ds, ev1)
        attach_evaluation(ds, ev2)
        assert len(ds.quality.evaluations) == 2
        assert ds.quality.latest.model_type == "PLS"
        assert ds.quality.latest.r2 == 0.95

    def test_quality_survives_build_dataset_like(self):
        ds = SherpaDataset(X=np.ones((5, 10)))
        ev = EvaluationResult(evaluation_id="ev1", model_type="PLS", r2=0.95)
        ds.quality.add_evaluation(ev)
        result = build_dataset_like(np.zeros((5, 10)), ds)
        assert len(result.quality.evaluations) == 1
        assert result.quality.latest.r2 == 0.95

    def test_quality_in_to_dict(self):
        ds = SherpaDataset(X=np.zeros((3, 5)))
        ev = EvaluationResult(evaluation_id="ev1", model_type="PLS", r2=0.92, rmse=0.05)
        ds.quality.add_evaluation(ev)
        d = ds.to_dict()
        assert "quality" in d
        assert len(d["quality"]["evaluations"]) == 1
        assert d["quality"]["evaluations"][0]["r2"] == 0.92

    def test_quality_summary_in_serialization(self):
        from spectra_sherpa.app.services.dag.serialize import serialize_for_api

        ds = SherpaDataset(X=np.zeros((3, 5)))
        ev = EvaluationResult(evaluation_id="ev1", model_type="PLS", r2=0.92, rmse=0.05)
        ds.quality.add_evaluation(ev)
        serialized = serialize_for_api(ds)
        meta = serialized["metadata"]
        assert "quality_summary" in meta
        assert meta["quality_summary"]["n_evaluations"] == 1
        assert meta["quality_summary"]["latest_model_type"] == "PLS"
        assert meta["quality_summary"]["latest_r2"] == 0.92
        assert meta["quality_summary"]["latest_rmse"] == 0.05

    def test_empty_quality_no_summary(self):
        from spectra_sherpa.app.services.dag.serialize import serialize_for_api

        ds = SherpaDataset(X=np.zeros((3, 5)))
        serialized = serialize_for_api(ds)
        assert "quality_summary" not in serialized["metadata"]
