"""
Combinatorial coverage: all 17 ready templates × up to 6 datasets each (WIP excluded).

For every (template, source, dataset_name) combination:
  1. Build a DAGExecutor from the template YAML, overriding the data node
     parameters to use the requested dataset/source.
  2. Execute the full pipeline.
  3. Record per-node PASS / FAIL / SKIP.

At the end, the collection test ``test_no_template_fully_broken`` asserts that
every template has at least one dataset that makes ALL core nodes pass.

Run with:
    cd spectra-sherpa
    python -m pytest tests/test_matrix_template_dataset.py -v --no-cov 2>&1 | tee matrix_results.txt

To see the summary table of failures:
    python -m pytest tests/test_matrix_template_dataset.py -v --no-cov -s 2>&1 | grep -E "FAIL|PASS|SKIP|summary"
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from spectra_sherpa.app.services.dag.executor import DAGExecutor, WorkflowEdge, WorkflowNode

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "data" / "templates"

# ---------------------------------------------------------------------------
# Node categories that are "output-only" — failures here are not blocking.
# (They depend on display / serialization infra that may not be present.)
# ---------------------------------------------------------------------------

_OUTPUT_NODE_TYPES = {"output.plot", "output.export"}

# ---------------------------------------------------------------------------
# Dataset overrides  ─  (source, dataset_key, override_params)
# ---------------------------------------------------------------------------
# Each entry supplies the parameters used to override the template's data node.
# We always replace the entire source + dataset_name to avoid leftover keys.


def _ev(name: str) -> dict:
    """Eigenvector override params."""
    return {"source": "eigenvector", "eigenvector_dataset": name}


def _sk(name: str) -> dict:
    """Sklearn override params."""
    return {"source": "sklearn", "sklearn_dataset": name}


def _scp(name: str) -> dict:
    """SpectroChemPy example override params."""
    return {"source": "spectrochempy", "example_dataset": name}


# ---------------------------------------------------------------------------
# Full test matrix
# ---------------------------------------------------------------------------
# (slug, label, data_params)
# Each template gets up to 5 dataset variants.
# "label" is a short human-readable identifier for parametrize output.

MATRIX: list[tuple[str, str, dict]] = [
    # ── classification_plsda ──────────────────────────────────────────────
    ("classification_plsda", "wine", _sk("wine")),
    ("classification_plsda", "iris", _sk("iris")),
    ("classification_plsda", "breast_cancer", _sk("breast_cancer")),
    ("classification_plsda", "digits", _sk("digits")),
    ("classification_plsda", "corn_m5_ev", _ev("corn_m5")),  # no class labels → expected fail
    # ── efa_analysis ──────────────────────────────────────────────────────
    ("efa_analysis", "irdata", _scp("irdata")),
    ("efa_analysis", "ramandata", _scp("ramandata")),
    ("efa_analysis", "diesel_nir", _ev("diesel_nir")),
    ("efa_analysis", "corn_m5", _ev("corn_m5")),
    ("efa_analysis", "nir_shootout1", _ev("nir_shootout_cal1")),
    ("efa_analysis", "als2004", _scp("matlabdata/als2004dataset.MAT")),
    # ── hierarchical_clustering ───────────────────────────────────────────
    ("hierarchical_clustering", "wine", _sk("wine")),
    ("hierarchical_clustering", "iris", _sk("iris")),
    ("hierarchical_clustering", "breast_cancer", _sk("breast_cancer")),
    ("hierarchical_clustering", "diesel_nir", _ev("diesel_nir")),
    ("hierarchical_clustering", "corn_m5", _ev("corn_m5")),
    # ── knn_classification ────────────────────────────────────────────────
    ("knn_classification", "wine", _sk("wine")),
    ("knn_classification", "iris", _sk("iris")),
    ("knn_classification", "breast_cancer", _sk("breast_cancer")),
    ("knn_classification", "digits", _sk("digits")),
    ("knn_classification", "corn_m5_ev", _ev("corn_m5")),  # no class labels → expected fail
    # ── mcr_als ───────────────────────────────────────────────────────────
    ("mcr_als", "irdata", _scp("irdata")),
    ("mcr_als", "nir_shootout_test1", _ev("nir_shootout_test1")),  # replaces ramandata (1 sample only)
    ("mcr_als", "diesel_nir", _ev("diesel_nir")),
    ("mcr_als", "corn_m5", _ev("corn_m5")),
    ("mcr_als", "nir_shootout1", _ev("nir_shootout_cal1")),
    ("mcr_als", "als2004", _scp("matlabdata/als2004dataset.MAT")),
    # ── mcr_als_kinetics ──────────────────────────────────────────────────
    ("mcr_als_kinetics", "irdata", _scp("irdata")),
    ("mcr_als_kinetics", "nir_shootout_test1", _ev("nir_shootout_test1")),  # replaces ramandata (1 sample only)
    ("mcr_als_kinetics", "diesel_nir", _ev("diesel_nir")),
    ("mcr_als_kinetics", "corn_m5", _ev("corn_m5")),
    ("mcr_als_kinetics", "cgl_nir", _ev("cgl_nir")),
    ("mcr_als_kinetics", "als2004", _scp("matlabdata/als2004dataset.MAT")),
    # ── oes_process_monitoring ────────────────────────────────────────────
    ("oes_process_monitoring", "metal_etch_oes", _ev("metal_etch_oes")),
    ("oes_process_monitoring", "diesel_nir", _ev("diesel_nir")),
    ("oes_process_monitoring", "corn_m5", _ev("corn_m5")),
    ("oes_process_monitoring", "wine", _sk("wine")),
    ("oes_process_monitoring", "irdata", _scp("irdata")),
    # ── pca ───────────────────────────────────────────────────────────────
    ("pca", "irdata", _scp("irdata")),
    ("pca", "diesel_nir", _ev("diesel_nir")),
    ("pca", "corn_m5", _ev("corn_m5")),
    ("pca", "wine", _sk("wine")),
    ("pca", "nir_shootout1", _ev("nir_shootout_cal1")),
    # ── pca_exploratory ───────────────────────────────────────────────────
    ("pca_exploratory", "irdata", _scp("irdata")),
    ("pca_exploratory", "diesel_nir", _ev("diesel_nir")),
    ("pca_exploratory", "corn_m5", _ev("corn_m5")),
    ("pca_exploratory", "wine", _sk("wine")),
    ("pca_exploratory", "cgl_nir", _ev("cgl_nir")),
    # ── peaks ─────────────────────────────────────────────────────────────
    ("peaks", "irdata", _scp("irdata")),
    ("peaks", "ramandata", _scp("ramandata")),
    ("peaks", "als2004", _scp("matlabdata/als2004dataset.MAT")),
    ("peaks", "diesel_nir", _ev("diesel_nir")),
    ("peaks", "diesel_nir_mat", _ev("diesel_nir_mat")),
    ("peaks", "corn_m5", _ev("corn_m5")),
    ("peaks", "cgl_nir", _ev("cgl_nir")),
    ("peaks", "nir_shootout1", _ev("nir_shootout_cal1")),
    ("peaks", "nir_shootout_test1", _ev("nir_shootout_test1")),
    ("peaks", "metal_etch_oes", _ev("metal_etch_oes")),
    # ── pls_calibration ───────────────────────────────────────────────────
    ("pls_calibration", "corn_m5", _ev("corn_m5")),
    ("pls_calibration", "diesel_nir", _ev("diesel_nir")),
    ("pls_calibration", "nir_shootout1", _ev("nir_shootout_cal1")),
    ("pls_calibration", "cgl_nir", _ev("cgl_nir")),
    ("pls_calibration", "diesel_nir_mat", _ev("diesel_nir_mat")),
    # ── preprocessing ─────────────────────────────────────────────────────
    ("preprocessing", "irdata", _scp("irdata")),
    ("preprocessing", "diesel_nir", _ev("diesel_nir")),
    ("preprocessing", "corn_m5", _ev("corn_m5")),
    ("preprocessing", "wine", _sk("wine")),
    ("preprocessing", "ramandata", _scp("ramandata")),
    # ── region_selection_pls ──────────────────────────────────────────────
    ("region_selection_pls", "corn_m5", _ev("corn_m5")),
    ("region_selection_pls", "diesel_nir", _ev("diesel_nir")),
    ("region_selection_pls", "nir_shootout1", _ev("nir_shootout_cal1")),
    ("region_selection_pls", "cgl_nir", _ev("cgl_nir")),
    ("region_selection_pls", "diesel_nir_mat", _ev("diesel_nir_mat")),
    # ── simca_classification ──────────────────────────────────────────────
    ("simca_classification", "wine", _sk("wine")),
    ("simca_classification", "iris", _sk("iris")),
    ("simca_classification", "breast_cancer", _sk("breast_cancer")),
    ("simca_classification", "digits", _sk("digits")),
    ("simca_classification", "corn_m5_ev", _ev("corn_m5")),  # no labels → fail expected
    # ── simca_qc ──────────────────────────────────────────────────────────
    ("simca_qc", "wine", _sk("wine")),
    ("simca_qc", "iris", _sk("iris")),
    ("simca_qc", "breast_cancer", _sk("breast_cancer")),
    ("simca_qc", "digits", _sk("digits")),
    ("simca_qc", "corn_m5_ev", _ev("corn_m5")),  # no labels → fail expected
    # ── simplisma ─────────────────────────────────────────────────────────
    ("simplisma", "irdata", _scp("irdata")),
    ("simplisma", "cgl_nir", _ev("cgl_nir")),  # replaces ramandata (1 sample only)
    ("simplisma", "diesel_nir", _ev("diesel_nir")),
    ("simplisma", "corn_m5", _ev("corn_m5")),
    ("simplisma", "nir_shootout1", _ev("nir_shootout_cal1")),
    ("simplisma", "als2004", _scp("matlabdata/als2004dataset.MAT")),
    # ── spectral_decomposition ────────────────────────────────────────────
    ("spectral_decomposition", "irdata", _scp("irdata")),
    ("spectral_decomposition", "diesel_nir", _ev("diesel_nir")),
    ("spectral_decomposition", "corn_m5", _ev("corn_m5")),
    ("spectral_decomposition", "wine", _sk("wine")),
    ("spectral_decomposition", "cgl_nir", _ev("cgl_nir")),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_template(slug: str) -> dict:
    path = TEMPLATES_DIR / f"{slug}.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw.get("template_data", raw)


def _find_data_node(td: dict) -> str:
    """Return the node_id of the first data.source node."""
    for n in td.get("nodes", []):
        if n.get("node_type") == "data.source":
            return n["node_id"]
    raise ValueError("No data.source node found in template")


def _build_executor(td: dict, data_node_id: str, data_override: dict) -> DAGExecutor:
    """Build a DAGExecutor from template_data, overriding the data node params."""
    executor = DAGExecutor()
    for n in td.get("nodes", []):
        params = dict(n.get("parameters") or {})
        if n["node_id"] == data_node_id:
            # Replace source + dataset keys wholesale
            for keep in list(params.keys()):
                if keep.endswith("_dataset") or keep == "source" or keep == "example_dataset":
                    del params[keep]
            params.update(data_override)
        executor.add_node(
            WorkflowNode(
                node_id=n["node_id"],
                node_type=n["node_type"],
                parameters=params,
            )
        )
    for e in td.get("edges", []):
        executor.add_edge(
            WorkflowEdge(
                from_node=e["from_node_id"],
                to_node=e["to_node_id"],
                from_output=e.get("from_output", "default"),
                to_input=e.get("to_input", "default"),
            )
        )
    return executor


def _node_type_map(td: dict) -> dict[str, str]:
    """Return {node_id: node_type} for all nodes in the template."""
    return {n["node_id"]: n["node_type"] for n in td.get("nodes", [])}


# ---------------------------------------------------------------------------
# Global results collector  (module-level so parametrized tests can write to it)
# ---------------------------------------------------------------------------

_RESULTS: dict[tuple[str, str], str] = {}  # (slug, label) → "pass" | "fail:msg" | "skip:msg"


# ---------------------------------------------------------------------------
# The parametrized execution test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug,label,data_params",
    [(s, l, p) for s, l, p in MATRIX],
    ids=[f"{s}::{l}" for s, l, p in MATRIX],
)
@pytest.mark.asyncio
async def test_template_x_dataset(slug: str, label: str, data_params: dict):
    """Execute a template end-to-end with a given dataset and assert no core node errors."""
    td = _load_template(slug)
    data_node_id = _find_data_node(td)
    node_types = _node_type_map(td)

    executor = _build_executor(td, data_node_id, data_params)

    key = (slug, label)
    exc_caught: Exception | None = None
    try:
        await executor.execute()
    except Exception as exc:
        exc_caught = exc

    # Non-output node IDs that must have results for the core pipeline to pass
    core_node_ids = [nid for nid, ntype in node_types.items() if ntype not in _OUTPUT_NODE_TYPES]
    core_ok = all(nid in executor.results for nid in core_node_ids)

    if exc_caught is not None:
        msg = str(exc_caught).lower()
        # Skip: SpectroChemPy not installed in this environment
        if "requires spectrochempy" in msg or "spectrochempy example dataset" in msg.replace("\n", " "):
            _RESULTS[key] = f"skip:{exc_caught}"
            pytest.skip(f"SpectroChemPy not installed: {exc_caught}")

        # Expected-fail: regression dataset fed to a classification template (no class labels)
        is_label_mismatch = (
            "target" in msg
            or "label" in msg
            or "class" in msg
            or "n_splits" in msg
            or "cv_folds" in msg
            or "categorical" in msg
            or "validation" in msg
        ) and label.endswith("_ev")
        if is_label_mismatch:
            _RESULTS[key] = f"xfail:{exc_caught}"
            pytest.xfail(f"Expected — no class labels in eigenvector dataset: {exc_caught}")

        # Tolerated: only output-only nodes failed, core pipeline succeeded
        if core_ok:
            _RESULTS[key] = "pass(output_err)"
            return

        # Real failure in a core computation node
        _RESULTS[key] = f"fail:{exc_caught}"
        pytest.fail(
            f"Template '{slug}' with dataset '{label}' — core node failed.\n"
            f"Data params: {data_params}\n"
            f"Error: {exc_caught}\n\n" + textwrap.indent(_format_node_statuses(executor, node_types), "  ")
        )

    missing = [
        f"  {nid} ({ntype}): NO RESULT"
        for nid, ntype in node_types.items()
        if ntype not in _OUTPUT_NODE_TYPES and nid not in executor.results
    ]
    if missing:
        _RESULTS[key] = "fail:missing_results"
        pytest.fail(f"Template '{slug}' + '{label}': core nodes missing results:\n" + "\n".join(missing))

    _RESULTS[key] = "pass"


# ---------------------------------------------------------------------------
# Helper: format per-node statuses for failure messages
# ---------------------------------------------------------------------------


def _format_node_statuses(executor: DAGExecutor, node_types: dict[str, str]) -> str:
    lines = ["Node results:"]
    for nid, ntype in node_types.items():
        r = executor.results.get(nid, "<MISSING>")
        if r == "<MISSING>":
            status = "✗ no result"
        elif isinstance(r, Exception):
            status = f"✗ ERROR: {r}"
        elif isinstance(r, dict):
            status = f"✓ dict keys={list(r.keys())[:5]}"
        else:
            status = f"✓ {type(r).__name__}"
        lines.append(f"  {nid} ({ntype}): {status}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Summary: assert every template has at least one passing dataset
# ---------------------------------------------------------------------------


def test_all_templates_have_at_least_one_passing_dataset():
    """
    Collect results from all parametrized runs and fail if any TEMPLATE has
    no passing dataset.  Run this AFTER the parametrized tests complete:

        pytest tests/test_matrix_template_dataset.py -v --no-cov

    This test is only meaningful when run as part of the full file.
    If _RESULTS is empty (isolated run), it is skipped.
    """
    if not _RESULTS:
        pytest.skip("No results collected — run together with parametrized tests")

    # Group by slug
    from collections import defaultdict

    by_slug: dict[str, list[str]] = defaultdict(list)
    for (slug, label), status in _RESULTS.items():
        by_slug[slug].append(status)

    all_slugs = {s for s, _, _ in MATRIX}
    fully_broken: list[str] = []

    print("\n" + "=" * 70)
    print("TEMPLATE × DATASET MATRIX RESULTS")
    print("=" * 70)

    for slug in sorted(all_slugs):
        statuses = by_slug.get(slug, [])
        n_pass = sum(1 for s in statuses if s == "pass" or s.startswith("pass("))
        n_xfail = sum(1 for s in statuses if s.startswith("xfail"))
        n_fail = sum(1 for s in statuses if s.startswith("fail"))
        n_skip = sum(1 for s in statuses if s.startswith("skip"))
        bar = f"pass={n_pass}  fail={n_fail}  skip={n_skip}  xfail={n_xfail}"
        marker = "✓" if n_pass > 0 else "✗"
        print(f"  {marker} {slug:<35} {bar}")
        if n_pass == 0 and n_fail > 0:
            fully_broken.append(slug)

    print("=" * 70)

    if fully_broken:
        details = "\n".join(
            f"  {slug}:\n" + "\n".join(f"    [{lbl}] → {st}" for (s, lbl), st in _RESULTS.items() if s == slug)
            for slug in fully_broken
        )
        pytest.fail(
            f"\nTemplates with NO passing dataset ({len(fully_broken)}):\n"
            + "\n".join(f"  • {s}" for s in fully_broken)
            + "\n\nDetails:\n"
            + details
        )
