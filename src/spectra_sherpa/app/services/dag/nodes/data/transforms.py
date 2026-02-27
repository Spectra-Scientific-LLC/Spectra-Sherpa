"""TrainTestSplitNode -- split datasets into training and test sets.

Registered as ``data.train_test_split``.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

from spectra_sherpa.app.lib.sherpa_dataset import TargetContext

from ...io_contracts import bind_X, bind_y, build_dataset_like, to_numpy_1d, to_numpy_2d, to_numpy_y
from ...node_base import Node, NodeMetadata, NodeParameter, PortMetadata, register_node
from ._utils import slice_axis_for_indices

logger = logging.getLogger(__name__)


@register_node
class TrainTestSplitNode(Node):
    """
    Split dataset into training and test sets.

    Enables proper ML workflow with separate train/test evaluation.
    Supports random, stratified, and grouped splitting strategies.

    Multi-output node with 4 output ports:
    - X_train: Training feature data
    - X_test: Test feature data
    - y_train: Training targets (if y provided)
    - y_test: Test targets (if y provided)
    """

    metadata = NodeMetadata(
        node_type="data.train_test_split",
        category="data",
        label="Train/Test Split",
        description="Split data into training and test sets with optional stratification",
        parameters=[
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
                name="split_method",
                label="Split Method",
                param_type="select",
                options=["random", "stratified", "sequential"],
                default="random",
                description="How to split the data",
                required=True,
            ),
            NodeParameter(
                name="random_seed",
                label="Random Seed",
                param_type="number",
                default=42,
                description="Seed for reproducible random splits",
                required=False,
            ),
            NodeParameter(
                name="shuffle",
                label="Shuffle",
                param_type="boolean",
                default=True,
                description="Shuffle data before splitting (for random method)",
                required=False,
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Data",
                description="Full dataset to split into train/test",
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Target Values (optional)",
                description="Target array for stratified splitting (1D or 2D)",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="X_train",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Training Data",
                description="Training subset of input data",
            ),
            PortMetadata(
                name="X_test",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Test Data",
                description="Test subset of input data",
            ),
            PortMetadata(
                name="y_train",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Training Targets",
                description="Training subset of targets (1D or 2D)",
            ),
            PortMetadata(
                name="y_test",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Test Targets",
                description="Test subset of targets (1D or 2D)",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",  # Returns dict with multiple outputs
    )

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> dict[str, Any]:
        """
        Split data into train and test sets.

        Args:
            X: Input dataset (NDDataset or SpectralResult)
            y: Optional target array for stratification
            **kwargs: Additional inputs (ignored)

        Returns:
            dict with keys: X_train, X_test, y_train (if y provided), y_test (if y provided)
        """
        test_size = self.parameters.get("test_size", 0.2)
        split_method = self.parameters.get("split_method", "random")
        random_seed = self.parameters.get("random_seed", 42)
        shuffle = self.parameters.get("shuffle", True)

        X_ds = bind_X(
            X,
            missing_message="Missing required input: X (dataset)",
            dataset_error_message="X must be an NDDataset or SherpaDataset object",
            allow_array=True,
        )
        y_value = bind_y(
            y,
            X=X_ds,
            required=False,
            infer_from_X=True,
            dataset_as_data=False,
        )

        X_array = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_array = to_numpy_y(y_value, name="y", expected_samples=X_array.shape[0]) if y_value is not None else None

        n_samples = X_array.shape[0]
        n_test = int(n_samples * test_size)
        n_train = n_samples - n_test

        if n_test < 1 or n_train < 1:
            raise ValueError(
                f"Test size {test_size} results in {n_test} test samples. " f"Need at least 1 train and 1 test sample."
            )

        # Generate indices
        if split_method == "sequential":
            # Sequential split (first N for train, rest for test)
            train_idx = np.arange(n_train)
            test_idx = np.arange(n_train, n_samples)

        elif split_method == "stratified" and y_array is not None:
            # Stratified split (preserve class proportions)
            from sklearn.model_selection import train_test_split

            indices = np.arange(n_samples)

            train_idx, test_idx = train_test_split(
                indices,
                test_size=test_size,
                random_state=random_seed,
                stratify=y_array,
                shuffle=shuffle,
            )

        else:
            # Random split
            indices = np.arange(n_samples)
            if shuffle:
                rng = np.random.RandomState(random_seed)
                rng.shuffle(indices)

            train_idx = indices[:n_train]
            test_idx = indices[n_train:]

        # Split data
        X_train_array = X_array[train_idx]
        X_test_array = X_array[test_idx]

        X_train = build_dataset_like(X_train_array, X_ds)
        X_test = build_dataset_like(X_test_array, X_ds)

        # Slice sample-axis metadata to match train/test rows.
        tts_y_coord = X_ds.sample_axis
        if tts_y_coord is not None and len(tts_y_coord) > 1:
            X_train.sample_axis = slice_axis_for_indices(tts_y_coord, train_idx)
            X_test.sample_axis = slice_axis_for_indices(tts_y_coord, test_idx)

        # Keep dataset.target aligned after row splitting.
        target = getattr(X_ds, "target", None)
        if target is not None:
            target_array = np.asarray(target)
            if target_array.shape[0] == n_samples:
                X_train.target = target_array[train_idx]
                X_test.target = target_array[test_idx]
            else:
                X_train.target = None
                X_test.target = None

        # Record provenance in dataset.meta
        add_processing_step(
            X_train,
            "data.train_test_split",
            {
                "split": "train",
                "test_size": test_size,
                "split_method": split_method,
                "random_seed": random_seed,
                "shuffle": shuffle,
                "n_train": n_train,
                "n_test": n_test,
            },
            node_id=self.node_id,
        )

        add_processing_step(
            X_test,
            "data.train_test_split",
            {
                "split": "test",
                "test_size": test_size,
                "split_method": split_method,
                "random_seed": random_seed,
                "shuffle": shuffle,
                "n_train": n_train,
                "n_test": n_test,
            },
            node_id=self.node_id,
        )

        # Build result dict
        result = {
            "X_train": X_train,
            "X_test": X_test,
        }

        # Split targets if provided/inferred
        if y_array is not None:
            result["y_train"] = y_array[train_idx]
            result["y_test"] = y_array[test_idx]

        logger.debug(f"Train/Test Split: {n_train} train, {n_test} test samples ({test_size*100:.0f}% test)")

        return result


@register_node
class AttachTargetNode(Node):
    """Attach target values to a dataset for supervised modeling.

    Use this when target data comes from a different source than X,
    or when you need to override the embedded target.
    """

    metadata = NodeMetadata(
        node_type="data.attach_target",
        category="data",
        label="Attach Target",
        description="Attach target values to a dataset for supervised modeling",
        parameters=[
            NodeParameter(
                name="target_type",
                label="Target Type",
                param_type="select",
                options=["continuous", "categorical"],
                default="continuous",
                description="Type of target variable",
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Dataset",
                description="Dataset to attach target values to",
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=True,
                label="Target Values",
                description="Target values (1D or 2D array, or dataset with target)",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Dataset with Target",
                description="Dataset with embedded target values",
            ),
        ],
    )

    async def execute(self, X=None, y=None, **kwargs):
        """Attach target to dataset."""
        X_ds = bind_X(
            X,
            missing_message="Missing required input: X (dataset)",
            allow_array=True,
        )

        y_raw = bind_y(
            y,
            X=None,  # Don't infer from X — we're explicitly attaching
            required=True,
            infer_from_X=False,
            dataset_as_data=True,
            missing_message="Missing required input: y (target values)",
        )

        y_arr = to_numpy_y(y_raw, name="y", expected_samples=X_ds.shape[0])

        result = X_ds.copy()
        result.target = y_arr

        target_type = self.parameters.get("target_type", "continuous")
        if target_type == "categorical":
            n_unique = len(np.unique(y_arr))
            result.target_context = TargetContext(
                target_type="categorical",
                n_classes=n_unique,
            )
        else:
            result.target_context = TargetContext(
                target_type="continuous",
            )

        add_processing_step(
            result,
            "data.attach_target",
            {"target_type": target_type, "target_shape": list(y_arr.shape)},
            node_id=self.node_id,
        )

        return {"default": result}
