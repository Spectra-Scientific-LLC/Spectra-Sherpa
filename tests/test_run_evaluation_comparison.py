from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.schemas.execution_runs import EvaluationSelection
from spectra_sherpa.app.schemas.run_evidence import OutputEvidence
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.services.dag.out_of_fold_evidence import (
    OUT_OF_FOLD_EVIDENCE_TYPE,
    build_out_of_fold_evidence,
)
from spectra_sherpa.app.services.run_evaluation_comparison import qualified_evaluation_comparison


@pytest.fixture(autouse=True)
def output_store(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))


def saved_run(identifier, *, delta=0.1, changed_input=False, folds=None):
    node = f"different-node-{identifier}"
    y = [1.0, 2.0, 3.0, 4.0]
    record = build_out_of_fold_evidence(
        producer_node_id=node,
        task_type="regression",
        observations=y,
        predictions=[v + delta for v in y],
        split_plan={
            "schema_version": "spectra-split-plan/1",
            "method": "kfold",
            "n_samples": 4,
            "grouped": False,
            "folds": folds
            or [
                {"train": [0, 1], "test": [2, 3]},
                {"train": [2, 3], "test": [0, 1]},
            ],
        },
    )
    outputs = {
        node: {"oof_evidence": record},
        "input": {
            "X": SherpaDataset(
                X=np.array([[i + int(changed_input), i * 2] for i in range(4)], dtype=float),
                extra={"source_collection": {"source_manifest_sha256": "a" * 64}},
            ),
            "y": y,
        },
        "__workflow__": {
            "definition": {
                "schema_version": 1,
                "nodes": [{"node_id": node, "node_type": "selection.nested_cv", "parameters": {"seed": identifier}}],
                "edges": [
                    {"from_node_id": "input", "from_output": name, "to_node_id": node, "to_input": name}
                    for name in ("X", "y")
                ],
            }
        },
    }
    return SimpleNamespace(
        id=identifier,
        user_id=1,
        evidence_completeness=retention.retain_run_outputs(1, outputs, {}),
        diagnostics={
            "_scientific_values": {node: {"oof_evidence": {"type_ref": OUT_OF_FOLD_EVIDENCE_TYPE}}},
            "_scientific_presentations": {
                node: {
                    "contract": {
                        "schema_version": "spectrasherpa-node-presentation/1",
                        "presentations": [
                            {
                                "presentation_id": "oof_evidence",
                                "kind": "out_of_fold_evidence",
                                "source_ports": ["oof_evidence"],
                            }
                        ],
                    }
                }
            },
        },
    )


def test_exact_common_evaluation_allows_different_node_ids_and_predictions():
    pairs, metrics = qualified_evaluation_comparison([saved_run(1), saved_run(2, delta=0.2)])
    assert pairs[0].state == "comparable"
    assert metrics["qualified_cv.rmse"] == pytest.approx({"1": 0.1, "2": 0.2})
    assert "qualified_cv.r2" in metrics


def test_one_incompatible_member_disables_ranking_for_the_selected_set():
    pairs, metrics = qualified_evaluation_comparison(
        [
            saved_run(1),
            saved_run(2),
            saved_run(3, changed_input=True),
        ]
    )
    assert [pair.state for pair in pairs] == ["comparable", "incompatible", "incompatible"]
    assert metrics == {}


def test_explicit_pairing_selects_one_of_multiple_saved_evaluations():
    left, right, second = saved_run(1), saved_run(2), saved_run(3, delta=0.3)
    right.evidence_completeness["outputs"]["different-node-3"] = second.evidence_completeness["outputs"][
        "different-node-3"
    ]
    for key in ("_scientific_values", "_scientific_presentations"):
        right.diagnostics[key].update(second.diagnostics[key])

    def definition(run):
        return retention.read_output(
            1, OutputEvidence.model_validate(run.evidence_completeness["outputs"]["__workflow__"]["definition"])
        )

    first, extra = definition(right), definition(second)
    first["nodes"].extend(extra["nodes"])
    first["edges"].extend(extra["edges"])
    right.evidence_completeness["outputs"]["__workflow__"]["definition"] = retention.retain_output(
        1, first
    ).model_dump()
    pairs, metrics = qualified_evaluation_comparison([left, right])
    assert pairs[0].requires_pairing and len(pairs[0].right) == 2 and not metrics
    pairs, metrics = qualified_evaluation_comparison(
        [left, right], {2: EvaluationSelection(node_id="different-node-3", presentation_id="oof_evidence")}
    )
    assert pairs[0].state == "comparable"
    assert metrics["qualified_cv.rmse"]["2"] == pytest.approx(0.3)
    pairs, metrics = qualified_evaluation_comparison(
        [left, right], {2: EvaluationSelection(node_id="not-saved", presentation_id="oof_evidence")}
    )
    assert pairs[0].state == "insufficient_evidence" and not metrics


def test_classification_ranking_limit_is_explicit():
    left, right = saved_run(1), saved_run(2)
    right.diagnostics["_scientific_values"] = {}
    record = right.diagnostics["_scientific_presentations"]["different-node-2"]
    record["contract"]["presentations"][0]["kind"] = "classification_model"
    pairs, metrics = qualified_evaluation_comparison([left, right])
    assert not metrics
    assert "Classification evaluation ranking is not yet supported" in pairs[0].reason


@pytest.mark.parametrize("changed", ["input", "folds"])
def test_different_population_or_folds_cannot_rank(changed):
    right = saved_run(
        2,
        changed_input=changed == "input",
        folds=([{"train": [0, 2], "test": [1, 3]}, {"train": [1, 3], "test": [0, 2]}] if changed == "folds" else None),
    )
    pairs, metrics = qualified_evaluation_comparison([saved_run(1), right])
    assert pairs[0].state == "incompatible"
    assert metrics == {}


@pytest.mark.parametrize("damage", ["missing", "corrupt", "reduced", "ambiguous", "no_target"])
def test_missing_or_untrusted_evidence_never_uses_metric_preview(damage):
    left, right = saved_run(1), saved_run(2)
    right.results_summary = {"rmse": 0.00001}
    item = right.evidence_completeness["outputs"]["different-node-2"]["oof_evidence"]
    if damage == "missing":
        (retention._user_directory(1) / f"{item['sha256']}.json").unlink()
    elif damage == "corrupt":
        (retention._user_directory(1) / f"{item['sha256']}.json").write_text("{}")
    elif damage == "reduced":
        item["state"] = "reduced"
        item["reason"] = "preview"
    elif damage == "ambiguous":
        right.diagnostics["_scientific_values"]["second"] = right.diagnostics["_scientific_values"]["different-node-2"]
    else:
        del right.evidence_completeness["outputs"]["input"]["y"]
    pairs, metrics = qualified_evaluation_comparison([left, right])
    assert pairs[0].state == "insufficient_evidence"
    assert pairs[0].reason
    assert metrics == {}


def test_exact_cv_reports_denominator_and_folds_without_external_test_claim():
    from spectra_sherpa.app.services.run_validation_summary import validation_summary

    def text(summary):
        return "\n".join(row["label"] + ": " + row["value"] for row in summary["rows"])

    run = saved_run(1)
    report = text(validation_summary(run, None))
    assert "Verified metric denominator (different-node-1): 4" in report
    assert "Fold 1 (different-node-1): 2 training rows; 2 validation rows" in report
    assert "not an external held-out test" in report
    # This fixture retains predictions, not workflow-computed statistics.
    # Reporting may count rows but must not reconstruct regression metrics.
    assert "Cross-validation rmse:" not in report
