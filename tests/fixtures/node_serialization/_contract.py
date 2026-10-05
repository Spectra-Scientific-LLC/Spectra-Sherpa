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
_ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?$")

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


def _build_canonical_file_load_result() -> Any:
    """Representative canonical ``data.file_load`` result.

    The source node itself is deliberately bound to owned database identity,
    so a serialization-shape test must not bypass that authority with a fake
    path.  This deterministic result pins the public node boundary shared by
    the backend serializer and frontend consumers: named ``default`` and
    ``target`` ports, with the dataset carried under ``default``.
    """
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
    from spectra_sherpa.app.services.dag.node_base import NodeResult

    data = np.arange(240, dtype=np.float64).reshape(40, 6)
    target = np.linspace(8.0, 12.0, 40, dtype=np.float64)
    dataset = SherpaDataset(
        data,
        target=target,
        target_context=TargetContext(
            target_type="continuous",
            target_name="Moisture",
            target_names=["Moisture"],
            selected_target="Moisture",
        ),
        title="canonical-file-load",
        backend="numpy",
        extra={
            "source.experiment_id": 17,
            "source.file_id": 23,
        },
    )
    return NodeResult(outputs={"default": dataset, "target": dataset.target})


def _build_regression_evaluator_single_target() -> Any:
    """Canonical one-target evaluator metrics and visualization ports."""
    from spectra_sherpa.app.services.dag.nodes.regression_evaluator_node import RegressionEvaluatorV2Node

    rng = np.random.RandomState(0)
    y_true = rng.normal(size=20) * 0.5 + 10.0
    y_pred = y_true + rng.normal(scale=0.02, size=20)

    node = RegressionEvaluatorV2Node(node_id="eval_1", parameters={})
    return asyncio.run(node.execute(input_data=y_pred, y_true=y_true))


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
        name="file_load_canonical_result",
        description=(
            "Canonical data.file_load result — pins the named default/target "
            "wrapper and the SherpaDataset target metadata consumed by the "
            "frontend without bypassing owned source identity."
        ),
        builder=_build_canonical_file_load_result,
    ),
    FixtureSpec(
        name="regression_evaluator_single_target",
        description=(
            "Canonical one-target regression evaluator — pins the default "
            "versioned metric record and predicted-versus-actual visualization."
        ),
        builder=_build_regression_evaluator_single_target,
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
