"""Sample partitioning node — train/test splitting.

Registered as ``selection.sample_partition``.

Consolidates random, stratified, sequential, Kennard-Stone, and DUPLEX
splitting strategies into a single node with standard ML output semantics
(X_train / X_test / y_train / y_test / train_indices / test_indices / diagnostics).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

from ...io_contracts import bind_X, bind_y, build_dataset_like, to_numpy_2d, to_numpy_y
from ...node_base import Node, NodeMetadata, NodeParameter, NodeResult, PortMetadata, register_node

logger = logging.getLogger(__name__)


@register_node
class SamplePartitionNode(Node):
    """Partition dataset into training and test sets.

    Supports both generic ML strategies (random, stratified, sequential)
    and chemometric space-filling designs (Kennard-Stone, DUPLEX) that
    ensure representative coverage of the spectral X-space.

    Multi-output node with train/test datasets, indices, and
    coverage diagnostics.
    """

    metadata = NodeMetadata(
        node_type="selection.sample_partition",
        category="selection",
        label="Sample Partition",
        description="Split data into train/test sets using chemometric or statistical designs",
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
                description="How to partition samples between training and test sets",
                required=True,
            ),
            NodeParameter(
                name="test_size",
                label="Test Size",
                param_type="number",
                default=0.2,
                min_value=0.01,
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
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Input Data",
                description="Spectral dataset or multivariate feature table to partition",
                accepted_data_roles=["X_spectra", "X_features"],
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
                name="X_train",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Training Data",
                description="Training subset",
            ),
            PortMetadata(
                name="X_test",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Test Data",
                description="Test subset (holdout)",
            ),
            PortMetadata(
                name="y_train",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Training Targets",
            ),
            PortMetadata(
                name="y_test",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Test Targets",
            ),
            PortMetadata(
                name="train_indices",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
                label="Training Indices",
                description="Integer indices of training samples in original data",
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
        diagnostics=["n_train", "n_test", "method", "coverage"],
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
        n_pcs = int(params.get("n_pcs", 0)) or None

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
        lines.append(f"{indent}_y_data = None if _raw_y is None else np.asarray(_raw_y)")
        lines.append(f"{indent}_n = _X_data.shape[0]")
        lines.append(f"{indent}_n_test = int(_n * {test_size})")
        lines.append(f"{indent}_n_train = _n - _n_test")

        if method == "kennard_stone":
            metric = params.get("metric", "euclidean")
            lines.append(f"{indent}# Kennard-Stone: greedy maximin in {metric} space")
            lines.append(
                f"{indent}from spectra_sherpa.app.services.dag.nodes.selection._sample_algorithms import kennard_stone"
            )
            lines.append(
                f"{indent}_train_idx = kennard_stone(" f"_X_data, _n_train, metric='{metric}', n_pcs={repr(n_pcs)})"
            )
            lines.append(f"{indent}_test_idx = np.setdiff1d(np.arange(_n), _train_idx)")
        elif method == "duplex":
            metric = params.get("metric", "euclidean")
            lines.append(
                f"{indent}from spectra_sherpa.app.services.dag.nodes.selection._sample_algorithms import duplex"
            )
            lines.append(
                f"{indent}_train_idx, _test_idx = duplex(" f"_X_data, _n_train, metric='{metric}', n_pcs={repr(n_pcs)})"
            )
        elif method == "spxy":
            metric = params.get("metric", "euclidean")
            lines.append(f"{indent}from spectra_sherpa.app.services.dag.nodes.selection._sample_algorithms import spxy")
            lines.append(f"{indent}if _y_data is None:")
            lines.append(f"{indent}    raise ValueError('SPXY requires target values (y)')")
            lines.append(
                f"{indent}_train_idx, _test_idx = spxy("
                f"_X_data, _y_data, _n_train, metric='{metric}', n_pcs={repr(n_pcs)})"
            )
        elif method == "stratified":
            seed = int(params.get("random_seed", 42))
            lines.append(f"{indent}from sklearn.model_selection import train_test_split")
            lines.append(f"{indent}if _y_data is None:")
            lines.append(f"{indent}    raise ValueError('Stratified partition requires target values (y)')")
            lines.append(f"{indent}_train_idx, _test_idx = train_test_split(")
            lines.append(f"{indent}    np.arange(_n), test_size={test_size}, random_state={seed},")
            lines.append(f"{indent}    stratify=_y_data, shuffle=True)")
        else:
            # random or sequential
            lines.append(f"{indent}_indices = np.arange(_n)")
            if method != "sequential":
                seed = int(params.get("random_seed", 42))
                lines.append(f"{indent}np.random.RandomState({seed}).shuffle(_indices)")
            lines.append(f"{indent}_train_idx = _indices[:_n_train]")
            lines.append(f"{indent}_test_idx = _indices[_n_train:]")

        lines.append(f"{indent}_X_train = _X_data[_train_idx]")
        lines.append(f"{indent}_X_test = _X_data[_test_idx]")
        lines.append(f"{indent}_y_train = _y_data[_train_idx] if _y_data is not None else None")
        lines.append(f"{indent}_y_test = _y_data[_test_idx] if _y_data is not None else None")

        lines.append(f"{indent}from spectra_sherpa.app.services.dag.io_contracts import build_dataset_like")
        lines.append(f"{indent}_X_train_ds = build_dataset_like(_X_train, _X_input)")
        lines.append(f"{indent}_X_test_ds = build_dataset_like(_X_test, _X_input)")
        lines.append(f"{indent}if _y_data is not None:")
        lines.append(f"{indent}    # target=_y_train / target=_y_test preserved after row slicing")
        lines.append(f"{indent}    _X_train_ds.target = _y_train")
        lines.append(f"{indent}    _X_test_ds.target = _y_test")
        lines.append(f"{indent}_src_sample_axis = getattr(_X_input, 'sample_axis', None)")
        lines.append(f"{indent}if _src_sample_axis is not None:")
        lines.append(
            f"{indent}    from spectra_sherpa.app.services.dag.nodes.data._utils import slice_axis_for_indices"
        )
        lines.append(f"{indent}    _X_train_ds.sample_axis = slice_axis_for_indices(_src_sample_axis, _train_idx)")
        lines.append(f"{indent}    _X_test_ds.sample_axis = slice_axis_for_indices(_src_sample_axis, _test_idx)")

        lines.append(f'{indent}print(f"  Partition ({method}): {{len(_train_idx)}} train, {{len(_test_idx)}} test")')
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'X_train': _X_train_ds, 'X_test': _X_test_ds,")
        lines.append(f"{indent}    'X_cal': _X_train_ds, 'cal_indices': _train_idx,")
        lines.append(f"{indent}    'train_indices': _train_idx, 'test_indices': _test_idx,")
        lines.append(f"{indent}}}")
        lines.append(f"{indent}if _y_data is not None:")
        lines.append(f"{indent}    results['{self.node_id}']['y_train'] = _y_train")
        lines.append(f"{indent}    results['{self.node_id}']['y_test'] = _y_test")
        lines.append(f"{indent}    results['{self.node_id}']['y_cal'] = _y_train")

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
        n_train = n_samples - n_test

        if n_test < 1 or n_train < 2:
            raise ValueError(
                f"test_size={test_size} gives {n_train} train / {n_test} test samples. "
                f"Need >= 2 training and >= 1 test samples."
            )

        # --- Compute indices ---
        if method == "kennard_stone":
            from ._sample_algorithms import kennard_stone

            train_idx = kennard_stone(X_array, n_train, metric=metric, n_pcs=n_pcs)
            test_idx = np.setdiff1d(np.arange(n_samples), train_idx)

        elif method == "duplex":
            from ._sample_algorithms import duplex

            train_idx, test_idx = duplex(X_array, n_train, metric=metric, n_pcs=n_pcs)

        elif method == "spxy":
            from ._sample_algorithms import spxy

            if y_array is None:
                raise ValueError("SPXY requires target values (y). Connect a target to the y input port.")
            train_idx, test_idx = spxy(X_array, y_array, n_train, metric=metric, n_pcs=n_pcs)

        elif method == "sequential":
            train_idx = np.arange(n_train)
            test_idx = np.arange(n_train, n_samples)

        elif method == "stratified" and y_array is not None:
            from sklearn.model_selection import train_test_split

            indices = np.arange(n_samples)
            train_idx, test_idx = train_test_split(
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
            train_idx = indices[:n_train]
            test_idx = indices[n_train:]

        # --- Build output datasets ---
        X_train_ds = build_dataset_like(X_array[train_idx], X_ds)
        X_test_ds = build_dataset_like(X_array[test_idx], X_ds)

        # Reattach sliced targets — build_dataset_like clears target when
        # row count changes, so we must re-set it from the sliced y_array.
        if y_array is not None:
            X_train_ds.target = y_array[train_idx]
            X_test_ds.target = y_array[test_idx]

        # Slice sample axis metadata
        src_sample_axis = getattr(X_ds, "sample_axis", None)
        if src_sample_axis is not None:
            from ..data._utils import slice_axis_for_indices

            X_train_ds.sample_axis = slice_axis_for_indices(src_sample_axis, train_idx)  # type: ignore[assignment]
            X_test_ds.sample_axis = slice_axis_for_indices(src_sample_axis, test_idx)  # type: ignore[assignment]

        # Provenance. Store the exact partition so persisted model artifacts
        # can later replay/compare train, test, or all sample scopes against
        # the original dataset without relying on random-state reconstruction.
        step_params = {
            "method": method,
            "test_size": test_size,
            "train_indices": train_idx.tolist(),
            "test_indices": test_idx.tolist(),
            "n_samples": int(n_samples),
            "random_seed": int(random_seed) if random_seed is not None else None,
        }
        if method in ("kennard_stone", "duplex", "spxy"):
            step_params["metric"] = metric
            if n_pcs:
                step_params["n_pcs"] = n_pcs
        add_processing_step(X_train_ds, "selection.sample_partition", step_params, self.node_id)
        add_processing_step(X_test_ds, "selection.sample_partition", step_params, self.node_id)

        outputs: dict[str, Any] = {
            "X_train": X_train_ds,
            "X_test": X_test_ds,
            "train_indices": train_idx,
            "test_indices": test_idx,
            # Backward-compatible aliases (chemometric convention)
            "X_cal": X_train_ds,
            "cal_indices": train_idx,
        }

        if y_array is not None:
            outputs["y_train"] = y_array[train_idx]
            outputs["y_test"] = y_array[test_idx]
            outputs["y_cal"] = y_array[train_idx]  # alias

        # --- Diagnostics ---
        diagnostics: dict[str, Any] = {
            "method": method,
            "n_train": len(train_idx),
            "n_test": len(test_idx),
            "n_total": n_samples,
            "n_cal": len(train_idx),  # alias
        }

        if method in ("kennard_stone", "duplex", "spxy"):
            # Coverage: mean nearest-neighbour distance in training set
            from ._sample_algorithms import _maybe_reduce, _pairwise_distances

            X_work = _maybe_reduce(X_array, n_pcs)
            D_train = _pairwise_distances(X_work[train_idx], metric=metric)
            np.fill_diagonal(D_train, np.inf)
            nn_dists = D_train.min(axis=1)
            diagnostics["coverage"] = {
                "mean_nn_distance": float(np.mean(nn_dists)),
                "max_nn_distance": float(np.max(nn_dists)),
                "min_nn_distance": float(np.min(nn_dists)),
            }

        logger.info(
            f"Sample partition ({method}): {len(train_idx)} train, {len(test_idx)} test " f"from {n_samples} total"
        )

        return NodeResult(outputs=outputs, diagnostics=diagnostics)
