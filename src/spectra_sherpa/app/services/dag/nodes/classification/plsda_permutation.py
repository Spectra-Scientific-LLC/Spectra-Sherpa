"""Bounded, model-bound PLS-DA response-permutation evidence.

The statistic is the best out-of-fold balanced accuracy obtained by repeating
the same latent-variable search for the observed and every shuffled response.
Only the active calibration cohort enters this calculation. Upstream transforms
whose fold-local fitting cannot be proved are refused by the caller.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from spectra_sherpa.sdk.validate import make_classification_split_plan

from .core_utils import classification_scalar_metrics

SCHEMA = "spectrasherpa-plsda-response-permutation/1"
MAX_WORK_UNITS = 100_000_000


def validated_permutation_scores(value: object) -> tuple[float, list[float], int]:
    """Recount a complete retained Monte Carlo record before interpreting it."""

    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA or value.get("status") != "complete":
        raise ValueError("PLS-DA permutation evidence is incomplete")
    null = value.get("null")
    total = value.get("permutations_successful")
    observed = value.get("observed")
    exceedances = value.get("exceedances")
    probability = value.get("p_value")
    maximum = value.get("component_search_maximum")
    counts = value.get("class_counts")
    calibration = value.get("n_calibration")
    classes = value.get("n_classes")
    model_hash = value.get("model_state_sha256")
    if (
        type(total) is not int
        or not 19 <= total <= 199
        or not isinstance(null, list)
        or len(null) != total
        or value.get("permutations_requested") != total
        or type(observed) not in (int, float)
        or not math.isfinite(observed)
        or not 0 <= observed <= 1
        or type(exceedances) is not int
        or not 0 <= exceedances <= total
        or type(probability) not in (int, float)
        or not math.isfinite(probability)
        or type(maximum) is not int
        or not 1 <= maximum <= 10
        or type(calibration) is not int
        or not 12 <= calibration <= 500
        or type(classes) is not int
        or not 2 <= classes <= calibration
        or not isinstance(counts, dict)
        or len(counts) != classes
        or any(
            not isinstance(label, str) or not label or type(count) is not int or count < 1
            for label, count in counts.items()
        )
        or sum(counts.values()) != calibration
        or not isinstance(model_hash, str)
        or len(model_hash) != 64
        or any(character not in "0123456789abcdef" for character in model_hash)
    ):
        raise ValueError("PLS-DA permutation evidence has inconsistent population or test metadata")
    scores = []
    for row in null:
        if not isinstance(row, dict):
            raise ValueError("PLS-DA permutation evidence has an invalid null row")
        score = row.get("balanced_accuracy")
        selected = row.get("selected_components")
        digest = row.get("split_digest")
        if (
            type(score) not in (int, float)
            or not math.isfinite(score)
            or not 0 <= score <= 1
            or type(selected) is not int
            or not 1 <= selected <= maximum
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("PLS-DA permutation evidence has an invalid null score")
        scores.append(float(score))
    if exceedances != sum(score >= observed for score in scores) or not math.isclose(
        probability, (1 + exceedances) / (1 + total), rel_tol=0.0, abs_tol=1e-12
    ):
        raise ValueError("PLS-DA permutation evidence has an inconsistent finite-sample p-value")
    return float(observed), scores, exceedances


def _vector(value: Sequence[Any] | None, size: int, name: str) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be an aligned vector")
    if len(value) != size:
        raise ValueError(f"{name} must align with every calibration sample")
    result = []
    for item in value:
        if isinstance(item, np.generic):
            item = item.item()
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            raise ValueError(f"{name} contains an unsupported or missing identity")
        if isinstance(item, float) and not np.isfinite(item):
            raise ValueError(f"{name} contains an unsupported or missing identity")
        if isinstance(item, str) and (not item or item != item.strip()):
            raise ValueError(f"{name} contains an unsupported or missing identity")
        result.append(f"{type(item).__name__}:{item}")
    return result


def _exchangeable_units(
    labels: np.ndarray, groups: Sequence[Any] | None, blocks: Sequence[Any] | None, folds: int
) -> tuple[list[np.ndarray], dict[tuple[str, int], list[int]], list[str] | None, list[str] | None]:
    group_values = _vector(groups, labels.size, "groups")
    block_values = _vector(blocks, labels.size, "blocks")
    if group_values is None:
        units = [np.asarray([index], dtype=np.int64) for index in range(labels.size)]
    else:
        by_group: dict[str, list[int]] = {}
        for index, group in enumerate(group_values):
            by_group.setdefault(group, []).append(index)
        units = [np.asarray(indices, dtype=np.int64) for indices in by_group.values()]
    if len(units) < max(6, 2 * folds):
        raise ValueError("Too few independent exchangeable units for a PLS-DA permutation test")
    strata: dict[tuple[str, int], list[int]] = {}
    for unit_index, rows in enumerate(units):
        if len(set(labels[rows].tolist())) != 1:
            raise ValueError("Each grouped permutation unit must have one class label")
        unit_blocks = {block_values[index] for index in rows} if block_values is not None else {"unblocked"}
        if len(unit_blocks) != 1:
            raise ValueError("A grouped permutation unit cannot cross exchangeability blocks")
        strata.setdefault((next(iter(unit_blocks)), len(rows)), []).append(unit_index)
    movable = [
        index
        for indices in strata.values()
        if len({str(labels[units[index][0]]) for index in indices}) > 1
        for index in indices
    ]
    if len(movable) < max(6, 2 * folds):
        raise ValueError("Blocks and group sizes leave too few class-exchangeable units")
    return units, strata, group_values, block_values


def _shuffle_labels(
    labels: np.ndarray,
    units: list[np.ndarray],
    strata: dict[tuple[str, int], list[int]],
    rng: np.random.Generator,
) -> np.ndarray:
    result = labels.copy()
    for indices in strata.values():
        original = [labels[units[index][0]] for index in indices]
        for unit_index, label in zip(indices, rng.permutation(original), strict=True):
            result[units[unit_index]] = label
    return result


def _score_one_response(
    X: np.ndarray,
    labels: np.ndarray,
    classes: np.ndarray,
    groups: list[str] | None,
    *,
    components: int,
    folds: int,
    fold_seed: int,
    scale: bool,
    fit_model: Callable[[np.ndarray, np.ndarray, np.ndarray, int, bool], Any],
    cancelled: Callable[[], bool],
) -> tuple[float, int, str]:
    plan = make_classification_split_plan(labels, n_splits=folds, groups=groups, shuffle=True, random_state=fold_seed)
    class_indices = {value: index for index, value in enumerate(classes.tolist())}
    dummy = np.eye(len(classes), dtype=np.float64)[[class_indices[value] for value in labels.tolist()]]
    predictions = np.empty((components, labels.size), dtype=labels.dtype)
    assigned = np.zeros(labels.size, dtype=bool)
    for fold in plan.folds:
        if cancelled():
            raise InterruptedError("PLS-DA permutation was cancelled; no partial evidence was retained")
        if len(fold.train) - 1 < components:
            raise ValueError("A classification training fold cannot support the requested component search")
        fitted = fit_model(X[fold.train], dummy[fold.train], classes, components, scale)
        if fitted.n_components != components:
            raise ValueError("A classification fold has insufficient latent-variable rank")
        assigned[fold.test] = True
        for count in range(1, components + 1):
            responses = np.asarray(fitted.predict(X[fold.test], n_components=count), dtype=np.float64)
            if responses.shape != (len(fold.test), len(classes)) or not np.isfinite(responses).all():
                raise ValueError("A PLS-DA fold produced nonfinite or misaligned class responses")
            predictions[count - 1, fold.test] = classes[np.argmax(responses, axis=1)]
    if not assigned.all():
        raise ValueError("Classification CV did not score every calibration row")
    scores = [
        float(classification_scalar_metrics(labels, predicted, classes)["balanced_accuracy"])
        for predicted in predictions
    ]
    selected = min(range(components), key=lambda index: (-scores[index], index))
    return scores[selected], selected + 1, plan.digest


def response_permutation_evidence(
    X: object,
    y: object,
    *,
    groups: Sequence[Any] | None,
    blocks: Sequence[Any] | None,
    model_state_sha256: str,
    saved_components: int,
    components: int,
    folds: int,
    permutations: int,
    seed: int,
    scale: bool,
    fit_model: Callable[[np.ndarray, np.ndarray, np.ndarray, int, bool], Any],
    cancelled: Callable[[], bool] = lambda: False,
) -> dict[str, object]:
    """Refit each CV fold and component search for every complete response shuffle.

    Any invalid fold, cancellation, or failed fit aborts the operation before a
    completed evidence record can be returned. No independent test rows enter.
    """

    matrix = np.asarray(X, dtype=np.float64)
    labels = np.asarray(y)
    if (
        matrix.ndim != 2
        or labels.ndim != 1
        or matrix.shape[0] != labels.size
        or not 12 <= labels.size <= 500
        or not 1 <= matrix.shape[1] <= 2_000
        or not np.isfinite(matrix).all()
    ):
        raise ValueError("Permutation validation requires 12–500 finite aligned calibration rows")
    if (
        type(components) is not int
        or type(saved_components) is not int
        or not 1 <= saved_components <= components <= min(10, matrix.shape[1])
        or type(folds) is not int
        or not 2 <= folds <= 5
        or type(permutations) is not int
        or not 19 <= permutations <= 199
        or type(seed) is not int
        or not 0 <= seed < 2**32
        or type(scale) is not bool
        or not isinstance(model_state_sha256, str)
        or len(model_state_sha256) != 64
        or any(character not in "0123456789abcdef" for character in model_state_sha256)
    ):
        raise ValueError("PLS-DA permutation settings or model binding are invalid")
    if matrix.size * components * folds * (permutations + 1) > MAX_WORK_UNITS:
        raise ValueError("PLS-DA permutation workload exceeds the bounded validation budget")
    classes = np.unique(labels)
    if len(classes) < 2:
        raise ValueError("Response permutation requires at least two observed classes")
    units, strata, group_values, block_values = _exchangeable_units(labels, groups, blocks, folds)
    rng = np.random.default_rng(seed)
    candidates = []
    for _ in range(permutations):
        candidate = _shuffle_labels(labels, units, strata, rng)
        # Identity draws belong to the permutation distribution. Rejecting one
        # would silently alter its null probability and make the p-value small.
        # Validate the complete null design before fitting any model.
        make_classification_split_plan(candidate, n_splits=folds, groups=group_values, shuffle=True, random_state=seed)
        candidates.append(candidate)
    observed, observed_lv, observed_split = _score_one_response(
        matrix,
        labels,
        classes,
        group_values,
        components=components,
        folds=folds,
        fold_seed=seed,
        scale=scale,
        fit_model=fit_model,
        cancelled=cancelled,
    )
    null = []
    for candidate in candidates:
        value, selected, split = _score_one_response(
            matrix,
            candidate,
            classes,
            group_values,
            components=components,
            folds=folds,
            fold_seed=seed,
            scale=scale,
            fit_model=fit_model,
            cancelled=cancelled,
        )
        null.append({"balanced_accuracy": value, "selected_components": selected, "split_digest": split})
    if cancelled():
        raise InterruptedError("PLS-DA permutation was cancelled; no partial evidence was retained")
    exceedances = sum(row["balanced_accuracy"] >= observed for row in null)
    matrix_bytes = np.ascontiguousarray(matrix.astype("<f8", copy=False)).tobytes()
    return {
        "schema_version": SCHEMA,
        "status": "complete",
        "model_family": "plsda",
        "scope": "calibration_development_only_no_independent_test",
        "model_state_sha256": model_state_sha256,
        "calibration_x_sha256": hashlib.sha256(matrix_bytes).hexdigest(),
        "calibration_labels_sha256": hashlib.sha256(
            json.dumps(labels.tolist(), ensure_ascii=True).encode()
        ).hexdigest(),
        "grouping_sha256": (
            None if group_values is None else hashlib.sha256(json.dumps(group_values).encode()).hexdigest()
        ),
        "blocks_sha256": (
            None if block_values is None else hashlib.sha256(json.dumps(block_values).encode()).hexdigest()
        ),
        "n_calibration": int(labels.size),
        "n_classes": int(len(classes)),
        "n_units": len(units),
        "n_blocks": None if block_values is None else len(set(block_values)),
        "class_counts": {str(value): int(np.count_nonzero(labels == value)) for value in classes.tolist()},
        "saved_model_components": saved_components,
        "observed_reselected_components": observed_lv,
        "component_search_maximum": components,
        "selection_rule": "maximum_out_of_fold_balanced_accuracy_tie_fewer_components",
        "metric": "balanced_accuracy",
        "observed": observed,
        "observed_split_digest": observed_split,
        "seed": seed,
        "folds": folds,
        "permutations_requested": permutations,
        "permutations_successful": len(null),
        "exceedances": exceedances,
        "p_value": (1 + exceedances) / (1 + len(null)),
        "null": null,
        "scaling": "fold_fitted_autoscale" if scale else "fold_fitted_mean_center",
        "cv_anova": {
            "status": "unavailable",
            "reason": "No qualified CV-ANOVA statistic for this PLS-DA response design.",
        },
        "interpretation_limit": (
            "A small p-value is evidence against exchangeable random labels under this validation design; "
            "it does not establish independent external validity or application-domain fitness."
        ),
    }
