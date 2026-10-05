"""Repeated predictions never become an inflated sample denominator."""

import json

import numpy as np
import pytest

from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import _nested_cv_dispatch


@pytest.mark.parametrize("grouped", [False, True])
def test_repeat_identity_spread_and_nonpooled_population(grouped):
    rng = np.random.default_rng(19)
    x = rng.normal(size=(36, 6))
    y = x[:, 0] + rng.normal(size=36) * 0.2
    groups = np.repeat(np.arange(12), 3) if grouped else None
    kwargs = dict(
        producer_node_id="nested",
        selection_method="none",
        n_components=2,
        cv_folds=3,
        vip_threshold=1.0,
        coef_threshold=0.0,
        random_seed=42,
        groups=groups,
        n_repeats=3,
    )
    outputs, _ = _nested_cv_dispatch(x, y, **kwargs)
    record = outputs["cv_metrics"]
    assert record["n_rows"] == 36
    assert record["n_repeats"] == 3
    assert "rmsecv" not in record
    assert "oof_evidence" not in outputs
    repeats = outputs["repeated_evidence"]["repeats"]
    assert len(set(r["seed"] for r in repeats)) == 3
    assert len(set(r["outputs"]["cv_metrics"]["split_plan_digest"] for r in repeats)) > 1
    values = [r["outputs"]["cv_metrics"]["rmsecv"] for r in repeats]
    assert record["distributions"]["rmsecv"]["mean"] == pytest.approx(np.mean(values))
    assert record["distributions"]["rmsecv"]["std_across_repeats"] == pytest.approx(np.std(values, ddof=1))
    for repeat in repeats:
        plan = repeat["outputs"]["cv_metrics"]["split_plan"]
        assert sorted(i for f in plan["folds"] for i in f["test"]) == list(range(36))
        if grouped:
            for fold in plan["folds"]:
                assert not set(groups[fold["train"]]) & set(groups[fold["test"]])
    replay, _ = _nested_cv_dispatch(x, y, **kwargs)
    assert json.dumps(outputs, sort_keys=True) == json.dumps(replay, sort_keys=True)


@pytest.mark.asyncio
async def test_repeated_export_replays_same_grouped_evidence():
    from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import NestedCVNode

    rng = np.random.default_rng(3)
    x = rng.normal(size=(36, 6))
    y = x[:, 0]
    groups = np.repeat(np.arange(12), 3)
    node = NestedCVNode("repeat-export", {"selection_method": "none", "n_components": 2, "cv_folds": 3, "n_repeats": 2})
    result = await node.execute(X=x, y=y, groups=groups)
    namespace = {"X": x, "y": y, "groups": groups, "results": {}}
    exec("\n".join(node.generate_python({"X": "X", "y": "y", "groups": "groups"}, indent="")), namespace)
    assert namespace["results"]["repeat-export"] == result.outputs
