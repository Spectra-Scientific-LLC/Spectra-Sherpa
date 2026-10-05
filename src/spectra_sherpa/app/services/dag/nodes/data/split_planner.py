"""Canonical sample-partition planning for ``data.train_test_split``.

This module is the single scientific authority used by live DAG execution,
exported Python, and the temporary prototype adapter during consumer migration.
It implements:

* seeded random, stratified, and sequential train/test splitting;
* named group holdout for external validation by lot or instrument;
* Kennard--Stone space-filling calibration selection;
* Snee's DUPLEX calibration/validation partition; and
* Galvao et al.'s SPXY joint X--Y calibration selection.

Scientific references
---------------------
Named group holdout follows the Leave-P-Groups-Out semantics of
``sklearn.model_selection.LeavePGroupsOut``: the scientist names the exact
groups that form the test partition, every other group trains, and no group
appears in both partitions.  This is the standard external-validation design
for a new production lot or a specific new instrument.

Kennard, R. W. & Stone, L. A. (1969), *Computer Aided Design of
Experiments*, Technometrics 11(1), 137--148,
https://doi.org/10.1080/00401706.1969.10490666.  The Euclidean and
Mahalanobis variants follow the public ``rchemo::sampks`` definition.

Snee, R. D. (1977), *Validation of Regression Models: Methods and
Examples*, Technometrics 19(4), 415--428,
https://doi.org/10.1080/00401706.1977.10489581.  DUPLEX assigns the most
distant pair to calibration, the most distant remaining pair to validation,
then alternates maximin additions.  When validation reaches its requested
size first, the remaining observations belong to calibration as specified by
Snee.

Galvao, R. K. H. et al. (2005), *A method for calibration and validation
subset partitioning*, Talanta 67(4), 736--740,
https://doi.org/10.1016/j.talanta.2005.03.025.  SPXY applies
Kennard--Stone selection to the sum of independently maximum-normalized
Euclidean X- and Y-distance matrices.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Final, Sequence

import numpy as np
from scipy.spatial.distance import cdist  # type: ignore[import-untyped]
from sklearn.decomposition import PCA  # type: ignore[import-untyped]
from sklearn.model_selection import StratifiedGroupKFold, train_test_split  # type: ignore[import-untyped]
from sklearn.utils.multiclass import type_of_target  # type: ignore[import-untyped]

from spectra_sherpa.app.lib.sherpa_dataset import TargetContext
from spectra_sherpa.app.services.dag.class_labels import prepare_class_labels, prepare_declared_class_labels
from spectra_sherpa.app.services.dag.io_contracts import (
    bind_y,
    build_dataset_like,
    coerce_to_sherpa,
    extract_target_like,
    to_numpy_y,
)
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.dag.supervision_binding import (
    admit_attached_sample_table_supervision,
    bind_sample_table_supervision,
)
from spectra_sherpa.core.target_authority import admit_target_authority

from ._utils import slice_axis_for_indices

SPLIT_PLAN_SCHEMA: Final = "spectrasherpa-split-plan/2"
SPLIT_METHODS: Final = (
    "random",
    "stratified",
    "sequential",
    "group_holdout",
    "kennard_stone",
    "duplex",
    "spxy",
)
DISTANCE_METRICS: Final = ("euclidean", "mahalanobis")
_SPACE_FILLING_METHODS: Final = frozenset({"kennard_stone", "duplex", "spxy"})


@dataclass(frozen=True)
class SplitPlan:
    """Closed, digest-bound identity of one sample partition."""

    method: str
    n_samples: int
    test_size: float
    random_seed: int
    distance_metric: str
    n_components: int
    x_content_digest: str
    y_content_digest: str | None
    groups_content_digest: str | None
    n_groups: int | None
    held_out_groups: tuple[object, ...] | None
    train_indices: np.ndarray
    test_indices: np.ndarray
    digest: str

    def as_dict(self) -> dict[str, object]:
        """Return the exact portable plan that is bound by ``digest``."""

        return {
            "schema": SPLIT_PLAN_SCHEMA,
            "method": self.method,
            "n_samples": self.n_samples,
            "test_size": self.test_size,
            "random_seed": self.random_seed,
            "distance_metric": self.distance_metric,
            "n_components": self.n_components,
            "x_content_digest": self.x_content_digest,
            "y_content_digest": self.y_content_digest,
            "groups_content_digest": self.groups_content_digest,
            "n_groups": self.n_groups,
            "held_out_groups": list(self.held_out_groups) if self.held_out_groups is not None else None,
            "train_indices": self.train_indices.tolist(),
            "test_indices": self.test_indices.tolist(),
            "digest": self.digest,
        }


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _plan_digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _unsigned_plan_payload(plan: SplitPlan) -> dict[str, object]:
    """Project a plan into the exact closed payload covered by its digest."""

    return {
        "schema": SPLIT_PLAN_SCHEMA,
        "method": plan.method,
        "n_samples": int(plan.n_samples),
        "test_size": float(plan.test_size),
        "random_seed": int(plan.random_seed),
        "distance_metric": plan.distance_metric,
        "n_components": int(plan.n_components),
        "x_content_digest": plan.x_content_digest,
        "y_content_digest": plan.y_content_digest,
        "groups_content_digest": plan.groups_content_digest,
        "n_groups": plan.n_groups,
        "held_out_groups": list(plan.held_out_groups) if plan.held_out_groups is not None else None,
        "train_indices": np.asarray(plan.train_indices).tolist(),
        "test_indices": np.asarray(plan.test_indices).tolist(),
    }


def _array_content_digest(value: np.ndarray) -> str:
    """Digest an admitted array with explicit shape, kind, and stable bytes."""

    array = np.asarray(value)
    identity: dict[str, object] = {"shape": list(array.shape)}
    if np.issubdtype(array.dtype, np.number):
        canonical = np.ascontiguousarray(array, dtype="<f8")
        identity.update({"kind": "numeric_float64_le", "data_sha256": hashlib.sha256(canonical.tobytes()).hexdigest()})
    else:
        identity.update({"kind": "categorical_json", "values": array.tolist()})
    return hashlib.sha256(_canonical_json(identity)).hexdigest()


def _plain_group(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    return value


def _ordered_groups(groups: np.ndarray) -> tuple[object, ...]:
    values: list[object] = []
    for value in groups:
        plain = _plain_group(value)
        if not any(plain == existing for existing in values):
            values.append(plain)
    return tuple(values)


def bind_split_groups(X_source: object) -> np.ndarray | None:
    """Re-admit an attached sample-table group authority for partitioning.

    Group identity is never inferred from a convenient metadata column.  It
    is usable only when ``data.attach_target`` issued an exact supervision
    binding and that binding still reproduces from the current dataset.
    """

    dataset = coerce_to_sherpa(X_source, input_name="X", allow_array=True)
    supervision = admit_attached_sample_table_supervision(dataset)
    return None if supervision is None else supervision.groups


def bind_split_target(
    X_source: object,
    y: object | None,
) -> tuple[np.ndarray | None, TargetContext | None]:
    """Resolve one target authority for live, generated, and adapter paths.

    A connected target dataset contributes its data matrix. When the y port is
    unconnected, the predictor dataset's embedded target is inferred instead.
    Target metadata follows whichever source supplied the effective values;
    predictor metadata is never attached to an unrelated explicit array.
    """

    X_dataset = coerce_to_sherpa(X_source, input_name="X", allow_array=True)
    authority = X_dataset if y is None else y
    if y is None:
        # A SherpaDataset's sample axis identifies observations; it is never a
        # supervised response.  Split planning may infer only the dataset's
        # explicit embedded target, then apply selected-target metadata below.
        y_value = getattr(X_dataset, "target", None)
    else:
        y_value = bind_y(
            y,
            X=X_dataset,
            required=False,
            infer_from_X=False,
            dataset_as_data=True,
        )
    if y_value is None:
        return None, None

    y_array = to_numpy_y(y_value, name="y", expected_samples=X_dataset.shape[0])
    context_value = getattr(authority, "target_context", None)
    context = context_value.model_copy(deep=True) if isinstance(context_value, TargetContext) else None
    if context is None and y is not None:
        embedded_target = extract_target_like(X_dataset)
        source_context = getattr(X_dataset, "target_context", None)
        if embedded_target is not None and isinstance(source_context, TargetContext):
            embedded_array = to_numpy_y(embedded_target, name="X.target", expected_samples=X_dataset.shape[0])
            exact_match = _array_content_digest(embedded_array) == _array_content_digest(y_array)
            canonical_categorical_match = False
            if not exact_match and source_context.target_type == "categorical":
                try:
                    canonical_embedded = prepare_declared_class_labels(
                        embedded_array,
                        X_dataset.shape[0],
                        selected_target=source_context.selected_target,
                        target_names=source_context.target_names,
                    )
                except ValueError:
                    pass
                else:
                    canonical_categorical_match = _array_content_digest(canonical_embedded) == _array_content_digest(
                        y_array
                    )
            if exact_match or canonical_categorical_match:
                # The explicit target edge carries the exact values embedded
                # in X, or its canonical categorical projection, so its
                # metadata authority is provably the same source. An unrelated
                # same-shaped array never inherits X metadata.
                context = source_context.model_copy(deep=True)
    if context is not None and context.selected_target:
        names = list(context.target_names or [])
        if context.selected_target not in names:
            raise ValueError("selected target is not present in the connected target metadata")
        if y_array.ndim == 2:
            selected_index = names.index(context.selected_target)
            if y_array.shape[1] != len(names):
                raise ValueError("connected target metadata does not name every target column")
            y_array = y_array[:, selected_index]
        context = context.model_copy(
            update={
                "target_name": context.selected_target,
                "target_names": [context.selected_target],
            },
            deep=True,
        )
    elif context is not None and context.target_names:
        n_targets = 1 if y_array.ndim == 1 else y_array.shape[1]
        if len(context.target_names) != n_targets:
            raise ValueError("connected target metadata does not name every target column")
    if context is not None and context.target_type == "categorical":
        if y_array.ndim == 2 and y_array.shape[1] > 1:
            raise ValueError("multi-column categorical split target requires a selected_target")
        y_array = prepare_class_labels(y_array, X_dataset.shape[0])
    return y_array, context


def _validate_requested_holdout(held_out_groups: Sequence[object] | None) -> None:
    if held_out_groups is None or isinstance(held_out_groups, (str, bytes)) or not list(held_out_groups):
        raise ValueError("group_holdout requires at least one named group to hold out")
    for value in held_out_groups:
        if isinstance(value, bool) or not isinstance(value, (str, int, float, np.integer, np.floating)):
            raise ValueError("held_out_groups must name exact scalar group values")
        if isinstance(value, str) and not value.strip():
            raise ValueError("held_out_groups must name exact non-empty group values")
        if isinstance(value, (float, np.floating)) and not np.isfinite(value):
            raise ValueError("held_out_groups must name finite group values")
    if len({repr(_plain_group(value)) for value in held_out_groups}) != len(list(held_out_groups)):
        raise ValueError("held_out_groups must not name the same group twice")


def _validate_inputs(
    X: np.ndarray,
    y: np.ndarray | None,
    *,
    method: str,
    test_size: float,
    random_seed: int,
    distance_metric: str,
    n_components: int,
    held_out_groups: Sequence[object] | None,
) -> tuple[np.ndarray, np.ndarray | None, int, int]:
    X_arr = np.asarray(X, dtype=np.float64)
    if X_arr.ndim != 2:
        raise ValueError("X must be a two-dimensional sample-by-feature matrix")
    if X_arr.shape[0] < 2 or X_arr.shape[1] < 1:
        raise ValueError("X must contain at least two samples and one feature")
    if not np.all(np.isfinite(X_arr)):
        raise ValueError("X must contain only finite values")
    if method not in SPLIT_METHODS:
        raise ValueError(f"Unsupported split method: {method!r}")
    if isinstance(random_seed, bool) or not isinstance(random_seed, (int, np.integer)):
        raise ValueError("random_seed must be an integer")
    if not 0 <= int(random_seed) <= 4_294_967_295:
        raise ValueError("random_seed must be between 0 and 4294967295")
    if not np.isfinite(test_size) or not 0.0 < float(test_size) < 1.0:
        raise ValueError("test_size must be strictly between 0 and 1")
    if distance_metric not in DISTANCE_METRICS:
        raise ValueError(f"Unsupported distance metric: {distance_metric!r}")
    if isinstance(n_components, bool) or not isinstance(n_components, (int, np.integer)):
        raise ValueError("n_components must be an integer")
    if int(n_components) < 0:
        raise ValueError("n_components must be non-negative")

    n_samples = X_arr.shape[0]
    # The canonical contract deliberately uses floor, matching the historical
    # workbench's explicit sample count rather than sklearn's float-size ceil.
    n_test = int(n_samples * float(test_size))
    n_train = n_samples - n_test
    if n_test < 1 or n_train < 1:
        raise ValueError(
            f"test_size={test_size} gives {n_train} training and {n_test} test samples; both sets must be non-empty"
        )
    if method in _SPACE_FILLING_METHODS and n_train < 2:
        raise ValueError(f"{method} requires at least two training samples")
    if method == "duplex" and n_test < 2:
        raise ValueError("duplex requires at least two test samples")
    if method == "spxy" and (distance_metric != "euclidean" or n_components != 0):
        raise ValueError(
            "spxy uses the published raw-space Euclidean definition; no alternate metric or PCA is admitted"
        )
    if method in {"random", "stratified", "sequential", "group_holdout"} and (
        distance_metric != "euclidean" or n_components != 0
    ):
        raise ValueError(f"{method} does not admit distance_metric or n_components settings")
    if method not in {"random", "stratified"} and int(random_seed) != 42:
        raise ValueError(f"{method} is deterministic and does not admit a random_seed setting")
    if method == "group_holdout":
        # The scientist names the exact groups that form the test partition, so
        # the list must be present, non-empty, free of duplicates, and made of
        # plain scalars; membership against the bound group vector is checked
        # once that vector is available.
        _validate_requested_holdout(held_out_groups)

    y_arr: np.ndarray | None = None
    if y is not None:
        y_arr = np.asarray(y)
        if y_arr.ndim not in (1, 2) or y_arr.shape[0] != n_samples:
            raise ValueError("y must be a one- or two-dimensional target array aligned to X samples")
        if np.issubdtype(y_arr.dtype, np.number) and not np.all(np.isfinite(y_arr.astype(np.float64))):
            raise ValueError("numeric y values must be finite")
    if method in {"stratified", "spxy"} and y_arr is None:
        raise ValueError(f"{method} requires explicit or embedded target values")
    # Stratification preserves the proportions of a target's classes, so it is
    # defined only on a categorical response. A continuous response such as a
    # moisture concentration has no classes to preserve: stratifying it would
    # first require binning it into ranges, and the bin edges are a scientific
    # choice this planner is not entitled to invent. Refuse it here, naming the
    # target, rather than letting the underlying splitter report its own
    # internal vocabulary once a run is already under way.
    if method == "stratified" and y_arr is not None:
        observed = y_arr[:, 0] if y_arr.ndim == 2 and y_arr.shape[1] == 1 else y_arr
        if type_of_target(observed) in {"continuous", "continuous-multioutput"}:
            raise ValueError(
                "stratified splitting requires a categorical target; this target is continuous. "
                "Use random, sequential, or group holdout splitting, or attach a categorical target"
            )
    if method == "spxy" and y_arr is not None and not np.issubdtype(y_arr.dtype, np.number):
        raise ValueError("spxy requires numeric target values")

    return X_arr, y_arr, n_train, n_test


def _project_samples(X: np.ndarray, n_components: int) -> np.ndarray:
    """Optionally project centered X onto an explicitly bounded PCA space."""

    if n_components == 0:
        return X
    maximum = min(X.shape)
    if n_components > maximum:
        raise ValueError(f"n_components={n_components} exceeds the data limit {maximum}")
    return np.asarray(PCA(n_components=n_components, svd_solver="full").fit_transform(X), dtype=np.float64)


def _pairwise_distances(X: np.ndarray, metric: str) -> np.ndarray:
    """Return a finite symmetric distance matrix under the admitted metric."""

    if metric == "euclidean":
        distances = cdist(X, X, metric="euclidean")
    elif metric == "mahalanobis":
        covariance = np.atleast_2d(np.cov(X, rowvar=False, ddof=1))
        inverse = np.linalg.pinv(covariance, hermitian=True)
        distances = cdist(X, X, metric="mahalanobis", VI=inverse)
    else:  # pragma: no cover - closed by _validate_inputs
        raise ValueError(f"Unsupported distance metric: {metric!r}")
    if not np.all(np.isfinite(distances)):
        raise ValueError("sample distances are not finite")
    distances = np.asarray((distances + distances.T) / 2.0, dtype=np.float64)
    np.fill_diagonal(distances, 0.0)
    return distances


def _farthest_pair(distances: np.ndarray, candidates: np.ndarray) -> tuple[int, int]:
    """Choose the lexicographically first farthest distinct candidate pair."""

    if candidates.size < 2:
        raise ValueError("at least two candidate samples are required")
    submatrix = distances[np.ix_(candidates, candidates)]
    upper_rows, upper_cols = np.triu_indices(candidates.size, k=1)
    pair_distances = submatrix[upper_rows, upper_cols]
    maximum = float(np.max(pair_distances))
    if maximum <= 0.0:
        raise ValueError("space-filling selection requires at least two distinct samples")
    first = int(np.flatnonzero(pair_distances == maximum)[0])
    return int(candidates[upper_rows[first]]), int(candidates[upper_cols[first]])


def _maximin(distances: np.ndarray, selected: list[int], candidates: np.ndarray) -> int:
    """Choose the lowest-index candidate maximizing distance to its nearest selected sample."""

    minima = distances[np.ix_(candidates, np.asarray(selected, dtype=np.intp))].min(axis=1)
    maximum = float(np.max(minima))
    return int(candidates[np.flatnonzero(minima == maximum)[0]])


def _kennard_stone_from_distances(distances: np.ndarray, n_select: int) -> np.ndarray:
    candidates = np.arange(distances.shape[0], dtype=np.intp)
    first, second = _farthest_pair(distances, candidates)
    selected = [first, second]
    available = candidates[~np.isin(candidates, np.asarray(selected, dtype=np.intp))]
    while len(selected) < n_select:
        chosen = _maximin(distances, selected, available)
        selected.append(chosen)
        available = available[available != chosen]
    return np.asarray(selected[:n_select], dtype=np.intp)


def _kennard_stone(X: np.ndarray, n_train: int, metric: str, n_components: int) -> tuple[np.ndarray, np.ndarray]:
    projected = _project_samples(X, n_components)
    distances = _pairwise_distances(projected, metric)
    train_indices = _kennard_stone_from_distances(distances, n_train)
    all_indices = np.arange(X.shape[0], dtype=np.intp)
    test_indices = all_indices[~np.isin(all_indices, train_indices)]
    return train_indices, test_indices


def _duplex(X: np.ndarray, n_train: int, n_test: int, metric: str, n_components: int) -> tuple[np.ndarray, np.ndarray]:
    projected = _project_samples(X, n_components)
    distances = _pairwise_distances(projected, metric)
    available = np.arange(X.shape[0], dtype=np.intp)

    first, second = _farthest_pair(distances, available)
    train = [first, second]
    available = available[~np.isin(available, np.asarray(train, dtype=np.intp))]

    first, second = _farthest_pair(distances, available)
    test = [first, second]
    available = available[~np.isin(available, np.asarray(test, dtype=np.intp))]

    while available.size and len(test) < n_test and len(train) < n_train:
        chosen = _maximin(distances, train, available)
        train.append(chosen)
        available = available[available != chosen]
        if not available.size or len(test) >= n_test:
            break
        chosen = _maximin(distances, test, available)
        test.append(chosen)
        available = available[available != chosen]

    # Snee explicitly assigns all observations remaining after the smaller
    # requested set is complete to the larger set.
    while available.size and len(train) < n_train:
        chosen = _maximin(distances, train, available)
        train.append(chosen)
        available = available[available != chosen]
    while available.size and len(test) < n_test:
        chosen = _maximin(distances, test, available)
        test.append(chosen)
        available = available[available != chosen]

    return np.asarray(train, dtype=np.intp), np.asarray(test, dtype=np.intp)


def _spxy_distance_matrix(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    y_matrix = np.asarray(y, dtype=np.float64)
    if y_matrix.ndim == 1:
        y_matrix = y_matrix.reshape(-1, 1)
    X_distances = _pairwise_distances(X, "euclidean")
    y_distances = _pairwise_distances(y_matrix, "euclidean")
    max_x = float(np.max(X_distances))
    max_y = float(np.max(y_distances))
    if max_x <= 0.0:
        raise ValueError("spxy requires variation in X")
    if max_y <= 0.0:
        raise ValueError("spxy requires variation in y")
    return np.asarray(X_distances / max_x + y_distances / max_y, dtype=np.float64)


def _spxy(X: np.ndarray, y: np.ndarray, n_train: int) -> tuple[np.ndarray, np.ndarray]:
    combined = _spxy_distance_matrix(X, y)
    train_indices = _kennard_stone_from_distances(combined, n_train)
    all_indices = np.arange(X.shape[0], dtype=np.intp)
    test_indices = all_indices[~np.isin(all_indices, train_indices)]
    return train_indices, test_indices


def _validated_groups(groups: object, *, n_samples: int, min_distinct_groups: int = 2) -> np.ndarray:
    array = np.asarray(groups)
    if array.ndim != 1 or array.shape[0] != n_samples:
        raise ValueError("validation groups must be a one-dimensional vector aligned to X")
    if array.dtype.kind not in "iufSU":
        raise ValueError("validation groups must use one numeric or text scalar representation")
    if array.dtype.kind in "f" and not np.isfinite(array).all():
        raise ValueError("validation groups must be finite")
    if len(_ordered_groups(array)) < min_distinct_groups:
        raise ValueError("grouped partitioning requires at least two distinct groups")
    return np.array(array, copy=True)


def _indices_for_held_out_groups(groups: np.ndarray, held_out: tuple[object, ...]) -> tuple[np.ndarray, np.ndarray]:
    test_mask = np.asarray([any(_plain_group(value) == item for item in held_out) for value in groups], dtype=bool)
    all_indices = np.arange(groups.shape[0], dtype=np.intp)
    return all_indices[~test_mask], all_indices[test_mask]


def _group_partition(
    groups: np.ndarray,
    y: np.ndarray | None,
    *,
    method: str,
    test_size: float,
    random_seed: int,
    desired_test_samples: int,
    requested_holdout: Sequence[object] | None = None,
) -> tuple[np.ndarray, np.ndarray, tuple[object, ...]]:
    ordered = _ordered_groups(groups)
    n_test_groups = min(len(ordered) - 1, max(1, int(np.ceil(float(test_size) * len(ordered)))))

    if method == "group_holdout":
        # The scientist names the exact groups that form the test partition
        # (Leave-P-Groups-Out semantics). Resolve each requested name to the
        # canonical group value: exact match first, then the plain string form
        # so a text-entered "2" selects an integer lot 2. The plan records the
        # bound group's own representation, never the entered spelling.
        assert requested_holdout is not None
        selected: list[object] = []
        for request in requested_holdout:
            plain = _plain_group(request)
            match = next(
                (value for value in ordered if plain == value or (isinstance(plain, str) and plain == str(value))),
                None,
            )
            if match is None:
                valid = ", ".join(str(value) for value in ordered)
                raise ValueError(f"held-out group {plain!r} is not one of the bound groups: {valid}")
            if any(match == existing for existing in selected):
                raise ValueError(f"held-out group {match!r} is named twice")
            selected.append(match)
        if len(selected) >= len(ordered):
            raise ValueError("group_holdout must leave at least one group in the training partition")
        held_out = tuple(selected)
        train, test = _indices_for_held_out_groups(groups, held_out)
        return train, test, held_out

    if method == "sequential":
        held_out = ordered[-n_test_groups:]
        train, test = _indices_for_held_out_groups(groups, held_out)
        return train, test, held_out

    if method == "random":
        shuffled = np.asarray(ordered, dtype=object)
        np.random.RandomState(int(random_seed)).shuffle(shuffled)
        held_out = tuple(_plain_group(value) for value in shuffled[:n_test_groups])
        train, test = _indices_for_held_out_groups(groups, held_out)
        return train, test, held_out

    assert method == "stratified" and y is not None
    stratification = y[:, 0] if y.ndim == 2 and y.shape[1] == 1 else y
    if stratification.ndim != 1:
        raise ValueError("stratified splitting requires a one-dimensional categorical target")
    labels = tuple(_ordered_groups(np.asarray(stratification)))
    if len(labels) < 2:
        raise ValueError("stratified splitting requires at least two target classes")
    n_splits = min(len(ordered), max(2, int(round(len(ordered) / n_test_groups))))
    splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=int(random_seed))
    candidates: list[tuple[tuple[float, float, tuple[int, ...]], np.ndarray, np.ndarray, tuple[object, ...]]] = []
    dummy = np.zeros((groups.shape[0], 1), dtype=np.float64)
    for train, test in splitter.split(dummy, stratification, groups):
        train_labels = _ordered_groups(np.asarray(stratification)[train])
        test_labels = _ordered_groups(np.asarray(stratification)[test])
        if set(train_labels) != set(labels) or set(test_labels) != set(labels):
            continue
        held_out = _ordered_groups(groups[test])
        full_counts = np.asarray([np.count_nonzero(stratification == label) for label in labels], dtype=np.float64)
        test_counts = np.asarray(
            [np.count_nonzero(np.asarray(stratification)[test] == label) for label in labels], dtype=np.float64
        )
        imbalance = float(np.sum(np.abs(test_counts / test.size - full_counts / groups.size)))
        objective = (abs(test.size - desired_test_samples), imbalance, tuple(int(value) for value in test))
        candidates.append((objective, np.asarray(train, dtype=np.intp), np.asarray(test, dtype=np.intp), held_out))
    if not candidates:
        # K-fold assignment can miss a feasible single holdout when minority
        # classes have fewer groups than folds. For class-pure groups, allocate
        # a constrained stratified holdout directly, without inspecting X.
        class_groups: list[list[object]] = [[] for _ in labels]
        for group in ordered:
            group_labels = _ordered_groups(stratification[groups == group])
            if len(group_labels) != 1:
                break
            class_groups[labels.index(group_labels[0])].append(group)
        else:
            counts = np.asarray([len(items) for items in class_groups], dtype=int)
            if np.all(counts >= 2) and len(labels) <= n_test_groups <= len(ordered) - len(labels):
                desired = counts * float(test_size)
                allocation = np.ones(len(labels), dtype=int)
                for _ in range(n_test_groups - len(labels)):
                    deficit = np.where(allocation < counts - 1, desired - allocation, -np.inf)
                    allocation[int(np.argmax(deficit))] += 1
                rng = np.random.RandomState(int(random_seed))
                selected: list[object] = []
                for items, count in zip(class_groups, allocation):
                    selected.extend(items[index] for index in rng.permutation(len(items))[:count])
                train, test = _indices_for_held_out_groups(groups, tuple(selected))
                return train, test, _ordered_groups(groups[test])
    if not candidates:
        raise ValueError(
            "grouped stratified splitting could not place every target class in both train and test partitions; "
            "check independent group support per class and the requested test size"
        )
    _, train, test, held_out = min(candidates, key=lambda item: item[0])
    return train, test, held_out


def plan_train_test_split(
    X: np.ndarray,
    y: np.ndarray | None = None,
    *,
    method: str = "random",
    test_size: float = 0.2,
    random_seed: int = 42,
    distance_metric: str = "euclidean",
    n_components: int = 0,
    groups: object | None = None,
    held_out_groups: Sequence[object] | None = None,
) -> SplitPlan:
    """Construct one deterministic, digest-bound train/test partition."""

    X_arr, y_arr, n_train, n_test = _validate_inputs(
        X,
        y,
        method=method,
        test_size=float(test_size),
        random_seed=random_seed,
        distance_metric=distance_metric,
        n_components=n_components,
        held_out_groups=held_out_groups,
    )
    all_indices = np.arange(X_arr.shape[0], dtype=np.intp)
    group_values = (
        None
        if groups is None
        else _validated_groups(
            groups,
            n_samples=X_arr.shape[0],
            min_distinct_groups=1 if method in _SPACE_FILLING_METHODS else 2,
        )
    )
    if method == "group_holdout" and group_values is None:
        raise ValueError(
            "group_holdout requires an attached grouping column; bind a group authority on the input dataset"
        )
    # A space-filling method selects individual samples by spectral distance and
    # has no whole-group definition, so it cannot hold a group out. Selecting a
    # grouping column is not by itself a request to partition by it: the column
    # names a validation authority, and the method decides whether the partition
    # is constrained by it. Kennard-Stone therefore covers the spectral extremes
    # as it would with no grouping at all, whether one instrument view is
    # selected or several, and a scientist asks for whole-group validation by
    # choosing random, stratified, sequential, or named group holdout splitting.
    #
    # The attached authority is still bound into the plan: groups_content_digest
    # and n_groups record that N groups were present, while held_out_groups stays
    # empty because none were held out. The plan therefore states plainly that a
    # group authority was attached and did not constrain this partition, and two
    # otherwise identical Kennard-Stone plans remain distinguishable by it.
    partition_by_group = group_values is not None and method not in _SPACE_FILLING_METHODS
    held_out: tuple[object, ...] | None = None
    if group_values is not None and partition_by_group:
        train_indices, test_indices, held_out = _group_partition(
            group_values,
            y_arr,
            method=method,
            test_size=float(test_size),
            random_seed=int(random_seed),
            desired_test_samples=n_test,
            requested_holdout=held_out_groups,
        )
    elif method == "sequential":
        train_indices = all_indices[:n_train]
        test_indices = all_indices[n_train:]
    elif method == "random":
        shuffled = np.array(all_indices, copy=True)
        np.random.RandomState(int(random_seed)).shuffle(shuffled)
        train_indices = shuffled[:n_train]
        test_indices = shuffled[n_train:]
    elif method == "stratified":
        assert y_arr is not None
        stratification = y_arr[:, 0] if y_arr.ndim == 2 and y_arr.shape[1] == 1 else y_arr
        if stratification.ndim != 1:
            raise ValueError("stratified splitting requires a one-dimensional categorical target")
        train_indices, test_indices = train_test_split(
            all_indices,
            test_size=n_test,
            random_state=int(random_seed),
            stratify=stratification,
            shuffle=True,
        )
        train_indices = np.asarray(train_indices, dtype=np.intp)
        test_indices = np.asarray(test_indices, dtype=np.intp)
    elif method == "kennard_stone":
        train_indices, test_indices = _kennard_stone(X_arr, n_train, distance_metric, n_components)
    elif method == "duplex":
        train_indices, test_indices = _duplex(X_arr, n_train, n_test, distance_metric, n_components)
    else:
        assert method == "spxy" and y_arr is not None
        train_indices, test_indices = _spxy(X_arr, y_arr, n_train)

    if not partition_by_group and (train_indices.size != n_train or test_indices.size != n_test):
        raise RuntimeError("split planner produced an unexpected partition size")
    if train_indices.size < 1 or test_indices.size < 1:
        raise RuntimeError("split planner produced an empty partition")
    combined = np.concatenate((train_indices, test_indices))
    if np.unique(combined).size != X_arr.shape[0] or set(combined.tolist()) != set(all_indices.tolist()):
        raise RuntimeError("split planner did not produce an exact, disjoint partition")

    train_indices = np.asarray(train_indices, dtype=np.intp)
    test_indices = np.asarray(test_indices, dtype=np.intp)
    train_indices.setflags(write=False)
    test_indices.setflags(write=False)
    plan = SplitPlan(
        method=method,
        n_samples=int(X_arr.shape[0]),
        test_size=float(test_size),
        random_seed=int(random_seed),
        distance_metric=distance_metric,
        n_components=int(n_components),
        x_content_digest=_array_content_digest(X_arr),
        y_content_digest=None if y_arr is None else _array_content_digest(y_arr),
        groups_content_digest=None if group_values is None else _array_content_digest(group_values),
        n_groups=None if group_values is None else len(_ordered_groups(group_values)),
        held_out_groups=held_out,
        train_indices=train_indices,
        test_indices=test_indices,
        digest="",
    )
    return replace(plan, digest=_plan_digest(_unsigned_plan_payload(plan)))


def _validate_plan_binding(
    X: np.ndarray,
    y: np.ndarray | None,
    plan: SplitPlan,
    groups: object | None = None,
) -> None:
    """Reject a malformed plan or inputs that differ from its bound content."""

    X_arr = np.asarray(X, dtype=np.float64)
    y_arr = None if y is None else np.asarray(y)
    if X_arr.ndim != 2 or X_arr.shape[0] != plan.n_samples:
        raise ValueError("X no longer matches the bound split plan")
    if _array_content_digest(X_arr) != plan.x_content_digest:
        raise ValueError("X content digest no longer matches the bound split plan")
    if y_arr is None:
        if plan.y_content_digest is not None:
            raise ValueError("y is missing from a split plan that binds target content")
    else:
        if y_arr.shape[0] != plan.n_samples:
            raise ValueError("y no longer matches the bound split plan")
        if _array_content_digest(y_arr) != plan.y_content_digest:
            raise ValueError("y content digest no longer matches the bound split plan")

    if groups is None:
        if plan.groups_content_digest is not None or plan.n_groups is not None or plan.held_out_groups is not None:
            raise ValueError("validation groups are missing from a split plan that binds group content")
    else:
        group_values = _validated_groups(
            groups,
            n_samples=plan.n_samples,
            min_distinct_groups=1 if plan.method in _SPACE_FILLING_METHODS else 2,
        )
        if _array_content_digest(group_values) != plan.groups_content_digest:
            raise ValueError("validation group content no longer matches the bound split plan")
        if plan.n_groups != len(_ordered_groups(group_values)):
            raise ValueError("split-plan group identity is malformed")
        # A space-filling method selects individual samples by spectral distance
        # and has no whole-group definition, so it binds the attached authority
        # without holding any group out. The whole-group checks below describe a
        # partition it never claimed to make, so they do not apply; what must
        # hold is the converse, that it claims no holdout it did not perform.
        if plan.method in _SPACE_FILLING_METHODS:
            if plan.held_out_groups is not None:
                raise ValueError("a space-filling split plan may not claim held-out groups")
        else:
            if plan.held_out_groups is None:
                raise ValueError("split-plan group identity is malformed")
            train_groups = set(_ordered_groups(group_values[np.asarray(plan.train_indices, dtype=np.intp)]))
            test_groups = set(_ordered_groups(group_values[np.asarray(plan.test_indices, dtype=np.intp)]))
            if train_groups & test_groups:
                raise ValueError("split plan leaks validation groups across train and test")
            if test_groups != set(plan.held_out_groups):
                raise ValueError("split plan held-out groups do not match its exact membership")

    train_indices = np.asarray(plan.train_indices)
    test_indices = np.asarray(plan.test_indices)
    if train_indices.ndim != 1 or test_indices.ndim != 1:
        raise ValueError("split-plan indices must be one-dimensional")
    if train_indices.dtype.kind not in "iu" or test_indices.dtype.kind not in "iu":
        raise ValueError("split-plan indices must be integers")
    combined = np.concatenate((train_indices, test_indices))
    if (
        combined.size != plan.n_samples
        or np.unique(combined).size != plan.n_samples
        or not np.array_equal(np.sort(combined), np.arange(plan.n_samples))
    ):
        raise ValueError("split plan is not an exact, disjoint sample partition")
    if _plan_digest(_unsigned_plan_payload(plan)) != plan.digest:
        raise ValueError("split-plan digest does not match its closed payload")


def materialize_split_outputs(
    X_source: object,
    X: np.ndarray,
    y: np.ndarray | None,
    plan: SplitPlan,
    *,
    node_id: str,
    target_context: TargetContext | None = None,
    groups: object | None = None,
) -> dict[str, object]:
    """Materialize one planned partition without reimplementing its science."""

    X_arr = np.asarray(X, dtype=np.float64)
    y_arr = None if y is None else np.asarray(y)
    _validate_plan_binding(X_arr, y_arr, plan, groups)

    train_indices = plan.train_indices
    test_indices = plan.test_indices
    X_train = build_dataset_like(X_arr[train_indices], X_source)
    X_test = build_dataset_like(X_arr[test_indices], X_source)

    source_sample_axis = getattr(X_source, "sample_axis", None)
    if source_sample_axis is not None:
        train_axis = slice_axis_for_indices(source_sample_axis, train_indices)
        test_axis = slice_axis_for_indices(source_sample_axis, test_indices)
        if train_axis is not None:
            X_train.sample_axis = train_axis
        if test_axis is not None:
            X_test.sample_axis = test_axis

    if y_arr is not None:
        X_train.target = y_arr[train_indices]
        X_test.target = y_arr[test_indices]
        resolved_context = target_context.model_copy(deep=True) if target_context is not None else TargetContext()
        X_train.target_context = resolved_context.model_copy(deep=True)
        X_test.target_context = resolved_context.model_copy(deep=True)
    else:
        # A predictor can carry stale target semantics even when no usable
        # target values were bound. Do not let those labels describe an empty
        # response in either output partition.
        X_train.target_context = TargetContext()
        X_test.target_context = TargetContext()

    source_binding = getattr(X_source, "meta", {}).get("supervision_binding")
    for output in (X_train, X_test):
        output.meta.pop("supervision_binding", None)
    if isinstance(source_binding, dict) and y_arr is not None:
        authority = admit_target_authority(source_binding.get("target_authority"), optional=False)
        assert authority is not None
        group_column = source_binding.get("group_column")
        if group_column is None or isinstance(group_column, str):
            for output in (X_train, X_test):
                # A whole-group test partition is independent validation
                # evidence, not a new training-supervision authority. Keep
                # its source receipt removed even though a one-group column
                # is now valid metadata on the original input dataset.
                if output is X_test and plan.held_out_groups is not None:
                    continue
                try:
                    rebound = bind_sample_table_supervision(
                        output,
                        target_column=authority.column,
                        target_type=authority.target_type,
                        group_column=group_column,
                        target_authority=authority,
                    )
                except ValueError as exc:
                    # A valid partition can contain only one class. Such a
                    # subset cannot carry a categorical target receipt.
                    if str(exc) != "categorical sample-table targets require at least two classes":
                        raise
                    continue
                if np.array_equal(np.asarray(output.target), rebound.target):
                    output.meta["supervision_binding"] = {
                        **rebound.record,
                        "supervision_binding_sha256": rebound.digest,
                    }

    provenance = plan.as_dict()
    provenance["split"] = "train"
    add_processing_step(X_train, "data.train_test_split", provenance, node_id=node_id)
    provenance = plan.as_dict()
    provenance["split"] = "test"
    add_processing_step(X_test, "data.train_test_split", provenance, node_id=node_id)

    outputs: dict[str, object] = {
        "X_train": X_train,
        "X_test": X_test,
        "train_indices": train_indices,
        "test_indices": test_indices,
    }
    if y_arr is not None:
        outputs["y_train"] = y_arr[train_indices]
        outputs["y_test"] = y_arr[test_indices]
    return outputs


def space_filling_coverage(
    X: np.ndarray,
    plan: SplitPlan,
    y: np.ndarray | None = None,
) -> dict[str, float]:
    """Summarize nearest-neighbour coverage for a space-filling training set."""

    if plan.method not in _SPACE_FILLING_METHODS:
        raise ValueError("coverage is defined only for space-filling partitions")
    X_arr = np.asarray(X, dtype=np.float64)
    if plan.method == "spxy":
        if y is None:
            raise ValueError("spxy coverage requires the target values used to construct the partition")
    _validate_plan_binding(X_arr, None if y is None else np.asarray(y), plan)
    if plan.method == "spxy":
        assert y is not None
        full_distances = _spxy_distance_matrix(X_arr, np.asarray(y))
        distances = full_distances[np.ix_(plan.train_indices, plan.train_indices)]
    else:
        projected = _project_samples(X_arr, plan.n_components)
        distances = _pairwise_distances(projected[plan.train_indices], plan.distance_metric)
    np.fill_diagonal(distances, np.inf)
    nearest = distances.min(axis=1)
    return {
        "mean_nn_distance": float(np.mean(nearest)),
        "max_nn_distance": float(np.max(nearest)),
        "min_nn_distance": float(np.min(nearest)),
    }


__all__ = [
    "DISTANCE_METRICS",
    "SPLIT_METHODS",
    "SPLIT_PLAN_SCHEMA",
    "SplitPlan",
    "bind_split_groups",
    "bind_split_target",
    "materialize_split_outputs",
    "plan_train_test_split",
    "space_filling_coverage",
]
