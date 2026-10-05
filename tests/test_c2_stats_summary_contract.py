"""Canonical contract, parity, numerical, and capacity proofs for statistics summaries."""

from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import (
    DatasetSourceIdentity,
    SampleAxis,
    SherpaDataset,
    SpectralAxis,
    TargetContext,
)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.output.data_table_node import build_data_table_result
from spectra_sherpa.app.services.dag.nodes.output.stats_summary_node import (
    _canonical_summary_parameters,
    _role_summary,
    build_statistics_result,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _dataset(*, n_samples: int = 12, n_features: int = 4) -> SherpaDataset:
    values = np.arange(n_samples * n_features, dtype=np.float64).reshape(n_samples, n_features)
    values[0, 0] = np.nan
    values[1, 1] = np.inf
    return SherpaDataset(
        X=values,
        feature_axis=SpectralAxis(
            values=np.linspace(1000.0, 1100.0, n_features),
            units="cm-1",
            title="Wavenumber",
        ),
        sample_axis=SampleAxis(labels=[f"sample-{index + 1}" for index in range(n_samples)]),
    )


def test_stats_summary_has_one_local_deterministic_contract() -> None:
    metadata = node_registry.get_metadata("stats.summary")
    contract = metadata.resolved_execution_contract()
    assert contract is not None
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["deterministic"] is True
    assert contract.payload["semantic_outputs"] == (
        {
            "name": "statistics",
            "type_ref": "spectrasherpa://types/StatisticsSummary/1.0",
            "required": True,
            "variadic": False,
            "accepted_data_roles": (),
        },
    )
    assert any("NIST/SEMATECH" in citation for citation in contract.payload["citations"])


def test_stats_summary_parameter_schema_is_closed() -> None:
    assert _canonical_summary_parameters({}) == {"max_samples": 100}
    assert _canonical_summary_parameters({"max_samples": np.int64(10)}) == {"max_samples": 10}
    for invalid in (
        {"unknown": 1},
        {"max_samples": True},
        {"max_samples": 10.5},
        {"max_samples": 9},
        {"max_samples": 10_001},
    ):
        with pytest.raises(ValueError):
            _canonical_summary_parameters(invalid)


def test_live_and_generated_python_use_the_same_authority() -> None:
    dataset = _dataset()
    node = node_registry.create_node("stats.summary", "stats", {"max_samples": 10})
    live = asyncio.run(node.execute(input_data=dataset))

    generated = "\n".join(node.generate_python({"default": "dataset"}, indent=""))
    assert "build_statistics_result" in generated
    assert "np.zeros" not in generated
    namespace = {"dataset": dataset, "results": {}}
    exec(generated, namespace)
    assert namespace["results"]["stats"] == live


def test_dataset_statistics_use_only_finite_values_and_report_truncation() -> None:
    result = build_statistics_result(_dataset(), max_samples=10)["statistics"]
    finite = np.arange(48, dtype=np.float64)
    finite = finite[~np.isin(finite, [0.0, 5.0])]

    assert result["input_type"] == "SherpaDataset"
    assert result["summary"]["nonfinite_count"] == 2
    assert result["summary"]["missing_count"] == 1
    assert result["summary"]["global_mean"] == pytest.approx(np.mean(finite))
    assert result["summary"]["global_std"] == pytest.approx(np.std(finite))
    assert result["summary"]["sample_rows_returned"] == 10
    assert result["summary"]["sample_rows_truncated"] == 2
    assert result["data"][0]["mean"] == pytest.approx(
        np.mean([4.0, 8.0, 12.0, 16.0, 20.0, 24.0, 28.0, 32.0, 36.0, 40.0, 44.0])
    )


def test_continuous_target_with_repeated_values_has_range_not_class_counts() -> None:
    dataset = SherpaDataset(
        X=np.arange(16, dtype=np.float64).reshape(4, 4),
        target=np.array([1.0, 1.0, 2.0, 3.0]),
        target_context=TargetContext(target_type="continuous", target_name="Assay", target_units="mg/L"),
    )

    target = build_statistics_result(dataset)["statistics"]["summary"]["target"]

    assert target["target_type"] == "continuous"
    assert target["target_units"] == "mg/L"
    assert "class_counts" not in target
    assert target["columns"] == [{"name": "Assay", "measured": 4, "missing": 0, "min": 1.0, "max": 3.0, "mean": 1.75}]


def test_multiresponse_continuous_target_reports_each_measured_range() -> None:
    dataset = SherpaDataset(
        X=np.arange(16, dtype=np.float64).reshape(4, 4),
        target=np.array([[1.0, 3.0], [1.0, np.nan], [2.0, 5.0], [3.0, 7.0]]),
        target_context=TargetContext(target_type="continuous", target_names=["Assay", "Density"]),
    )

    target = build_statistics_result(dataset)["statistics"]["summary"]["target"]

    assert target["nonfinite"] == 1
    assert target["columns"] == [
        {"name": "Assay", "measured": 4, "missing": 0, "min": 1.0, "max": 3.0, "mean": 1.75},
        {"name": "Density", "measured": 3, "missing": 1, "min": 3.0, "max": 7.0, "mean": 5.0},
    ]
    context = build_statistics_result(dataset)["statistics"]["summary"]["source_context"]
    assert context["data_fingerprint"] == dataset.fingerprint


def test_source_context_retains_finite_x_identity_when_scientific_digest_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = SherpaDataset(X=np.arange(12, dtype=np.float64).reshape(3, 4))
    expected_fingerprint = dataset.fingerprint

    def _unavailable_digest(_dataset: SherpaDataset) -> str:
        raise ValueError("scientific metadata is not canonically serializable")

    monkeypatch.setattr(SherpaDataset, "scientific_digest", property(_unavailable_digest))

    context = build_statistics_result(dataset)["statistics"]["summary"]["source_context"]

    assert context["scientific_digest"] is None
    assert context["data_fingerprint"] == expected_fingerprint
    assert context["sample_identity"]["count"] == 3


def test_res45_statistics_retains_external_source_and_specimen_custody() -> None:
    dataset = SherpaDataset(
        X=np.arange(16, dtype=np.float64).reshape(4, 4),
        target=np.array([1.0, 1.0, 2.0, 3.0]),
        target_context=TargetContext(target_type="continuous", target_name="Assay", target_units="mg/L"),
        sample_axis=SampleAxis(
            labels=["specimen-4", "specimen-1", "specimen-3", "specimen-2"],
            sample_table={
                "sample_id": ["specimen-4", "specimen-1", "specimen-3", "specimen-2"],
                "analysis_role": ["external", "external", "external", "external"],
                "instrument": ["instrument-2", "instrument-2", "instrument-2", "instrument-2"],
            },
        ),
        source_identity=DatasetSourceIdentity(source_format="eigenvector-dso", object_name="Test 1"),
        extra={
            "reference.artifact_id": "shootout-fixture",
            "reference.artifact_sha256": "a" * 64,
            "reference.member_sha256": "b" * 64,
            "reference.projection_id": "shootout-test-1",
            "reference.package_id": "shootout",
            "reference.view_id": "test-1",
            "reference.instrument_view": "instrument-2",
            "reference.cohort": "external-test",
        },
    )

    statistics = build_statistics_result(dataset)["statistics"]
    context = statistics["summary"]["source_context"]

    assert context == statistics["metadata"]["source_context"]
    assert context["scientific_digest"] == dataset.scientific_digest
    assert context["data_fingerprint"] == dataset.fingerprint
    assert context["source_identity"] == {"source_format": "eigenvector-dso", "object_name": "Test 1"}
    assert context["reference"] == {
        "reference.artifact_id": "shootout-fixture",
        "reference.artifact_sha256": "a" * 64,
        "reference.member_sha256": "b" * 64,
        "reference.projection_id": "shootout-test-1",
        "reference.package_id": "shootout",
        "reference.view_id": "test-1",
        "reference.instrument_view": "instrument-2",
        "reference.cohort": "external-test",
    }
    assert context["sample_identity"]["count"] == 4
    assert context["sample_identity"]["labels_present"] is True
    assert context["sample_identity"]["labels_unique"] is True
    assert len(context["sample_identity"]["labels_sha256"]) == 64
    assert context["sample_table_columns"] == ["analysis_role", "instrument", "sample_id"]
    assert context["sample_role_counts"]["analysis_role"]["counts"] == {"text:external": 4}
    assert context["sample_role_counts"]["instrument"]["counts"] == {"text:instrument-2": 4}
    assert context["sample_role_counts"]["analysis_role"]["values_redacted"] is False
    assert context["sample_role_counts"]["instrument"]["values_redacted"] is False
    table = build_data_table_result(statistics)
    assert table["visualization"]["metadata"]["source_context"] == context


def test_res45_source_context_omits_nested_and_invalid_reference_values() -> None:
    dataset = SherpaDataset(
        X=np.arange(12, dtype=np.float64).reshape(3, 4),
        extra={
            "reference.cohort": {"private_rows": [[0, 1], [1, 2]]},
            "reference.instrument_view": "instrument-1",
            "reference.artifact_sha256": "not-a-digest",
            "reference.member_sha256": "a" * 64,
        },
    )

    reference = build_statistics_result(dataset)["statistics"]["summary"]["source_context"]["reference"]

    assert reference == {
        "reference.member_sha256": "a" * 64,
        "reference.instrument_view": "instrument-1",
    }


def test_res45_source_context_redacts_high_cardinality_role_values() -> None:
    labels = [f"specimen-{index}" for index in range(10_000)]
    dataset = SherpaDataset(
        X=np.arange(40_000, dtype=np.float64).reshape(10_000, 4),
        sample_axis=SampleAxis(
            labels=labels,
            sample_table={
                "sample_id": labels,
                "instrument": [f"unique-private-instrument-{index}" for index in range(10_000)],
            },
        ),
    )

    role = build_statistics_result(dataset)["statistics"]["summary"]["source_context"]["sample_role_counts"][
        "instrument"
    ]

    assert role["counts"] is None
    assert role["distinct_count"] is None
    assert role["distinct_count_lower_bound"] == 33
    assert role["total_count"] == 10_000
    assert role["values_redacted"] is True
    assert len(role["values_sha256"]) == 64
    assert "unique-private-instrument" not in json.dumps(role)


def test_res45_bounded_role_counts_preserve_mixed_scalar_membership() -> None:
    summary = _role_summary([1, "1", 1, True, "true", None, "<missing>"])

    assert summary["values_redacted"] is False
    assert summary["counts"] == {
        "boolean:true": 1,
        "integer:1": 2,
        "null": 1,
        "text:1": 1,
        "text:<missing>": 1,
        "text:true": 1,
    }
    assert sum(summary["counts"].values()) == summary["total_count"] == 7


def test_declared_categorical_target_keeps_class_counts() -> None:
    dataset = SherpaDataset(
        X=np.arange(16, dtype=np.float64).reshape(4, 4),
        target=np.array([0, 1, 0, 1]),
        target_context=TargetContext(target_type="categorical", target_name="Class"),
    )

    target = build_statistics_result(dataset)["statistics"]["summary"]["target"]

    assert target["target_type"] == "categorical"
    assert target["class_counts"] == {"0": 2, "1": 2}
    assert "columns" not in target


def test_categorical_target_does_not_count_missing_values_as_classes() -> None:
    dataset = SherpaDataset(
        X=np.arange(12, dtype=np.float64).reshape(3, 4),
        target=np.array([0.0, 1.0, np.nan]),
        target_context=TargetContext(target_type="categorical", target_name="Class"),
    )

    target = build_statistics_result(dataset)["statistics"]["summary"]["target"]

    assert target["nonfinite"] == 1
    assert target["missing"] == 1
    assert target["class_counts"] == {"0.0": 1, "1.0": 1}


def test_text_categorical_target_omits_null_label() -> None:
    dataset = SherpaDataset(
        X=np.arange(12, dtype=np.float64).reshape(3, 4),
        target=np.array(["A", "B", None], dtype=object),
        target_context=TargetContext(target_type="categorical", target_name="Class"),
    )

    target = build_statistics_result(dataset)["statistics"]["summary"]["target"]

    assert target["missing"] == 1
    assert target["class_counts"] == {"A": 1, "B": 1}


def test_pca_summary_reports_producer_diagnostics_without_inventing_outliers() -> None:
    result = build_statistics_result(
        {
            "scores": np.array([[1.0, 0.2], [0.4, np.nan], [-0.8, 0.7]]),
            "t2": [1.0, 2.0, 3.0],
            "spe": [0.1, 0.2, 0.3],
            "metadata": {"explained_variance_ratio": [0.7, 0.2], "t2_p95": 4.0, "spe_p95": 0.5},
        }
    )["statistics"]

    assert result["input_type"] == "PCA"
    assert result["summary"]["total_variance_explained"] == pytest.approx(0.9)
    assert result["summary"]["nonfinite_score_count"] == 1
    assert "outliers" not in result
    assert result["metadata"]["diagnostic_decisions_deferred_to"] == "diagnostics.outliers"


def test_mcr_summary_validates_component_shape_and_uses_unit_neutral_names() -> None:
    result = build_statistics_result(
        {
            "C": np.array([[0.2, 0.8], [0.7, 0.3]]),
            "St": np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]),
        }
    )["statistics"]
    assert result["summary"] == {"n_observations": 2, "n_components": 2, "n_features": 3}
    assert result["detailed"]["pure_spectra"][0] == {
        "component": 1,
        "max_response": 3.0,
        "mean_response": 2.0,
    }

    with pytest.raises(ValueError, match="component dimensions"):
        build_statistics_result({"C": np.ones((3, 2)), "St": np.ones((3, 4))})


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"unknown": {"nested": 1}}, "does not infer semantics"),
        (np.ones((2, 3, 4)), "one- or two-dimensional"),
        ({"C": np.ones((2, 2)), "St": np.array([[1.0, np.nan], [2.0, 3.0]])}, "must be finite"),
    ],
)
def test_stats_summary_fails_closed_instead_of_fabricating_data(payload: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_statistics_result(payload)


def test_categorical_counts_are_deterministic() -> None:
    result = build_statistics_result(np.array(["B", "A", "B", "C", "B"]))["statistics"]
    assert result["input_type"] == "categorical_array"
    assert result["summary"]["mode"] == "B"
    assert result["data"][0] == {"value": "B", "count": 3, "fraction": 0.6}


def test_stats_summary_has_a_representative_capacity_ceiling() -> None:
    dataset = SherpaDataset(
        X=np.arange(200 * 1600, dtype=np.float64).reshape(200, 1600),
        feature_axis=SpectralAxis(values=np.linspace(400.0, 4000.0, 1600), units="cm-1"),
    )
    with PerformanceCeiling("stats.summary", "200x1600-dataset", 5.0).measure():
        result = build_statistics_result(dataset, max_samples=100)
    assert result["statistics"]["summary"]["n_samples"] == 200


def test_stats_summary_has_multiple_ready_in_tree_consumers() -> None:
    templates = __import__("pathlib").Path(__file__).parents[1] / "src/spectra_sherpa/data/templates"
    consumers = ["pca.yaml", "mcr_als.yaml", "peaks.yaml"]
    for filename in consumers:
        text = (templates / filename).read_text(encoding="utf-8")
        assert "status: ready" in text
        assert "node_type: stats.summary" in text
