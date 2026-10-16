"""Exact scope, model binding, and null-protocol checks for PLS-DA random labels."""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.cross_decomposition import PLSRegression
from sklearn.metrics import balanced_accuracy_score
from sklearn.model_selection import StratifiedKFold

from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset
from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import (
    _native_plsda_fit,
    _plsda_scientific_core,
)
from spectra_sherpa.app.services.dag.nodes.classification.plsda_permutation import response_permutation_evidence
from spectra_sherpa.app.services.dag.nodes.classification.plsda_permutation_node import (
    PLSDAPermutationNode,
    _permutation_outputs,
)
from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_target_dataset


def _cohort() -> tuple[np.ndarray, np.ndarray]:
    generator = np.random.default_rng(55)
    labels = np.asarray(["A"] * 15 + ["B"] * 15)
    matrix = generator.normal(size=(30, 5))
    matrix[labels == "B", 0] += 3.0
    return matrix, labels


def _fit(matrix: np.ndarray, dummy: np.ndarray, classes: np.ndarray, count: int, scale: bool):
    return _native_plsda_fit(matrix, dummy, classes, n_components=count, scale=scale)[0]


def test_permutation_repeats_component_search_and_retains_exact_model_binding() -> None:
    matrix, labels = _cohort()
    state = _plsda_scientific_core(matrix, labels, parameters={"n_components": 2, "scale": False})[
        "artifact"
    ].to_fitted_state()
    settings = {"permutations": 19, "folds": 3, "maximum_components": 2, "seed": 42}
    evidence = _permutation_outputs(matrix, labels, state, parameters=settings)
    repeated = _permutation_outputs(matrix, labels, state, parameters=settings)
    assert evidence == repeated
    assert evidence["status"] == "complete"
    assert evidence["permutations_successful"] == len(evidence["null"]) == 19
    assert evidence["p_value"] == (1 + evidence["exceedances"]) / 20
    assert evidence["saved_model_components"] == 2
    assert all(1 <= row["selected_components"] <= 2 for row in evidence["null"])
    assert evidence["cv_anova"]["status"] == "unavailable"
    assert "independent" in evidence["interpretation_limit"]

    changed = matrix.copy()
    changed[0, 0] += 0.01
    with pytest.raises(ValueError, match="not fitted from this exact calibration cohort"):
        _permutation_outputs(changed, labels, state, parameters=settings)


def test_null_distribution_matches_independent_sklearn_cv_reference() -> None:
    """Check every Monte Carlo score against a separate PLS implementation."""

    matrix, labels = _cohort()
    evidence = response_permutation_evidence(
        matrix,
        labels,
        groups=None,
        blocks=None,
        model_state_sha256="a" * 64,
        saved_components=2,
        components=2,
        folds=3,
        permutations=19,
        seed=42,
        scale=False,
        fit_model=_fit,
    )

    def independent_score(response: np.ndarray) -> tuple[float, int]:
        classes = np.unique(response)
        dummy = (response[:, None] == classes[None, :]).astype(float)
        predictions = np.empty((2, len(response)), dtype=response.dtype)
        splitter = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
        for train, test in splitter.split(matrix, response):
            for components in (1, 2):
                fitted = PLSRegression(n_components=components, scale=False).fit(matrix[train], dummy[train])
                predictions[components - 1, test] = classes[np.argmax(fitted.predict(matrix[test]), axis=1)]
        scores = [balanced_accuracy_score(response, row) for row in predictions]
        selected = min(range(2), key=lambda index: (-scores[index], index))
        return float(scores[selected]), selected + 1

    generator = np.random.default_rng(42)
    observed, chosen = independent_score(labels)
    null = [independent_score(generator.permutation(labels)) for _ in range(19)]
    assert evidence["observed"] == pytest.approx(observed)
    assert evidence["observed_reselected_components"] == chosen
    assert [row["balanced_accuracy"] for row in evidence["null"]] == pytest.approx([score for score, _ in null])
    assert [row["selected_components"] for row in evidence["null"]] == [count for _, count in null]
    assert evidence["exceedances"] == sum(score >= observed for score, _ in null)
    assert evidence["p_value"] == pytest.approx((1 + evidence["exceedances"]) / 20)


def test_grouped_permutations_preserve_blocks_and_refuse_unsafe_designs() -> None:
    generator = np.random.default_rng(72)
    labels = np.asarray(["A"] * 12 + ["B"] * 12 + ["A"] * 12 + ["B"] * 12)
    matrix = generator.normal(size=(48, 4))
    matrix[labels == "B", 0] += 2.0
    groups = np.repeat(np.arange(24), 2)
    blocks = np.repeat(["instrument-1", "instrument-2"], 24)
    evidence = response_permutation_evidence(
        matrix,
        labels,
        groups=groups,
        blocks=blocks,
        model_state_sha256="a" * 64,
        saved_components=1,
        components=1,
        folds=2,
        permutations=19,
        seed=5,
        scale=False,
        fit_model=_fit,
    )
    assert evidence["n_units"] == 24
    assert evidence["n_blocks"] == 2
    assert evidence["permutations_successful"] == 19
    with pytest.raises(ValueError, match="cannot cross exchangeability blocks"):
        crossed = blocks.copy()
        crossed[1] = "instrument-2"
        response_permutation_evidence(
            matrix,
            labels,
            groups=groups,
            blocks=crossed,
            model_state_sha256="a" * 64,
            saved_components=1,
            components=1,
            folds=2,
            permutations=19,
            seed=5,
            scale=False,
            fit_model=_fit,
        )


def test_cancelled_permutation_returns_no_partial_evidence() -> None:
    matrix, labels = _cohort()
    with pytest.raises(InterruptedError, match="no partial evidence"):
        response_permutation_evidence(
            matrix,
            labels,
            groups=None,
            blocks=None,
            model_state_sha256="b" * 64,
            saved_components=1,
            components=1,
            folds=3,
            permutations=19,
            seed=5,
            scale=False,
            fit_model=_fit,
            cancelled=lambda: True,
        )


def test_small_cohort_and_nonexchangeable_blocks_are_refused_before_scoring() -> None:
    matrix, labels = _cohort()
    common = {
        "groups": None,
        "model_state_sha256": "c" * 64,
        "saved_components": 1,
        "components": 1,
        "folds": 3,
        "permutations": 19,
        "seed": 42,
        "scale": False,
        "fit_model": _fit,
    }
    with pytest.raises(ValueError, match="12–500"):
        response_permutation_evidence(matrix[:11], labels[:11], blocks=None, **common)
    with pytest.raises(ValueError, match="too few class-exchangeable units"):
        response_permutation_evidence(
            matrix,
            labels,
            blocks=["instrument-a"] * 15 + ["instrument-b"] * 15,
            **common,
        )


def test_exchangeability_blocks_require_verified_sample_table_row_identity() -> None:
    generator = np.random.default_rng(91)
    labels = np.asarray(["A", "B"] * 15)
    matrix = generator.normal(size=(30, 5))
    matrix[labels == "B", 0] += 2.0
    sample_ids = [f"specimen-{index}" for index in range(30)]
    source = SherpaDataset(
        X=matrix,
        sample_axis=SampleAxis(
            labels=sample_ids,
            sample_table={
                "sample_id": sample_ids,
                "class": labels.tolist(),
                "instrument": ["one"] * 15 + ["two"] * 15,
            },
        ),
        extra={
            "source_collection": {
                "manifest_digest": "a" * 64,
                "collection_definition_sha256": "b" * 64,
                "scientific_collection_sha256": "c" * 64,
            }
        },
    )
    attached = attach_target_dataset(
        source,
        None,
        target_type="categorical",
        node_id="attach",
        target_source="sample_table_column",
        target_column="class",
    )
    state = _plsda_scientific_core(attached, None, parameters={"n_components": 1, "scale": False})[
        "artifact"
    ].to_fitted_state()
    settings = {"permutations": 19, "folds": 2, "maximum_components": 1, "seed": 5, "block_column": "instrument"}
    evidence = _permutation_outputs(attached, None, state, parameters=settings)
    assert evidence["n_blocks"] == 2
    assert evidence["exchangeability_block_column"] == "instrument"
    changed_axis = attached.sample_axis
    assert changed_axis is not None and changed_axis.sample_table is not None
    changed_axis.sample_table["instrument"].reverse()
    attached.sample_axis = changed_axis
    with pytest.raises(ValueError, match="binding|projection|digest|sample table"):
        _permutation_outputs(attached, None, state, parameters=settings)
    with pytest.raises(ValueError, match="verified attached sample table"):
        _permutation_outputs(
            matrix,
            labels,
            _plsda_scientific_core(matrix, labels, parameters={"n_components": 1, "scale": False})[
                "artifact"
            ].to_fitted_state(),
            parameters=settings,
        )


@pytest.mark.asyncio
async def test_workflow_node_and_python_export_share_one_result() -> None:
    matrix, labels = _cohort()
    state = _plsda_scientific_core(matrix, labels, parameters={"n_components": 2, "scale": False})[
        "artifact"
    ].to_fitted_state()
    node = PLSDAPermutationNode("response_check", {"permutations": 19, "folds": 3, "maximum_components": 2, "seed": 42})
    result = await node.execute(X=matrix, y=labels, fitted_state=state)
    namespace = {"matrix": matrix, "labels": labels, "state": state, "results": {}}
    code = "\n".join(node.generate_python({"X": "matrix", "y": "labels", "fitted_state": "state"}, indent=""))
    exec(compile(code, "<plsda-permutation-export>", "exec"), namespace)
    assert namespace["results"][node.node_id] == result.outputs
