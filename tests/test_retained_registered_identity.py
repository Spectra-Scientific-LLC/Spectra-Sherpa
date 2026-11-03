"""Synthetic catalog fixtures exercising real retained source validation, never a provider fit."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.collection_assembly import source_collection_manifest
from spectra_sherpa.app.lib.comparison_identity import INVALID_IDENTITY_REASON, LEGACY_IDENTITY_REASON
from spectra_sherpa.app.lib.reference_artifacts import ReferenceArtifact, ReferenceArtifactRegistry, ReferenceProjection
from spectra_sherpa.app.lib.reference_dataset_packages import reference_annotation_table_digest
from spectra_sherpa.app.lib.reference_datasets import feature_axis_values_digest
from spectra_sherpa.app.lib.registered_reference_collection_identity import registered_reference_collection_identity
from spectra_sherpa.app.lib.sherpa_dataset import DatasetSourceIdentity, Provenance, SherpaDataset, TargetContext
from spectra_sherpa.app.services import retained_registered_identity as recovery
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.services.dag.nodes.data.split_planner import materialize_split_outputs, plan_train_test_split
from spectra_sherpa.app.services.dag.regression_comparison import build_regression_comparison
from spectra_sherpa.app.services.retained_regression_comparison import retained_regression_evidence
from spectra_sherpa.sdk.dataset_identity import public_dataset_digest


@pytest.fixture
def registered(tmp_path, monkeypatch):
    # The test-only catalog is synthetic; canonical scientific/source validators
    # below run unchanged. Production always loads the installed governed catalog.
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    x = np.arange(48, dtype=float).reshape(12, 4)
    y = np.arange(12, dtype=float)
    lactate = y + 10
    table = {"sample_id": [f"obs-{i}" for i in range(12)], "Glucose": y.tolist(), "Lactate": lactate.tolist()}
    fields = [
        {"name": "Glucose", "index": 0, "target_type": "continuous", "units": "wt%"},
        {"name": "Lactate", "index": 1, "target_type": "continuous", "units": "wt%"},
    ]
    annotation = reference_annotation_table_digest(np.column_stack([y, lactate]), fields)
    extra = {
        "reference.projection_id": "test-projection",
        "reference.artifact_id": "test-artifact",
        "reference.artifact_sha256": "a" * 64,
        "reference.member_sha256": "b" * 64,
        "reference.package_id": "test-package",
        "reference.view_id": "test-view",
        "reference.instrument_view": "nir",
        "reference.cohort": "test-cohort",
        "reference.annotation_table_sha256": annotation,
    }
    root = SherpaDataset(
        X=x,
        target=y,
        sample_axis=SampleAxis(labels=table["sample_id"], sample_table=table),
        feature_axis=SpectralAxis(values=np.arange(4.0), units="nm"),
        target_context=TargetContext(
            target_names=["Glucose"], selected_target="Glucose", target_units="wt%", target_type="continuous"
        ),
        source_identity=DatasetSourceIdentity(source_format="eigenvector-dso"),
        extra=extra,
        provenance=Provenance.from_list(
            [{"op_id": "import.matlab_dso", "op_version": "1", "parameters": {}, "timestamp": ""}]
        ),
    )
    manifest = source_collection_manifest(
        [{"file_name": "test.mat", "size_bytes": 10, "sha256": "b" * 64, "prepared_data_sha256": "c" * 64}]
    )
    root.meta["source_collection"] = {**manifest, **registered_reference_collection_identity(manifest, root)}
    registry = ReferenceArtifactRegistry(
        artifacts=(
            ReferenceArtifact(
                {
                    "artifact_id": "test-artifact",
                    "sha256": "a" * 64,
                    "members": [{"path": "test.mat", "sha256": "b" * 64, "expected_size_bytes": 10}],
                }
            ),
        ),
        projections=(
            ReferenceProjection(
                {
                    "projection_id": "test-projection",
                    "artifact_id": "test-artifact",
                    "member_path": "test.mat",
                    "n_samples": 12,
                    "n_features": 4,
                    "feature_axis_sha256": feature_axis_values_digest(np.arange(4.0)),
                    "feature_axis_title": root.feature_axis.title,
                    "feature_axis_units": "nm",
                    # As in CGL, the selected response need not be the
                    # projection's original default response column.
                    "target_name": "Lactate",
                    "scientific_sha256": public_dataset_digest(x, lactate),
                }
            ),
        ),
    )
    monkeypatch.setattr(recovery, "load_reference_artifact_registry", lambda: registry)
    monkeypatch.setattr(
        recovery,
        "package_view_projection",
        lambda _: {
            "package_id": "test-package",
            "view_id": "test-view",
            "instrument": "nir",
            "cohort": "test-cohort",
            "annotation_table": {"values_sha256": annotation, "fields": fields},
        },
    )
    plan = plan_train_test_split(x, y, method="random")
    split = materialize_split_outputs(root, x, y, plan, node_id="split", target_context=root.target_context)
    comparison = build_regression_comparison(
        y[plan.test_indices],
        y[plan.test_indices] + 0.1,
        role="held_out_test",
        target_names=["Glucose"],
        sample_dataset=split["X_test"],
    )
    comparison["metadata"]["population_authority"] = {
        "qualification": "graph_verified",
        "population": ["split", "test"],
        "fitted_populations": [["split", "train"]],
    }
    definition = {
        "schema_version": 1,
        "nodes": [
            {"node_id": "data", "node_type": "data.file_load"},
            {"node_id": "split", "node_type": "data.train_test_split"},
            {"node_id": "eval", "node_type": "diagnostics.regression_evaluator"},
        ],
        "edges": [
            {"from_node_id": "data", "from_output": "default", "to_node_id": "split", "to_input": "X"},
            {"from_node_id": "predict", "from_output": "default", "to_node_id": "eval", "to_input": "default"},
            {"from_node_id": "split", "from_output": "y_test", "to_node_id": "eval", "to_input": "y_true"},
        ],
    }
    return root, split, comparison, definition, y[plan.test_indices] + 0.1


def resolve(values):
    root, split, comparison, definition, predictions = values
    calibration = (
        next(node for node in definition["nodes"] if node["node_id"] == "eval")["node_type"] == "model.fitted_pls"
    )
    data = {
        "data": {"default": root},
        "split": split,
        "predict": {"default": predictions},
        "eval": {"calibration_comparison" if calibration else "comparison": comparison},
        "__workflow__": {"definition": definition},
    }
    run = SimpleNamespace(id="registered", user_id=1, evidence_completeness=retention.retain_run_outputs(1, data, {}))
    return retained_regression_evidence(run)


def test_registered_root_recovers_exact_retained_branch_without_rewriting_producer(registered):
    comparison = registered[2]
    before = deepcopy(comparison)
    records, population, complete = resolve(registered)
    assert len(records) == 1
    assert population.response == "Glucose" and population.units == "wt%"
    assert records[0].role == "held_out" and population.verification == "partial"
    assert complete and comparison == before
    assert comparison["metadata"]["sample_identity_unavailable"] == LEGACY_IDENTITY_REASON


@pytest.mark.parametrize(
    "damage",
    [
        "root_receipt",
        "catalog",
        "ids",
        "table",
        "source",
        "indices",
        "features",
        "multisource",
        "unknown_refusal",
        "invalid_refusal",
        "unknown_branch",
        "prediction_values",
        "prediction_binding",
        "generic_dso",
        "root_units",
    ],
)
def test_registered_recovery_refuses_drift_but_keeps_retained_response(registered, damage):
    root, split, comparison, definition, predictions = registered
    if damage == "root_receipt":
        root.meta["source_collection"]["collection_definition_sha256"] = "0" * 64
    elif damage == "catalog":
        root.meta["reference.artifact_sha256"] = "0" * 64
    elif damage == "ids":
        axis = split["X_test"].sample_axis.model_dump(mode="python")
        axis["sample_table"]["sample_id"].reverse()
        split["X_test"].sample_axis = SampleAxis.model_validate(axis)
    elif damage == "table":
        axis = split["X_test"].sample_axis.model_dump(mode="python")
        axis["sample_table"]["Glucose"][0] += 1
        split["X_test"].sample_axis = SampleAxis.model_validate(axis)
    elif damage == "source":
        split["X_test"].meta["source_collection"] = {"source_manifest_sha256": "d" * 64}
    elif damage == "indices":
        entries = split["X_test"].provenance.to_list()
        entries[-1]["parameters"]["split"] = "train"
        split["X_test"].provenance = Provenance.from_list(entries)
    elif damage == "features":
        split["X_test"].data[0, 0] += 1
    elif damage == "multisource":
        definition["edges"].append({**definition["edges"][0], "from_node_id": "other"})
    elif damage == "unknown_refusal":
        comparison["metadata"]["sample_identity_unavailable"] = "A different producer refusal"
    elif damage == "invalid_refusal":
        comparison["metadata"]["sample_identity_unavailable"] = INVALID_IDENTITY_REASON
    elif damage == "generic_dso":
        root.meta.pop("reference.projection_id")
    elif damage == "root_units":
        context = root.target_context.model_dump(mode="python")
        context["target_units"] = "mg/L"
        root.target_context = TargetContext.model_validate(context)
    elif damage == "prediction_values":
        predictions[0] += 1
    elif damage == "prediction_binding":
        definition["edges"].pop(1)
    else:
        comparison["metadata"]["population_authority"]["population"][1] = "other"
    records, population, _ = resolve(registered)
    assert not records
    if damage != "unknown_branch":
        assert population.response == "Glucose" and population.units == "wt%"
        assert population.verification == "unknown" and population.limitations
    if damage == "generic_dso":
        assert LEGACY_IDENTITY_REASON in population.limitations
    if damage == "invalid_refusal":
        assert INVALID_IDENTITY_REASON in population.limitations


def test_valid_registered_reference_does_not_upgrade_unrelated_legacy_prediction(registered):
    root, split, comparison, definition, predictions = registered
    unrelated = SherpaDataset(
        X=predictions[:, None],
        sample_axis=split["X_test"].sample_axis.copy(),
        source_identity=DatasetSourceIdentity(source_format="eigenvector-dso"),
    )
    records, population, _ = resolve((root, split, comparison, definition, unrelated))
    assert not records
    assert population.response == "Glucose" and population.verification == "unknown"
    assert "source custody" in " ".join(population.limitations)


def test_registered_calibration_recovers_without_promoting_oof_or_rewriting_metadata(registered):
    root, split, _, definition, predictions = registered
    observed = split["X_train"].target
    comparison = build_regression_comparison(
        observed, observed + 0.1, role="calibration", target_names=["Glucose"], sample_dataset=split["X_train"]
    )
    definition["nodes"][-1]["node_type"] = "model.fitted_pls"
    definition["edges"] = [
        definition["edges"][0],
        {"from_node_id": "split", "from_output": "X_train", "to_node_id": "eval", "to_input": "default"},
    ]
    before = deepcopy(comparison)
    records, population, complete = resolve((root, split, comparison, definition, predictions))
    assert complete and len(records) == 1 and records[0].role == "calibration"
    assert population.response == "Glucose" and population.units == "wt%"
    assert population.verification == "partial" and comparison == before


def test_registered_recovery_reuses_full_root_validation_per_read(registered, monkeypatch):
    original = recovery.validate_registered_reference_source_identity
    calls = []

    def validate(source, root):
        calls.append(root)
        return original(source, root)

    monkeypatch.setattr(recovery, "validate_registered_reference_source_identity", validate)
    assert len(resolve(registered)[0]) == 1
    assert len(calls) == 1


def test_registered_root_must_reproduce_saved_scientific_manifest(registered):
    from spectra_sherpa.app.services.serialization import serialize_result

    root, *rest = registered
    wire = serialize_result(root)
    wire["manifest"]["scientific_digest"] = "0" * 64
    records, population, _ = resolve((wire, *rest))
    assert not records
    assert "scientific receipt" in " ".join(population.limitations)


def test_recomputing_source_metadata_cannot_substitute_registered_feature_content(registered):
    root, *rest = registered
    root.data[0, 0] += 1
    # Reproduce the same count/table/source collection and even its local
    # scientific receipt. The governed projection digest must still reject it.
    plan = plan_train_test_split(root.data, root.target, method="random")
    rest[0] = materialize_split_outputs(
        root, root.data, root.target, plan, node_id="split", target_context=root.target_context
    )
    records, population, _ = resolve((root, *rest))
    assert not records
    assert "governed projection" in " ".join(population.limitations)


def test_calibration_population_namespace_uses_raw_split_signal_not_fitted_transform(registered):
    from spectra_sherpa.app.contracts.comparison_evidence import ResolvedComparisonEvidence
    from spectra_sherpa.app.schemas.scientific_comparison import EvidenceReference
    from spectra_sherpa.app.services.dag.io_contracts import build_dataset_like
    from spectra_sherpa.app.services.scientific_comparison import compare_evidence
    from spectra_sherpa.app.services.serialization import serialize_result

    root, split, _, definition, _ = registered
    raw = split["X_train"]
    transformed = build_dataset_like(raw.data * 2, raw, units="dimensionless")
    transformed.domain = transformed.domain.model_copy(update={"technique": "derived_features"})
    transformed.data_role = "X_features"
    wire = serialize_result(transformed)
    wire["metadata"] = {**wire.get("metadata", {}), "value_units": "scaled", "value_units_label": "Scaled signal"}
    raw_wire = serialize_result(raw)
    assert all(wire.get(key) != raw_wire.get(key) for key in ("units", "domain", "data_role"))
    assert wire["metadata"]["value_units"] != raw_wire.get("metadata", {}).get("value_units")
    assert wire["metadata"]["value_units_label"] != raw_wire.get("metadata", {}).get("value_units_label")
    resolved = []
    for index, fitted_input in enumerate((raw, wire), 1):
        comparison = build_regression_comparison(
            raw.target, raw.target + index * 0.1, role="calibration", target_names=["Glucose"], sample_dataset=raw
        )
        saved_definition = deepcopy(definition)
        saved_definition["nodes"][-1]["node_type"] = "model.fitted_pls"
        saved_definition["edges"] = [
            saved_definition["edges"][0],
            {"from_node_id": "fit-input", "from_output": "default", "to_node_id": "eval", "to_input": "default"},
        ]
        outputs = {
            "data": {"default": root},
            "split": split,
            "fit-input": {"default": fitted_input},
            "eval": {"calibration_comparison": comparison},
            "__workflow__": {"definition": saved_definition},
        }
        run = SimpleNamespace(id=index, user_id=1, evidence_completeness=retention.retain_run_outputs(1, outputs, {}))
        records, population, complete = retained_regression_evidence(run)
        assert complete and len(records) == 1 and records[0].role == "calibration"
        resolved.append(
            ResolvedComparisonEvidence(
                EvidenceReference(kind="run", provider="runs", id=str(index), revision=str(index) * 64),
                f"Calibration {index}",
                records,
                population,
            )
        )
    left, right = (item.evaluations[0] for item in resolved)
    assert left.feature_receipt == right.feature_receipt
    assert left.sample_ids == right.sample_ids and left.fitted_sample_ids == right.fitted_sample_ids
    assert left.response_identity == right.response_identity and left.units == right.units == "wt%"
    result = compare_evidence(resolved)
    sections = {section.role: section for section in result.pairs[0].sections}
    assert sections["calibration"].state == "comparable"
    assert sections["held_out"].state == sections["training_cv"].state == "unavailable"
    assert not sections["held_out"].metric_values and not sections["training_cv"].metric_values
