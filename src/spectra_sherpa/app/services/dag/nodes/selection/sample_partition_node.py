"""Sample partitioning node — chemometric calibration design.

Registered as ``selection.sample_partition``.

Consolidates random, stratified, sequential, Kennard-Stone, and DUPLEX
splitting strategies into a single node with chemometric output semantics
(X_cal / X_test / y_cal / y_test / cal_indices / test_indices / diagnostics).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

from ...io_contracts import bind_X, bind_y, build_dataset_like, to_numpy_2d, to_numpy_y
from ...node_base import Node, NodeMetadata, NodeParameter, NodeResult, PortMetadata, register_node
from ..data._utils import slice_axis_for_indices

logger = logging.getLogger(__name__)


@register_node
class SamplePartitionNode(Node):
    """Partition dataset into calibration and test sets.

    Supports both generic ML strategies (random, stratified, sequential)
    and chemometric space-filling designs (Kennard-Stone, DUPLEX) that
    ensure representative coverage of the spectral X-space.

    Multi-output node with calibration/test datasets, indices, and
    coverage diagnostics.
    """

    metadata = NodeMetadata(
        node_type="selection.sample_partition",
        category="selection",
        label="Sample Partition",
        description="Split data into calibration/test sets using chemometric or statistical designs",
        parameters=[
            NodeParameter(
                name="method",
                label="Partition Method",
                param_type="select",
                options=[
                    {"label": "Random", "value": "random"},
                    {"label": "Stratified", "value": "stratified"},
                    {"label": "Sequential", "value": "sequential"},
                    {"label": "Kennard-Stone", "value": "kennard_stone"},
                    {"label": "DUPLEX", "value": "duplex"},
                    {"label": "SPXY (joint X+Y)", "value": "spxy"},
                ],
                default="kennard_stone",
                description="How to partition samples between calibration and test sets",
                required=True,
            ),
            NodeParameter(
                name="test_size",
                label="Test Size",
                param_type="number",
                default=0.2,
                min_value=0.01,
                max_value=0.99,
                step=0.05,
                description="Fraction of data to use for testing (0.2 = 20%)",
                required=True,
            ),
            NodeParameter(
                name="metric",
                label="Distance Metric",
                param_type="select",
                options=["euclidean", "mahalanobis", "correlation"],
                default="euclidean",
                description="Distance metric for space-filling algorithms",
                required=False,
                category="advanced",
                visible_when={"method": ["kennard_stone", "duplex", "spxy"]},
            ),
            NodeParameter(
                name="n_pcs",
                label="PCA Components",
                param_type="number",
                default=0,
                min_value=0,
                max_value=50,
                step=1,
                description="Reduce to N PCA components before distance calc (0 = no reduction)",
                required=False,
                category="advanced",
                visible_when={"method": ["kennard_stone", "duplex", "spxy"]},
                hint="Recommended for high-dimensional spectra (>500 features) to avoid distance degeneracy",
            ),
            NodeParameter(
                name="random_seed",
                label="Random Seed",
                param_type="number",
                default=42,
                description="Seed for reproducible random splits",
                required=False,
                visible_when={"method": ["random", "stratified"]},
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Data",
                description="Full dataset to partition",
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Target Values (optional)",
                description="Target array for stratified splitting or pass-through",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="X_cal",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Calibration Data",
                description="Calibration subset (training)",
            ),
            PortMetadata(
                name="X_test",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Test Data",
                description="Test subset (validation)",
            ),
            PortMetadata(
                name="y_cal",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Calibration Targets",
            ),
            PortMetadata(
                name="y_test",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Test Targets",
            ),
            PortMetadata(
                name="cal_indices",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
                label="Calibration Indices",
                description="Integer indices of calibration samples in original data",
            ),
            PortMetadata(
                name="test_indices",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
                label="Test Indices",
                description="Integer indices of test samples in original data",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        diagnostics=["n_cal", "n_test", "method", "coverage"],
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        params = self._resolve_params()
        method = params.get("method", "kennard_stone")
        test_size = params.get("test_size", 0.2)

        X_expr = inputs.get("X", inputs.get("default", "input_data"))
        y_expr = inputs.get("y")
        lines: list[str] = []
        lines.append(f"{indent}# --- Sample Partition ({self.node_id}) ---")
        lines.append(f"{indent}# Method: {method}, test_size: {test_size}")
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(
            f"{indent}_X_data = np.asarray("
            f"_X_input.data if hasattr(_X_input, 'data') else _X_input, dtype=np.float64)"
        )
        if y_expr:
            lines.append(f"{indent}_raw_y = {y_expr}")
        else:
            lines.append(
                f"{indent}_raw_y = ("
                f"_X_input.target if hasattr(_X_input, 'target') and getattr(_X_input, 'target', None) is not None "
                f"else None)"
            )
        lines.append(f"{indent}_y_data = None if _raw_y is None else np.asarray(_raw_y, dtype=np.float64)")
        lines.append(f"{indent}_n = _X_data.shape[0]")
        lines.append(f"{indent}_n_test = int(_n * {test_size})")
        lines.append(f"{indent}_n_cal = _n - _n_test")

        if method == "kennard_stone":
            metric = params.get("metric", "euclidean")
            lines.append(f"{indent}# Kennard-Stone: greedy maximin in {metric} space")
            lines.append(
                f"{indent}from spectra_sherpa.app.services.dag.nodes.selection._sample_algorithms import kennard_stone"
            )
            lines.append(f"{indent}_cal_idx = kennard_stone(_X_data, _n_cal, metric='{metric}')")
            lines.append(f"{indent}_test_idx = np.setdiff1d(np.arange(_n), _cal_idx)")
        elif method == "duplex":
            metric = params.get("metric", "euclidean")
            lines.append(
                f"{indent}from spectra_sherpa.app.services.dag.nodes.selection._sample_algorithms import duplex"
            )
            lines.append(f"{indent}_cal_idx, _test_idx = duplex(_X_data, _n_cal, metric='{metric}')")
        elif method == "spxy":
            metric = params.get("metric", "euclidean")
            lines.append(f"{indent}from spectra_sherpa.app.services.dag.nodes.selection._sample_algorithms import spxy")
            lines.append(f"{indent}if _y_data is None:")
            lines.append(f"{indent}    raise ValueError('SPXY requires target values (y)')")
            lines.append(f"{indent}_cal_idx, _test_idx = spxy(_X_data, _y_data, _n_cal, metric='{metric}')")
        elif method == "stratified":
            seed = int(params.get("random_seed", 42))
            lines.append(f"{indent}from sklearn.model_selection import train_test_split")
            lines.append(f"{indent}if _y_data is None:")
            lines.append(f"{indent}    raise ValueError('Stratified partition requires target values (y)')")
            lines.append(f"{indent}_cal_idx, _test_idx = train_test_split(")
            lines.append(f"{indent}    np.arange(_n), test_size={test_size}, random_state={seed},")
            lines.append(f"{indent}    stratify=_y_data, shuffle=True)")
        else:
            # random or sequential
            lines.append(f"{indent}_indices = np.arange(_n)")
            if method != "sequential":
                seed = int(params.get("random_seed", 42))
                lines.append(f"{indent}np.random.RandomState({seed}).shuffle(_indices)")
            lines.append(f"{indent}_cal_idx = _indices[:_n_cal]")
            lines.append(f"{indent}_test_idx = _indices[_n_cal:]")

        lines.append(f"{indent}_X_cal = _X_data[_cal_idx]")
        lines.append(f"{indent}_X_test = _X_data[_test_idx]")
        lines.append(f"{indent}_y_cal = _y_data[_cal_idx] if _y_data is not None else None")
        lines.append(f"{indent}_y_test = _y_data[_test_idx] if _y_data is not None else None")
        if use_scp:
            lines.append(f"{indent}from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset")
            lines.append(
                f"{indent}_X_cal_ds = SherpaDataset("
                f"X=_X_cal, feature_axis=getattr(_X_input, 'feature_axis', None), target=_y_cal)"
            )
            lines.append(
                f"{indent}_X_test_ds = SherpaDataset("
                f"X=_X_test, feature_axis=getattr(_X_input, 'feature_axis', None), target=_y_test)"
            )
        else:
            lines.append(f"{indent}_x_axis = getattr(_X_input, 'x', None)")
            lines.append(
                f"{indent}_X_cal_ds = _Result("
                f"_X_cal, x=_x_axis, target=_y_cal, target_names=getattr(_X_input, 'target_names', None))"
            )
            lines.append(
                f"{indent}_X_test_ds = _Result("
                f"_X_test, x=_x_axis, target=_y_test, target_names=getattr(_X_input, 'target_names', None))"
            )
        lines.append(f'{indent}print(f"  Partition ({method}): {{len(_cal_idx)}} cal, {{len(_test_idx)}} test")')
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'X_cal': _X_cal_ds, 'X_test': _X_test_ds,")
        lines.append(f"{indent}    'cal_indices': _cal_idx, 'test_indices': _test_idx,")
        lines.append(f"{indent}}}")
        lines.append(f"{indent}if _y_data is not None:")
        lines.append(f"{indent}    results['{self.node_id}']['y_cal'] = _y_cal")
        lines.append(f"{indent}    results['{self.node_id}']['y_test'] = _y_test")

        return lines

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> NodeResult:
        params = self._resolve_params()
        method = params.get("method", "kennard_stone")
        test_size = float(params.get("test_size", 0.2))
        metric = params.get("metric", "euclidean")
        n_pcs = int(params.get("n_pcs", 0)) or None
        random_seed = int(params.get("random_seed", 42))

        X_ds = bind_X(
            X,
            missing_message="Missing required input: X (dataset)",
            dataset_error_message="X must be an NDDataset or SherpaDataset",
            allow_array=True,
        )
        y_value = bind_y(y, X=X_ds, required=False, infer_from_X=True, dataset_as_data=False)

        X_array = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_array = to_numpy_y(y_value, name="y", expected_samples=X_array.shape[0]) if y_value is not None else None

        n_samples = X_array.shape[0]
        n_test = int(n_samples * test_size)
        n_cal = n_samples - n_test

        if n_test < 1 or n_cal < 2:
            raise ValueError(
                f"test_size={test_size} gives {n_cal} cal / {n_test} test samples. "
                f"Need >= 2 calibration and >= 1 test samples."
            )

        # --- Compute indices ---
        if method == "kennard_stone":
            from ._sample_algorithms import kennard_stone

            cal_idx = kennard_stone(X_array, n_cal, metric=metric, n_pcs=n_pcs)
            test_idx = np.setdiff1d(np.arange(n_samples), cal_idx)

        elif method == "duplex":
            from ._sample_algorithms import duplex

            cal_idx, test_idx = duplex(X_array, n_cal, metric=metric, n_pcs=n_pcs)

        elif method == "spxy":
            from ._sample_algorithms import spxy

            if y_array is None:
                raise ValueError("SPXY requires target values (y). Connect a target to the y input port.")
            cal_idx, test_idx = spxy(X_array, y_array, n_cal, metric=metric, n_pcs=n_pcs)

        elif method == "sequential":
            cal_idx = np.arange(n_cal)
            test_idx = np.arange(n_cal, n_samples)

        elif method == "stratified" and y_array is not None:
            from sklearn.model_selection import train_test_split

            indices = np.arange(n_samples)
            cal_idx, test_idx = train_test_split(
                indices,
                test_size=test_size,
                random_state=random_seed,
                stratify=y_array,
                shuffle=True,
            )

        else:
            # random
            rng = np.random.RandomState(random_seed)
            indices = np.arange(n_samples)
            rng.shuffle(indices)
            cal_idx = indices[:n_cal]
            test_idx = indices[n_cal:]

        # --- Build output datasets ---
        X_cal_ds = build_dataset_like(X_array[cal_idx], X_ds)
        X_test_ds = build_dataset_like(X_array[test_idx], X_ds)

        # Reattach sliced targets — build_dataset_like clears target when
        # row count changes, so we must re-set it from the sliced y_array.
        if y_array is not None:
            X_cal_ds.target = y_array[cal_idx]
            X_test_ds.target = y_array[test_idx]

        # Slice sample axis metadata
        src_sample_axis = getattr(X_ds, "sample_axis", None)
        if src_sample_axis is not None:
            X_cal_ds.sample_axis = slice_axis_for_indices(src_sample_axis, cal_idx)
            X_test_ds.sample_axis = slice_axis_for_indices(src_sample_axis, test_idx)

        # Provenance
        step_params = {"method": method, "test_size": test_size}
        if method in ("kennard_stone", "duplex", "spxy"):
            step_params["metric"] = metric
            if n_pcs:
                step_params["n_pcs"] = n_pcs
        add_processing_step(X_cal_ds, "selection.sample_partition", step_params, self.node_id)
        add_processing_step(X_test_ds, "selection.sample_partition", step_params, self.node_id)

        outputs: dict[str, Any] = {
            "X_cal": X_cal_ds,
            "X_test": X_test_ds,
            "cal_indices": cal_idx,
            "test_indices": test_idx,
        }

        if y_array is not None:
            outputs["y_cal"] = y_array[cal_idx]
            outputs["y_test"] = y_array[test_idx]

        # --- Diagnostics ---
        diagnostics: dict[str, Any] = {
            "method": method,
            "n_cal": len(cal_idx),
            "n_test": len(test_idx),
            "n_total": n_samples,
        }

        if method in ("kennard_stone", "duplex", "spxy"):
            # Coverage: mean nearest-neighbour distance in cal set
            from ._sample_algorithms import _maybe_reduce, _pairwise_distances

            X_work = _maybe_reduce(X_array, n_pcs)
            D_cal = _pairwise_distances(X_work[cal_idx], metric=metric)
            np.fill_diagonal(D_cal, np.inf)
            nn_dists = D_cal.min(axis=1)
            diagnostics["coverage"] = {
                "mean_nn_distance": float(np.mean(nn_dists)),
                "max_nn_distance": float(np.max(nn_dists)),
                "min_nn_distance": float(np.min(nn_dists)),
            }

        logger.info(f"Sample partition ({method}): {len(cal_idx)} cal, {len(test_idx)} test " f"from {n_samples} total")

        return NodeResult(outputs=outputs, diagnostics=diagnostics)
