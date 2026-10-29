"""Retain the exact last manual-PLS campaign profile for read-only inspection."""

from copy import deepcopy

import pytest

from spectra_sherpa.app.services.dag.executor_types import WorkflowNode
from spectra_sherpa.app.services.dag.historical_contracts import HistoricalReconstructionContext
from spectra_sherpa.app.services.dag.validation_graph import ValidationGraphError, assert_admitted_validation_graph
from spectra_sherpa.core.contract_compatibility import inspection_predecessor_catalog
from spectra_sherpa.sdk.canonical_execution_evidence import (
    CanonicalExecutionEvidenceError,
    _validate_first_profile_parameters,
)

PROFILE = "eec02d6f13ac5b5fa1af45dfea754b0c054faf1c92d75cf9af88ec74ac066cdb"


def test_preautomatic_profile_retains_curve_controls_and_exact_historical_identity():
    from pathlib import Path

    from spectra_sherpa.app.types import type_registry

    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).parents[1] / "src/spectra_sherpa/app/types")
    context = HistoricalReconstructionContext(PROFILE)
    assert context.profile().digest == PROFILE
    graph = context.reconstruct(
        [
            WorkflowNode(
                "model",
                "model.fitted_pls",
                {
                    "n_components": 4,
                    "component_selection_rule": "one_standard_error",
                    "component_curve_max": 8,
                    "component_cv_folds": 4,
                },
            )
        ],
        [],
    )
    node = graph.nodes[0]
    assert node.parameters["n_components"] == 4
    assert node.parameters["component_cv_folds"] == 4
    assert node.parameters["component_curve_max"] == 8
    assert node.parameters["component_selection_rule"] == "one_standard_error"
    assert "component_fit_mode" not in node.parameters
    assert node.contract.digest == inspection_predecessor_catalog(PROFILE)["contracts"]["model.fitted_pls"]["digest"]
    assert context.graph(graph.as_dict()).as_dict() == graph.as_dict()
    _validate_first_profile_parameters(
        dict(node.parameters), operation_id="model.fitted_pls", historical_context=context
    )
    with pytest.raises(ValidationGraphError):
        assert_admitted_validation_graph(graph)
    forged = deepcopy(graph.as_dict())
    forged["nodes"][0]["parameters"]["component_fit_mode"] = "one_standard_error"
    with pytest.raises(ValidationGraphError):
        context.graph(forged)
    with pytest.raises(CanonicalExecutionEvidenceError, match="post-profile controls"):
        _validate_first_profile_parameters(
            {**node.parameters, "component_fit_mode": "manual"},
            operation_id="model.fitted_pls",
            historical_context=context,
        )


def test_unknown_profile_is_not_implicitly_admitted():
    with pytest.raises(ValueError, match="unrecognized historical"):
        inspection_predecessor_catalog("a" * 64)
