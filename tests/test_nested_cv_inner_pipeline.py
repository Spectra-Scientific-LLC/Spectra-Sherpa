"""Inner validation targets must never reach variable selection or fitting."""

import numpy as np
import pytest
from sklearn.model_selection import KFold

from spectra_sherpa.app.services.dag.nodes.selection import nested_cv_node as nested


@pytest.mark.parametrize("method", ["none", "vip", "coef_abs"])
def test_inner_selector_never_receives_validation_targets(monkeypatch, method):
    rng = np.random.default_rng(25)
    x = rng.normal(size=(30, 8))
    y = x[:, 0] + 0.2 * rng.normal(size=30)
    tr, va = next(KFold(3, shuffle=True, random_state=42).split(x))
    original = nested._select_variables_inner
    captured = []

    def selector(matrix, target, *args, **kwargs):
        mask = original(matrix, target, *args, **kwargs)
        captured.append((matrix.copy(), target.copy(), mask.copy()))
        return mask

    monkeypatch.setattr(nested, "_select_variables_inner", selector)
    nested._choose_pls_components_inner_cv(
        x, y, max_components=2, random_seed=42, selection_method=method, vip_threshold=0.1
    )
    first = captured[0]
    captured.clear()
    changed = y.copy()
    changed[va] += 100
    nested._choose_pls_components_inner_cv(
        x, changed, max_components=2, random_seed=42, selection_method=method, vip_threshold=0.1
    )
    second = captured[0]
    np.testing.assert_array_equal(first[0], x[tr])
    np.testing.assert_array_equal(first[1], y[tr])
    for a, b in zip(first, second):
        np.testing.assert_array_equal(a, b)


def test_impossible_candidate_is_not_scored_on_only_successful_folds(monkeypatch):
    monkeypatch.setattr(nested, "_select_variables_inner", lambda x, *a, **k: np.zeros(x.shape[1], dtype=bool))
    with pytest.raises(ValueError, match="every inner fold"):
        nested._choose_pls_components_inner_cv(np.ones((12, 4)), np.arange(12.0), max_components=2, random_seed=42)


def test_outer_refit_adapts_components_and_records_both_counts(monkeypatch):
    rng = np.random.default_rng(6)
    x = rng.normal(size=(24, 5))
    y = x[:, 0] + 0.2 * x[:, 1]
    monkeypatch.setattr(nested, "_choose_pls_components_inner_cv", lambda *a, **k: 3)
    monkeypatch.setattr(nested, "_select_variables_inner", lambda *a, **k: np.array([True, True, False, False, False]))
    result, _ = nested._nested_cv_dispatch(
        x,
        y,
        producer_node_id="refit",
        selection_method="vip",
        n_components=3,
        cv_folds=3,
        vip_threshold=1.0,
        coef_threshold=0.0,
        random_seed=42,
    )
    assert result["cv_metrics"]["per_fold_inner_chosen_components"] == [3, 3, 3]
    assert result["cv_metrics"]["per_fold_n_components"] == [2, 2, 2]


def test_selector_budget_refuses_before_any_scientific_fitting(monkeypatch):
    def unexpected(*a, **k):
        raise AssertionError("selector ran before budget check")

    monkeypatch.setattr(nested, "_select_variables_inner", unexpected)
    with pytest.raises(ValueError, match="3100 selector calls"):
        nested._nested_cv_dispatch(
            np.ones((30, 15)),
            np.arange(30.0),
            producer_node_id="cost",
            selection_method="cars",
            n_components=10,
            cv_folds=5,
            n_repeats=20,
            vip_threshold=1.0,
            coef_threshold=0.0,
            random_seed=42,
        )
