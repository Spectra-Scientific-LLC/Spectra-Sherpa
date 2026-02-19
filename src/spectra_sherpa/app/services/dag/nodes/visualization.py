"""
Visualization utilities for DAG nodes.

This module provides shared plotting functions for various nodes
to ensure consistency and reduce code duplication.
"""

from typing import Any, Dict, List

import numpy as np


def generate_confusion_matrix_heatmap(cm: np.ndarray, classes: List[Any], title: str) -> Dict[str, Any]:
    """
    Generate a confusion matrix heatmap using Plotly.

    Args:
        cm: Confusion matrix array (n_classes x n_classes)
        classes: List of class labels
        title: Plot title

    Returns:
        Dict: Plotly-formatted heatmap specification
    """
    # Normalize confusion matrix for color scale (0-1 range)
    # Avoid division by zero if a class has no samples
    row_sums = cm.sum(axis=1)
    # Use a safe division approach
    cm_normalized = np.zeros_like(cm, dtype=float)
    mask = row_sums > 0
    cm_normalized[mask] = cm[mask].astype("float") / row_sums[mask][:, np.newaxis]

    # Create annotations for cell text (show both count and percentage)
    annotations = []
    classes_str = [str(c) for c in classes]

    for i in range(len(classes)):
        for j in range(len(classes)):
            # Determine text color based on cell intensity for readability
            # If normalized > 0.5 (darker blue), use white text, else black
            is_dark_cell = cm_normalized[i, j] > 0.5
            text_color = "white" if is_dark_cell else "black"

            percentage = cm_normalized[i, j] * 100

            annotations.append(
                {
                    "x": classes_str[j],  # Use label value for categorical axis
                    "y": classes_str[i],
                    "text": f"{cm[i, j]}<br>({percentage:.1f}%)",
                    "showarrow": False,
                    "font": {"color": text_color, "size": 12},
                    "xref": "x",
                    "yref": "y",
                }
            )

    return {
        "data": [
            {
                "type": "heatmap",
                "z": cm.tolist(),
                "x": classes_str,
                "y": classes_str,
                "colorscale": "Blues",
                "showscale": True,
                "hovertemplate": "True: %{y}<br>Predicted: %{x}<br>Count: %{z}<extra></extra>",
            }
        ],
        "layout": {
            "title": title,
            "xaxis": {"title": "Predicted Label", "side": "bottom"},
            "yaxis": {"title": "True Label", "autorange": "reversed"},
            "annotations": annotations,
        },
    }
