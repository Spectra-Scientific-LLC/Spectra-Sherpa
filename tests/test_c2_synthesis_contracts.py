"""Canonical contracts and scientific oracles for explicit mixture synthesis."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.axes import SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.node_base import NodeResult, node_registry
from spectra_sherpa.app.services.dag.nodes.blend import (
    BlendNode,
    MergeSpectraNode,
    SpeciesSelectorNode,
    build_bilinear_blend_result,
    build_hitran_response_result,
    build_merge_result,
    build_nist_quant_ir_response_result,
    build_ppm_fraction_result,
    build_species_result,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from spectra_sherpa.sdk.canonical_synthesis import reference_synthesis_workflow
from tests.performance_contract import PerformanceCeiling


def _pure_response(values: list[float], *, axis_offset: float = 0.0, units: str = "absorbance") -> SherpaDataset:
    return SherpaDataset(
        X=np.asarray([values], dtype=np.float64),
        feature_axis=SpectralAxis(
            values=np.linspace(1000.0, 1300.0, len(values)) + axis_offset,
            title="Wavenumber",
            units="cm-1",
        ),
        units=units,
        title="Reference response",
    )


def _labelled(values: list[float], name: str) -> SherpaDataset:
    result, _ = build_species_result(
        _pure_response(values),
        {"species_name": name, "molar_absorptivity": None},
        node_id=f"species-{name}",
    )
    return result


def test_synthesis_nodes_publish_one_local_deterministic_contract_each() -> None:
    expected_effects = {
        "synthesis.ppm_fraction": ("preserves_samples", "changes_units"),
        "synthesis.nist_quant_ir_response": ("preserves_samples", "changes_units"),
        "synthesis.hitran_response": ("preserves_samples", "changes_units"),
        "synthesis.species": ("preserves_samples", "preserves_units"),
        "synthesis.merge": ("aggregates_samples", "requires_compatible_units"),
        "synthesis.blend": ("generates_samples", "preserves_units"),
    }
    for node_type, (sample_effect, unit_effect) in expected_effects.items():
        contract = node_registry.get_metadata(node_type).resolved_execution_contract()
        assert contract is not None
        assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
        assert contract.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
        assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
        assert contract.payload["deterministic"] is True
        assert contract.payload["sample_effect"] == sample_effect
        assert contract.payload["unit_effect"] == unit_effect
        expected_output = "TargetMatrix" if node_type == "synthesis.ppm_fraction" else "SpectralDataset"
        assert contract.payload["semantic_outputs"][0]["type_ref"].endswith(f"/{expected_output}/1.0")

    blend_contract = node_registry.get_metadata("synthesis.blend").resolved_execution_contract()
    assert blend_contract is not None
    assert blend_contract.payload["target_access"] == "required"
    assert any("de Juan" in citation and "Tauler" in citation for citation in blend_contract.payload["citations"])

    ppm_citations = (
        node_registry.get_metadata("synthesis.ppm_fraction").resolved_execution_contract().payload["citations"]
    )
    nist_contract = node_registry.get_metadata("synthesis.nist_quant_ir_response").resolved_execution_contract()
    assert nist_contract is not None
    nist_citations = nist_contract.payload["citations"]
    hitran_citations = (
        node_registry.get_metadata("synthesis.hitran_response").resolved_execution_contract().payload["citations"]
    )
    assert any("10.1039/9781847557889" in citation for citation in ppm_citations)
    assert any("10.1351/goldbook.B00626" in citation for citation in nist_citations)
    assert any("NIST Chemistry WebBook" in citation for citation in nist_citations)
    assert any("10.1016/j.jqsrt.2021.107949" in citation for citation in hitran_citations)


def test_reference_response_operations_match_their_cited_equations() -> None:
    concentrations_ppm = np.asarray([[100.0, 250.0]], dtype=np.float64)
    fractions, ppm_diagnostics = build_ppm_fraction_result(concentrations_ppm, node_id="ppm")
    np.testing.assert_array_equal(fractions, concentrations_ppm * 1e-6)
    assert ppm_diagnostics["scale_factor"] == 1e-6

    nist_source = _pure_response([1.0, 2.0], units="ppm^-1 m^-1")
    nist_response, nist_diagnostics = build_nist_quant_ir_response_result(
        nist_source,
        {"pathlength_cm": 10.0},
        node_id="nist",
    )
    expected_nist_unit_fraction = nist_source.data * (10.0 / 100.0) * 1e6
    np.testing.assert_array_equal(nist_response.data, expected_nist_unit_fraction)
    assert nist_diagnostics["response_scale"] == 100_000.0

    hitran_source = _pure_response([1.0e-20, 2.0e-20], units="cm^2 molecule^-1")
    temperature_k = 300.0
    pressure_atm = 0.8
    pathlength_cm = 5.0
    hitran_response, hitran_diagnostics = build_hitran_response_result(
        hitran_source,
        {
            "pathlength_cm": pathlength_cm,
            "pressure_atm": pressure_atm,
            "temperature_k": temperature_k,
        },
        node_id="hitran",
    )
    expected_number_density_cm3 = pressure_atm * 101325.0 / (1.380649e-23 * temperature_k) / 1e6
    expected_hitran_unit_fraction = hitran_source.data * expected_number_density_cm3 * pathlength_cm / np.log(10.0)
    np.testing.assert_allclose(hitran_response.data, expected_hitran_unit_fraction, rtol=1e-15, atol=0.0)
    assert hitran_diagnostics["response_scale"] == pytest.approx(
        expected_number_density_cm3 * pathlength_cm / np.log(10.0)
    )


@pytest.mark.parametrize(
    ("source", "expected_response_type"),
    [("nist_quant_ir", "synthesis.nist_quant_ir_response"), ("hitran", "synthesis.hitran_response")],
)
def test_reference_synthesis_projects_only_registered_canonical_operations(
    source: str,
    expected_response_type: str,
) -> None:
    workflow = reference_synthesis_workflow(
        component_names=("A", "B"),
        source=source,
        pathlength_cm=1.0,
        temperature_k=293.0,
        pressure_atm=1.0,
        noise_sigma_au=0.0,
        seed=7,
    )
    node_types = [node["node_type"] for node in workflow.payload["nodes"]]
    assert node_types.count("deploy.input") == 3
    assert node_types.count(expected_response_type) == 2
    assert node_types.count("synthesis.species") == 2
    assert node_types.count("synthesis.ppm_fraction") == 1
    assert node_types.count("synthesis.merge") == 1
    assert node_types.count("synthesis.blend") == 1
    assert "custom.noise_injection" not in node_types

    for node_type in node_types:
        assert node_registry.get_metadata(node_type).resolved_execution_contract() is not None


def test_bilinear_mixture_project_executes_explicit_species_merge_and_mixture() -> None:
    left = SpeciesSelectorNode("species-a", {"species_name": "A", "molar_absorptivity": None})
    right = SpeciesSelectorNode("species-b", {"species_name": "B", "molar_absorptivity": 2.5})
    merge = MergeSpectraNode("merge", {})
    blend = BlendNode("blend", {})
    concentrations = np.asarray([[1.0, 0.0], [0.25, 0.75], [0.0, 1.0]])

    left_live = asyncio.run(left.execute(_pure_response([1.0, 2.0, 3.0])))
    right_live = asyncio.run(right.execute(_pure_response([4.0, 2.0, 0.0])))
    assert isinstance(left_live, NodeResult)
    merged_live = asyncio.run(merge.execute(default=[left_live.outputs["default"], right_live.outputs["default"]]))
    blended_live = asyncio.run(blend.execute(merged_live.outputs["default"], concentrations))

    S = np.asarray([[1.0, 2.0, 3.0], [4.0, 2.0, 0.0]])
    np.testing.assert_allclose(merged_live.outputs["default"].data, S)
    np.testing.assert_allclose(blended_live.outputs["default"].data, concentrations @ S)
    np.testing.assert_array_equal(blended_live.outputs["default"].target, concentrations)
    assert blended_live.diagnostics["equation"] == "D=C@S"

    namespace = {
        "left_source": _pure_response([1.0, 2.0, 3.0]),
        "right_source": _pure_response([4.0, 2.0, 0.0]),
        "concentrations": concentrations,
        "results": {},
    }
    generated = [
        *left.generate_python({"default": "left_source"}, indent=""),
        *right.generate_python({"default": "right_source"}, indent=""),
        *merge.generate_python(
            {"default": ["results['species-a']", "results['species-b']"]},
            indent="",
        ),
        *blend.generate_python(
            {"pure_spectra": "results['merge']", "concentrations": "concentrations"},
            indent="",
        ),
    ]
    exec("\n".join(generated), namespace)  # noqa: S102 - generated-code parity is the contract under test
    np.testing.assert_allclose(namespace["results"]["blend"].data, blended_live.outputs["default"].data)
    assert namespace["results"]["blend"].meta["spectra"] == blended_live.outputs["default"].meta["spectra"]


def test_blend_retains_the_exact_known_factors_without_hidden_science() -> None:
    pure, _ = build_merge_result(
        [_labelled([1.0, 0.5], "A"), _labelled([0.2, 2.0], "B")],
        node_id="merge",
    )
    C = np.asarray([[0.2, 0.8], [1.5, 0.0]], dtype=np.float64)
    result, diagnostics = build_bilinear_blend_result(pure, C, node_id="blend")
    metadata = result.meta["spectra"]

    assert metadata["concentration_matrix"] == C.tolist()
    assert metadata["pure_spectra_matrix"] == pure.data.tolist()
    assert metadata["custom"]["mixture_model"] == {
        "schema_version": "spectrasherpa-bilinear-mixture/1",
        "equation": "D=C@S",
        "coefficient_semantics": "dimensionless_nonnegative",
    }
    assert metadata["is_ground_truth"] is True
    assert diagnostics["noise_added"] is False
    assert diagnostics["alignment_performed"] is False


@pytest.mark.parametrize(
    "node_type,parameters",
    [
        ("synthesis.merge", {"align_wavenumbers": True}),
        ("synthesis.blend", {"noise_level": 0.01}),
        ("synthesis.blend", {"model_type": "saturation"}),
        ("synthesis.blend", {"pathlength": 0.01}),
    ],
)
def test_deprecated_hidden_synthesis_switches_fail_at_admission(node_type: str, parameters: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="undeclared fields"):
        node_registry.create_node(node_type, "node", parameters)


def test_species_rejects_ambiguous_or_malformed_identity() -> None:
    for parameters in (
        {"species_name": " ", "molar_absorptivity": None},
        {"species_name": " A", "molar_absorptivity": None},
        {"species_name": "A", "molar_absorptivity": 0.0},
    ):
        with pytest.raises(ValueError):
            build_species_result(_pure_response([1.0, 2.0]), parameters, node_id="species")

    source = _pure_response([1.0, 2.0])
    source.meta["spectra"] = {"unknown": "silently accepted before canonical repair"}
    with pytest.raises(ValueError, match="unknown fields"):
        build_species_result(
            source,
            {"species_name": "A", "molar_absorptivity": None},
            node_id="species",
        )

    with pytest.raises(ValueError, match="exactly one"):
        build_species_result(
            SherpaDataset(
                X=np.ones((2, 3)),
                feature_axis=SpectralAxis(values=np.arange(3.0), units="cm-1"),
            ),
            {"species_name": "A", "molar_absorptivity": None},
            node_id="species",
        )

    with pytest.raises(ValueError, match="spectral value units"):
        build_species_result(
            SherpaDataset(
                X=np.ones((1, 3)),
                feature_axis=SpectralAxis(values=np.arange(3.0), title="Wavenumber", units="cm-1"),
            ),
            {"species_name": "A", "molar_absorptivity": None},
            node_id="species",
        )


def test_merge_fails_closed_on_axis_or_unit_mismatch() -> None:
    left = _labelled([1.0, 2.0, 3.0], "A")
    offset, _ = build_species_result(
        _pure_response([2.0, 3.0, 4.0], axis_offset=0.5),
        {"species_name": "B", "molar_absorptivity": None},
        node_id="species-b",
    )
    with pytest.raises(ValueError, match="identical feature-axis"):
        build_merge_result([left, offset], node_id="merge")

    other_units, _ = build_species_result(
        _pure_response([2.0, 3.0, 4.0], units="transmittance"),
        {"species_name": "B", "molar_absorptivity": None},
        node_id="species-b",
    )
    with pytest.raises(ValueError, match="spectral value units"):
        build_merge_result([left, other_units], node_id="merge")

    with pytest.raises(ValueError, match="unique species identities"):
        build_merge_result([left, _labelled([2.0, 3.0, 4.0], "A")], node_id="merge")


@pytest.mark.parametrize(
    "concentrations,message",
    [
        (np.asarray([[1.0, -0.1]]), "non-negative"),
        (np.asarray([[1.0, np.nan]]), "finite"),
        (np.asarray([[1.0, 0.0, 0.0]]), "columns"),
    ],
)
def test_blend_rejects_invalid_coefficients(concentrations: np.ndarray, message: str) -> None:
    pure, _ = build_merge_result(
        [_labelled([1.0, 2.0], "A"), _labelled([3.0, 4.0], "B")],
        node_id="merge",
    )
    with pytest.raises(ValueError, match=message):
        build_bilinear_blend_result(pure, concentrations, node_id="blend")


def test_synthesis_operations_stay_inside_representative_capacity_ceiling() -> None:
    feature_count = 1600
    species_count = 10
    mixture_count = 200
    axis = SpectralAxis(
        values=np.linspace(400.0, 4000.0, feature_count),
        title="wavenumber",
        units="cm-1",
    )
    labelled = []
    for index in range(species_count):
        source = SherpaDataset(
            X=np.full((1, feature_count), index + 1.0),
            feature_axis=axis.copy(),
            units="absorbance",
        )
        result, _ = build_species_result(
            source,
            {"species_name": f"species-{index}", "molar_absorptivity": None},
            node_id=f"species-{index}",
        )
        labelled.append(result)
    C = np.full((mixture_count, species_count), 1.0 / species_count)

    with PerformanceCeiling("synthesis.merge+blend", "10x1600-to-200x1600", 5.0).measure():
        pure, _ = build_merge_result(labelled, node_id="merge")
        result, _ = build_bilinear_blend_result(pure, C, node_id="blend")
    assert result.shape == (mixture_count, feature_count)
