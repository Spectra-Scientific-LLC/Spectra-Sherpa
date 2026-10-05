"""Canonical calibration-transfer lifecycle and numerical proofs."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.executor_validation import _is_model_payload
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.transfer import (
    ApplySpectralTransferNode,
    DSNode,
    PDSNode,
    SWSNode,
)
from tests.performance_contract import PerformanceCeiling


def _dataset(
    matrix: np.ndarray,
    *,
    labels: list[str],
    axis: np.ndarray,
    axis_title: str = "Wavenumber",
    axis_units: str = "cm-1",
    signal_units: str | None = "absorbance",
) -> SherpaDataset:
    return SherpaDataset(
        X=np.asarray(matrix, dtype=np.float64),
        feature_axis=SpectralAxis(values=axis, title=axis_title, units=axis_units),
        sample_axis=SampleAxis(labels=labels),
        units=signal_units,
        data_role="X_spectra",
    )


def _sws_case(*, standards: int = 32, new_samples: int = 12, features: int = 20):
    rng = np.random.default_rng(402)
    axis = np.linspace(4000.0, 1000.0, features)
    secondary_all = rng.normal(size=(standards + new_samples, features)) + np.linspace(0.2, 1.3, features)
    source_slope = np.linspace(0.8, 1.2, features)
    source_bias = np.linspace(-0.12, 0.08, features)
    primary_all = secondary_all * source_slope + source_bias
    labels = [f"standard-{index:03d}" for index in range(standards)]
    return (
        _dataset(primary_all[:standards], labels=labels, axis=axis),
        _dataset(secondary_all[:standards], labels=labels, axis=axis),
        _dataset(
            secondary_all[standards:],
            labels=[f"unknown-{index:03d}" for index in range(new_samples)],
            axis=axis,
        ),
        primary_all[standards:],
    )


def _ds_case(*, standards: int = 48, new_samples: int = 10, secondary_features: int = 8, primary_features: int = 6):
    rng = np.random.default_rng(403)
    secondary_all = rng.normal(size=(standards + new_samples, secondary_features))
    transfer = rng.normal(size=(secondary_features, primary_features))
    primary_all = secondary_all @ transfer
    labels = [f"standard-{index:03d}" for index in range(standards)]
    secondary_axis = np.linspace(900.0, 1700.0, secondary_features)
    primary_axis = np.linspace(950.0, 1650.0, primary_features)
    return (
        _dataset(primary_all[:standards], labels=labels, axis=primary_axis),
        _dataset(secondary_all[:standards], labels=labels, axis=secondary_axis),
        _dataset(
            secondary_all[standards:],
            labels=[f"unknown-{index:03d}" for index in range(new_samples)],
            axis=secondary_axis,
        ),
        primary_all[standards:],
        transfer,
    )


def _pds_case(*, standards: int = 44, new_samples: int = 9, features: int = 18):
    rng = np.random.default_rng(404)
    latent = rng.normal(size=(standards + new_samples, 2))
    secondary_all = latent @ rng.normal(size=(2, features))
    primary_all = np.empty_like(secondary_all)
    for index in range(features):
        lo = max(0, index - 1)
        hi = min(features, index + 2)
        coefficients = np.zeros(hi - lo, dtype=np.float64)
        coefficients[: min(2, hi - lo)] = np.asarray([0.3, 0.7], dtype=np.float64)[: min(2, hi - lo)]
        primary_all[:, index] = secondary_all[:, lo:hi] @ coefficients + (index + 1) * 0.002
    labels = [f"standard-{index:03d}" for index in range(standards)]
    axis = np.linspace(1000.0, 1800.0, features)
    return (
        _dataset(primary_all[:standards], labels=labels, axis=axis),
        _dataset(secondary_all[:standards], labels=labels, axis=axis),
        _dataset(
            secondary_all[standards:],
            labels=[f"unknown-{index:03d}" for index in range(new_samples)],
            axis=axis,
        ),
        primary_all[standards:],
    )


@pytest.mark.parametrize(
    ("node_class", "operation_id", "serializer"),
    [
        (PDSNode, "transfer.pds", "spectrasherpa.transfer.pds-state/2"),
        (SWSNode, "transfer.sws", "spectrasherpa.transfer.sws-state/1"),
        (DSNode, "transfer.ds", "spectrasherpa.transfer.ds-state/1"),
    ],
)
def test_transfer_producers_have_explicit_fitted_contracts(node_class, operation_id, serializer):
    metadata = node_class.metadata
    contract = metadata.resolved_execution_contract()
    assert metadata.node_type == operation_id
    assert metadata.policy is not None
    assert metadata.policy.safe_for_auto_apply is False
    assert metadata.policy.requires_human_review is True
    assert contract is not None
    assert contract.payload["lifecycle_kind"] == "fitted_transform"
    assert contract.payload["managed_optimization_eligibility"] == ("local",)
    assert contract.payload["fitted_state_serializer"] == serializer
    assert contract.payload["citations"]


def test_old_misnamed_sbc_node_is_absent_and_methods_are_explicit():
    assert "transfer.sbc" not in node_registry
    assert node_registry.get_node_class("transfer.pds") is PDSNode
    assert node_registry.get_node_class("transfer.sws") is SWSNode
    assert node_registry.get_node_class("transfer.ds") is DSNode
    assert node_registry.get_node_class("transfer.apply_fitted") is ApplySpectralTransferNode


def test_transfer_envelope_is_a_runtime_model_artifact_not_generic_config():
    primary, secondary, _, _ = _sws_case()
    state = SWSNode("sws", {}).fit_fitted_state(primary, secondary)
    envelope = SWSNode("sws", {}).make_fitted_state_envelope(state)
    assert envelope["schema_version"] == "spectrasherpa.model-artifact.spectral-transfer-envelope/1"
    assert _is_model_payload(envelope) is True


@pytest.mark.asyncio
async def test_sws_recovers_per_wavelength_affine_transfer_and_emits_reusable_state():
    primary, secondary, new, expected = _sws_case()
    result = await SWSNode("sws", {}).execute(X_primary=primary, X_secondary=secondary)
    np.testing.assert_allclose(result.outputs["X_standardized"].X, primary.X, rtol=2e-13, atol=2e-13)
    assert result.outputs["fitted_state"]["source_operation_id"] == "transfer.sws"
    assert result.outputs["transfer_error"]["rmse_transfer"] < 1e-13
    assert result.outputs["X_standardized"].feature_axis.units == "cm-1"


@pytest.mark.asyncio
async def test_ds_matches_independent_moore_penrose_solution_and_changes_axis():
    primary, secondary, new, expected, expected_map = _ds_case()
    node = DSNode("ds", {})
    result = await node.execute(X_primary=primary, X_secondary=secondary)
    state = node.verify_fitted_state_envelope(result.outputs["fitted_state"])
    np.testing.assert_allclose(state["transfer_matrix"], expected_map, rtol=2e-13, atol=2e-13)
    np.testing.assert_allclose(result.outputs["X_standardized"].X, primary.X, rtol=2e-13, atol=2e-13)
    np.testing.assert_array_equal(result.outputs["X_standardized"].feature_axis.values, primary.feature_axis.values)
    assert result.outputs["transfer_error"]["rmse_transfer"] < 1e-13


@pytest.mark.asyncio
async def test_pds_matches_independent_local_linear_relations():
    primary, secondary, new, expected = _pds_case()
    result = await PDSNode("pds", {"half_window": 1, "n_components": 2}).execute(
        X_primary=primary,
        X_secondary=secondary,
    )
    np.testing.assert_allclose(result.outputs["X_standardized"].X, primary.X, rtol=5e-11, atol=5e-11)
    assert result.outputs["transfer_error"]["rmse_transfer"] < 1e-11


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("node", "case"),
    [
        (SWSNode("sws", {}), _sws_case),
        (DSNode("ds", {}), _ds_case),
        (PDSNode("pds", {"half_window": 1, "n_components": 2}), _pds_case),
    ],
)
async def test_fitted_application_reuses_state_without_standards(node, case):
    values = case()
    primary, secondary, new = values[:3]
    producer = await node.execute(X_primary=primary, X_secondary=secondary)
    application = await ApplySpectralTransferNode("apply", {}).execute(
        default=new,
        fitted_state=producer.outputs["fitted_state"],
    )
    expected = values[3]
    np.testing.assert_allclose(application.outputs["default"].X, expected, rtol=5e-11, atol=5e-11)
    assert application.diagnostics["source_operation_id"] == node.metadata.node_type


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("node", "case", "function_name"),
    [
        (SWSNode("sws", {}), _sws_case, "execute_sws"),
        (DSNode("ds", {}), _ds_case, "execute_ds"),
        (PDSNode("pds", {"half_window": 1, "n_components": 2}), _pds_case, "execute_pds"),
    ],
)
async def test_generated_python_calls_the_live_authority(node, case, function_name):
    primary, secondary = case()[:2]
    live = await node.execute(X_primary=primary, X_secondary=secondary)
    namespace = {
        "primary": primary,
        "secondary": secondary,
        "results": {},
    }
    source = "\n".join(
        node.generate_python(
            {"X_primary": "primary", "X_secondary": "secondary"},
            indent="",
            use_scp=False,
        )
    )
    assert function_name in source
    assert "np.linalg" not in source
    exec(source, namespace)
    generated = namespace["results"][node.node_id]
    np.testing.assert_allclose(generated["X_standardized"].X, live.outputs["X_standardized"].X)
    assert generated["fitted_state"] == live.outputs["fitted_state"]


@pytest.mark.asyncio
async def test_pairing_requires_exact_unique_ordered_sample_identity():
    primary, secondary, new, _ = _sws_case()
    secondary.sample_axis = SampleAxis(labels=list(reversed(secondary.sample_axis.labels)))
    with pytest.raises(ValueError, match="identical ordered sample identities"):
        await SWSNode("sws", {}).execute(X_primary=primary, X_secondary=secondary)


@pytest.mark.asyncio
async def test_unknown_signal_units_are_preserved_without_inventing_a_physical_unit():
    primary, secondary, new, expected = _sws_case()
    primary.units = None
    secondary.units = None
    new.units = None

    producer = await SWSNode("sws", {}).execute(X_primary=primary, X_secondary=secondary)
    assert producer.outputs["fitted_state"]["state"]["primary_signal_units"] is None
    assert producer.outputs["fitted_state"]["state"]["secondary_signal_units"] is None

    application = await ApplySpectralTransferNode("apply", {}).execute(
        default=new,
        fitted_state=producer.outputs["fitted_state"],
    )
    np.testing.assert_allclose(application.outputs["default"].X, expected, rtol=2e-13, atol=2e-13)
    assert application.outputs["default"].units is None


@pytest.mark.asyncio
async def test_pairing_rejects_declared_and_unknown_signal_unit_mismatch():
    primary, secondary, _, _ = _sws_case()
    secondary.units = None
    with pytest.raises(ValueError, match="identical signal units"):
        await SWSNode("sws", {}).execute(X_primary=primary, X_secondary=secondary)


@pytest.mark.asyncio
async def test_application_rejects_axis_drift_even_when_feature_count_matches():
    primary, secondary, new, _ = _sws_case()
    producer = await SWSNode("sws", {}).execute(X_primary=primary, X_secondary=secondary)
    drifted = copy.deepcopy(new)
    drifted.feature_axis = SpectralAxis(
        values=np.asarray(new.feature_axis.values) + 0.5,
        title="Wavenumber",
        units="cm-1",
    )
    with pytest.raises(ValueError, match="secondary spectral axis"):
        await ApplySpectralTransferNode("apply", {}).execute(
            default=drifted,
            fitted_state=producer.outputs["fitted_state"],
        )


@pytest.mark.asyncio
async def test_sws_rejects_constant_secondary_channel_instead_of_inventing_a_slope():
    primary, secondary, new, _ = _sws_case()
    secondary.X[:, 3] = 1.0
    with pytest.raises(ValueError, match="constant secondary channels"):
        await SWSNode("sws", {}).execute(X_primary=primary, X_secondary=secondary)


@pytest.mark.asyncio
async def test_sws_identifiability_is_invariant_to_large_signal_offset():
    primary, secondary, new, expected = _sws_case()
    offset = 1.0e8
    slope = np.linspace(0.8, 1.2, secondary.X.shape[1])
    secondary = _dataset(
        secondary.X + offset,
        labels=list(secondary.sample_axis.labels),
        axis=np.asarray(secondary.feature_axis.values),
    )
    new = _dataset(
        new.X + offset,
        labels=list(new.sample_axis.labels),
        axis=np.asarray(new.feature_axis.values),
    )
    primary = _dataset(
        primary.X + offset * slope,
        labels=list(primary.sample_axis.labels),
        axis=np.asarray(primary.feature_axis.values),
    )
    expected += offset * slope

    producer = await SWSNode("sws", {}).execute(X_primary=primary, X_secondary=secondary)
    application = await ApplySpectralTransferNode("apply", {}).execute(
        default=new,
        fitted_state=producer.outputs["fitted_state"],
    )

    np.testing.assert_allclose(application.outputs["default"].X, expected, rtol=2e-13, atol=2e-7)


@pytest.mark.asyncio
async def test_pds_rejects_unsupported_rank_instead_of_silently_truncating():
    primary, secondary, new, _ = _pds_case()
    with pytest.raises(ValueError, match="exceeds the admitted local rank"):
        await PDSNode("pds", {"half_window": 1, "n_components": 3}).execute(
            X_primary=primary,
            X_secondary=secondary,
        )


@pytest.mark.asyncio
async def test_pds_rejects_numerically_rank_deficient_local_windows():
    primary, secondary, _, _ = _pds_case()
    latent = np.asarray(secondary.X[:, [0]], dtype=np.float64)
    secondary = _dataset(
        latent @ np.linspace(0.5, 1.5, secondary.X.shape[1]).reshape(1, -1),
        labels=list(secondary.sample_axis.labels),
        axis=np.asarray(secondary.feature_axis.values),
    )

    with pytest.raises(ValueError, match="exceeds the admitted local rank 1"):
        await PDSNode("pds", {"half_window": 1, "n_components": 2}).execute(
            X_primary=primary,
            X_secondary=secondary,
        )


@pytest.mark.parametrize(
    ("node", "case"),
    [
        (SWSNode("sws-tamper", {}), _sws_case),
        (DSNode("ds-tamper", {}), _ds_case),
        (PDSNode("pds-tamper", {"half_window": 1, "n_components": 2}), _pds_case),
    ],
)
@pytest.mark.asyncio
async def test_state_envelope_tampering_fails_before_application(node, case):
    primary, secondary, new = case()[:3]
    producer = await node.execute(X_primary=primary, X_secondary=secondary)
    envelope = copy.deepcopy(producer.outputs["fitted_state"])
    envelope["state_content_digest"] = "0" * 64
    with pytest.raises(ValueError, match="content digest"):
        await ApplySpectralTransferNode("apply", {}).execute(default=new, fitted_state=envelope)


@pytest.mark.parametrize(
    ("node", "case"),
    [
        (SWSNode("sws-perf", {}), _sws_case),
        (DSNode("ds-perf", {}), _ds_case),
        (PDSNode("pds-perf", {"half_window": 1, "n_components": 2}), _pds_case),
    ],
)
@pytest.mark.asyncio
async def test_transfer_representative_performance_ceiling(node, case):
    primary, secondary, new = (
        case(standards=60, new_samples=20, features=100)[:3]
        if case is not _ds_case
        else (_ds_case(standards=60, new_samples=20, secondary_features=100, primary_features=80)[:3])
    )
    fixture_id = "60-standards-20-applications-100-features"
    with PerformanceCeiling(node.metadata.node_type, fixture_id, 5.0).measure():
        producer = await node.execute(X_primary=primary, X_secondary=secondary)
        await ApplySpectralTransferNode("apply-perf", {}).execute(
            default=new,
            fitted_state=producer.outputs["fitted_state"],
        )
