from __future__ import annotations

import json
from pathlib import Path

import pytest

from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.presentation_contract import (
    NodePresentationContract,
    ScientificPresentation,
    build_portable_presentation_manifest,
    build_scientific_presentation_census,
    describe_executed_presentations,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_PRESENTATION_CENSUS_PATH = _REPOSITORY_ROOT / "docs/evidence/scientific-presentation-census.json"


def test_pls_and_evaluator_publish_closed_renderer_neutral_presentations() -> None:
    pls = node_registry.get_metadata("model.fitted_pls").resolved_presentation_contract()
    evaluator = node_registry.get_metadata("diagnostics.regression_evaluator").resolved_presentation_contract()

    assert pls is not None
    assert pls.default_presentation == "calibration_fit"
    assert {item.presentation_id for item in pls.presentations} == {
        "calibration_fit",
        "scores",
        "loadings",
        "vip",
        "explained_variance",
        "coefficients",
        "model",
    }
    assert {item.presentation_id: item.kind for item in pls.presentations} == {
        "calibration_fit": "regression_comparison",
        "scores": "pls_scores",
        "loadings": "pls_loadings",
        "vip": "variable_profile",
        "explained_variance": "pls_explained_variance",
        "coefficients": "regression_coefficients",
        "model": "model_summary",
    }
    assert evaluator is not None
    assert evaluator.default_presentation == "held_out_comparison"
    assert {item.presentation_id for item in evaluator.presentations} == {"held_out_comparison", "metrics"}


def test_plsda_leads_one_curated_classification_fit_contract() -> None:
    plsda = node_registry.get_metadata("classification.plsda")
    contract = plsda.resolved_presentation_contract()

    assert plsda.presentation_contract is not None
    assert contract.default_presentation == "scores"
    assert {item.presentation_id: item.kind for item in contract.presentations} == {
        "scores": "plsda_scores",
        "loadings": "plsda_loadings",
        "vip": "variable_profile",
        "explained_variance": "pls_explained_variance",
        "coefficients": "regression_coefficients",
        "calibration_confusion": "confusion_matrix",
        "class_responses": "classification_responses",
        "metrics": "statistics_summary",
        "model": "classification_model",
    }


def test_pca_publishes_scientist_facing_scores_loadings_scree_and_diagnostics() -> None:
    pca = node_registry.get_metadata("model.pca").resolved_presentation_contract()

    assert pca.default_presentation == "scores"
    assert {item.presentation_id for item in pca.presentations} == {
        "scores",
        "loadings",
        "explained_variance",
        "diagnostics",
    }
    assert next(item for item in pca.presentations if item.presentation_id == "explained_variance").label == (
        "Explained Variance (Scree)"
    )
    diagnostics = next(item for item in pca.presentations if item.presentation_id == "diagnostics")
    assert diagnostics.kind == "t2_q_diagnostics"
    assert diagnostics.modes == ("plot", "table")
    assert {item.presentation_id: item.kind for item in pca.presentations} == {
        "scores": "pca_scores",
        "loadings": "pca_loadings",
        "explained_variance": "pca_explained_variance",
        "diagnostics": "t2_q_diagnostics",
    }


def test_outlier_screen_publishes_one_joint_diagnostic_view() -> None:
    outliers = node_registry.get_metadata("diagnostics.outliers").resolved_presentation_contract()

    assert outliers.default_presentation == "diagnostics"
    assert len(outliers.presentations) == 1
    diagnostics = outliers.presentations[0]
    assert diagnostics.kind == "t2_q_diagnostics"
    assert diagnostics.source_ports == ("T2", "Q", "flags")
    assert diagnostics.modes == ("plot", "table")


def test_presentation_contract_rejects_unknown_or_missing_source_ports() -> None:
    with pytest.raises(ValueError, match="unknown scientific presentation kind"):
        ScientificPresentation("bad", "Bad", "plotly_scatter", ("default",), ("plot",))

    contract = NodePresentationContract(
        default_presentation="summary",
        presentations=(ScientificPresentation("summary", "Summary", "metric_record", ("missing",), ("record",)),),
    )
    with pytest.raises(ValueError, match="unknown output ports"):
        contract.validate_ports({"default"})


def test_presentation_digest_changes_with_scientist_facing_identity() -> None:
    first = NodePresentationContract(
        default_presentation="summary",
        presentations=(ScientificPresentation("summary", "Metrics", "metric_record", ("default",), ("record",)),),
    )
    second = NodePresentationContract(
        default_presentation="summary",
        presentations=(
            ScientificPresentation("summary", "Held-out Metrics", "metric_record", ("default",), ("record",)),
        ),
    )
    assert first.digest != second.digest


def test_every_builtin_has_one_closed_presentation_authority() -> None:
    metadata_rows = node_registry.list_nodes()
    assert len(metadata_rows) == 101
    for metadata in metadata_rows:
        contract = metadata.resolved_presentation_contract()
        assert contract.presentations, metadata.node_type
        contract.validate_ports({port.name for port in metadata.output_ports})


def test_frontend_plot_renderer_authority_exactly_covers_live_plot_kinds() -> None:
    """A new plot kind cannot fall through to frontend shape heuristics."""

    package_root = Path(__file__).resolve().parents[1]
    authority = json.loads(
        (package_root / "frontend/src/utils/scientific-presentation-renderers.json").read_text(encoding="utf-8")
    )
    assert authority["schema_version"] == "spectrasherpa-scientific-presentation-renderers/1"
    declared = authority["plot_kinds"]
    live = {
        presentation.kind
        for metadata in node_registry.list_nodes()
        for presentation in metadata.resolved_presentation_contract().presentations
        if "plot" in presentation.modes
    }
    # Removed from the live Peak Finding ports, but retained run records still
    # need their original SalientFeatures renderer. No unreviewed extra kinds.
    assert set(declared) == live | {"salient_features"}
    for kind, renderer in declared.items():
        assert isinstance(renderer["strategy"], str) and renderer["strategy"]
        assert renderer["plots"], f"{kind} has no renderer option"
        assert all(set(item) == {"key", "label"} and item["key"] and item["label"] for item in renderer["plots"])


def test_frontend_does_not_reintroduce_node_identity_presentation_registries() -> None:
    """Scientist-facing behavior must follow presentation kinds, not node-name lists."""

    frontend_source = Path(__file__).resolve().parents[1] / "frontend/src"
    retired_authority = frontend_source / "utils/nodeCapabilities.ts"
    assert not retired_authority.exists()

    forbidden_markers = {
        "REGRESSION_RESULT_NODE_TYPES",
        "isRegressionResultNode",
    }
    offenders = {
        str(path.relative_to(frontend_source)): sorted(
            marker for marker in forbidden_markers if marker in path.read_text(encoding="utf-8")
        )
        for path in frontend_source.rglob("*")
        if path.suffix in {".ts", ".vue"}
    }
    assert not {path: markers for path, markers in offenders.items() if markers}


def test_live_presentation_census_matches_checked_authority() -> None:
    live = build_scientific_presentation_census(node_registry.list_nodes())
    checked = json.loads(_PRESENTATION_CENSUS_PATH.read_text(encoding="utf-8"))

    assert live == checked
    assert checked["aggregates"]["registered_nodes"] == 101
    assert checked["aggregates"]["explicit_contracts"] == 11
    assert checked["aggregates"]["derived_contracts"] == 90
    assert all(row["contract"]["presentations"] for row in checked["nodes"])


def test_unclassified_ports_are_disposed_but_never_presented() -> None:
    census = build_scientific_presentation_census(node_registry.list_nodes())
    for node in census["nodes"]:
        source_ports = {
            source for presentation in node["contract"]["presentations"] for source in presentation["source_ports"]
        }
        for port in node["output_port_dispositions"]:
            if port["scientific_kind"] == "unclassified":
                assert port["disposition"] == "no_scientist_view_unclassified"
                assert port["port_name"] not in source_ports


def test_executed_presentations_bind_materialized_content_categories() -> None:
    metadata = node_registry.get_metadata("model.fitted_pls")
    descriptors = {
        "vip_scores": {
            "content_categories": ["model_diagnostics", "variable_level_results"],
        },
        "explained_variance": {
            "content_categories": ["model_diagnostics"],
        },
    }

    record = describe_executed_presentations(metadata, descriptors)

    assert record["contract_digest"] == metadata.resolved_presentation_contract().digest
    assert [item["presentation_id"] for item in record["presentations"]] == ["vip", "explained_variance"]
    assert record["presentations"][0]["content_categories"] == [
        "model_diagnostics",
        "variable_level_results",
    ]


def test_portable_manifest_is_derived_from_registered_application_nodes() -> None:
    manifest = build_portable_presentation_manifest([{"node_id": "model", "operation_id": "model.apply_fitted_pls"}])

    assert manifest["schema_version"] == "spectrasherpa-portable-presentation-manifest/1"
    assert len(manifest["manifest_digest"]) == 64
    assert manifest["nodes"][0]["operation_id"] == "model.apply_fitted_pls"
    assert manifest["nodes"][0]["presentations"]
