"""System gate: one current DAG vocabulary, with no prototype aliases."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from spectra_sherpa.app.core.template_loader import TemplateLoader
from spectra_sherpa.app.services.dag.node_base import node_registry

_RETIRED = {
    "data.my_dataset",
    "data.source",
    "diagnostics.holdout_evaluation",
    "model.pls",
    "model.pls_predict",
    "selection.sample_partition",
}
_REPLACEMENTS = {
    "data.file_load",
    "data.train_test_split",
    "diagnostics.regression_evaluator",
    "model.apply_fitted_pls",
    "model.fitted_pls",
}


def test_registry_exposes_replacements_and_no_prototype_aliases() -> None:
    import spectra_sherpa.app.services.dag.nodes  # noqa: F401

    registered = {metadata.node_type for metadata in node_registry.list_nodes()}
    assert registered.isdisjoint(_RETIRED)
    assert _REPLACEMENTS <= registered

    for node_type in sorted(_RETIRED):
        with pytest.raises(KeyError, match="Unknown node type"):
            node_registry.create_node(node_type, "retired", {})


def test_shipped_templates_use_no_prototype_node_identity() -> None:
    templates = TemplateLoader().load_all()
    used = {str(node["node_type"]) for template in templates for node in template["template_data"]["nodes"]}
    assert used.isdisjoint(_RETIRED)


def test_current_managed_harness_profile_uses_only_canonical_replacements() -> None:
    """The active managed optimization profile is derived from canonical registry contracts."""

    from spectra_sherpa.app.services.dag.managed_optimization_profile import managed_optimization_profile

    operation_ids = managed_optimization_profile().operation_ids
    assert operation_ids.isdisjoint(_RETIRED)
    assert "model.fitted_pls" in operation_ids


def test_frontend_source_references_no_prototype_identity() -> None:
    """Scientist-facing code must not silently retain branches for removed nodes."""

    package_root = Path(__file__).resolve().parents[1]
    roots = (package_root / "frontend/src",)
    quoted_retired = re.compile(
        r"(?P<quote>['\"`])(?:" + "|".join(re.escape(value) for value in sorted(_RETIRED)) + r")(?P=quote)"
    )
    offenders: list[str] = []
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix not in {".js", ".ts", ".vue"}:
                continue
            if quoted_retired.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(package_root)))

    assert offenders == []
