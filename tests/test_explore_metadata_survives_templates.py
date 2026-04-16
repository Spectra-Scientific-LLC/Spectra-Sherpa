"""End-to-end regression: user-edited Data/Explore metadata must survive
through every workflow template.

The Explore page lets users assert metadata about a dataset (x-axis title,
x-axis units, y-axis / data quantity title, is_time_series flag) that is
persisted as a sidecar JSON next to the source reference. The
``data.source`` node applies these overrides when the dataset is loaded.

This test monkeypatches ``load_prepared_data_overrides_for_source`` so that
every template's ``data_1`` node receives a known-good ``PreparedDataOverrides``
payload, then executes the DAG and asserts that every terminal
``SherpaDataset`` still carries the override-derived metadata (accounting for
legitimate node-level rewrites like PCA loadings renaming the feature axis
to "Principal Component").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

import spectra_sherpa.app.services.dag.nodes.data.source as source_module
from spectra_sherpa.app.lib.scp_compat import HAS_SCP
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.executor import DAGExecutor, WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.prepared_data import PreparedDataOverrides

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "data" / "templates"

# Expected override payload — mirrors what a user would enter on Explore.
EXPECTED_X_TITLE = "Wavelength"
EXPECTED_X_UNITS = "nm"
EXPECTED_Y_TITLE = "Absorbance"
EXPECTED_IS_TIME_SERIES = True

# Feature-axis titles that legitimately replace "Wavelength" downstream because
# the node's output columns are *no longer* wavelengths (e.g. PCA loadings are
# indexed by component, not wavelength).  When we see one of these titles we
# skip the x_title/x_units propagation assertions for that port.
KNOWN_NEW_X_TITLES = (
    "Principal Component",
    "Latent Variable",
    "Component",
    "Components",
    "PC",
    "LV",
    "Source",
    "Pure Component",
    "Cluster",
    "Eigenvalue",
)

# Templates whose data_1 node gets overridden to an eigenvector corn_m5 dataset
# (small, fast, NIR — consistent with the existing regression-test baseline).
_EIGENVECTOR_CORN_OVERRIDE = {"source": "eigenvector", "eigenvector_dataset": "corn_m5"}
# Classification templates need a categorical-target dataset.  sklearn iris
# is small (150 samples × 4 features), discrete-class, and always available.
_SKLEARN_IRIS_OVERRIDE = {"source": "sklearn", "sklearn_dataset": "iris"}

TEMPLATES: list[tuple[str, bool, dict]] = [
    # (slug, requires_scp_after_override, data_1_override)
    # None of these fundamentally require SCP once data_1 is overridden, but
    # we keep the hook in place in case a template adds an SCP-only node later.
    ("preprocessing", False, _EIGENVECTOR_CORN_OVERRIDE),
    ("pca_exploratory", False, _EIGENVECTOR_CORN_OVERRIDE),
    ("pls_calibration", False, _EIGENVECTOR_CORN_OVERRIDE),
    ("mcr_als", False, _EIGENVECTOR_CORN_OVERRIDE),
    ("simplisma", False, _EIGENVECTOR_CORN_OVERRIDE),
    ("spectral_decomposition", False, _EIGENVECTOR_CORN_OVERRIDE),
    ("classification_plsda", False, _SKLEARN_IRIS_OVERRIDE),
    ("simca_classification", False, _SKLEARN_IRIS_OVERRIDE),
    ("hierarchical_clustering", False, _EIGENVECTOR_CORN_OVERRIDE),
    ("efa_analysis", False, _EIGENVECTOR_CORN_OVERRIDE),
]


def _load_template(slug: str) -> dict:
    raw = yaml.safe_load((TEMPLATES_DIR / f"{slug}.yaml").read_text(encoding="utf-8"))
    return raw.get("template_data", raw)


def _build_executor(td: dict, overrides: dict[str, dict]) -> tuple[DAGExecutor, dict[str, str]]:
    """Build a DAGExecutor from a template dict, applying ``overrides`` to
    the matching node_ids.  When a node is overridden, source-selecting
    parameters from the template are purged first so the override wins."""
    executor = DAGExecutor()
    node_types: dict[str, str] = {}

    for node in td.get("nodes", []):
        params = dict(node.get("parameters") or {})
        if node["node_id"] in overrides:
            for keep in list(params.keys()):
                if keep.endswith("_dataset") or keep in {"source", "example_dataset", "example_file"}:
                    del params[keep]
            params.update(overrides[node["node_id"]])
        executor.add_node(
            WorkflowNode(
                node_id=node["node_id"],
                node_type=node["node_type"],
                parameters=params,
            )
        )
        node_types[node["node_id"]] = node["node_type"]

    for edge in td.get("edges", []):
        executor.add_edge(
            WorkflowEdge(
                from_node=edge["from_node_id"],
                to_node=edge["to_node_id"],
                from_output=edge.get("from_output", "default"),
                to_input=edge.get("to_input", "default"),
            )
        )

    return executor, node_types


def _patched_overrides_factory() -> PreparedDataOverrides:
    return PreparedDataOverrides(
        x_title=EXPECTED_X_TITLE,
        x_units=EXPECTED_X_UNITS,
        y_title=EXPECTED_Y_TITLE,
        is_time_series=EXPECTED_IS_TIME_SERIES,
    )


def _install_overrides_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the data.source override loader with one that always returns
    the expected PreparedDataOverrides payload, regardless of arguments."""

    def _fake_loader(**_kwargs: Any) -> PreparedDataOverrides:
        return _patched_overrides_factory()

    monkeypatch.setattr(
        source_module,
        "load_prepared_data_overrides_for_source",
        _fake_loader,
    )


def _is_node_overridden_x_title(feature_axis_title: str | None) -> bool:
    """True if the port's feature axis was intentionally re-titled by a
    downstream node (e.g. PCA loadings → 'Principal Component').  Such ports
    legitimately drop the user-supplied x_title/x_units and should not be
    asserted against."""
    if not feature_axis_title:
        return False
    return any(known in feature_axis_title for known in KNOWN_NEW_X_TITLES)


def _input_row_count(executor: DAGExecutor) -> int:
    """Row count of the data_1 output — used to decide whether a downstream
    port preserved the sample axis (rows still = samples) or not (e.g.
    loadings have row count = n_components)."""
    src = executor.results.get("data_1")
    if src is None:
        return 0
    if hasattr(src, "shape"):
        try:
            return int(src.shape[0])
        except Exception:
            return 0
    if isinstance(src, dict):
        for v in src.values():
            if isinstance(v, SherpaDataset):
                try:
                    return int(v.shape[0])
                except Exception:
                    continue
            if hasattr(v, "shape") and not callable(v.shape):
                try:
                    return int(v.shape[0])
                except Exception:
                    continue
    return 0


def _iter_terminal_datasets(executor: DAGExecutor, node_types: dict[str, str]) -> list[tuple[str, str, SherpaDataset]]:
    """Yield (node_id, port_name, dataset) for every SherpaDataset produced
    by ANY non-output node in the DAG (not just exit nodes).

    Templates' true exit nodes are typically output sinks (output.plot /
    output.export / output.data_table) — those don't carry a dataset to
    assert on. The dataset the user actually sees in View Data is the
    one feeding INTO the sink (the model / decomposition node). So we
    iterate every result and pick out SherpaDataset payloads on every
    non-sink node, which gives broader coverage of metadata propagation
    along the whole pipeline."""
    skip_node_types = {"output.plot", "output.export", "output.data_table"}
    # Also skip data_1 itself — its overrides are asserted by the
    # baseline test; here we want to verify propagation to *downstream*
    # nodes only.
    skip_node_ids = {"data_1"}
    out: list[tuple[str, str, SherpaDataset]] = []
    for node_id, result in executor.results.items():
        if node_id in skip_node_ids:
            continue
        if node_types.get(node_id) in skip_node_types:
            continue
        if isinstance(result, SherpaDataset):
            out.append((node_id, "default", result))
        elif isinstance(result, dict):
            for port, value in result.items():
                if isinstance(value, SherpaDataset):
                    out.append((node_id, port, value))
    return out


# ────────────────────────────────────────────────────────────────────────────
# Sanity baseline — proves the monkeypatch itself works before we start
# chasing propagation through downstream nodes.
# ────────────────────────────────────────────────────────────────────────────
async def test_baseline_data_source_receives_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the ``data_1`` node only and verify the monkeypatched overrides
    actually reach the dataset.  If this fails, every downstream assertion
    in the parametrized tests is suspect."""
    _install_overrides_patch(monkeypatch)
    td = _load_template("pca_exploratory")
    executor, _ = _build_executor(td, {"data_1": _EIGENVECTOR_CORN_OVERRIDE})

    await executor.execute_node("data_1")

    result = executor.results.get("data_1")
    assert result is not None, "data_1 produced no result"

    dataset: SherpaDataset | None
    if isinstance(result, SherpaDataset):
        dataset = result
    elif isinstance(result, dict):
        dataset = result.get("default")
        assert isinstance(dataset, SherpaDataset), f"data_1 default port is {type(result.get('default'))!r}"
    else:
        dataset = None
    assert isinstance(dataset, SherpaDataset), f"data_1 returned {type(result)!r}, not SherpaDataset"

    fa = dataset.feature_axis
    assert fa is not None, "corn_m5 should have a feature axis"
    assert fa.title == EXPECTED_X_TITLE, f"baseline: feature_axis.title = {fa.title!r}, expected {EXPECTED_X_TITLE!r}"
    assert fa.units == EXPECTED_X_UNITS, f"baseline: feature_axis.units = {fa.units!r}, expected {EXPECTED_X_UNITS!r}"

    assert (
        dataset.meta.get("x_title") == EXPECTED_X_TITLE
    ), f"baseline: meta['x_title'] = {dataset.meta.get('x_title')!r}"
    assert (
        dataset.meta.get("x_units") == EXPECTED_X_UNITS
    ), f"baseline: meta['x_units'] = {dataset.meta.get('x_units')!r}"
    assert (
        dataset.meta.get("data_quantity") == EXPECTED_Y_TITLE
    ), f"baseline: meta['data_quantity'] = {dataset.meta.get('data_quantity')!r}"
    assert dataset.is_time_series is EXPECTED_IS_TIME_SERIES, f"baseline: is_time_series = {dataset.is_time_series!r}"

    # The corn_m5 catalog entry is NIR; domain.technique should reflect that.
    assert dataset.domain.technique, "baseline: domain.technique should be set for corn_m5 (NIR)"


# ────────────────────────────────────────────────────────────────────────────
# Per-template propagation assertions
# ────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "slug,override",
    [
        pytest.param(
            slug,
            override,
            marks=([pytest.mark.skipif(not HAS_SCP, reason="requires SCP")] if requires_scp else []),
        )
        for slug, requires_scp, override in TEMPLATES
    ],
)
async def test_explore_metadata_survives_template(slug: str, override: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_overrides_patch(monkeypatch)
    td = _load_template(slug)
    executor, node_types = _build_executor(td, {"data_1": override})

    await executor.execute()

    input_rows = _input_row_count(executor)
    assert input_rows > 0, f"template {slug}: could not determine data_1 row count"

    terminals = _iter_terminal_datasets(executor, node_types)
    # At least one terminal dataset must exist for the assertions to mean
    # anything — a template that produces only plots/exports would pass
    # vacuously otherwise.
    assert terminals, f"template {slug}: no terminal SherpaDataset outputs to assert on"

    for node_id, port, ds in terminals:
        ctx = f"template {slug}: terminal {node_id}.{port}"

        # Always — is_spectra / spectral_technique sanity.
        # NOTE: is_spectra / spectral_technique are derived from domain.technique.
        # For the corn_m5 baseline (NIR) these should be truthy unless a node
        # explicitly wipes them out.
        technique = ds.domain.technique if ds.domain is not None else None
        assert technique, f"{ctx}: domain.technique dropped (expected NIR-ish, got {technique!r})"

        fa = ds.feature_axis
        fa_title = fa.title if fa is not None else None

        # x_title / x_units survive unless the node legitimately re-titled
        # the feature axis (e.g. PCA loadings → 'Principal Component').
        if not _is_node_overridden_x_title(fa_title):
            assert fa is not None, f"{ctx}: feature_axis missing (expected title={EXPECTED_X_TITLE!r})"
            assert (
                fa.title == EXPECTED_X_TITLE
            ), f"{ctx}: feature_axis.title = {fa.title!r} (expected {EXPECTED_X_TITLE!r})"
            assert (
                fa.units == EXPECTED_X_UNITS
            ), f"{ctx}: feature_axis.units = {fa.units!r} (expected {EXPECTED_X_UNITS!r})"
            assert (
                ds.meta.get("x_title") == EXPECTED_X_TITLE
            ), f"{ctx}: meta['x_title'] = {ds.meta.get('x_title')!r} (expected {EXPECTED_X_TITLE!r})"
            assert (
                ds.meta.get("x_units") == EXPECTED_X_UNITS
            ), f"{ctx}: meta['x_units'] = {ds.meta.get('x_units')!r} (expected {EXPECTED_X_UNITS!r})"

        # is_time_series is only meaningful on ports whose rows are still
        # samples (row count == input row count).  Loadings/pure spectra/etc.
        # have row count = n_components and is_time_series is irrelevant.
        try:
            port_rows = int(ds.shape[0])
        except Exception:
            port_rows = -1
        if port_rows == input_rows:
            assert ds.is_time_series is True, (
                f"{ctx}: is_time_series = {ds.is_time_series!r} " f"(rows preserved at {port_rows}, expected True)"
            )

        # data_quantity (y_title) is a soft-assert: many nodes legitimately
        # rewrite it (e.g. scores are dimensionless), but any port that
        # preserves the sample axis should also preserve data_quantity.
        if port_rows == input_rows:
            dq = ds.meta.get("data_quantity") or (ds.domain.data_quantity if ds.domain is not None else None)
            # Permit nodes to downgrade y_title to a different scientific
            # label (e.g. "Intensity") but flag silent drops to empty/None.
            assert dq, f"{ctx}: data_quantity dropped to {dq!r} on a sample-axis-preserving port"
