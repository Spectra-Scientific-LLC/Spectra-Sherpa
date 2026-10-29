"""Counterexamples from the data-portfolio handoff audit, using generated data."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import DatasetSourceIdentity, Provenance, SherpaDataset
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.services.dag.nodes.data.split_planner import materialize_split_outputs, plan_train_test_split
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node
from spectra_sherpa.app.services.dag.nodes.modeling.mcr_nodes import _compare_mcr_spectra_to_truth
from spectra_sherpa.app.services.dag.nodes.regression_evaluator_node import evaluate_regression_v2
from spectra_sherpa.app.services.dag.population_authority import qualify_evaluation_result
from spectra_sherpa.app.services.dag.regression_comparison import build_regression_comparison
from spectra_sherpa.app.services.scientific_comparison import compare_evidence, resolve_run_evidence


def retained_run(
    prefix,
    *,
    label_prefix="display",
    collection="a",
    typed=True,
    comparison_ids=None,
    source_format=None,
    identity_unavailable=False,
):
    x = np.arange(36, dtype=float).reshape(12, 3)
    y = np.arange(12, dtype=float)
    plan = plan_train_test_split(x, y, method="random")
    source = SherpaDataset(
        X=x,
        target=y,
        source_identity=DatasetSourceIdentity(source_format=source_format) if source_format else None,
        provenance=(
            Provenance.from_list(
                [
                    {
                        "op_id": (
                            "import.matlab_dso" if source_format == "eigenvector-dso" else "import.matlab_process_log"
                        ),
                        "op_version": "1.0",
                        "parameters": {},
                        "timestamp": "",
                    }
                ]
            )
            if source_format
            else None
        ),
        sample_axis=SampleAxis(
            labels=[f"{label_prefix}-{i}" for i in range(12)],
            sample_table={"sample_id": [f"{prefix}-{i}" for i in range(12)]} if typed else None,
        ),
        extra={
            "source_collection": {
                "source_manifest_sha256": "a" * 64,
                "collection_definition_sha256": collection * 64,
                "scientific_collection_sha256": collection * 64,
            }
        },
    )
    outputs = materialize_split_outputs(source, x, y, plan, node_id="split")
    target = y[plan.test_indices]
    comparison = build_regression_comparison(target, target + 0.1, role="held_out_test")
    comparison["metadata"]["population_authority"] = {
        "schema_version": "spectrasherpa-population-authority/1",
        "qualification": "graph_verified",
        "population": ["split", "test"],
        "fitted_populations": [["split", "train"]],
    }
    if identity_unavailable:
        comparison["metadata"]["sample_identity_unavailable"] = "Unavailable identity origin"
    if comparison_ids is not None:
        comparison["metadata"]["sample_ids"] = comparison_ids
    return SimpleNamespace(
        id=prefix,
        user_id=1,
        name=prefix,
        diagnostics={},
        source_metadata={},
        evidence_completeness=retention.retain_run_outputs(
            1,
            {
                "split": outputs,
                "eval": {"comparison": comparison},
                "__workflow__": {
                    "definition": {
                        "schema_version": 1,
                        "nodes": [{"node_id": "split", "node_type": "data.train_test_split"}],
                        "edges": [],
                    }
                },
            },
            {},
        ),
    )


@pytest.mark.parametrize("change", ["ids", "collection", "labels"])
def test_real_retention_preserves_identity_and_distinguishes_labels(tmp_path, monkeypatch, change):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    left = resolve_run_evidence(retained_run("A"))
    right = resolve_run_evidence(
        retained_run(
            "B" if change == "ids" else "A",
            collection="b" if change == "collection" else "a",
            label_prefix="renamed" if change == "labels" else "display",
        )
    )
    assert len(left.evaluations) == len(right.evaluations) == 1
    result = compare_evidence([left, right])
    section = next(s for s in result.pairs[0].sections if s.role == "held_out")
    assert (section.state == "comparable") == (change == "labels")
    if change == "ids":
        assert left.evaluations[0].sample_ids != right.evaluations[0].sample_ids


@pytest.mark.parametrize("kwargs", [{"typed": False}, {"comparison_ids": ["A-6", "A-3"]}])
def test_missing_or_misaligned_identity_cannot_qualify_retained_comparison(tmp_path, monkeypatch, kwargs):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    assert not resolve_run_evidence(retained_run("A", **kwargs)).evaluations


@pytest.mark.parametrize(
    "mutation",
    ["shifted", "reversed", "roundoff", "rounded_report", "wrong_units", "missing", "quantity", "nan", "exact"],
)
def test_mcr_ground_truth_requires_exact_physical_grid(mutation):
    axis = np.arange(600.0, 611.0)
    signal = (np.exp(-((axis - 603) ** 2) / 3) + 0.1 * (axis - 600))[None, :]
    truth_signal = signal.copy()
    truth = axis.copy()
    if mutation == "shifted":
        truth += 10
    if mutation == "reversed":
        truth = truth[::-1]
        truth_signal = truth_signal[:, ::-1]
    if mutation == "roundoff":
        truth = np.nextafter(truth, np.inf)
    if mutation == "rounded_report":
        truth += 0.00001
    if mutation == "nan":
        truth[0] = np.nan
    dataset = SherpaDataset(
        X=np.zeros((3, len(axis))),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        extra={
            "ground_truth.spectra": truth_signal.tolist(),
            "ground_truth.spectra_x": None if mutation == "missing" else truth.tolist(),
            "ground_truth.spectra_x_title": "Raman shift" if mutation == "quantity" else "Wavenumber",
            "ground_truth.spectra_x_units": "nm" if mutation == "wrong_units" else "cm^-1",
        },
    )
    reasons = []
    result = _compare_mcr_spectra_to_truth(signal, dataset, unavailable_reasons=reasons)
    admitted = mutation in {"exact", "reversed", "roundoff"}
    assert bool(reasons) != admitted
    assert (result is not None) == admitted
    if result is not None:
        assert (
            result["axis_alignment"]
            == {"exact": "exact", "reversed": "reversed", "roundoff": "floating_point_roundoff"}[mutation]
        )
        assert result["selected_match"]["r2"] == pytest.approx(1.0)


@pytest.mark.parametrize("n_targets", [1, 2])
def test_graph_verified_regression_uses_exact_branch_labels_and_ids(n_targets):
    target = np.arange(6 * n_targets, dtype=float).reshape(6, n_targets)
    source = SherpaDataset(
        X=np.ones((6, 3)),
        target=target,
        sample_axis=SampleAxis(
            labels=[f"original-{i}" for i in [135, 142, 149, 151, 155, 157]],
            sample_table={"sample_id": [f"id-{i}" for i in range(6)]},
        ),
    )
    result = evaluate_regression_v2(target + 0.1, target)
    receipt = {
        "role": "held_out_test",
        "qualification": "graph_verified",
        "population": ["split", "test"],
        "fitted_populations": [["split", "train"]],
    }
    qualify_evaluation_result(result, receipt, source_results={"split": {"X_test": source}})
    comparison = result.outputs["comparison"]
    assert [row["sample"] for row in comparison["data"]] == [
        label for label in source.sample_axis.labels for _ in range(n_targets)
    ]
    assert comparison["metadata"]["sample_ids"] == source.sample_axis.sample_table["sample_id"]
    assert comparison["data"][0]["predicted"] == 0.1


@pytest.mark.asyncio
async def test_fitted_pls_preserves_curated_sample_labels():
    rng = np.random.default_rng(2026)
    x = rng.normal(size=(20, 5))
    y = x[:, 0] * 2 + x[:, 1]
    labels = [f"vial-{i+135}" for i in range(20)]
    source = SherpaDataset(
        X=x, target=y, sample_axis=SampleAxis(labels=labels, sample_table={"sample_id": [f"id-{i}" for i in range(20)]})
    )
    result = await FittedPLSV2Node("fit", {"n_components": 2}).run(source)
    comparison = result.outputs["calibration_comparison"]
    assert [row["sample"] for row in comparison["data"]] == labels
    assert comparison["metadata"]["sample_ids"] == source.sample_axis.sample_table["sample_id"]


def test_qualification_cannot_overwrite_contradictory_producer_identity():
    from copy import deepcopy

    source = SherpaDataset(
        X=np.ones((3, 2)),
        sample_axis=SampleAxis(labels=["a", "b", "c"], sample_table={"sample_id": ["id-a", "id-b", "id-c"]}),
    )
    result = evaluate_regression_v2(np.arange(3.0) + 0.1, np.arange(3.0))
    result.outputs["comparison"]["metadata"]["sample_ids"] = ["id-b", "id-a", "id-c"]
    before = deepcopy(result.outputs["comparison"]["data"])
    receipt = {
        "role": "held_out_test",
        "qualification": "graph_verified",
        "population": ["split", "test"],
        "fitted_populations": [["split", "train"]],
    }
    with pytest.raises(ValueError, match="identities disagree"):
        qualify_evaluation_result(result, receipt, source_results={"split": {"X_test": source}})
    assert result.outputs["comparison"]["metadata"]["sample_ids"] == ["id-b", "id-a", "id-c"]
    assert result.outputs["comparison"]["data"] == [{**row, "role": "held_out_test"} for row in before]


def test_typed_target_evaluator_preserves_ids_and_refuses_misaligned_predictions():
    target = SherpaDataset(
        X=np.arange(4.0).reshape(-1, 1),
        sample_axis=SampleAxis(
            labels=["vial135", "", "vial142", "vial155"], sample_table={"sample_id": ["a", "b", "c", "d"]}
        ),
    )
    result = evaluate_regression_v2(target.X + 0.1, target)
    assert [row["sample"] for row in result.outputs["comparison"]["data"]] == ["vial135", "b", "vial142", "vial155"]
    assert result.outputs["comparison"]["metadata"]["sample_ids"] == ["a", "b", "c", "d"]
    predicted = SherpaDataset(
        X=target.X + 0.1, sample_axis=SampleAxis(sample_table={"sample_id": ["b", "a", "c", "d"]})
    )
    with pytest.raises(ValueError, match="sample IDs"):
        evaluate_regression_v2(predicted, target)


@pytest.mark.asyncio
async def test_pls_blank_display_label_does_not_invalidate_typed_identity():
    rng = np.random.default_rng(21)
    x = rng.normal(size=(15, 3))
    dataset = SherpaDataset(
        X=x,
        target=x[:, 0],
        sample_axis=SampleAxis(
            labels=[""] + [f"vial-{i}" for i in range(1, 15)],
            sample_table={"sample_id": [f"id-{i}" for i in range(15)]},
        ),
    )
    result = await FittedPLSV2Node("fit", {"n_components": 2}).run(dataset)
    assert result.outputs["calibration_comparison"]["data"][0]["sample"] == "id-0"


def test_unsplit_calibration_identity_does_not_depend_on_display_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))

    def make_run(labels, offset=0, units="absorbance", masked=False):
        x = np.arange(36.0, dtype=float).reshape(12, 3) + offset
        if masked:
            x[0, 0] = np.nan
        y = np.arange(12.0, dtype=float)
        source = SherpaDataset(
            X=x,
            target=y,
            units=units,
            sample_axis=SampleAxis(labels=labels, sample_table={"sample_id": [f"id-{i}" for i in range(12)]}),
            extra={"source_collection": {"source_manifest_sha256": "a" * 64}},
        )
        comparison = build_regression_comparison(y, y + 0.1, role="calibration", sample_dataset=source)
        return SimpleNamespace(
            id="run",
            user_id=1,
            name="run",
            diagnostics={},
            source_metadata={},
            evidence_completeness=retention.retain_run_outputs(
                1,
                {
                    "load": {"default": source},
                    "pls": {"calibration_comparison": comparison},
                    "__workflow__": {
                        "definition": {
                            "schema_version": 1,
                            "nodes": [{"node_id": "pls", "node_type": "model.fitted_pls"}],
                            "edges": [{"from_node_id": "load", "to_node_id": "pls", "to_input": "default"}],
                        }
                    },
                },
                {},
            ),
        )

    first = resolve_run_evidence(make_run([f"a-{i}" for i in range(12)]))
    renamed = resolve_run_evidence(make_run([f"b-{i}" for i in range(12)]))
    changed = resolve_run_evidence(make_run([f"a-{i}" for i in range(12)], 1))
    assert len(first.evaluations) == len(renamed.evaluations) == len(changed.evaluations) == 1
    assert first.evaluations[0].sample_ids == renamed.evaluations[0].sample_ids
    assert first.evaluations[0].feature_receipt != changed.evaluations[0].feature_receipt
    unit_change = resolve_run_evidence(make_run([f"a-{i}" for i in range(12)], units="transmittance"))
    assert first.evaluations[0].feature_receipt != unit_change.evaluations[0].feature_receipt

    # Current retention marks nonfinite-to-null conversion as reduced evidence.
    # Supporting a numeric fingerprint must not promote that payload to exact.
    masked = resolve_run_evidence(make_run([f"a-{i}" for i in range(12)], masked=True))
    assert not masked.evaluations
    assert "Exact retained population evidence is unavailable" in masked.unavailable_reason


def test_typed_label_only_evaluator_refuses_contradictory_order():
    target = SherpaDataset(X=np.arange(3.0).reshape(-1, 1), sample_axis=SampleAxis(labels=["A", "B", "C"]))
    prediction = SherpaDataset(X=target.X, sample_axis=SampleAxis(labels=["B", "A", "C"]))
    with pytest.raises(ValueError, match="sample labels"):
        evaluate_regression_v2(prediction, target)


def test_closed_retained_budget_refusal_is_not_reported_as_missing_cv(monkeypatch):
    from spectra_sherpa.app.services import retained_regression_comparison as adapter

    def unavailable(run):
        raise adapter.RetainedComparisonUnavailable(
            "Retained comparison exceeds the bounded read budget; inspect individual run outputs."
        )

    monkeypatch.setattr(adapter, "retained_regression_evidence", unavailable)
    run = SimpleNamespace(id=1, user_id=1, name="limited", diagnostics={}, source_metadata={}, evidence_completeness={})
    result = resolve_run_evidence(run)
    assert "bounded read budget" in result.unavailable_reason
    assert "out-of-fold" not in result.unavailable_reason


def test_run_metric_projection_preserves_equal_distinct_producers():
    from spectra_sherpa.app.services.run_metrics import comparable_results_for_run

    assert comparable_results_for_run(
        {"held_out": {"rmse": 1}, "training_cv": {"rmse": 1}}, qualify_producers=True
    ) == {
        "held_out.rmse": 1,
        "training_cv.rmse": 1,
    }
    assert comparable_results_for_run({"renamed": {"rmse": 1}}, qualify_producers=True) == {"renamed.rmse": 1}


def test_missing_held_out_identity_reason_survives_valid_calibration(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    x = np.arange(36.0).reshape(12, 3)
    y = np.arange(12.0)
    source = SherpaDataset(
        X=x,
        target=y,
        sample_axis=SampleAxis(sample_table={"sample_id": [f"id-{i}" for i in range(12)]}),
        extra={"source_collection": {"source_manifest_sha256": "a" * 64}},
    )
    plan = plan_train_test_split(x, y, method="random")
    outputs = materialize_split_outputs(source, x, y, plan, node_id="split")
    axis = outputs["X_test"].sample_axis
    axis.sample_table = None
    outputs["X_test"].sample_axis = axis
    retained = {
        "split": outputs,
        "__workflow__": {
            "definition": {
                "schema_version": 1,
                "nodes": [{"node_id": "split", "node_type": "data.train_test_split"}],
                "edges": [],
            }
        },
    }
    for branch, role, indices in [
        ("train", "calibration", plan.train_indices),
        ("test", "held_out_test", plan.test_indices),
    ]:
        comparison = build_regression_comparison(y[indices], y[indices] + 0.1, role=role)
        comparison["metadata"]["population_authority"] = {
            "qualification": "graph_verified",
            "population": ["split", branch],
            "fitted_populations": [["split", "train"]],
        }
        retained[branch] = {"comparison": comparison}
    run = SimpleNamespace(
        id=1,
        user_id=1,
        name="mixed",
        diagnostics={},
        source_metadata={},
        evidence_completeness=retention.retain_run_outputs(1, retained, {}),
    )
    resolved = resolve_run_evidence(run)
    assert [item.role for item in resolved.evaluations] == ["calibration"]
    assert "Typed sample identities were not retained" in resolved.unavailable_reason
    assert not any("Typed sample identities" in reason for reason in resolved.evaluations[0].population.limitations)


def test_evaluation_storage_error_does_not_expose_paths(monkeypatch):
    from spectra_sherpa.app.schemas.scientific_comparison import PopulationSummary
    from spectra_sherpa.app.services import retained_regression_comparison as adapter
    from spectra_sherpa.app.services import scientific_comparison as module

    monkeypatch.setattr(adapter, "retained_regression_evidence", lambda run: ((), PopulationSummary()))

    def fail(*args):
        raise OSError("PRIVATE_PATH_SENTINEL")

    monkeypatch.setattr(module, "_evaluation", fail)
    run = SimpleNamespace(
        id=1, user_id=1, name="unreadable", diagnostics={}, source_metadata={}, evidence_completeness={}
    )
    result = resolve_run_evidence(run)
    assert result.unavailable_reason == "Retained evaluation evidence could not be read."


def test_missing_training_port_preserves_other_retained_evaluations(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    caplog.set_level("WARNING")
    healthy = retained_run("A")
    # Second evaluator references a distinct split with no retained training data.
    from copy import deepcopy

    from spectra_sherpa.app.schemas.run_evidence import RunEvidence

    evidence = RunEvidence.model_validate(healthy.evidence_completeness)
    definition = retention.read_output(1, evidence.outputs["__workflow__"]["definition"])
    outputs = {
        name: {port: retention.read_output(1, item) for port, item in ports.items()}
        for name, ports in evidence.outputs.items()
        if name != "__workflow__"
    }
    outputs["missing"] = deepcopy(outputs["split"])
    outputs["missing"].pop("X_train")
    for value in outputs["missing"].values():
        if isinstance(value, dict):
            for step in value.get("provenance", []):
                if step.get("node_id") == "split":
                    step["node_id"] = "missing"
    broken = deepcopy(outputs["eval"]["comparison"])
    broken["metadata"]["population_authority"].update(
        population=["missing", "test"], fitted_populations=[["missing", "train"]]
    )
    outputs["broken_eval"] = {"comparison": broken}
    definition["nodes"].append({"node_id": "missing", "node_type": "data.train_test_split"})
    outputs["__workflow__"] = {"definition": definition}
    healthy.evidence_completeness = retention.retain_run_outputs(1, outputs, {})
    result = resolve_run_evidence(healthy)
    assert len(result.evaluations) == 1
    assert "Exact retained population evidence is unavailable" in result.unavailable_reason
    assert "RETAINED_COMPARISON_UNAVAILABLE" in caplog.text
    assert "broken_eval" in caplog.text


@pytest.mark.parametrize("declared_ids", [None, ["scan-1", "scan-2", "scan-3"]])
def test_mat_pair_preserves_historical_identity_payload(monkeypatch, tmp_path, declared_ids):
    import spectra_sherpa.io as io
    from spectra_sherpa.app.lib.eigenvector import load_eigenvector_mat_pair_as_sherpa

    axis = SampleAxis(labels=["S1", "S1", "S1"], sample_table={"sample_id": declared_ids} if declared_ids else None)
    spectra = SherpaDataset(
        X=np.ones((3, 4)),
        sample_axis=axis,
        feature_axis=SpectralAxis(values=np.arange(4.0), title="Wavelength", units="nm"),
    )
    properties = SherpaDataset(X=np.arange(21.0).reshape(3, 7), sample_axis=axis.copy())
    monkeypatch.setattr(
        io,
        "ingest",
        lambda path: SimpleNamespace(
            assets=[
                SimpleNamespace(asset_id="spectra", dataset=spectra),
                SimpleNamespace(asset_id="properties", dataset=properties),
            ]
        ),
    )
    loaded = load_eigenvector_mat_pair_as_sherpa(
        tmp_path / "unused.mat",
        spec_key="spectra",
        prop_key="properties",
        prop_names=[f"y{i}" for i in range(7)],
        x_title="Wavelength",
        x_units="nm",
        technique="NIR",
    )
    assert loaded.sample_axis.labels == ["S1", "S1", "S1"]
    # Keep the historical payload until a versioned source migration exists.
    # Even unique label copies do not establish declared observation identity.
    assert loaded.sample_axis.sample_table.get("sample_id") == ["S1", "S1", "S1"]


@pytest.mark.parametrize("grid", [[600.0, 600.0, 602.0], [600.0, 602.0, 601.0]])
def test_mcr_rejects_ambiguous_grid_order_even_when_truth_matches(grid):
    dataset = SherpaDataset(
        X=np.ones((2, 3)),
        feature_axis=SpectralAxis(values=grid, title="Wavenumber", units="cm-1"),
        extra={
            "ground_truth.spectra": [[1.0, 3.0, 2.0]],
            "ground_truth.spectra_x": grid,
            "ground_truth.spectra_x_title": "Wavenumber",
            "ground_truth.spectra_x_units": "cm-1",
        },
    )
    reasons = []
    assert _compare_mcr_spectra_to_truth(np.array([[1.0, 3.0, 2.0]]), dataset, unavailable_reasons=reasons) is None
    assert reasons == ["Spectral truth comparison unavailable: physical coordinates differ."]


@pytest.mark.parametrize("ids", [["S1"] * 20, [""] * 20])
@pytest.mark.asyncio
async def test_optional_comparison_identity_does_not_fail_embedded_target_pls(ids):
    rng = np.random.default_rng(2026)
    x = rng.normal(size=(20, 5))
    y = x[:, 0] + 0.1 * x[:, 1]
    source = SherpaDataset(
        X=x,
        target=y,
        sample_axis=SampleAxis(
            labels=[f"scan-{i}" for i in range(20)],
            sample_table={"sample_id": ids},
        ),
    )
    node = FittedPLSV2Node(node_id="pls", parameters={"n_components": 2})
    result = await node.execute(source)
    comparison = result.outputs["calibration_comparison"]
    assert comparison["metadata"]["sample_identity"] == "unavailable"
    assert "sample_ids" not in comparison["metadata"]
    assert len(comparison["data"]) == 20
    assert comparison["data"][0]["sample"] == "scan-0"
    from spectra_sherpa.app.lib.sample_identity import sample_ids

    with pytest.raises(ValueError, match="unique"):
        sample_ids(source)  # Actual identity consumers remain strict.


@pytest.mark.parametrize(
    "kwargs",
    [
        {"source_format": "eigenvector-dso"},
        {"source_format": "matlab-process-log"},
        {"identity_unavailable": True},
    ],
)
def test_legacy_or_explicitly_unavailable_identity_cannot_requalify(tmp_path, monkeypatch, kwargs):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    result = resolve_run_evidence(retained_run("A", **kwargs))
    assert not result.evaluations
    assert result.unavailable_reason


def test_genuine_typed_ids_equal_to_labels_remain_qualified_for_annotation():
    source = SherpaDataset(
        X=np.ones((3, 2)),
        sample_axis=SampleAxis(
            labels=["one", "two", "three"],
            sample_table={"sample_id": ["one", "two", "three"]},
        ),
    )
    comparison = build_regression_comparison([1, 2, 3], [1.1, 2.1, 3.1], role="calibration", sample_dataset=source)
    assert comparison["metadata"]["sample_ids"] == ["one", "two", "three"]
    assert comparison["metadata"]["sample_identity"] == "typed_sample_id"


@pytest.mark.parametrize("contradictory", [False, True])
def test_evaluator_legacy_origin_refusal_preserves_results_but_not_conflicting_ids(contradictory):
    from copy import deepcopy

    target = SherpaDataset(
        X=np.arange(4.0).reshape(-1, 1),
        sample_axis=SampleAxis(sample_table={"sample_id": ["a", "b", "c", "d"]}),
    )
    result = evaluate_regression_v2(target.X + 0.1, target)
    comparison = result.outputs["comparison"]
    before = deepcopy(comparison)
    source = SherpaDataset(
        X=np.ones((4, 2)),
        sample_axis=SampleAxis(
            sample_table={"sample_id": ["b", "a", "c", "d"] if contradictory else ["a", "b", "c", "d"]}
        ),
        source_identity=DatasetSourceIdentity(source_format="eigenvector-dso"),
    )
    receipt = {
        "role": "held_out_test",
        "qualification": "graph_verified",
        "population": ["split", "test"],
        "fitted_populations": [["split", "train"]],
    }
    if contradictory:
        with pytest.raises(ValueError, match="identities disagree"):
            qualify_evaluation_result(result, receipt, source_results={"split": {"X_test": source}})
        return
    qualify_evaluation_result(result, receipt, source_results={"split": {"X_test": source}})
    assert comparison["statistics"] == before["statistics"]
    assert comparison["data"] == [{**row, "role": "held_out_test"} for row in before["data"]]
    assert comparison["metadata"]["sample_identity"] == "unavailable"
    assert "sample_ids" not in comparison["metadata"]


def test_rebinding_cannot_erase_producer_identity_refusal():
    from copy import deepcopy

    from spectra_sherpa.app.services.dag.regression_comparison import bind_regression_sample_axis

    legacy = SherpaDataset(
        X=np.ones((3, 2)),
        sample_axis=SampleAxis(labels=["a", "b", "c"], sample_table={"sample_id": ["a", "b", "c"]}),
        source_identity=DatasetSourceIdentity(source_format="matlab-process-log"),
    )
    comparison = build_regression_comparison([1, 2, 3], [1.1, 2.1, 3.1], role="calibration", sample_dataset=legacy)
    before = deepcopy(comparison)
    generic = SherpaDataset(X=legacy.X, sample_axis=legacy.sample_axis.copy())
    bind_regression_sample_axis(comparison, generic)
    assert comparison == before
    assert comparison["metadata"]["sample_identity"] == "unavailable"
    assert "sample_ids" not in comparison["metadata"]


@pytest.mark.parametrize(
    "array, expected",
    [
        (np.array([[1.0, np.nan], [2.0, 3.0]]), "a6de65f9cd1e4e30201e7347e13e1aed6267ee5fb42a9a316924442854a2e1fa"),
        (np.array([["A"], ["B"]]), "5e4daa6fd14cba4e3ee9b6e09e18df9556f0c2e0c685b7b3fafbd23fc7f26829"),
        (np.array([1, 2, 3]), "9b608210261719aa44d067585746ea013de441afc0e43ac92a6f7cb58a50ad77"),
    ],
)
def test_shared_array_identity_preserves_pre_refactor_digests(array, expected):
    from spectra_sherpa.app.lib.array_identity import array_content_digest

    assert array_content_digest(array) == expected


@pytest.mark.parametrize(
    "operation, helper",
    [
        ("data.train_test_split", "array_identity"),
        ("model.fitted_pls", "comparison_identity"),
        ("diagnostics.regression_evaluator", "comparison_identity"),
        ("diagnostics.labeled_regression_evaluator", "comparison_identity"),
        ("selection.nested_cv", "comparison_identity"),
        ("output.plot", "comparison_identity"),
    ],
)
def test_extracted_helpers_remain_in_explicit_scientific_contract(operation, helper):
    import hashlib
    import importlib
    from pathlib import Path

    from spectra_sherpa.app.services.dag import node_registry

    contract = node_registry.get_metadata(operation).resolved_execution_contract()
    components = {item["component_id"]: item["digest"] for item in contract.payload["implementation_components"]}
    for name in (helper, "sample_identity"):
        module = importlib.import_module(f"spectra_sherpa.app.lib.{name}")
        assert components[module.__name__] == hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()


@pytest.mark.parametrize("origin", ["eigenvector-dso", "matlab-process-log"])
def test_renamed_and_mixed_legacy_origins_remain_explicitly_unqualified(origin):
    from spectra_sherpa.app.lib.comparison_identity import comparison_sample_ids

    source = SherpaDataset(
        X=np.ones((3, 2)),
        title="Renamed by user",
        sample_axis=SampleAxis(
            labels=["A", "B", "C"],
            sample_table={"sample_id": ["A", "B", "C"]},
        ),
        extra={"source_member_metadata": [{"source_identity": {"source_format": origin}}]},
    )
    ids, reason = comparison_sample_ids(source)
    assert ids is None and "identity-origin proof" in reason
