#!/usr/bin/env python3
"""
Node Template Generator for Spectra Scientific Platform.

Generates scaffold code for new workflow nodes using one of three modes:

Usage:
    python node_template.py transform <node_type> <ClassName>
    python node_template.py estimator <node_type> <ClassName>
    python node_template.py custom <node_type> <ClassName> <category>

Examples:
    python node_template.py transform preprocess.clip_range ClipRangeNode
    python node_template.py estimator model.ridge RidgeNode
    python node_template.py custom diagnostics.snr SNRNode diagnostics
"""

import sys

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

TRANSFORM_TEMPLATE = '''"""
{label} preprocessing node.
"""

import numpy as np

from spectra_sherpa.app.services.dag.node_base import (
    NodeMetadata,
    NodeParameter,
    register_node,
)
from spectra_sherpa.app.services.dag.spec_nodes import TransformSpec, TransformSpecNode


def _transform(data: np.ndarray) -> np.ndarray:
    """Apply the transform to a 2-D float64 matrix.

    Args:
        data: (n_samples, n_features) array extracted from the input dataset.

    Returns:
        Transformed array of the same shape.
    """
    # TODO: implement transform logic
    return data


@register_node
class {class_name}(TransformSpecNode):
    """{label} node."""

    metadata = NodeMetadata(
        node_type="{node_type}",
        category="preprocessing",
        label="{label}",
        description="TODO: describe what this transform does",
        parameters=[
            # NodeParameter(
            #     name="example_param",
            #     label="Example",
            #     param_type="number",
            #     default=1.0,
            # ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    spec = TransformSpec(
        transform_fn=_transform,
        numpy_expr=None,  # TODO: add for auto Python export, e.g. "np.clip(_data, {{low}}, {{high}})"
        extra_imports=["import numpy as np"],
    )
'''

ESTIMATOR_TEMPLATE = '''"""
{label} modeling node.
"""

import numpy as np

from spectra_sherpa.app.services.dag.node_base import (
    NodeMetadata,
    NodeParameter,
    PortMetadata,
    register_node,
)
from spectra_sherpa.app.services.dag.spec_nodes import EstimatorSpec, EstimatorSpecNode

# TODO: replace with your estimator class
from sklearn.linear_model import LinearRegression


@register_node
class {class_name}(EstimatorSpecNode):
    """{label} node."""

    metadata = NodeMetadata(
        node_type="{node_type}",
        category="modeling",
        label="{label}",
        description="TODO: describe what this estimator does",
        parameters=[
            # NodeParameter(
            #     name="n_components",
            #     label="Components",
            #     param_type="number",
            #     default=5,
            #     min_value=1,
            # ),
        ],
        input_types=["NDDataset", "array"],
        output_type="dict",
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Features (X)",
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Targets (y)",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/FittedModel/1.0",
                label="Model",
            ),
            PortMetadata(
                name="predictions",
                type_ref="spectrasherpa://types/Array1D/1.0",
                label="Predictions",
            ),
            PortMetadata(
                name="residuals",
                type_ref="spectrasherpa://types/Array1D/1.0",
                label="Residuals",
            ),
        ],
    )

    spec = EstimatorSpec(
        estimator_class=LinearRegression,  # TODO: replace with your estimator
        estimator_import="from sklearn.linear_model import LinearRegression",  # auto-export
    )
'''

CUSTOM_TEMPLATE = '''"""
{label} node.
"""

from typing import Any, Dict

import numpy as np

from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodeResult,
    PortMetadata,
    register_node,
)


@register_node
class {class_name}(Node):
    """{label} node."""

    metadata = NodeMetadata(
        node_type="{node_type}",
        category="{category}",
        label="{label}",
        description="TODO: describe what this node does",
        parameters=[
            # NodeParameter(
            #     name="example_param",
            #     label="Example",
            #     param_type="number",
            #     default=1.0,
            # ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """Execute the node operation.

        Args:
            input_data: Input dataset from upstream node.

        Returns:
            Processed output data.
        """
        # TODO: implement node logic
        return input_data
'''


def _label_from_class(class_name: str) -> str:
    """Derive a human-readable label from a class name."""
    label = class_name.replace("Node", "").strip()
    # Insert spaces before uppercase letters (simple camelCase split)
    result = []
    for i, ch in enumerate(label):
        if ch.isupper() and i > 0 and not label[i - 1].isupper():
            result.append(" ")
        result.append(ch)
    return "".join(result)


def generate(mode: str, node_type: str, class_name: str, category: str = "") -> str:
    label = _label_from_class(class_name)
    if mode == "transform":
        return TRANSFORM_TEMPLATE.format(
            node_type=node_type,
            class_name=class_name,
            label=label,
        )
    elif mode == "estimator":
        return ESTIMATOR_TEMPLATE.format(
            node_type=node_type,
            class_name=class_name,
            label=label,
        )
    elif mode == "custom":
        return CUSTOM_TEMPLATE.format(
            node_type=node_type,
            class_name=class_name,
            label=label,
            category=category or "custom",
        )
    else:
        print(f"Unknown mode: {mode}. Use 'transform', 'estimator', or 'custom'.")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    mode = sys.argv[1]
    node_type = sys.argv[2]
    class_name = sys.argv[3]
    category = sys.argv[4] if len(sys.argv) > 4 else ""

    print(generate(mode, node_type, class_name, category))
