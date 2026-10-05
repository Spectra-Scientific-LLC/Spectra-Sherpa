from __future__ import annotations

import importlib
import json

import numpy as np
import pytest

import spectra_sherpa.sdk as ss
from spectra_sherpa.examples import canonical_workflow, ipls_selection, native_pca


def test_deployment_contract_imports_from_a_clean_public_module() -> None:
    deployment = importlib.import_module("spectra_sherpa.sdk.deployment")
    assert deployment.DEPLOYMENT_INPUT_SCHEMA == "spectrasherpa.deploy-input/1"


def test_shipped_canonical_workflow_executes_persists_and_reopens(tmp_path) -> None:
    summary = canonical_workflow.run(tmp_path)

    workflow_manifest = json.loads((tmp_path / "canonical-workflow.json").read_text(encoding="utf-8"))
    plot = json.loads((tmp_path / "canonical-plot.json").read_text(encoding="utf-8"))
    reopened = ss.workflow.WorkflowSpec.from_dict(workflow_manifest)
    assert reopened.workflow_digest == summary["workflow_digest"]
    assert summary["completed_nodes"] == ["normalize", "plot", "spectra"]
    assert summary["plot_traces"] == 8
    assert len(plot["data"]) == 8
    assert plot["layout"]["title"] == "Canonical SDK quickstart"


def test_shipped_ipls_journey_uses_current_canonical_result() -> None:
    summary = ipls_selection.run()

    assert summary["method"] == "iPLS"
    assert summary["n_selected"] == 4
    assert summary["n_total"] == 24
    assert summary["beats_global_rmsecv"] is True
    assert summary["best_rmsecv"] < summary["global_rmsecv"]
    assert len(summary["workflow_digest"]) == 64


def test_ipls_convenience_rejects_ambiguous_targets() -> None:
    X = np.ones((8, 6))
    with pytest.raises(ValueError, match="one target value per sample"):
        ss.selection.ipls(X, np.ones((8, 2)), n_intervals=2, max_components=1, cv_folds=2)
    with pytest.raises(ValueError, match="one target value per sample"):
        ss.selection.ipls(X, np.ones(7), n_intervals=2, max_components=1, cv_folds=2)


def test_shipped_native_pca_journey_executes_current_node() -> None:
    summary = native_pca.run()

    assert summary["model_type"] == "PCA"
    assert summary["n_components"] == 2
    assert summary["scores_shape"] == [12, 2]
    assert summary["loadings_shape"] == [2, 32]
