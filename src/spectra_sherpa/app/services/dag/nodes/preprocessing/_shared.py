"""
Shared constants, imports, and re-exports for preprocessing nodes.

All preprocessing node modules import common symbols from here to avoid
repeating the same import blocks. This also makes it easy to see all
external dependencies of the preprocessing subpackage at a glance.
"""

from __future__ import annotations

import logging

from spectra_sherpa.app.lib.adapters.scp_adapter import scp_roundtrip  # noqa: F401

# --- Preprocessing library functions ---
from spectra_sherpa.app.lib.preprocessing import (  # noqa: F401
    baseline_penalized_ls,
    gaussian_smooth,
    norris_williams,
    whittaker_smooth,
)

# --- SpectroChemPy compatibility ---
from spectra_sherpa.app.lib.scp_compat import (  # noqa: F401
    HAS_SCP,
    NDDataset,
    scp,
)

# --- Core data container ---
from spectra_sherpa.app.lib.sherpa_dataset import (  # noqa: F401
    EFFECT_BASELINE_CORRECTED,
    EFFECT_DERIVATIVE,
    EFFECT_NORMALIZED,
    EFFECT_SCALED,
    EFFECT_SCATTER_CORRECTED,
    EFFECT_SMOOTHED,
    SherpaDataset,
)

# --- Export helpers ---
from ...export_helpers import (  # noqa: F401
    _format_value,
    extract_data_lines,
    header_line,
)
from ...meta_helpers import copy_processing_history  # noqa: F401

# --- DAG node framework ---
from ...node_base import (  # noqa: F401
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)

# --- Spec nodes (transform-oriented base class and helpers) ---
from ...spec_nodes import (  # noqa: F401
    TransformSpec,
    TransformSpecNode,
    add_processing_step,
    bind_X,
    bind_y,
    build_dataset_like,
    coerce_to_sherpa,
    to_numpy_1d,
    to_numpy_2d,
)

logger = logging.getLogger(__name__)


def _wrap_result_lines(
    node_id: str,
    data_expr: str,
    input_expr: str,
    indent: str,
    use_scp: bool = True,
) -> list[str]:
    """Preprocessing-local re-export of the shared result wrapper helper."""
    from ...export_helpers import wrap_result_lines

    return wrap_result_lines(node_id, data_expr, input_expr, indent, use_scp)


import numpy as np  # noqa: F811 — re-import for local use


def estimate_snr(data: "np.ndarray") -> float:
    """Estimate signal-to-noise ratio from spectral data.

    Uses the ratio of overall signal RMS to noise estimated from the
    second-difference (Savitzky-Golay-inspired noise estimator).
    Returns SNR in dB.  Works on 2D (n_samples, n_features) arrays.
    """
    if data.size == 0 or data.ndim < 2 or data.shape[1] < 3:
        return 0.0
    signal_rms = float(np.sqrt(np.mean(data**2)))
    # Second-difference noise estimate (robust to baseline trends)
    diff2 = data[:, 2:] - 2 * data[:, 1:-1] + data[:, :-2]
    noise_std = float(np.std(diff2) / np.sqrt(6))  # scale factor for 2nd diff
    if noise_std < 1e-15:
        return 100.0  # effectively noiseless
    return float(20 * np.log10(signal_rms / noise_std))


# ---------------------------------------------------------------------------
# Technology-aware baseline lambda defaults
# ---------------------------------------------------------------------------
_BASELINE_LAMBDA_DEFAULT = 1e5  # node metadata default — "no technique set"

_LAMBDA_BY_TECHNIQUE: dict[str, float] = {
    "NIR": 1e6,
    "NEAR_INFRARED": 1e6,
    "RAMAN": 1e5,
    "FTIR": 1e7,
    "IR": 1e7,
    "MIR": 1e7,
    "OES": 1e4,
    "OPTICAL_EMISSION": 1e4,
}
