"""Specimen separation is preserved through nested tuning and retained evidence."""

import copy

import numpy as np
import pytest

from spectra_sherpa.app.services.dag import out_of_fold_evidence as evidence
from spectra_sherpa.app.services.dag.nodes.selection import nested_cv_node as nested


def inputs():
    rng = np.random.default_rng(7)
    x = rng.normal(size=(48, 8))
    return x, x[:, 0] + rng.normal(size=48) * 0.1, np.repeat(np.arange(12), 4)


def run(x, y, groups):
    return nested._nested_cv_dispatch(
        x,
        y,
        groups=groups,
        producer_node_id="nested",
        selection_method="none",
        n_components=3,
        cv_folds=3,
        vip_threshold=1.0,
        coef_threshold=0.0,
        random_seed=42,
    )[0]


def test_outer_and_inner_folds_keep_whole_groups(monkeypatch):
    x, y, groups = inputs()
    original = nested.sdk_validate.make_split_plan
    plans = []

    def record(n, **kwargs):
        plan = original(n, **kwargs)
        plans.append((plan, kwargs.get("groups")))
        return plan

    monkeypatch.setattr(nested.sdk_validate, "make_split_plan", record)
    result = run(x, y, groups)
    assert len(plans) == 4
    for plan, identities in plans:
        assert identities is not None
        for fold in plan.folds:
            assert not set(identities[fold.train]) & set(identities[fold.test])
    plan = result["cv_metrics"]["split_plan"]
    assert plan["groups"] == groups.tolist()
    assert plan["grouped"] is True


def test_retained_group_evidence_rejects_forged_membership():
    x, y, groups = inputs()
    result = run(x, y, groups)
    payload = copy.deepcopy(result["cv_metrics"]["split_plan"])
    payload = {k: payload[k] for k in ("schema_version", "method", "n_samples", "grouped", "folds", "groups")}
    evidence._normalized_split_plan(payload, n_samples=len(y))
    payload["groups"] = [0] * len(y)
    with pytest.raises(ValueError, match="leaks group"):
        evidence._normalized_split_plan(payload, n_samples=len(y))


@pytest.mark.parametrize("bad", [[None] * 48, [float("nan")] * 48, [1] * 47])
def test_missing_or_misaligned_groups_are_not_silently_ignored(bad):
    x, y, _ = inputs()
    with pytest.raises(ValueError):
        run(x, y, bad)


@pytest.mark.asyncio
async def test_existing_workflow_ignores_attached_single_group_unless_chosen(monkeypatch):
    from spectra_sherpa.app.services.dag.nodes.data import split_planner

    x, y, _ = inputs()
    calls = []

    def attached(_source):
        calls.append(True)
        return np.repeat("instrument-1", len(y))

    monkeypatch.setattr(split_planner, "bind_split_groups", attached)
    node = nested.NestedCVNode("legacy", {"selection_method": "none", "n_components": 2, "cv_folds": 3})
    result = await node.execute(X=x, y=y)
    assert calls == []
    assert result.outputs["cv_metrics"]["population_scope"] == "row_wise"
    assert result.diagnostics["group_boundary"] == "row_wise_no_group_protection"
    grouped = nested.NestedCVNode(
        "chosen", {"selection_method": "none", "n_components": 2, "cv_folds": 3, "group_source": "attached"}
    )
    with pytest.raises(ValueError, match="distinct groups"):
        await grouped.execute(X=x, y=y)
    assert calls == [True]


@pytest.mark.asyncio
async def test_explicit_group_choice_exports_and_reports_same_boundary():
    x, y, groups = inputs()
    node = nested.NestedCVNode("groups", {"selection_method": "none", "n_components": 2, "cv_folds": 3})
    result = await node.execute(X=x, y=y, groups=groups)
    assert result.diagnostics["group_boundary"] == "whole_groups_outer_and_inner"
    namespace = {"X": x, "y": y, "groups": groups, "results": {}}
    exec("\n".join(node.generate_python({"X": "X", "y": "y", "groups": "groups"}, indent="")), namespace)
    assert namespace["results"]["groups"] == result.outputs
