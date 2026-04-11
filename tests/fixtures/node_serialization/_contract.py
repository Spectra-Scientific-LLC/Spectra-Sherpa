"""Shared machinery for node-serialization contract tests.

This module is not a test file itself; it's imported by both
``tests/test_node_serialization_contract.py`` (which verifies that the
current backend output still matches the checked-in fixtures) and
``tests/fixtures/node_serialization/generate.py`` (which regenerates
the fixtures when the backend intentionally changes shape).

Keeping the fixture spec here means there's a single source of truth
for (a) which nodes are pinned, (b) how to build each one, and (c)
how to normalize volatile fields before comparison.
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

# --------------------------------------------------------------------------- #
# Volatile field handling
# --------------------------------------------------------------------------- #

_UUID_PLACEHOLDER = "<uuid>"
_TIMESTAMP_PLACEHOLDER = "<timestamp>"
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_ISO_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?$"
)

# Fields whose value is intentionally replaced with a placeholder because
# it changes between runs (UUIDs, timestamps, path-dependent strings).
_VOLATILE_KEYS = {
    "dataset_id",
    "evaluation_id",
    "timestamp",
    "last_modified",
    "created_at",
    "executed_at",
    # Sklearn dataset descriptions include long text that may change when
    # sklearn versions bump.  We pin structure, not prose.
    "sklearn.description",
    "description",
}

# Fields whose value is a large numeric array (raw samples, coordinate
# data, etc.) — we pin shape, not content, to keep fixture files small
# (1 MB spectral payloads are not something git should see).  Each
# entry replaces the list value with a shape descriptor like
# ``<ndarray: shape=[80, 700]>``.
_LARGE_ARRAY_KEYS = {
    "data",
    "target",
    "predictions",
    "wavenumbers",
    "sample_labels",
    "labels",
    "feature_names",
}

# Threshold above which a list value is summarised instead of embedded
# verbatim.  Short lists (typical for metrics, axis titles, per-target
# labels) still get pinned in full so the shape assertions work.
_LARGE_ARRAY_THRESHOLD = 32


def _summarize_large_list(value: list[Any]) -> dict[str, Any]:
    """Replace a large numeric/sample-label list with a shape descriptor."""

    def _elem_type(item: Any) -> str:
        if item is None:
            return "null"
        if isinstance(item, bool):
            return "bool"
        if isinstance(item, int):
            return "int"
        if isinstance(item, float):
            return "float"
        if isinstance(item, str):
            return "str"
        if isinstance(item, list):
            return "list"
        if isinstance(item, dict):
            return "dict"
        return type(item).__name__

    # Shape descriptor works for both 1D lists (floats, sample labels)
    # and nested 2D lists (the X matrix of a SherpaDataset).
    shape: list[int] = [len(value)]
    probe: Any = value
    while isinstance(probe, list) and probe and isinstance(probe[0], list):
        shape.append(len(probe[0]))
        probe = probe[0]
    element_type = _elem_type(value[0]) if value else "unknown"
    return {
        "__array_summary__": True,
        "shape": shape,
        "element_type": element_type,
    }


def _normalize_value(value: Any, *, in_key: str | None = None) -> Any:
    """Recursively normalize volatile strings to stable placeholders.

    Handles: UUIDs, ISO-8601 timestamps, large numeric arrays (replaced
    with a shape descriptor), and nested dicts / lists.  Numbers,
    booleans, and ``None`` pass through unchanged.  ``in_key`` carries
    the parent dict key down one level so list values can be summarized
    based on which field they live under (``data``, ``wavenumbers``, ...).
    """
    if isinstance(value, str):
        if _UUID_RE.match(value):
            return _UUID_PLACEHOLDER
        if _ISO_TIMESTAMP_RE.match(value):
            return _TIMESTAMP_PLACEHOLDER
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, sub in value.items():
            if key in _VOLATILE_KEYS:
                out[key] = f"<{key}>"
                continue
            out[key] = _normalize_value(sub, in_key=key)
        return out
    if isinstance(value, list):
        if (
            in_key in _LARGE_ARRAY_KEYS
            and len(value) >= _LARGE_ARRAY_THRESHOLD
            # Only summarize if the elements look numeric-ish or stringy
            # — lists of row dicts (metrics.data) should always be pinned
            # in full, never summarized.
            and not (value and isinstance(value[0], dict))
        ):
            return _summarize_large_list(value)
        return [_normalize_value(item) for item in value]
    return value


def normalize_for_fixture(payload: Any) -> Any:
    """Return a deep-copied, volatile-field-stripped version of *payload*.

    Always JSON-round-trips first so numpy scalars, tuples, and other
    Python-native types are coerced to their JSON equivalents — otherwise
    ``serialize_result`` output (which may contain numpy scalars) would
    not equal the JSON we eventually write to disk.
    """
    roundtripped = json.loads(json.dumps(payload, default=_json_default))
    return _normalize_value(copy.deepcopy(roundtripped))


def _json_default(obj: Any) -> Any:
    """Fallback encoder for numpy/datetime/etc. values."""
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


# --------------------------------------------------------------------------- #
# Fixture specification
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FixtureSpec:
    """Declarative spec for one pinned node output.

    Attributes:
        name: File-system safe identifier; becomes ``<name>.json``.
        description: Short prose explaining why this fixture exists
            (written into the JSON file as a ``_description`` key for
            documentation and to help future readers of the fixture
            file understand intent without hunting through git history).
        builder: Callable that returns a ``NodeResult`` (awaited if
            coroutine).  The fixture captures the serialized form of
            ``result.outputs``.
    """

    name: str
    description: str
    builder: Callable[[], Any]


def _build_datasource_sklearn_wine() -> Any:
    """Multi-output data.source result from sklearn wine dataset.

    Canonical shape for ``data.source`` nodes: the outputs dict contains
    ``{default: SherpaDataset, target: numpy.ndarray}``, so after
    ``serialize_result`` the payload is ``{default: {...}, target: [...]}``.
    The dataset identity (title, backend, extra, metadata.feature_names,
    target_context) lives on ``default``, not at the top level.

    The Sherpa Advisor "dataset identity" feature (wine → Moisture/Oil/
    etc.) relies on the frontend unwrapping ``default`` correctly before
    reading these fields.  PR #16 shipped with a version that didn't
    unwrap and silently showed stale catalog state.  This fixture pins
    the exact shape so both the backend serializer and the frontend
    unwrap logic stay in lockstep.
    """
    from spectra_sherpa.app.services.dag.nodes.data.source import DataSourceNode

    node = DataSourceNode(
        node_id="data_1",
        parameters={"source": "sklearn", "sklearn_dataset": "wine"},
    )
    return asyncio.run(node.run())


def _build_datasource_eigenvector_corn() -> Any:
    """Multi-output data.source result from eigenvector corn_m5.

    Exercises the other major ``data.source`` path: Eigenvector catalog
    datasets carry continuous reference properties (Moisture, Oil,
    Protein, Starch) in ``target_context.target_names`` rather than
    sklearn's ``class_names``.  PR #13's per-target HoldoutEvaluation
    relies on these names propagating through.  Skipped gracefully if
    the eigenvector test data isn't present on this machine.
    """
    from spectra_sherpa.app.services.dag.nodes.data.source import DataSourceNode

    node = DataSourceNode(
        node_id="data_1",
        parameters={"source": "eigenvector", "eigenvector_dataset": "corn_m5"},
    )
    return asyncio.run(node.run())


def _build_holdout_regression_multitarget() -> Any:
    """HoldoutEvaluation on synthetic 4-target regression data.

    Pins the named-port output shape from PR #13:
    ``{metrics: {data: [row_dict, ...], ...}, visualization: {series:
    [{name, actual, predicted}, ...]}, predictions: [...], evaluation:
    {...}}``.  The frontend's ``holdoutVisualization`` computed reads
    from ``ports.visualization.value``, and PR #13's fix depended on
    ``metrics`` being the primary port for Quick Plot to work.  Any
    re-ordering of these ports silently breaks those consumers.
    """
    from spectra_sherpa.app.services.dag.nodes.diagnostics import HoldoutEvaluationNode

    # Deterministic seeded inputs — 20 samples × 4 targets, small noise
    # per target so the metrics differ enough to be useful in assertions.
    rng = np.random.RandomState(0)
    n, k = 20, 4
    y_true = rng.normal(size=(n, k)) * np.array(
        [0.5, 0.3, 0.8, 1.0]
    ) + np.array([10.0, 3.0, 8.0, 60.0])
    y_pred = y_true + rng.normal(scale=0.1, size=(n, k)) * np.array(
        [0.2, 1.5, 0.5, 0.8]
    )

    node = HoldoutEvaluationNode(
        node_id="eval_1", parameters={"task_type": "regression"}
    )
    return asyncio.run(
        node.run(
            y_true=y_true,
            y_pred=y_pred,
            target_names=["Moisture", "Oil", "Protein", "Starch"],
        )
    )


def _build_data_table_per_target_metrics() -> Any:
    """DataTableNode output for per-target metrics payload.

    Exercises the list-of-row-dicts path that PR #13 wired up for the
    Test Metrics panel.  The fixture pins that
    ``visualization.data == [row_dict, ...]`` remains keyed by real
    target names (not `[object Object]` from a naive String() cast).
    """
    from spectra_sherpa.app.services.dag.nodes.output.data_table_node import (
        DataTableNode,
    )

    payload = {
        "data": [
            {"target": "Moisture", "RMSEP": 0.11, "R2": 0.98, "MAE": 0.09},
            {"target": "Oil", "RMSEP": 0.22, "R2": 0.83, "MAE": 0.18},
            {"target": "Protein", "RMSEP": 0.15, "R2": 0.95, "MAE": 0.12},
            {"target": "Starch", "RMSEP": 0.20, "R2": 0.91, "MAE": 0.17},
        ],
        "metadata": {
            "type": "RegressionTest",
            "n_samples": 20,
            "n_targets": 4,
            "target_names": ["Moisture", "Oil", "Protein", "Starch"],
            "aggregate": "mean_across_targets",
            "status": "ok",
        },
    }
    node = DataTableNode(node_id="table_1", parameters={})
    return asyncio.run(node.run(payload))


FIXTURE_SPECS: tuple[FixtureSpec, ...] = (
    FixtureSpec(
        name="datasource_sklearn_wine",
        description=(
            "data.source sklearn wine — pins the multi-output wrapper "
            "shape {default: SherpaDataset, target: ndarray} and the "
            "dataset identity fields inside default (extra, metadata, "
            "target_context) that Sherpa Advisor consumes."
        ),
        builder=_build_datasource_sklearn_wine,
    ),
    FixtureSpec(
        name="datasource_eigenvector_corn_m5",
        description=(
            "data.source eigenvector corn_m5 — pins the continuous "
            "multi-target case with real reference property names "
            "(Moisture/Oil/Protein/Starch) in target_context."
        ),
        builder=_build_datasource_eigenvector_corn,
    ),
    FixtureSpec(
        name="holdout_regression_multitarget",
        description=(
            "HoldoutEvaluation regression on 20x4 targets — pins the "
            "named-port shape (metrics/visualization/predictions/"
            "evaluation), the per-target row structure in metrics.data, "
            "and the multi-target series shape in visualization."
        ),
        builder=_build_holdout_regression_multitarget,
    ),
    FixtureSpec(
        name="data_table_per_target_metrics",
        description=(
            "DataTableNode rendering of per-target HoldoutEvaluation "
            "metrics — pins the list-of-row-dicts shape that the "
            "frontend DataTableModal + outputPreview consume."
        ),
        builder=_build_data_table_per_target_metrics,
    ),
)


# --------------------------------------------------------------------------- #
# Fixture I/O
# --------------------------------------------------------------------------- #


FIXTURE_DIR = Path(__file__).resolve().parent


def fixture_path(spec: FixtureSpec) -> Path:
    return FIXTURE_DIR / f"{spec.name}.json"


def capture_fixture(spec: FixtureSpec) -> dict[str, Any]:
    """Run the spec's builder, serialize, normalize, and return the fixture dict.

    The returned dict is what gets written to disk (or compared against
    a checked-in fixture during test execution).
    """
    from spectra_sherpa.app.services.serialization import serialize_result

    result = spec.builder()
    serialized = serialize_result(result.outputs)
    payload = normalize_for_fixture(serialized)
    return {
        "_description": spec.description,
        "_spec": spec.name,
        "serialized": payload,
    }


def load_fixture(spec: FixtureSpec) -> dict[str, Any]:
    path = fixture_path(spec)
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_fixture(spec: FixtureSpec, fixture: dict[str, Any]) -> None:
    path = fixture_path(spec)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(fixture, fh, indent=2, sort_keys=False, default=_json_default)
        fh.write("\n")
