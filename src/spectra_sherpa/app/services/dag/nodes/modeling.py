"""
Modeling nodes for chemometrics analysis.

These nodes implement various modeling techniques like PCA, PLS, MCR-ALS.
"""

from __future__ import annotations

from typing import Any, Optional
import numpy as np
import spectrochempy as scp
from spectrochempy import NDDataset

from ..node_base import Node, NodeMetadata, NodeParameter, InputPort, PortMetadata, register_node
from app.services.dag.meta_helpers import add_processing_step, copy_processing_history, safe_get_coord


def _create_spectral_dataset(
    data: np.ndarray,
    x_coord: Optional[Any] = None,
    y_coord: Optional[Any] = None,
    units: Optional[str] = None,
    title: Optional[str] = None,
    meta: Optional[dict] = None,
) -> NDDataset:
    """
    Create an NDDataset with proper coordinate preservation.

    This ensures that spectral data always carries its coordinate system,
    enabling "smart array" behavior where slicing data also slices coordinates.

    Args:
        data: The spectral data array (1D or 2D)
        x_coord: X-axis coordinate (wavenumbers, wavelengths, etc.) - can be Coord or NDDataset.x
        y_coord: Y-axis coordinate (sample labels, time points) - can be Coord or NDDataset.y
        units: Y-axis units (e.g., "absorbance", "a.u.")
        title: Dataset title
        meta: Metadata dictionary to attach

    Returns:
        NDDataset with coordinates properly attached
    """
    dataset = scp.NDDataset(data)

    if x_coord is not None:
        # Copy the coordinate to preserve it
        if hasattr(x_coord, 'copy'):
            dataset.x = x_coord.copy()
        else:
            dataset.x = scp.Coord(x_coord)

    if y_coord is not None:
        if hasattr(y_coord, 'copy'):
            dataset.y = y_coord.copy()
        else:
            dataset.y = scp.Coord(y_coord)

    if units is not None:
        dataset.units = units

    if title is not None:
        dataset.title = title

    if meta is not None:
        dataset.meta = meta.copy() if hasattr(meta, 'copy') else dict(meta)

    return dataset


def _is_sequential_numeric(values: list) -> bool:
    """
    Check if numeric values are sequential (e.g., time series, temperature series).
    Sequential data should NOT be treated as categorical.

    Args:
        values: List of numeric values (already converted to hashable types)

    Returns:
        True if values appear to be a sequential series, False otherwise
    """
    try:
        # Convert to numeric array
        numeric_values = []
        for v in values:
            if isinstance(v, (int, float, np.integer, np.floating)):
                numeric_values.append(float(v))
            else:
                # If any value is not numeric, not sequential
                return False

        if len(numeric_values) < 3:
            # Need at least 3 values to detect sequence
            return False

        # Check if values form an arithmetic sequence (constant difference)
        diffs = np.diff(sorted(set(numeric_values)))

        # If all differences are the same (within tolerance), it's sequential
        if len(diffs) > 0:
            mean_diff = np.mean(diffs)
            # Allow 1% tolerance for floating point errors
            tolerance = max(abs(mean_diff) * 0.01, 1e-10)
            return bool(np.all(np.abs(diffs - mean_diff) < tolerance))

        return False
    except (TypeError, ValueError):
        return False


@register_node
class PCANode(Node):
    """
    Principal Component Analysis node.

    Performs PCA decomposition on spectral data using SpectroChemPy.
    """

    metadata = NodeMetadata(
        node_type="model.pca",
        category="modeling",
        label="PCA",
        description="Principal Component Analysis for dimensionality reduction",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="text",
                default="2",
                description="Number of components: integer (e.g., '2'), 'mle' (auto-select via Maximum Likelihood), or float 0-1 (e.g., '0.95' for 95% variance)",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="standardized",
                label="Standardize Data",
                param_type="boolean",
                default=False,
                description="Apply standardization (mean centering + unit variance) before PCA",
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="scaled",
                label="Scale Data",
                param_type="boolean",
                default=False,
                description="Apply scaling (unit variance) before PCA",
                required=False,
                category="advanced",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="model",
                port_type="model",
                required=True,
                label="PCA Model",
                description="Trained PCA model object",
            ),
            PortMetadata(
                name="scores",
                port_type="dataset",
                required=True,
                label="Scores",
                description="Transformed scores as NDDataset (n_samples × n_components) with sample labels",
            ),
            PortMetadata(
                name="loadings",
                port_type="dataset",
                required=True,
                label="Loadings",
                description="Principal component loadings as NDDataset (n_components × n_features) with wavenumber axis",
            ),
            PortMetadata(
                name="explained_variance",
                port_type="array",
                required=True,
                label="Explained Variance",
                description="Variance explained by each component",
            ),
        ],
    )

    async def execute(self, input_data: Any) -> Any:
        """
        Execute PCA on input dataset.

        Args:
            input_data: NDDataset or SpectralResult containing spectral data

        Returns:
            PCA model object with scores, loadings, and explained variance
        """
        # Input should already be NDDataset from DAG pipeline

        # Get parameters
        n_components_str = self.parameters.get("n_components", "5")
        standardized = self.parameters.get("standardized", False)
        scaled = self.parameters.get("scaled", False)

        # Parse n_components parameter (can be int, "mle", or float 0-1)
        n_components_parsed: int | str | float
        if isinstance(n_components_str, str):
            n_components_str = n_components_str.strip()
            if n_components_str.lower() == "mle":
                n_components_parsed = "mle"
            else:
                try:
                    # Try to parse as float first
                    val = float(n_components_str)
                    # If it's a whole number, convert to int
                    if val.is_integer() and val >= 1:
                        n_components_parsed = int(val)
                    # If it's between 0 and 1, keep as float (variance threshold)
                    elif 0.0 < val < 1.0:
                        n_components_parsed = val
                    else:
                        raise ValueError(f"Invalid n_components value: {n_components_str}")
                except ValueError:
                    raise ValueError(
                        f"n_components must be an integer, 'mle', or float between 0 and 1. Got: {n_components_str}"
                    )
        else:
            # Handle numeric input from legacy workflows
            n_components_parsed = n_components_str

        # Validate MLE constraint: n_observations >= n_features
        n_observations, n_features = input_data.shape
        if n_components_parsed == "mle" and n_observations < n_features:
            raise ValueError(
                f"n_components='mle' requires n_observations >= n_features. "
                f"Got {n_observations} observations and {n_features} features. "
                f"Consider using a specific number of components or a variance threshold (0-1)."
            )

        print(f"\n[PCA Node] Executing with:")
        print(f"  - All parameters: {self.parameters}")
        print(f"  - n_components parsed: {n_components_parsed} (type: {type(n_components_parsed).__name__})")
        print(f"  - Data shape: {n_observations} observations × {n_features} features")

        # Perform PCA using SpectroChemPy
        pca = scp.PCA(n_components=n_components_parsed, standardized=standardized, scaled=scaled)
        pca.fit(input_data)

        # Use SpectroChemPy's native NDDataset outputs — they carry proper
        # coordinates from the input dataset (wavenumbers, sample labels, etc.)
        scores_dataset = pca.transform()
        loadings_dataset = pca.components

        # Extract numeric scores array for T²/SPE computation
        scores_data = np.array(scores_dataset.data) if hasattr(scores_dataset, "data") else np.array(scores_dataset)
        if scores_data.ndim == 1:
            scores_data = scores_data.reshape(-1, 1)

        actual_n_components = scores_data.shape[1]

        # Get explained variance ratio - extract data from NDDataset if needed
        evr_raw = pca.explained_variance_ratio
        if evr_raw is not None:
            # SpectroChemPy returns NDDataset, extract the underlying data
            evr = np.array(evr_raw.data).flatten() if hasattr(evr_raw, "data") else np.array(evr_raw).flatten()
        else:
            evr = np.zeros(actual_n_components)

        # Ensure evr has at least actual_n_components elements (pad with zeros if needed)
        if len(evr) < actual_n_components:
            evr = np.pad(evr, (0, actual_n_components - len(evr)), mode='constant', constant_values=0)

        # Normalize EVR to ratio form (0-1) for consistent handling
        max_evr = evr.max() if len(evr) > 0 else 0
        evr_ratio = evr / 100.0 if max_evr > 1 else evr

        # PCA diagnostics: Hotelling T2 and SPE (Q residuals)
        t2_stats: Optional[np.ndarray] = None
        spe_stats: Optional[np.ndarray] = None
        if scores_data.size > 0:
            scores_matrix = np.array(scores_data)
            if scores_matrix.ndim == 1:
                scores_matrix = scores_matrix.reshape(-1, 1)

            # Hotelling T2 = sum(scores^2 / eigenvalues)
            # CRITICAL: Use PCA eigenvalues (explained_variance), NOT score variances
            # Reference: Nomikos & MacGregor (1995), Technometrics
            eigenvalues_raw = pca.explained_variance
            if eigenvalues_raw is not None:
                eigenvalues = np.array(eigenvalues_raw.data).flatten() if hasattr(eigenvalues_raw, "data") else np.array(eigenvalues_raw).flatten()
            else:
                eigenvalues = np.var(scores_matrix, axis=0)
            eigenvalues = np.maximum(eigenvalues[:actual_n_components], 1e-12)
            t2_stats = np.sum((scores_matrix ** 2) / eigenvalues, axis=1)

            # SPE (Squared Prediction Error) from reconstruction residuals
            reconstructed = None
            if hasattr(pca, "inverse_transform"):
                try:
                    reconstructed = pca.inverse_transform(scores_dataset)
                except Exception:
                    reconstructed = None
            if reconstructed is None and hasattr(pca, "reconstruct"):
                try:
                    reconstructed = pca.reconstruct(scores_dataset)
                except Exception:
                    reconstructed = None

            if reconstructed is not None:
                reconstructed_data = np.array(reconstructed.data) if hasattr(reconstructed, "data") else np.array(reconstructed)
                input_matrix = np.array(input_data.data) if hasattr(input_data, "data") else np.array(input_data)
                if reconstructed_data.shape == input_matrix.shape:
                    residuals = input_matrix - reconstructed_data
                    spe_stats = np.sum(residuals ** 2, axis=1)

        # Extract label_categories for categorical coloring
        label_categories = None
        _y_coord = safe_get_coord(input_data, 'y')
        if _y_coord is not None:
            try:
                if hasattr(_y_coord, 'labels') and _y_coord.labels is not None:
                    raw = _y_coord.labels.tolist() if hasattr(_y_coord.labels, 'tolist') else list(_y_coord.labels)
                    str_labels = [str(l) for l in raw]
                    label_categories = sorted(set(str_labels))
                elif hasattr(_y_coord, 'data') and _y_coord.data is not None:
                    raw = _y_coord.data.tolist() if hasattr(_y_coord.data, 'tolist') else list(_y_coord.data)
                    str_labels = [str(l) for l in raw]
                    unique = sorted(set(str_labels))
                    if len(unique) < 20 and not _is_sequential_numeric(raw):
                        label_categories = unique
            except Exception:
                label_categories = None

        # scores_dataset and loadings_dataset are already SpectroChemPy NDDatasets
        # from pca.transform() / pca.components — coordinates inherited from input.
        # Add processing history for provenance tracking.
        copy_processing_history(input_data, scores_dataset)
        add_processing_step(
            scores_dataset,
            "model.pca.scores",
            {"n_components": actual_n_components},
            node_id=self.node_id,
        )

        copy_processing_history(input_data, loadings_dataset)
        add_processing_step(
            loadings_dataset,
            "model.pca.loadings",
            {"n_components": actual_n_components},
            node_id=self.node_id,
        )

        # Store only scientific metadata that coordinates can't carry.
        # serialize_for_api() extracts wavenumbers, sample_labels, x_title, etc.
        # from NDDataset coordinates automatically at the API boundary.
        scores_dataset.meta.update({
            "explained_variance_ratio": evr_ratio.tolist(),
            "n_components": actual_n_components,
            "t2": t2_stats.tolist() if t2_stats is not None else [],
            "spe": spe_stats.tolist() if spe_stats is not None else [],
            "t2_p95": float(np.percentile(t2_stats, 95)) if t2_stats is not None else None,
            "spe_p95": float(np.percentile(spe_stats, 95)) if spe_stats is not None else None,
            "t2_mean": float(np.mean(t2_stats)) if t2_stats is not None else None,
            "spe_mean": float(np.mean(spe_stats)) if spe_stats is not None else None,
            "label_categories": label_categories,
        })

        # NDDataset-only return: one serialization boundary at API layer
        print(f"[PCA Node] Requested n_components={n_components_parsed}, fitted with {actual_n_components} components")
        print(f"[PCA Node] Scores shape: {scores_dataset.shape}, Loadings shape: {loadings_dataset.shape}")

        return {
            "default": scores_dataset,      # NDDataset: scores + sample labels (y) + PC coords (x)
            "loadings": loadings_dataset,    # NDDataset: loadings + wavenumbers (x) + PC coords (y)
            "model": pca,                    # Model port for Apply PCA Transform
            "_internal": {
                "input_data": input_data,
            },
        }


@register_node
class PLSNode(Node):
    """
    Partial Least Squares Regression node.

    Performs PLS regression using SpectroChemPy.
    """

    metadata = NodeMetadata(
        node_type="model.pls",
        category="modeling",
        label="PLS",
        description="Partial Least Squares regression for calibration",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=3,
                min_value=1,
                max_value=20,
                step=1,
                description="Number of PLS components",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="scale",
                label="Scale Data",
                param_type="boolean",
                default=True,
                description="Apply mean centering and scaling",
                required=False,
                category="basic",
            ),
        ],
        input_types=["NDDataset", "array"],
        output_type="dict",
        # Named input ports for multi-input node
        input_ports=[
            PortMetadata(
                name="X",
                port_type="dataset",
                required=True,
                label="Spectra (X)",
                description="Spectral data matrix (n_samples × n_wavenumbers)",
            ),
            PortMetadata(
                name="y",
                port_type="target",
                required=True,
                label="Concentrations (y)",
                description="Target concentration values",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="model",
                port_type="model",
                required=True,
                label="PLS Model",
                description="Trained PLS regression model",
            ),
            PortMetadata(
                name="X_scores",
                port_type="dataset",
                required=True,
                label="X Scores",
                description="Scores for X block as NDDataset (samples × components) with sample labels",
            ),
            PortMetadata(
                name="Y_scores",
                port_type="dataset",
                required=True,
                label="Y Scores",
                description="Scores for Y block as NDDataset (samples × components) with sample labels",
            ),
            PortMetadata(
                name="X_loadings",
                port_type="dataset",
                required=True,
                label="X Loadings",
                description="Loadings for X block as NDDataset (features × components) with wavenumber axis",
            ),
            PortMetadata(
                name="Y_loadings",
                port_type="dataset",
                required=True,
                label="Y Loadings",
                description="Loadings for Y block as NDDataset (targets × components)",
            ),
        ],
    )

    async def execute(self, X: Any = None, y: Any = None, **kwargs) -> Any:
        """
        Execute PLS regression.

        Args:
            X: NDDataset or SpectralResult containing spectral data (predictors)
            y: Target values (concentrations)

        Returns:
            PLS model with regression results
        """
        # Handle both positional and keyword arguments for backward compatibility
        if X is None and "input_0" in kwargs:
            X = kwargs["input_0"]
        if y is None and "input_1" in kwargs:
            y = kwargs["input_1"]

        if X is None:
            raise ValueError("Missing required input: X (spectra)")
        if y is None:
            raise ValueError("Missing required input: y (concentrations)")
        # X should already be NDDataset from DAG pipeline

        n_components = self.parameters.get("n_components", 3)
        scale = self.parameters.get("scale", True)

        # Prepare y as NDDataset if it's not already
        if isinstance(y, NDDataset):
            y_dataset = y
        else:
            y_array = np.array(y).flatten()
            if X.shape[0] != y_array.shape[0]:
                raise ValueError("X and y must have the same number of samples")
            y_dataset = scp.NDDataset(y_array.reshape(-1, 1))

        # Validate n_components
        max_components = min(X.shape[0] - 1, X.shape[1])
        if n_components > max_components:
            raise ValueError(
                f"n_components must be <= min(n_samples - 1, n_features). Got {n_components} with max {max_components}."
            )

        print(f"\n[PLS Node] Executing with:")
        print(f"  - n_components: {n_components}")
        print(f"  - scale: {scale}")
        print(f"  - X shape: {X.shape}")
        print(f"  - y shape: {y_dataset.shape}")

        # Perform PLS using SpectroChemPy
        pls = scp.PLSRegression(n_components=n_components, scale=scale)
        pls.fit(X, y_dataset)

        # Extract results - SpectroChemPy PLSRegression follows sklearn API
        X_scores_data = np.array(pls.x_scores_) if hasattr(pls, "x_scores_") else None
        Y_scores_data = np.array(pls.y_scores_) if hasattr(pls, "y_scores_") else None
        X_loadings_data = np.array(pls.x_loadings_) if hasattr(pls, "x_loadings_") else None
        Y_loadings_data = np.array(pls.y_loadings_) if hasattr(pls, "y_loadings_") else None
        coef_data = np.array(pls.coef_) if hasattr(pls, "coef_") else None

        print(f"[PLS Node] PLS model fitted successfully")
        print(f"  - X_scores shape: {X_scores_data.shape if X_scores_data is not None else 'N/A'}")
        print(f"  - Coefficients shape: {coef_data.shape if coef_data is not None else 'N/A'}")

        # Extract label_categories for categorical coloring
        label_categories = None
        _y_coord = safe_get_coord(X, 'y')
        if _y_coord is not None:
            try:
                if hasattr(_y_coord, 'labels') and _y_coord.labels is not None:
                    raw = _y_coord.labels.tolist() if hasattr(_y_coord.labels, 'tolist') else list(_y_coord.labels)
                    label_categories = sorted(set(str(l) for l in raw))
                elif hasattr(_y_coord, 'data') and _y_coord.data is not None:
                    raw = _y_coord.data.tolist() if hasattr(_y_coord.data, 'tolist') else list(_y_coord.data)
                    str_labels = [str(l) for l in raw]
                    unique = sorted(set(str_labels))
                    if len(unique) < 20 and not _is_sequential_numeric(raw):
                        label_categories = unique
            except Exception:
                label_categories = None

        # Get input x_coord for loadings NDDataset
        _x_coord = safe_get_coord(X, 'x')

        # Build LV labels with physical quantity context for scientific traceability
        x_data_quantity = None
        if hasattr(X, "units") and X.units:
            x_data_quantity = str(X.units) if str(X.units) != "dimensionless" else None
        if x_data_quantity is None and hasattr(X, "title") and X.title:
            x_data_quantity = str(X.title)

        # =====================================================================
        # Create proper NDDataset objects for scores and loadings with coordinate coupling
        # This enables "smart array" behavior - slicing data also slices axes
        # =====================================================================

        # Build LV labels with physical quantity context for scientific traceability
        # Example: "LV1 [Absorbance]" instead of just "LV1"
        quantity_suffix = f" [{x_data_quantity}]" if x_data_quantity else ""
        lv_labels = [f"LV{i+1}{quantity_suffix}" for i in range(n_components)]

        # X_scores: shape (n_samples, n_components)
        X_scores_dataset = None
        if X_scores_data is not None:
            X_scores_dataset = _create_spectral_dataset(
                data=X_scores_data,
                x_coord=scp.Coord(lv_labels, title="Latent Variable"),
                y_coord=_y_coord,  # Preserve sample labels from input
                units="score",
                title="PLS X Scores",
            )

        # Y_scores: shape (n_samples, n_components)
        Y_scores_dataset = None
        if Y_scores_data is not None:
            Y_scores_dataset = _create_spectral_dataset(
                data=Y_scores_data,
                x_coord=scp.Coord(lv_labels, title="Latent Variable"),
                y_coord=_y_coord,  # Preserve sample labels from input
                units="score",
                title="PLS Y Scores",
            )

        # X_loadings: shape (n_features, n_components) - needs wavenumber axis
        X_loadings_dataset = None
        if X_loadings_data is not None:
            X_loadings_dataset = _create_spectral_dataset(
                data=X_loadings_data.T if X_loadings_data.ndim == 2 else X_loadings_data,  # Transpose to (n_components, n_features)
                x_coord=_x_coord,
                y_coord=scp.Coord(lv_labels, title="Latent Variable"),
                units="loading",
                title="PLS X Loadings",
            )

        # Y_loadings: shape (n_targets, n_components)
        Y_loadings_dataset = None
        if Y_loadings_data is not None:
            Y_loadings_dataset = _create_spectral_dataset(
                data=Y_loadings_data,
                x_coord=scp.Coord(lv_labels, title="Latent Variable"),
                units="loading",
                title="PLS Y Loadings",
            )

        # Add processing history to NDDataset outputs
        if X_scores_dataset is not None:
            copy_processing_history(X, X_scores_dataset)
            add_processing_step(
                X_scores_dataset,
                "model.pls.x_scores",
                {"n_components": n_components},
                node_id=self.node_id,
            )

        if Y_scores_dataset is not None:
            copy_processing_history(X, Y_scores_dataset)
            add_processing_step(
                Y_scores_dataset,
                "model.pls.y_scores",
                {"n_components": n_components},
                node_id=self.node_id,
            )

        if X_loadings_dataset is not None:
            copy_processing_history(X, X_loadings_dataset)
            add_processing_step(
                X_loadings_dataset,
                "model.pls.x_loadings",
                {"n_components": n_components},
                node_id=self.node_id,
            )

        if Y_loadings_dataset is not None:
            copy_processing_history(X, Y_loadings_dataset)
            add_processing_step(
                Y_loadings_dataset,
                "model.pls.y_loadings",
                {"n_components": n_components},
                node_id=self.node_id,
            )

        # Store scientific metadata in X_scores NDDataset meta
        if X_scores_dataset is not None:
            X_scores_dataset.meta.update({
                "n_components": n_components,
                "pc_labels": lv_labels,  # LV labels (no EVR for PLS, so store explicitly)
                "label_categories": label_categories,
            })

        # NDDataset-only return: one serialization boundary at API layer
        return {
            "default": X_scores_dataset,       # NDDataset: X scores + sample labels (y) + LV coords (x)
            "X_loadings": X_loadings_dataset,   # NDDataset: loadings + wavenumbers (x) + LV coords (y)
            "Y_scores": Y_scores_dataset,       # NDDataset: Y scores
            "Y_loadings": Y_loadings_dataset,   # NDDataset: Y loadings
            "model": pls,                        # Model port for Apply PLS Model
            "coef": coef_data,
        }


@register_node
class PCRNode(Node):
    """
    Principal Component Regression (PCR) node.

    Performs PCA followed by linear regression on the scores.
    """

    metadata = NodeMetadata(
        node_type="model.pcr",
        category="modeling",
        label="PCR",
        description="Principal Component Regression for calibration",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=3,
                min_value=1,
                max_value=20,
                step=1,
                description="Number of PCA components for regression",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="scale",
                label="Scale Data",
                param_type="boolean",
                default=True,
                description="Apply mean centering and scaling",
                required=False,
                category="basic",
            ),
        ],
        input_types=["NDDataset", "array"],
        output_type="dict",
        input_ports=[
            PortMetadata(
                name="X",
                port_type="dataset",
                required=True,
                label="Spectra (X)",
                description="Spectral data matrix (n_samples × n_wavenumbers)",
            ),
            PortMetadata(
                name="y",
                port_type="target",
                required=True,
                label="Targets (y)",
                description="Target values for regression",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="model",
                port_type="model",
                required=True,
                label="PCR Model",
                description="Trained PCR model object",
            ),
            PortMetadata(
                name="scores",
                port_type="array",
                required=True,
                label="Scores",
                description="PCA Scores (n_samples × n_components)",
            ),
            PortMetadata(
                name="loadings",
                port_type="array",
                required=True,
                label="Loadings",
                description="PCA Loadings (n_features × n_components)",
            ),
        ],
    )

    async def execute(self, X: Any = None, y: Any = None, **kwargs) -> Any:
        """
        Execute PCR regression.

        Args:
            X: NDDataset or SpectralResult containing spectral data (predictors)
            y: Target values (concentrations)

        Returns:
            PCR model with regression results
        """
        from sklearn.decomposition import PCA as SkPCA
        from sklearn.linear_model import LinearRegression
        from sklearn.metrics import mean_squared_error, r2_score
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        # Handle both positional and keyword arguments for backward compatibility
        if X is None and "input_0" in kwargs:
            X = kwargs["input_0"]
        if y is None and "input_1" in kwargs:
            y = kwargs["input_1"]

        if X is None:
            raise ValueError("Missing required input: X (spectra)")
        if y is None:
            raise ValueError("Missing required input: y (targets)")

        # Convert to numpy arrays - accept NDDataset or array
        X_orig = X
        if isinstance(X, NDDataset):
            X_data = np.array(X.data)
        else:
            X_data = np.array(X)

        if X_data.ndim == 1:
            X_data = X_data.reshape(-1, 1)

        y_array = np.array(y).flatten()
        if X_data.shape[0] != y_array.shape[0]:
            raise ValueError("X and y must have the same number of samples")

        n_components = self.parameters.get("n_components", 3)
        scale = self.parameters.get("scale", True)

        max_components = min(X_data.shape[0] - 1, X_data.shape[1])
        if n_components > max_components:
            raise ValueError(
                f"n_components must be <= min(n_samples - 1, n_features). Got {n_components} with max {max_components}."
            )

        print(f"\n[PCR Node] Executing with:")
        print(f"  - n_components: {n_components}")
        print(f"  - scale: {scale}")
        print(f"  - X shape: {X_data.shape}")
        print(f"  - y shape: {y_array.shape}")

        scaler = StandardScaler(with_mean=True, with_std=scale)
        pca = SkPCA(n_components=n_components)
        regressor = LinearRegression()
        model = Pipeline(
            [
                ("scaler", scaler),
                ("pca", pca),
                ("regressor", regressor),
            ]
        )
        model.fit(X_data, y_array)

        y_pred = model.predict(X_data)
        r2 = r2_score(y_array, y_pred)
        rmse = float(np.sqrt(mean_squared_error(y_array, y_pred)))

        X_scores = model.named_steps["pca"].transform(model.named_steps["scaler"].transform(X_data))

        # Extract label_categories for categorical coloring
        label_categories = None
        _y_coord = safe_get_coord(X, 'y') if isinstance(X, NDDataset) else None
        if _y_coord is not None:
            try:
                if hasattr(_y_coord, 'labels') and _y_coord.labels is not None:
                    raw = _y_coord.labels.tolist() if hasattr(_y_coord.labels, 'tolist') else list(_y_coord.labels)
                    label_categories = sorted(set(str(l) for l in raw))
                elif hasattr(_y_coord, 'data') and _y_coord.data is not None:
                    raw = _y_coord.data.tolist() if hasattr(_y_coord.data, 'tolist') else list(_y_coord.data)
                    str_labels = [str(l) for l in raw]
                    unique = sorted(set(str_labels))
                    if len(unique) < 20 and not _is_sequential_numeric(raw):
                        label_categories = unique
            except Exception:
                label_categories = None

        # Get input coordinates for NDDataset creation
        _x_coord = safe_get_coord(X, 'x') if isinstance(X, NDDataset) else None

        # Build PC labels with explained variance ratio
        evr = pca.explained_variance_ratio_
        pc_labels = [f"PC{i+1} ({evr[i]*100:.1f}%)" for i in range(n_components)]

        # =====================================================================
        # Create proper NDDataset objects for scores and loadings with coordinate coupling
        # =====================================================================

        # Scores: shape (n_samples, n_components)
        scores_dataset = _create_spectral_dataset(
            data=X_scores,
            x_coord=scp.Coord(pc_labels, title="Principal Component"),
            y_coord=_y_coord,  # Preserve sample labels from input
            units="score",
            title="PCR Scores",
        )

        # Loadings: shape (n_components, n_features)
        loadings_dataset = _create_spectral_dataset(
            data=pca.components_,
            x_coord=_x_coord,
            y_coord=scp.Coord(pc_labels, title="Principal Component"),
            units="loading",
            title="PCR Loadings",
        )

        # Add processing history to NDDataset outputs
        if isinstance(X, NDDataset):
            copy_processing_history(X, scores_dataset)
            copy_processing_history(X, loadings_dataset)
        add_processing_step(
            scores_dataset,
            "model.pcr.scores",
            {"n_components": n_components},
            node_id=self.node_id,
        )
        add_processing_step(
            loadings_dataset,
            "model.pcr.loadings",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        # Store only scientific metadata that coordinates can't carry
        scores_dataset.meta.update({
            "n_components": n_components,
            "explained_variance_ratio": evr.tolist(),
            "label_categories": label_categories,
            "r2": float(r2),
            "rmse": rmse,
            "coef": regressor.coef_.tolist(),
            "intercept": float(regressor.intercept_),
            "y_pred": y_pred.tolist(),
        })

        print(f"[PCR Node] Scores shape: {scores_dataset.shape}, Loadings shape: {loadings_dataset.shape}")

        return {
            "default": scores_dataset,      # NDDataset: scores + sample labels (y) + PC coords (x)
            "loadings": loadings_dataset,    # NDDataset: loadings + wavenumbers (x) + PC coords (y)
            "model": model,                  # Model port for downstream use
        }


@register_node
class SVRNode(Node):
    """
    Support Vector Regression (SVR) node.

    Performs SVR with optional scaling for calibration models.
    """

    metadata = NodeMetadata(
        node_type="model.svr",
        category="modeling",
        label="SVR",
        description="Support Vector Regression for calibration",
        parameters=[
            NodeParameter(
                name="kernel",
                label="Kernel",
                param_type="select",
                default="rbf",
                options=["rbf", "linear", "poly", "sigmoid"],
                description="Kernel type for SVR",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="C",
                label="C",
                param_type="number",
                default=1.0,
                min_value=0.01,
                max_value=1000.0,
                step=0.1,
                description="Regularization parameter",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="epsilon",
                label="Epsilon",
                param_type="number",
                default=0.1,
                min_value=0.0,
                max_value=1.0,
                step=0.01,
                description="Epsilon-tube width",
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="gamma",
                label="Gamma",
                param_type="select",
                default="scale",
                options=["scale", "auto"],
                description="Kernel coefficient for RBF/poly/sigmoid",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="degree",
                label="Polynomial Degree",
                param_type="number",
                default=3,
                min_value=1,
                max_value=6,
                step=1,
                description="Degree for polynomial kernel",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="coef0",
                label="Coef0",
                param_type="number",
                default=0.0,
                min_value=-1.0,
                max_value=1.0,
                step=0.1,
                description="Independent term for poly/sigmoid kernels",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="scale",
                label="Scale Data",
                param_type="boolean",
                default=True,
                description="Apply mean centering and scaling",
                required=False,
                category="basic",
            ),
        ],
        input_types=["NDDataset", "array"],
        output_type="dict",
        input_ports=[
            PortMetadata(
                name="X",
                port_type="dataset",
                required=True,
                label="Spectra (X)",
                description="Spectral data matrix (n_samples × n_wavenumbers)",
            ),
            PortMetadata(
                name="y",
                port_type="target",
                required=True,
                label="Targets (y)",
                description="Target values for regression",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="model",
                port_type="model",
                required=True,
                label="SVR Model",
                description="Trained SVR model object",
            ),
            PortMetadata(
                name="predictions",
                port_type="array",
                required=True,
                label="Predictions",
                description="Predicted values (y_pred)",
            ),
            PortMetadata(
                name="residuals",
                port_type="array",
                required=True,
                label="Residuals",
                description="Regression residuals (y_true - y_pred)",
            ),
        ],
    )

    async def execute(self, X: Any = None, y: Any = None, **kwargs) -> Any:
        """
        Execute SVR regression.

        Args:
            X: NDDataset or SpectralResult containing spectral data (predictors)
            y: Target values (concentrations)

        Returns:
            SVR model with regression results
        """
        from sklearn.metrics import mean_squared_error, r2_score
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.svm import SVR

        # Handle both positional and keyword arguments for backward compatibility
        if X is None and "input_0" in kwargs:
            X = kwargs["input_0"]
        if y is None and "input_1" in kwargs:
            y = kwargs["input_1"]

        if X is None:
            raise ValueError("Missing required input: X (spectra)")
        if y is None:
            raise ValueError("Missing required input: y (targets)")

        # Convert to numpy arrays - accept NDDataset or array
        if isinstance(X, NDDataset):
            X_data = np.array(X.data)
        else:
            X_data = np.array(X)

        if X_data.ndim == 1:
            X_data = X_data.reshape(-1, 1)

        y_array = np.array(y).flatten()
        if X_data.shape[0] != y_array.shape[0]:
            raise ValueError("X and y must have the same number of samples")

        kernel = self.parameters.get("kernel", "rbf")
        C = self.parameters.get("C", 1.0)
        epsilon = self.parameters.get("epsilon", 0.1)
        gamma = self.parameters.get("gamma", "scale")
        degree = self.parameters.get("degree", 3)
        coef0 = self.parameters.get("coef0", 0.0)
        scale = self.parameters.get("scale", True)

        print(f"\n[SVR Node] Executing with:")
        print(f"  - kernel: {kernel}")
        print(f"  - C: {C}")
        print(f"  - epsilon: {epsilon}")
        print(f"  - gamma: {gamma}")
        print(f"  - X shape: {X_data.shape}")
        print(f"  - y shape: {y_array.shape}")

        scaler = StandardScaler(with_mean=True, with_std=scale)
        svr = SVR(kernel=kernel, C=C, epsilon=epsilon, gamma=gamma, degree=degree, coef0=coef0)
        model = Pipeline(
            [
                ("scaler", scaler),
                ("svr", svr),
            ]
        )
        model.fit(X_data, y_array)

        y_pred = model.predict(X_data)
        r2 = r2_score(y_array, y_pred)
        rmse = float(np.sqrt(mean_squared_error(y_array, y_pred)))

        # Extract sample labels from input data for categorical coloring
        sample_labels = None
        label_categories = None
        n_observations = X_data.shape[0]

        if isinstance(X, NDDataset) and X.y is not None:
            if hasattr(X.y, "labels") and X.y.labels is not None:
                try:
                    labels = X.y.labels
                    raw = labels.tolist() if hasattr(labels, "tolist") else list(labels)
                    # Convert ALL labels to native Python str — avoids numpy StrDType
                    # ufunc errors when sorting/comparing numpy string scalars
                    sample_labels = [str(l) for l in raw]
                    label_categories = sorted(set(sample_labels))
                except Exception as e:
                    print(f"[SVR Node] Warning: Could not extract categorical labels from y.labels: {e}")
                    sample_labels = None
                    label_categories = None

            if sample_labels is None and hasattr(X.y, "data") and X.y.data is not None:
                try:
                    y_data = X.y.data
                    raw = y_data.tolist() if hasattr(y_data, "tolist") else list(y_data)
                    sample_labels = [str(l) for l in raw]
                    unique_values = sorted(set(sample_labels))
                    if len(unique_values) < 20 and not _is_sequential_numeric(raw):
                        label_categories = unique_values
                except Exception as e:
                    print(f"[SVR Node] Warning: Could not extract categorical labels from y.data: {e}")
                    sample_labels = None
                    label_categories = None

        if sample_labels is None:
            sample_labels = [f"Sample {i+1}" for i in range(n_observations)]

        # Calculate residuals
        residuals = y_array - y_pred

        return {
            "model": model,
            "predictions": y_pred.tolist(),
            "residuals": residuals.tolist(),
            "support_vectors": svr.support_vectors_.tolist(),
            "y_pred": y_pred.tolist(),
            "r2": float(r2),
            "rmse": rmse,
            "data": [[float(y_true), float(y_hat)] for y_true, y_hat in zip(y_array, y_pred)],
            "metadata": {
                "type": "SVR",
                "output_type": "regression",
                "n_observations": n_observations,
                "n_features": X_data.shape[1],
                "kernel": kernel,
                "C": C,
                "epsilon": epsilon,
                "gamma": gamma,
                "r2": float(r2),
                "rmse": rmse,
                "sample_labels": sample_labels,
                "label_categories": label_categories,
            },
        }


@register_node
class LinearRegressionNode(Node):
    """
    Simple Linear Regression node.

    Performs linear regression for calibration curves.
    """

    metadata = NodeMetadata(
        node_type="model.linear_regression",
        category="modeling",
        label="Linear Regression",
        description="Simple linear regression for calibration",
        parameters=[
            NodeParameter(
                name="fit_intercept",
                label="Fit Intercept",
                param_type="boolean",
                default=True,
                description="Calculate intercept (if False, force through origin)",
                required=False,
            ),
        ],
        input_types=["array", "array"],
        output_type="dict",
        # Named input ports for multi-input node
        input_ports=[
            PortMetadata(
                name="X",
                port_type="dataset",
                required=True,
                label="Features (X)",
                description="Feature matrix (predictors)",
            ),
            PortMetadata(
                name="y",
                port_type="target",
                required=True,
                label="Targets (y)",
                description="Target values",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="model",
                port_type="model",
                required=True,
                label="Linear Model",
                description="Trained Linear Regression model",
            ),
            PortMetadata(
                name="predictions",
                port_type="array",
                required=True,
                label="Predictions",
                description="Predicted values (y_pred)",
            ),
            PortMetadata(
                name="residuals",
                port_type="array",
                required=True,
                label="Residuals",
                description="Regression residuals (y_true - y_pred)",
            ),
        ],
    )

    async def execute(self, X: Any = None, y: Any = None, **kwargs) -> Any:
        """
        Execute linear regression.

        Args:
            X: Feature matrix
            y: Target values

        Returns:
            Linear regression model
        """
        from sklearn.linear_model import LinearRegression
        import numpy as np

        # Handle both positional and keyword arguments for backward compatibility
        if X is None and "input_0" in kwargs:
            X = kwargs["input_0"]
        if y is None and "input_1" in kwargs:
            y = kwargs["input_1"]

        if X is None:
            raise ValueError("Missing required input: X (features)")
        if y is None:
            raise ValueError("Missing required input: y (targets)")

        fit_intercept = self.parameters.get("fit_intercept", True)

        # Ensure X is 2D - accept NDDataset or array
        if isinstance(X, NDDataset):
            X = np.array(X.data)
        X_array = np.array(X)
        if X_array.ndim == 1:
            X_array = X_array.reshape(-1, 1)

        model = LinearRegression(fit_intercept=fit_intercept)
        model.fit(X_array, y)

        y_pred = model.predict(X_array)
        residuals = y - y_pred

        return {
            "model": model,
            "predictions": y_pred.tolist(),
            "residuals": residuals.tolist(),
            "coef": model.coef_.tolist(),
            "intercept": model.intercept_ if fit_intercept else 0,
            "score": model.score(X_array, y),
        }


@register_node
class MCRNode(Node):
    """
    Multivariate Curve Resolution - Alternating Least Squares (MCR-ALS) node.

    Performs MCR-ALS decomposition on spectral data to resolve mixtures
    into pure component spectra and concentration profiles.

    Uses SpectroChemPy's MCRALS implementation.
    """

    metadata = NodeMetadata(
        node_type="model.mcr_als",
        category="modeling",
        label="MCR-ALS",
        description="Multivariate Curve Resolution for mixture analysis",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=3,
                min_value=2,
                max_value=20,
                step=1,
                description="Number of pure components to resolve",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="non_negative_C",
                label="Non-negative Concentrations",
                param_type="boolean",
                default=True,
                description="Enforce non-negative concentration profiles",
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="non_negative_St",
                label="Non-negative Spectra",
                param_type="boolean",
                default=True,
                description="Enforce non-negative spectra",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="max_iter",
                label="Maximum Iterations",
                param_type="number",
                default=50,
                min_value=10,
                max_value=500,
                step=10,
                description="Maximum ALS iterations",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="tol",
                label="Convergence Tolerance",
                param_type="number",
                default=0.1,
                min_value=0.001,
                max_value=1.0,
                step=0.01,
                description="Convergence tolerance for ALS",
                required=False,
                category="advanced",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="model",
                port_type="model",
                required=True,
                label="MCR Model",
                description="Fitted MCR-ALS model object",
            ),
            PortMetadata(
                name="C",
                port_type="dataset",
                required=True,
                label="Concentrations",
                description="Resolved concentration profiles (C) as NDDataset with sample/component axes",
            ),
            PortMetadata(
                name="St",
                port_type="dataset",
                required=True,
                label="Pure Spectra",
                description="Resolved pure component spectra (S^T)",
            ),
            PortMetadata(
                name="residuals",
                port_type="dataset",
                required=False,
                label="Residuals",
                description="Modeling residuals",
            ),
        ],
    )

    async def execute(self, input_data: Any) -> Any:
        """
        Execute MCR-ALS decomposition on input dataset.

        Args:
            input_data: NDDataset or SpectralResult containing spectral mixture data (D matrix)
                       Shape should be (n_samples, n_wavenumbers)

        Returns:
            Dict containing:
            - model: The MCRALS model object
            - C: Concentration profiles (n_samples, n_components) as SpectralResult
            - St: Pure spectra (n_components, n_wavenumbers) as SpectralResult
            - n_components: Number of resolved components
        """
        # Input should already be NDDataset from DAG pipeline

        # Get parameters
        n_components = self.parameters.get("n_components", 3)
        max_iter = self.parameters.get("max_iter", 50)
        tol = self.parameters.get("tol", 0.1)

        # Validate input shape
        if len(input_data.shape) != 2:
            raise ValueError(f"Expected 2D input, got shape {input_data.shape}")

        n_samples, n_features = input_data.shape
        if n_components > min(n_samples, n_features):
            raise ValueError(
                f"n_components ({n_components}) cannot exceed min(n_samples, n_features) = {min(n_samples, n_features)}"
            )

        # Create initial guess for C using SVD
        # This provides a good starting point for ALS
        from numpy.linalg import svd

        data = np.array(input_data.data)
        U, S, Vt = svd(data, full_matrices=False)

        # Initial C estimate from first n_components of U*S
        C0_data = U[:, :n_components] @ np.diag(S[:n_components])
        # Make non-negative (shift and scale)
        C0_data = np.abs(C0_data)
        C0 = scp.NDDataset(C0_data)

        # Create and fit MCR-ALS model
        mcr = scp.MCRALS(max_iter=max_iter, tol=tol)
        mcr.fit(input_data, C0)

        # Extract results
        C_data = np.array(mcr.C.data) if hasattr(mcr.C, "data") else np.array(mcr.C)
        St_data = np.array(mcr.St.data) if hasattr(mcr.St, "data") else np.array(mcr.St)

        # Get input coordinates for NDDataset creation
        _x_coord = safe_get_coord(input_data, 'x')
        _y_coord = safe_get_coord(input_data, 'y')

        # Extract label_categories for categorical coloring
        label_categories = None
        if _y_coord is not None:
            try:
                if hasattr(_y_coord, 'labels') and _y_coord.labels is not None:
                    raw = _y_coord.labels.tolist() if hasattr(_y_coord.labels, 'tolist') else list(_y_coord.labels)
                    label_categories = sorted(set(str(l) for l in raw))
                elif hasattr(_y_coord, 'data') and _y_coord.data is not None:
                    raw = _y_coord.data.tolist() if hasattr(_y_coord.data, 'tolist') else list(_y_coord.data)
                    str_labels = [str(l) for l in raw]
                    unique = sorted(set(str_labels))
                    if len(unique) < 20 and not _is_sequential_numeric(raw):
                        label_categories = unique
            except Exception:
                label_categories = None

        # Try to extract species names from input metadata (from BlendNode ground truth)
        species_names = None
        if hasattr(input_data, 'meta') and input_data.meta:
            spectra_meta = input_data.meta.get("spectra", {})
            if isinstance(spectra_meta, dict):
                species_list = spectra_meta.get("species", [])
                if species_list and len(species_list) >= n_components:
                    try:
                        names = []
                        for spec in species_list[:n_components]:
                            if isinstance(spec, dict):
                                names.append(spec.get("name", f"Species {len(names)+1}"))
                            elif hasattr(spec, "name"):
                                names.append(spec.name)
                            else:
                                names.append(f"Species {len(names)+1}")
                        species_names = names
                        print(f"[MCR-ALS Node] Extracted species names from input metadata: {species_names}")
                    except Exception as e:
                        print(f"[MCR-ALS Node] Warning: Could not extract species names: {e}")

        # Use species names if available, otherwise use generic labels
        component_labels = species_names or [f"Component {i+1}" for i in range(n_components)]
        spectrum_labels = species_names or [f"Pure Spectrum {i+1}" for i in range(n_components)]

        # =====================================================================
        # Create proper NDDataset objects for St and C with coordinate coupling
        # This enables "smart array" behavior - slicing data also slices axes
        # =====================================================================

        # St (Pure Spectra): shape (n_components, n_features)
        # X-axis = wavenumbers from input, Y-axis = component labels
        St_dataset = _create_spectral_dataset(
            data=St_data,
            x_coord=_x_coord,
            y_coord=scp.Coord(spectrum_labels, title="Component"),
            units=input_data.units if hasattr(input_data, 'units') else None,
            title="MCR-ALS Pure Component Spectra",
        )

        # C (Concentrations): shape (n_samples, n_components)
        # X-axis = component labels, Y-axis = sample labels/time
        C_dataset = _create_spectral_dataset(
            data=C_data,
            x_coord=scp.Coord(component_labels, title="Component"),
            y_coord=_y_coord,  # Preserve sample labels from input
            units="relative concentration",
            title="MCR-ALS Concentration Profiles",
        )

        # Compute residuals as NDDataset
        reconstructed = C_data @ St_data
        residuals_data = np.array(input_data.data) - reconstructed
        residuals_dataset = _create_spectral_dataset(
            data=residuals_data,
            x_coord=_x_coord,
            y_coord=_y_coord,  # Preserve sample labels from input
            units=input_data.units if hasattr(input_data, 'units') else None,
            title="MCR-ALS Residuals",
        )

        # Add processing history to NDDataset outputs
        copy_processing_history(input_data, C_dataset)
        add_processing_step(
            C_dataset,
            "model.mcr_als.concentrations",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        copy_processing_history(input_data, St_dataset)
        add_processing_step(
            St_dataset,
            "model.mcr_als.spectra",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        copy_processing_history(input_data, residuals_dataset)
        add_processing_step(
            residuals_dataset,
            "model.mcr_als.residuals",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        # Store only scientific metadata that coordinates can't carry
        C_dataset.meta.update({
            "n_components": n_components,
            "label_categories": label_categories,
            "species_names": species_names,
        })

        return {
            "default": C_dataset,                # NDDataset: concentration profiles + sample labels (y) + component coords (x)
            "C": C_dataset,                      # Alias for concentrations
            "St": St_dataset,                    # NDDataset: pure spectra + wavenumbers (x) + component coords (y)
            "residuals": residuals_dataset,      # NDDataset: residuals
            "model": mcr,                        # Model port
        }


@register_node
class EFANode(Node):
    """
    Evolving Factor Analysis (EFA) node.

    Performs EFA to determine the number of significant factors
    and the chemical rank of evolving systems.

    Uses SpectroChemPy's EFA implementation.
    """

    metadata = NodeMetadata(
        node_type="model.efa",
        category="modeling",
        label="EFA",
        description="Evolving Factor Analysis for rank determination",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=10,
                min_value=1,
                max_value=50,
                step=1,
                description="Number of components to compute",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="model",
                port_type="model",
                required=True,
                label="EFA Model",
                description="EFA model object",
            ),
            PortMetadata(
                name="forward_eigenvalues",
                port_type="dataset",
                required=True,
                label="Forward Eigenvalues",
                description="Eigenvalues from forward EFA as NDDataset (samples × components)",
            ),
            PortMetadata(
                name="backward_eigenvalues",
                port_type="dataset",
                required=True,
                label="Backward Eigenvalues",
                description="Eigenvalues from backward EFA as NDDataset (samples × components)",
            ),
        ],
    )

    async def execute(self, input_data: Any) -> Any:
        """
        Execute EFA on input dataset.

        Args:
            input_data: NDDataset or SpectralResult containing evolving spectral data

        Returns:
            Dict containing forward and backward eigenvalues
        """
        # Input should already be NDDataset from DAG pipeline

        n_components = self.parameters.get("n_components", 10)

        # Perform EFA using SpectroChemPy
        efa = scp.EFA(n_components=n_components)
        efa.fit(input_data)

        # Extract forward and backward results
        forward_ev = np.array(efa.f_ev) if hasattr(efa, "f_ev") else None
        backward_ev = np.array(efa.b_ev) if hasattr(efa, "b_ev") else None

        # Get input y_coord for sample labels
        n_samples = input_data.shape[0]
        _y_coord = safe_get_coord(input_data, 'y')

        # =====================================================================
        # Create proper NDDataset objects for eigenvalues with coordinate coupling
        # This enables "smart array" behavior - slicing data also slices axes
        # =====================================================================

        component_labels = [f"EV{i+1}" for i in range(n_components)]

        # Forward eigenvalues: shape (n_samples, n_components)
        forward_ev_dataset = None
        if forward_ev is not None:
            forward_ev_dataset = _create_spectral_dataset(
                data=forward_ev,
                x_coord=scp.Coord(component_labels, title="Component"),
                y_coord=_y_coord,  # Preserve sample labels from input
                units="eigenvalue",
                title="EFA Forward Eigenvalues",
            )

        # Backward eigenvalues: shape (n_samples, n_components)
        backward_ev_dataset = None
        if backward_ev is not None:
            backward_ev_dataset = _create_spectral_dataset(
                data=backward_ev,
                x_coord=scp.Coord(component_labels, title="Component"),
                y_coord=_y_coord,  # Preserve sample labels from input
                units="eigenvalue",
                title="EFA Backward Eigenvalues",
            )

        # Add processing history to NDDataset outputs
        if forward_ev_dataset is not None:
            copy_processing_history(input_data, forward_ev_dataset)
            add_processing_step(
                forward_ev_dataset,
                "model.efa.forward_eigenvalues",
                {"n_components": n_components},
                node_id=self.node_id,
            )

        if backward_ev_dataset is not None:
            copy_processing_history(input_data, backward_ev_dataset)
            add_processing_step(
                backward_ev_dataset,
                "model.efa.backward_eigenvalues",
                {"n_components": n_components},
                node_id=self.node_id,
            )

        # Store only scientific metadata that coordinates can't carry
        # Use forward_ev_dataset as default output
        default_dataset = forward_ev_dataset or backward_ev_dataset
        if default_dataset is not None:
            default_dataset.meta.update({
                "n_components": n_components,
            })

        return {
            "default": default_dataset,                    # NDDataset: forward eigenvalues (primary output)
            "forward_eigenvalues": forward_ev_dataset,     # NDDataset: forward eigenvalues
            "backward_eigenvalues": backward_ev_dataset,   # NDDataset: backward eigenvalues
            "model": efa,                                  # Model port
        }


@register_node
class HCANode(Node):
    """
    Hierarchical Cluster Analysis (HCA) node.

    Performs agglomerative clustering on spectral data.
    """

    metadata = NodeMetadata(
        node_type="model.hca",
        category="modeling",
        label="HCA",
        description="Hierarchical clustering (agglomerative) for unsupervised grouping",
        parameters=[
            NodeParameter(
                name="n_clusters",
                label="Number of Clusters",
                param_type="number",
                default=3,
                min_value=2,
                max_value=50,
                step=1,
                description="Number of clusters to form",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="linkage",
                label="Linkage",
                param_type="select",
                default="ward",
                options=[
                    {"label": "Ward", "value": "ward"},
                    {"label": "Average", "value": "average"},
                    {"label": "Complete", "value": "complete"},
                    {"label": "Single", "value": "single"},
                ],
                description="Linkage criterion",
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="metric",
                label="Distance Metric",
                param_type="select",
                default="euclidean",
                options=[
                    {"label": "Euclidean", "value": "euclidean"},
                    {"label": "Manhattan", "value": "manhattan"},
                    {"label": "Cosine", "value": "cosine"},
                    {"label": "L1", "value": "l1"},
                    {"label": "L2", "value": "l2"},
                ],
                description="Distance metric (ward requires euclidean)",
                required=False,
                category="advanced",
            ),
        ],
        input_types=["NDDataset", "array"],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="model",
                port_type="model",
                required=True,
                label="HCA Model",
                description="Cluster hierarchy (Linkage Matrix)",
            ),
            PortMetadata(
                name="labels",
                port_type="array",
                required=True,
                label="Cluster Labels",
                description="Assigned cluster labels for each sample",
            ),
            PortMetadata(
                name="linkage_matrix",
                port_type="array",
                required=True,
                label="Linkage Matrix",
                description="SciPy linkage matrix (Z)",
            ),
        ],
    )

    async def execute(self, input_data: Any) -> Any:
        """
        Execute hierarchical clustering.

        Args:
            input_data: NDDataset, SpectralResult, or array (samples x features)

        Returns:
            Dict containing cluster labels and metadata
        """
        from scipy.cluster.hierarchy import linkage, fcluster
        from scipy.spatial.distance import pdist
        from sklearn.decomposition import PCA as SkPCA

        # Convert input to numpy array - accept NDDataset or array
        if isinstance(input_data, NDDataset):
            X_data = np.array(input_data.data)
        else:
            X_data = np.array(input_data)

        if X_data.ndim == 1:
            X_data = X_data.reshape(-1, 1)

        n_clusters = self.parameters.get("n_clusters", 3)
        linkage_method = self.parameters.get("linkage", "ward")
        metric = self.parameters.get("metric", "euclidean")

        if linkage_method == "ward" and metric != "euclidean":
            raise ValueError("Ward linkage requires euclidean metric")

        print(f"\n[HCA Node] Executing with:")
        print(f"  - n_clusters: {n_clusters}")
        print(f"  - linkage: {linkage_method}")
        print(f"  - metric: {metric}")
        print(f"  - X shape: {X_data.shape}")

        # 1. Compute Linkage Matrix (Once)
        if linkage_method == "ward":
            # Ward requires euclidean distance
            Z = linkage(X_data, method=linkage_method, metric="euclidean")
        else:
            # Compute pairwise distances
            distances = pdist(X_data, metric=metric)
            Z = linkage(distances, method=linkage_method)

        # 2. Extract Cluster Labels
        # fcluster returns 1-based labels, convert to 0-based
        labels = fcluster(Z, t=n_clusters, criterion='maxclust') - 1

        if X_data.shape[1] == 1:
            embedding = np.column_stack([X_data[:, 0], np.zeros(X_data.shape[0])])
            embedding_method = "axis"
        elif X_data.shape[1] == 2:
            embedding = X_data
            embedding_method = "axis"
        else:
            embedding = SkPCA(n_components=2, random_state=42).fit_transform(X_data)
            embedding_method = "pca"

        label_list = labels.tolist()
        sample_labels = [str(label) for label in label_list]
        label_categories = sorted(list(set(sample_labels)))

        source_labels = None
        _y_coord = safe_get_coord(input_data, 'y') if isinstance(input_data, NDDataset) else None
        if _y_coord is not None:
            if hasattr(_y_coord, "labels") and _y_coord.labels is not None:
                labels_data = _y_coord.labels
                source_labels = labels_data.tolist() if hasattr(labels_data, "tolist") else list(labels_data)
            elif hasattr(_y_coord, "data") and _y_coord.data is not None:
                data_values = _y_coord.data
                source_labels = data_values.tolist() if hasattr(data_values, "tolist") else list(data_values)

        # Generate dendrogram plot using pre-computed linkage Z
        dendrogram_plot = self._generate_dendrogram(Z, linkage_method, source_labels, X_data.shape[0])

        return {
            "model": None,  # Scikit-learn model not used
            "linkage_matrix": Z.tolist(),
            "labels": label_list,
            "n_clusters": int(n_clusters),
            "data": embedding.tolist(),  # Restore tabular data for Data Table
            "plots": {
                "dendrogram": dendrogram_plot,
                "default": dendrogram_plot,  # Hint for Quick Plot to use this
            },
            "metadata": {
                "type": "HCA",
                "output_type": "clustering",
                "n_clusters": int(n_clusters),
                "linkage": linkage_method,
                "metric": metric,
                "embedding": embedding_method,
                "sample_labels": sample_labels,
                "label_categories": label_categories,
                "source_labels": source_labels,
            },
        }

    def _generate_dendrogram(self, Z, linkage_method, sample_labels=None, n_samples=None):
        """
        Generate dendrogram plot from linkage matrix.

        Args:
            Z: Linkage matrix
            linkage_method: Linkage method name
            sample_labels: Optional list of sample labels
            n_samples: Number of samples (for validation)

        Returns:
            Dict with dendrogram plot specification
        """
        from scipy.cluster.hierarchy import dendrogram

        # Generate dendrogram data structure: default orientation (we rotate manually)
        dend = dendrogram(Z, no_plot=True)

        # Extract dendrogram coordinates
        # Standard orientation:
        # - icoord = Index / X-axis
        # - dcoord = Distance / Y-axis
        icoord = dend["icoord"]
        dcoord = dend["dcoord"]
        colors = dend.get("color_list", ["#1f77b4"] * len(icoord))

        # Create traces for each dendrogram link
        traces = []
        for i, (idx_coords, dist_coords) in enumerate(zip(icoord, dcoord)):
            color = colors[i]
            
            # ROTATION MAP: Map Index(icoord) to Y, Distance(dcoord) to X
            x_vals = [float(val) for val in dist_coords]
            y_vals = [float(val) for val in idx_coords]
            
            traces.append({
                "x": x_vals,
                "y": y_vals,
                "type": "scatter",
                "mode": "lines",
                "line": {"color": color, "width": 3},
                "text": [f"Dist: {x:.2f}" for x in x_vals], # Simple hover info
                "hoverinfo": "text+x+y",
                "showlegend": False,
            })

        # Compute max distance for tight x-axis range (with null safety)
        # Handle edge cases: empty dcoord, empty rows, or all-zero values
        max_distance = 1.0
        if dcoord:
            valid_maxes = []
            for d in dcoord:
                if d and len(d) > 0:  # Check row is not empty
                    row_max = max(d)
                    if row_max is not None and np.isfinite(row_max):
                        valid_maxes.append(row_max)
            if valid_maxes:
                max_distance = max(valid_maxes)

        # Build layout with optional sample labels
        layout = {
            "title": f"Hierarchical Clustering Dendrogram ({linkage_method} linkage)",
            "xaxis": {
                "title": "Distance",
                "showgrid": True,
                "range": [0, max_distance * 1.02],  # Tight range with 2% padding
            },
            "yaxis": {
                "title": "Sample Index",
                "showgrid": False,
                "zeroline": False,
                "side": "right",  # Put labels on right side for readability
            },
            "hovermode": "closest",
        }

        # Add sample labels if available
        if sample_labels is not None and n_samples is not None and len(sample_labels) == n_samples:
            # Map dendrogram leaf positions to sample labels
            # leaves contains the original sample indices in dendrogram order
            leaves = dend["leaves"]
            leaf_labels = [str(sample_labels[i]) for i in leaves]
            layout["yaxis"]["ticktext"] = leaf_labels
            # Extract actual Y-positions from icoord (leaf positions are at the bottom of links)
            # scipy dendrogram places leaves at y = 5, 15, 25, ... (spacing of 10, starting at 5)
            # We use the icoord values which represent actual positions
            leaf_positions = sorted(set(
                coord for link in icoord for coord in [link[0], link[-1]]
                if coord == link[0] or coord == link[-1]  # Only endpoints (leaf positions)
            ))
            # If we can't extract positions reliably, fall back to standard spacing
            if len(leaf_positions) != len(leaves):
                leaf_positions = list(range(5, len(leaves) * 10 + 5, 10))
            layout["yaxis"]["tickvals"] = leaf_positions

        if n_samples:
            min_height_per_sample = 15  # pixels per sample for readability
            total_height = max(1000, n_samples * min_height_per_sample)
            layout["height"] = total_height
            layout["margin"] = {"l": 50, "r": 150}  # Right margin for labels
            # Tight y-axis range: scipy uses 10 units per leaf, starting at 5
            layout["yaxis"]["range"] = [0, n_samples * 10]

        return {
            "data": traces,
            "layout": layout,
        }


@register_node
class KMeansNode(Node):
    """
    K-Means clustering node.

    Performs k-means clustering on spectral data.
    """

    metadata = NodeMetadata(
        node_type="model.kmeans",
        category="modeling",
        label="KMeans",
        description="K-Means clustering for unsupervised grouping",
        parameters=[
            NodeParameter(
                name="n_clusters",
                label="Number of Clusters",
                param_type="number",
                default=3,
                min_value=2,
                max_value=50,
                step=1,
                description="Number of clusters to form",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="n_init",
                label="Initializations",
                param_type="number",
                default=10,
                min_value=1,
                max_value=50,
                step=1,
                description="Number of k-means initializations",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="max_iter",
                label="Max Iterations",
                param_type="number",
                default=300,
                min_value=50,
                max_value=1000,
                step=50,
                description="Maximum iterations per initialization",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="random_state",
                label="Random Seed",
                param_type="number",
                default=42,
                min_value=0,
                max_value=9999,
                step=1,
                description="Random seed for reproducibility",
                required=False,
                category="advanced",
            ),
        ],
        input_types=["NDDataset", "array"],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="model",
                port_type="model",
                required=True,
                label="KMeans Model",
                description="Fitted KMeans model object",
            ),
            PortMetadata(
                name="labels",
                port_type="array",
                required=True,
                label="Cluster Labels",
                description="Assigned cluster labels",
            ),
            PortMetadata(
                name="centroids",
                port_type="array",
                required=True,
                label="Centroids",
                description="Cluster centers coordinates",
            ),
        ],
    )

    async def execute(self, input_data: Any) -> Any:
        """
        Execute K-Means clustering.

        Args:
            input_data: NDDataset, SpectralResult, or array (samples x features)

        Returns:
            Dict containing cluster labels and metadata
        """
        from sklearn.cluster import KMeans
        from sklearn.decomposition import PCA as SkPCA

        # Accept NDDataset or array
        if isinstance(input_data, NDDataset):
            X_data = np.array(input_data.data)
        else:
            X_data = np.array(input_data)

        if X_data.ndim == 1:
            X_data = X_data.reshape(-1, 1)

        n_clusters = self.parameters.get("n_clusters", 3)
        n_init = self.parameters.get("n_init", 10)
        max_iter = self.parameters.get("max_iter", 300)
        random_state = self.parameters.get("random_state", 42)

        print(f"\n[KMeans Node] Executing with:")
        print(f"  - n_clusters: {n_clusters}")
        print(f"  - n_init: {n_init}")
        print(f"  - max_iter: {max_iter}")
        print(f"  - X shape: {X_data.shape}")

        model = KMeans(
            n_clusters=n_clusters,
            n_init=n_init,
            max_iter=max_iter,
            random_state=random_state,
        )
        labels = model.fit_predict(X_data)

        if X_data.shape[1] == 1:
            embedding = np.column_stack([X_data[:, 0], np.zeros(X_data.shape[0])])
            embedding_method = "axis"
        elif X_data.shape[1] == 2:
            embedding = X_data
            embedding_method = "axis"
        else:
            embedding = SkPCA(n_components=2, random_state=42).fit_transform(X_data)
            embedding_method = "pca"

        label_list = labels.tolist()
        sample_labels = [str(label) for label in label_list]
        label_categories = sorted(list(set(sample_labels)))

        source_labels = None
        _y_coord = safe_get_coord(input_data, 'y') if isinstance(input_data, NDDataset) else None
        if _y_coord is not None:
            if hasattr(_y_coord, "labels") and _y_coord.labels is not None:
                labels_data = _y_coord.labels
                source_labels = labels_data.tolist() if hasattr(labels_data, "tolist") else list(labels_data)
            elif hasattr(_y_coord, "data") and _y_coord.data is not None:
                data_values = _y_coord.data
                source_labels = data_values.tolist() if hasattr(data_values, "tolist") else list(data_values)

        return {
            "model": model,
            "labels": label_list,
            "centroids": model.cluster_centers_.tolist(),
            "inertia": float(model.inertia_),
            "n_clusters": int(n_clusters),
            "data": embedding.tolist(),
            "metadata": {
                "type": "KMeans",
                "output_type": "clustering",
                "n_clusters": int(n_clusters),
                "embedding": embedding_method,
                "sample_labels": sample_labels,
                "label_categories": label_categories,
                "source_labels": source_labels,
            },
        }


@register_node
class DBSCANNode(Node):
    """
    DBSCAN clustering node.

    Performs density-based clustering and marks noise points as -1.
    """

    metadata = NodeMetadata(
        node_type="model.dbscan",
        category="modeling",
        label="DBSCAN",
        description="Density-based clustering for unsupervised grouping",
        parameters=[
            NodeParameter(
                name="eps",
                label="Epsilon",
                param_type="number",
                default=0.5,
                min_value=0.01,
                max_value=10.0,
                step=0.01,
                description="Neighborhood radius",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="min_samples",
                label="Min Samples",
                param_type="number",
                default=5,
                min_value=2,
                max_value=50,
                step=1,
                description="Minimum samples per cluster",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="metric",
                label="Distance Metric",
                param_type="select",
                default="euclidean",
                options=["euclidean", "manhattan", "cosine", "l1", "l2"],
                description="Distance metric",
                required=False,
                category="advanced",
            ),
        ],
        input_types=["NDDataset", "array"],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="model",
                port_type="model",
                required=True,
                label="DBSCAN Model",
                description="Fitted DBSCAN model object",
            ),
            PortMetadata(
                name="labels",
                port_type="array",
                required=True,
                label="Cluster Labels",
                description="Assigned cluster labels (noise=-1)",
            ),
        ],
    )

    async def execute(self, input_data: Any) -> Any:
        """
        Execute DBSCAN clustering.

        Args:
            input_data: NDDataset, SpectralResult, or array (samples x features)

        Returns:
            Dict containing cluster labels and metadata
        """
        from sklearn.cluster import DBSCAN
        from sklearn.decomposition import PCA as SkPCA

        # Accept NDDataset or array
        if isinstance(input_data, NDDataset):
            X_data = np.array(input_data.data)
        else:
            X_data = np.array(input_data)

        if X_data.ndim == 1:
            X_data = X_data.reshape(-1, 1)

        eps = self.parameters.get("eps", 0.5)
        min_samples = self.parameters.get("min_samples", 5)
        metric = self.parameters.get("metric", "euclidean")

        print(f"\n[DBSCAN Node] Executing with:")
        print(f"  - eps: {eps}")
        print(f"  - min_samples: {min_samples}")
        print(f"  - metric: {metric}")
        print(f"  - X shape: {X_data.shape}")

        model = DBSCAN(eps=eps, min_samples=min_samples, metric=metric)
        labels = model.fit_predict(X_data)

        if X_data.shape[1] == 1:
            embedding = np.column_stack([X_data[:, 0], np.zeros(X_data.shape[0])])
            embedding_method = "axis"
        elif X_data.shape[1] == 2:
            embedding = X_data
            embedding_method = "axis"
        else:
            embedding = SkPCA(n_components=2, random_state=42).fit_transform(X_data)
            embedding_method = "pca"

        label_list = labels.tolist()
        sample_labels = [str(label) for label in label_list]
        label_categories = sorted(list(set(sample_labels)))
        n_clusters = len([label for label in label_categories if label != "-1"])

        source_labels = None
        _y_coord = safe_get_coord(input_data, 'y') if isinstance(input_data, NDDataset) else None
        if _y_coord is not None:
            if hasattr(_y_coord, "labels") and _y_coord.labels is not None:
                labels_data = _y_coord.labels
                source_labels = labels_data.tolist() if hasattr(labels_data, "tolist") else list(labels_data)
            elif hasattr(_y_coord, "data") and _y_coord.data is not None:
                data_values = _y_coord.data
                source_labels = data_values.tolist() if hasattr(data_values, "tolist") else list(data_values)

        return {
            "model": model,
            "labels": label_list,
            "n_clusters": int(n_clusters),
            "data": embedding.tolist(),
            "metadata": {
                "type": "DBSCAN",
                "output_type": "clustering",
                "n_clusters": int(n_clusters),
                "eps": eps,
                "min_samples": min_samples,
                "metric": metric,
                "embedding": embedding_method,
                "sample_labels": sample_labels,
                "label_categories": label_categories,
                "source_labels": source_labels,
            },
        }


@register_node
class PeakFindingNode(Node):
    """
    Peak Finding node.

    Identifies peaks in spectroscopic data using scipy's signal processing algorithms.
    Supports height, distance, prominence, and width-based peak detection criteria.

    Returns peak positions, heights, widths, prominences, and integrated areas.
    """

    metadata = NodeMetadata(
        node_type="analysis.peak_finding",
        category="modeling",
        label="Peak Finding",
        description="Find peaks in spectral data with domain-specific algorithms",
        parameters=[
            NodeParameter(
                name="height",
                label="Minimum Height",
                param_type="number",
                default=None,
                min_value=0.0,
                max_value=100.0,
                step=0.01,
                description="Minimum peak height (leave empty for auto)",
                required=False,
            ),
            NodeParameter(
                name="threshold",
                label="Threshold",
                param_type="number",
                default=None,
                min_value=0.0,
                max_value=10.0,
                step=0.01,
                description="Minimum vertical distance to neighbors",
                required=False,
            ),
            NodeParameter(
                name="distance",
                label="Minimum Distance",
                param_type="number",
                default=10,
                min_value=1,
                max_value=100,
                step=1,
                description="Minimum horizontal distance between peaks (in points)",
                required=False,
            ),
            NodeParameter(
                name="prominence",
                label="Prominence",
                param_type="number",
                default=None,
                min_value=0.0,
                max_value=10.0,
                step=0.01,
                description="Peak prominence threshold",
                required=False,
            ),
            NodeParameter(
                name="width",
                label="Expected Width",
                param_type="number",
                default=None,
                min_value=1,
                max_value=100,
                step=1,
                description="Expected peak width (in points)",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="PeakData",
        output_ports=[
            PortMetadata(
                name="peaks",
                port_type="array",
                required=True,
                label="Peak List",
                description="Detected peaks with positions, heights, widths, areas",
            ),
            PortMetadata(
                name="annotated_spectrum",
                port_type="array",
                required=True,
                label="Annotated Spectrum",
                description="Spectrum with peak markers and labels",
            ),
            PortMetadata(
                name="spectrum",
                port_type="array",
                required=False,
                label="Original Spectrum",
                description="Input spectrum (for comparison)",
            ),
        ],
    )

    async def execute(self, input_data: Any) -> Any:
        """
        Execute peak finding on spectral data.

        Args:
            input_data: NDDataset or SpectralResult containing spectral data

        Returns:
            Dict containing peak positions, heights, widths, and areas
        """
        from scipy.signal import find_peaks as scipy_find_peaks

        # Input should already be NDDataset from DAG pipeline

        # Get parameters
        height = self.parameters.get("height")
        threshold = self.parameters.get("threshold")
        distance = self.parameters.get("distance", 10)
        prominence = self.parameters.get("prominence")
        width = self.parameters.get("width")

        # Convert to numpy array
        data = np.array(input_data.data)

        # Handle multi-spectrum input (take first spectrum for peak finding)
        if data.ndim > 1:
            spectrum = data[0]
            print(f"[Peak Finding] Multi-spectrum input detected, analyzing first spectrum")
        else:
            spectrum = data

        # Build kwargs for scipy find_peaks
        peak_kwargs = {}
        if height is not None:
            peak_kwargs['height'] = height
        if threshold is not None:
            peak_kwargs['threshold'] = threshold
        if distance is not None:
            peak_kwargs['distance'] = distance
        if prominence is not None:
            peak_kwargs['prominence'] = prominence
        if width is not None:
            peak_kwargs['width'] = width

        # Find peaks using scipy
        peak_indices, peak_properties = scipy_find_peaks(spectrum, **peak_kwargs)

        # Get wavenumber/ppm positions if available
        _x_coord = safe_get_coord(input_data, 'x')
        if _x_coord is not None:
            x_axis = np.array(_x_coord.data)
            peak_positions = x_axis[peak_indices].tolist()
            x_unit = str(_x_coord.units) if hasattr(_x_coord, 'units') else "cm⁻¹"
        else:
            peak_positions = peak_indices.tolist()
            x_unit = "index"

        # Extract peak properties
        peak_heights = spectrum[peak_indices].tolist()

        # Get widths if calculated
        peak_widths = peak_properties.get('widths', np.zeros(len(peak_indices))).tolist()

        # Get prominences if calculated
        peak_prominences = peak_properties.get('prominences', np.zeros(len(peak_indices))).tolist()

        # Estimate peak areas (simple trapezoidal integration around peak)
        peak_areas = []
        for idx, width in zip(peak_indices, peak_widths):
            if width > 0:
                # Integration window: peak ± width/2
                left = max(0, int(idx - width / 2))
                right = min(len(spectrum), int(idx + width / 2))
                area = np.trapz(spectrum[left:right])
                peak_areas.append(area)
            else:
                peak_areas.append(peak_heights[peak_indices.tolist().index(idx)])

        # Create annotated spectrum for visualization
        annotated_spectrum = spectrum.copy()

        result = {
            "peaks": {
                "count": len(peak_indices),
                "positions": peak_positions,
                "indices": peak_indices.tolist(),
                "heights": peak_heights,
                "widths": peak_widths,
                "prominences": peak_prominences,
                "areas": peak_areas,
            },
            "spectrum": spectrum.tolist(),
            "annotated_spectrum": annotated_spectrum.tolist(),
            "x_axis": (np.array(_x_coord.data).tolist() if _x_coord is not None else list(range(len(spectrum)))),
            "x_unit": x_unit,
            # Visualization data
            "data": [[pos, height] for pos, height in zip(peak_positions, peak_heights)],
            "metadata": {
                "type": "PeakFinding",
                "output_type": "analysis",
                "n_peaks": len(peak_indices),
                "x_unit": x_unit,
                "peak_table": [
                    {
                        "position": pos,
                        "height": height,
                        "width": width,
                        "prominence": prom,
                        "area": area,
                    }
                    for pos, height, width, prom, area in zip(
                        peak_positions, peak_heights, peak_widths, peak_prominences, peak_areas
                    )
                ],
            },
        }

        print(f"[Peak Finding] Found {len(peak_indices)} peaks")

        return result


@register_node
class SIMPLISMANode(Node):
    """
    SIMPLISMA (SIMPLe-to-use Interactive Self-modeling Mixture Analysis) node.

    Performs SIMPLISMA decomposition to resolve pure component spectra
    from mixture data using a self-modeling approach based on purity maximization.

    Uses SpectroChemPy's SIMPLISMA implementation.
    """

    metadata = NodeMetadata(
        node_type="model.simplisma",
        category="modeling",
        label="SIMPLISMA",
        description="Self-modeling mixture analysis using purity maximization",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=3,
                min_value=2,
                max_value=20,
                step=1,
                description="Number of pure components to resolve",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="tol",
                label="Tolerance",
                param_type="number",
                default=0.1,
                min_value=0.001,
                max_value=1.0,
                step=0.01,
                description="Convergence tolerance",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="noise",
                label="Noise Level",
                param_type="number",
                default=3.0,
                min_value=0.0,
                max_value=10.0,
                step=0.1,
                description="Noise level for purity calculation",
                required=False,
                category="advanced",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="model",
                port_type="model",
                required=True,
                label="SIMPLISMA Model",
                description="Fitted SIMPLISMA model object",
            ),
            PortMetadata(
                name="concentrations",
                port_type="array",
                required=True,
                label="Concentrations",
                description="Resolved concentration profiles (C)",
            ),
            PortMetadata(
                name="spectra",
                port_type="dataset",
                required=True,
                label="Pure Spectra",
                description="Resolved pure component spectra (St)",
            ),
            PortMetadata(
                name="purity_values",
                port_type="array",
                required=False,
                label="Purity Values",
                description="Purity values for resolved components",
            ),
        ],
    )

    async def execute(self, input_data: Any) -> Any:
        """
        Execute SIMPLISMA decomposition on input dataset.

        Args:
            input_data: NDDataset or SpectralResult containing spectral mixture data
                       Shape should be (n_samples, n_wavenumbers)

        Returns:
            Dict containing:
            - C: Concentration profiles (n_samples, n_components)
            - St: Pure spectra (n_components, n_wavenumbers)
            - n_components: Number of resolved components
        """
        # Input should already be NDDataset from DAG pipeline

        # Get parameters
        n_components = self.parameters.get("n_components", 3)
        tol = self.parameters.get("tol", 0.1)
        noise = self.parameters.get("noise", 3.0)

        # Validate input shape
        if len(input_data.shape) != 2:
            raise ValueError(f"Expected 2D input, got shape {input_data.shape}")

        n_samples, n_features = input_data.shape
        if n_components > min(n_samples, n_features):
            raise ValueError(
                f"n_components ({n_components}) cannot exceed min(n_samples, n_features) = {min(n_samples, n_features)}"
            )

        print(f"\n[SIMPLISMA Node] Executing with:")
        print(f"  - n_components: {n_components}")
        print(f"  - tol: {tol}")
        print(f"  - noise: {noise}")
        print(f"  - Data shape: {n_samples} samples × {n_features} features")

        # Perform SIMPLISMA using SpectroChemPy
        simplisma = scp.SIMPLISMA(n_components=n_components, tol=tol, noise=noise)
        simplisma.fit(input_data)

        # Extract results
        C_data = np.array(simplisma.C.data) if hasattr(simplisma.C, "data") else np.array(simplisma.C)
        St_data = np.array(simplisma.St.data) if hasattr(simplisma.St, "data") else np.array(simplisma.St)

        # Get wavenumber axis from input if available
        wavenumbers = None
        _x_coord = safe_get_coord(input_data, 'x')
        if _x_coord is not None:
            wavenumbers = np.array(_x_coord.data).tolist()

        # Get time axis from input if available
        times = None
        _y_coord = safe_get_coord(input_data, 'y')
        if _y_coord is not None:
            times = np.array(_y_coord.data).tolist()
        else:
            # Use sample indices as time points
            times = list(range(n_samples))

        print(f"[SIMPLISMA Node] Decomposition completed successfully")
        print(f"  - C shape: {C_data.shape}")
        print(f"  - St shape: {St_data.shape}")

        # Extract sample labels from input data for categorical coloring
        sample_labels = None
        label_categories = None

        if _y_coord is not None:
            if hasattr(_y_coord, 'labels') and _y_coord.labels is not None:
                try:
                    labels = _y_coord.labels
                    raw = labels.tolist() if hasattr(labels, 'tolist') else list(labels)
                    # Convert ALL labels to native Python str — avoids numpy StrDType
                    # ufunc errors when sorting/comparing numpy string scalars
                    sample_labels = [str(l) for l in raw]
                    label_categories = sorted(set(sample_labels))
                    print(f"[SIMPLISMA Node] Extracted {len(sample_labels)} sample labels with {len(label_categories)} unique categories")
                except Exception as e:
                    print(f"[SIMPLISMA Node] Warning: Could not extract categorical labels from y.labels: {e}")
                    sample_labels = None
                    label_categories = None

            if sample_labels is None and hasattr(_y_coord, 'data') and _y_coord.data is not None:
                try:
                    # Fallback: use y-axis data as numeric labels
                    y_data = _y_coord.data
                    raw = y_data.tolist() if hasattr(y_data, 'tolist') else list(y_data)
                    sample_labels = [str(l) for l in raw]

                    # For numeric data, only treat as categorical if:
                    # 1. Reasonable number of unique values (< 20)
                    # 2. NOT a sequential series (e.g., not time indices or temperature series)
                    unique_values = sorted(set(sample_labels))
                    if len(unique_values) < 20 and not _is_sequential_numeric(raw):
                        label_categories = unique_values
                        print(f"[SIMPLISMA Node] Using numeric y.data as categorical labels: {len(label_categories)} categories")
                except Exception as e:
                    print(f"[SIMPLISMA Node] Warning: Could not extract categorical labels from y.data: {e}")
                    sample_labels = None
                    label_categories = None

        # If no labels found, generate default sample labels
        if sample_labels is None:
            sample_labels = [f"Sample {i+1}" for i in range(n_samples)]

        # Get purity values if available
        purities = None
        if hasattr(simplisma, "purities"):
            purities = np.array(simplisma.purities).tolist()

        return {
            "model": simplisma,
            "concentrations": C_data.tolist(),
            "spectra": St_data.tolist(),
            "purity_values": purities if purities is not None else [],
            "C": C_data.tolist(),          # Concentration profiles (n_samples, n_components)
            "St": St_data.tolist(),        # Pure spectra (n_components, n_features)
            "n_components": n_components,
            "n_samples": n_samples,
            "n_features": n_features,
            # Primary data for visualization - concentration profiles
            "data": C_data.tolist(),
            "metadata": {
                "type": "SIMPLISMA",
                "output_type": "decomposition",
                "n_components": n_components,
                "n_samples": n_samples,
                "n_features": n_features,
                # Labels for concentration columns
                "labels": [f"Component {i+1}" for i in range(n_components)],
                # X-axis for C plot (time/sample index)
                "x_axis": times,
                "x_label": "Time / Sample Index",
                "y_label": "Relative Concentration",
                # Wavenumbers for St plot
                "wavenumbers": wavenumbers,
                # Additional data for St visualization
                "St": St_data.tolist(),
                "St_labels": [f"Pure Spectrum {i+1}" for i in range(n_components)],
                # Sample labels for categorical coloring
                "sample_labels": sample_labels,  # List of labels (one per sample)
                "label_categories": label_categories,  # List of unique categories (None if no categorical labels)
            },
        }


@register_node
class NMFNode(Node):
    """
    Non-negative Matrix Factorization (NMF) node.

    Performs NMF decomposition with non-negativity constraints on both
    the concentration (W) and spectral (H) matrices. Provides physically
    interpretable results for mixture analysis.

    Uses SpectroChemPy's NMF implementation.
    """

    metadata = NodeMetadata(
        node_type="model.nmf",
        category="modeling",
        label="NMF",
        description="Non-negative Matrix Factorization for mixture analysis",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=3,
                min_value=2,
                max_value=20,
                step=1,
                description="Number of components to extract",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="solver",
                label="Solver",
                param_type="select",
                default="mu",
                options=["mu", "cd"],
                description="NMF solver: 'mu' (Multiplicative Update) or 'cd' (Coordinate Descent)",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="max_iter",
                label="Maximum Iterations",
                param_type="number",
                default=200,
                min_value=50,
                max_value=1000,
                step=50,
                description="Maximum number of iterations",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="tol",
                label="Convergence Tolerance",
                param_type="number",
                default=0.0001,
                min_value=0.00001,
                max_value=0.01,
                step=0.0001,
                description="Convergence tolerance",
                required=False,
                category="advanced",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="model",
                port_type="model",
                required=True,
                label="NMF Model",
                description="Fitted NMF model object",
            ),
            PortMetadata(
                name="concentrations",
                port_type="dataset",
                required=True,
                label="Concentrations",
                description="Concentration profiles (W matrix) as NDDataset with sample/component axes",
            ),
            PortMetadata(
                name="spectra",
                port_type="dataset",
                required=True,
                label="Pure Spectra",
                description="Pure component spectra (H matrix) as NDDataset with wavenumber axis",
            ),
            PortMetadata(
                name="reconstruction_error",
                port_type="array",
                required=False,
                label="Reconstruction Error",
                description="Final reconstruction error value",
            ),
        ],
    )

    async def execute(self, input_data: Any) -> Any:
        """
        Execute NMF decomposition on input dataset.

        Args:
            input_data: NDDataset or SpectralResult containing non-negative spectral data
                       Shape should be (n_samples, n_wavenumbers)

        Returns:
            Dict containing:
            - W: Basis matrix / concentration profiles (n_samples, n_components) as SpectralResult
            - H: Coefficient matrix / pure spectra (n_components, n_wavenumbers) as SpectralResult
            - n_components: Number of components
        """
        # Input should already be NDDataset from DAG pipeline

        # Get parameters
        n_components = self.parameters.get("n_components", 3)
        solver = self.parameters.get("solver", "mu")
        max_iter = self.parameters.get("max_iter", 200)
        tol = self.parameters.get("tol", 0.0001)

        # Validate input shape
        if len(input_data.shape) != 2:
            raise ValueError(f"Expected 2D input, got shape {input_data.shape}")

        n_samples, n_features = input_data.shape
        if n_components > min(n_samples, n_features):
            raise ValueError(
                f"n_components ({n_components}) cannot exceed min(n_samples, n_features) = {min(n_samples, n_features)}"
            )

        # Check for negative values (NMF requires non-negative data)
        data_array = np.array(input_data.data)
        if np.any(data_array < 0):
            print("[NMF Node] Warning: Input contains negative values, shifting to non-negative range")
            data_array = data_array - data_array.min()
            input_data = scp.NDDataset(data_array)

        print(f"\n[NMF Node] Executing with:")
        print(f"  - n_components: {n_components}")
        print(f"  - solver: {solver}")
        print(f"  - max_iter: {max_iter}")
        print(f"  - tol: {tol}")
        print(f"  - Data shape: {n_samples} samples × {n_features} features")

        # Perform NMF using SpectroChemPy
        nmf = scp.NMF(n_components=n_components, solver=solver, max_iter=max_iter, tol=tol)
        nmf.fit(input_data)

        # Extract results (W = concentration, H = spectra)
        # NMF.transform() returns W matrix (basis coefficients)
        W = nmf.transform(input_data)
        W_data = np.array(W.data) if hasattr(W, "data") else np.array(W)

        # NMF.components_ returns H matrix (components)
        if hasattr(nmf, "components_"):
            H_data = np.array(nmf.components_.data) if hasattr(nmf.components_, "data") else np.array(nmf.components_)
        else:
            # Fallback if components_ is not available
            H_data = np.zeros((n_components, n_features))

        # Get input coordinates for NDDataset creation
        _x_coord = safe_get_coord(input_data, 'x')
        _y_coord = safe_get_coord(input_data, 'y')

        # Get reconstruction error if available
        reconstruction_err = None
        if hasattr(nmf, "reconstruction_err_"):
            reconstruction_err = float(nmf.reconstruction_err_)

        print(f"[NMF Node] Decomposition completed successfully")
        print(f"  - W shape: {W_data.shape}")
        print(f"  - H shape: {H_data.shape}")
        if reconstruction_err is not None:
            print(f"  - Reconstruction error: {reconstruction_err:.6f}")

        # Extract label_categories for categorical coloring
        label_categories = None
        if _y_coord is not None:
            try:
                if hasattr(_y_coord, 'labels') and _y_coord.labels is not None:
                    raw = _y_coord.labels.tolist() if hasattr(_y_coord.labels, 'tolist') else list(_y_coord.labels)
                    label_categories = sorted(set(str(l) for l in raw))
                elif hasattr(_y_coord, 'data') and _y_coord.data is not None:
                    raw = _y_coord.data.tolist() if hasattr(_y_coord.data, 'tolist') else list(_y_coord.data)
                    str_labels = [str(l) for l in raw]
                    unique = sorted(set(str_labels))
                    if len(unique) < 20 and not _is_sequential_numeric(raw):
                        label_categories = unique
            except Exception:
                label_categories = None

        # =====================================================================
        # Create proper NDDataset objects for W and H with coordinate coupling
        # This enables "smart array" behavior - slicing data also slices axes
        # =====================================================================

        component_labels = [f"Component {i+1}" for i in range(n_components)]
        spectrum_labels = [f"Basis Spectrum {i+1}" for i in range(n_components)]

        # H (Pure Spectra): shape (n_components, n_features)
        # X-axis = wavenumbers from input, Y-axis = component labels
        H_dataset = _create_spectral_dataset(
            data=H_data,
            x_coord=_x_coord,
            y_coord=scp.Coord(spectrum_labels, title="Component"),
            units=input_data.units if hasattr(input_data, 'units') else None,
            title="NMF Basis Spectra (H)",
        )

        # W (Concentrations): shape (n_samples, n_components)
        # X-axis = component labels, Y-axis = sample labels/time
        W_dataset = _create_spectral_dataset(
            data=W_data,
            x_coord=scp.Coord(component_labels, title="Component"),
            y_coord=_y_coord,  # Preserve sample labels from input
            units="relative concentration",
            title="NMF Concentration Profiles (W)",
        )

        # Add processing history to NDDataset outputs
        copy_processing_history(input_data, W_dataset)
        add_processing_step(
            W_dataset,
            "model.nmf.concentrations",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        copy_processing_history(input_data, H_dataset)
        add_processing_step(
            H_dataset,
            "model.nmf.spectra",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        # Store only scientific metadata that coordinates can't carry
        W_dataset.meta.update({
            "n_components": n_components,
            "label_categories": label_categories,
            "reconstruction_error": reconstruction_err,
        })

        return {
            "default": W_dataset,                # NDDataset: concentration profiles + sample labels (y) + component coords (x)
            "concentrations": W_dataset,         # Alias for default
            "spectra": H_dataset,                # NDDataset: basis spectra + wavenumbers (x) + component coords (y)
            "W": W_dataset,                      # Alias for concentrations
            "H": H_dataset,                      # Alias for spectra
            "model": nmf,                        # Model port
        }


@register_node
class FastICANode(Node):
    """
    Fast Independent Component Analysis (FastICA) node.

    Performs ICA to separate multivariate signals into independent
    non-Gaussian signals. Useful for blind source separation in
    spectroscopic mixture analysis.

    Uses SpectroChemPy's FastICA implementation.
    """

    metadata = NodeMetadata(
        node_type="model.ica",
        category="modeling",
        label="FastICA",
        description="Independent Component Analysis for blind source separation",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=3,
                min_value=2,
                max_value=20,
                step=1,
                description="Number of independent components to extract",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="algorithm",
                label="Algorithm",
                param_type="select",
                default="parallel",
                options=["parallel", "deflation"],
                description="ICA algorithm: 'parallel' (all components at once) or 'deflation' (one at a time)",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="fun",
                label="Contrast Function",
                param_type="select",
                default="logcosh",
                options=["logcosh", "exp", "cube"],
                description="Contrast function for ICA: 'logcosh', 'exp', or 'cube'",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="max_iter",
                label="Maximum Iterations",
                param_type="number",
                default=200,
                min_value=50,
                max_value=1000,
                step=50,
                description="Maximum number of iterations",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="tol",
                label="Convergence Tolerance",
                param_type="number",
                default=0.0001,
                min_value=0.00001,
                max_value=0.01,
                step=0.0001,
                description="Convergence tolerance",
                required=False,
                category="advanced",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="model",
                port_type="model",
                required=True,
                label="ICA Model",
                description="Fitted FastICA model object",
            ),
            PortMetadata(
                name="sources",
                port_type="array",
                required=True,
                label="Source Signals",
                description="Independent source signals (S)",
            ),
            PortMetadata(
                name="mixing_matrix",
                port_type="array",
                required=True,
                label="Mixing Matrix",
                description="Mixing matrix (A)",
            ),
            PortMetadata(
                name="components",
                port_type="dataset",
                required=True,
                label="Components",
                description="Independent components (St)",
            ),
        ],
    )

    async def execute(self, input_data: Any) -> Any:
        """
        Execute FastICA decomposition on input dataset.

        Args:
            input_data: NDDataset or SpectralResult containing spectral mixture data
                       Shape should be (n_samples, n_wavenumbers)

        Returns:
            Dict containing:
            - S: Independent source signals (n_samples, n_components)
            - A: Mixing matrix (n_components, n_wavenumbers)
            - n_components: Number of components
        """
        # Input should already be NDDataset from DAG pipeline

        # Get parameters
        n_components = self.parameters.get("n_components", 3)
        algorithm = self.parameters.get("algorithm", "parallel")
        fun = self.parameters.get("fun", "logcosh")
        max_iter = self.parameters.get("max_iter", 200)
        tol = self.parameters.get("tol", 0.0001)

        # Validate input shape
        if len(input_data.shape) != 2:
            raise ValueError(f"Expected 2D input, got shape {input_data.shape}")

        n_samples, n_features = input_data.shape
        if n_components > min(n_samples, n_features):
            raise ValueError(
                f"n_components ({n_components}) cannot exceed min(n_samples, n_features) = {min(n_samples, n_features)}"
            )

        print(f"\n[FastICA Node] Executing with:")
        print(f"  - n_components: {n_components}")
        print(f"  - algorithm: {algorithm}")
        print(f"  - fun: {fun}")
        print(f"  - max_iter: {max_iter}")
        print(f"  - tol: {tol}")
        print(f"  - Data shape: {n_samples} samples × {n_features} features")

        # Perform FastICA using SpectroChemPy
        ica = scp.FastICA(
            n_components=n_components,
            algorithm=algorithm,
            fun=fun,
            max_iter=max_iter,
            tol=tol
        )
        ica.fit(input_data)

        # Extract results
        # St = source spectral profiles (n_components, n_features) - transpose of sources
        # A = mixing matrix (n_samples, n_components)
        # Sources: extract from transform
        sources = ica.transform(input_data)
        S_data = np.array(sources.data) if hasattr(sources, "data") else np.array(sources)

        # Get spectral profiles (St attribute)
        if hasattr(ica, "St"):
            St_data = np.array(ica.St.data) if hasattr(ica.St, "data") else np.array(ica.St)
        elif hasattr(ica, "components_"):
            St_data = np.array(ica.components_)
        else:
            St_data = None

        # Get mixing matrix
        if hasattr(ica, "A"):
            A_data = np.array(ica.A.data) if hasattr(ica.A, "data") else np.array(ica.A)
        elif hasattr(ica, "mixing_"):
            A_data = np.array(ica.mixing_)
        else:
            A_data = None

        # Get input coordinates for NDDataset creation
        _x_coord = safe_get_coord(input_data, 'x')
        _y_coord = safe_get_coord(input_data, 'y')

        print(f"[FastICA Node] Decomposition completed successfully")
        print(f"  - S (sources) shape: {S_data.shape}")
        if St_data is not None:
            print(f"  - St (spectral profiles) shape: {St_data.shape}")
        if A_data is not None:
            print(f"  - A (mixing) shape: {A_data.shape}")

        # Extract label_categories for categorical coloring
        label_categories = None
        if _y_coord is not None:
            try:
                if hasattr(_y_coord, 'labels') and _y_coord.labels is not None:
                    raw = _y_coord.labels.tolist() if hasattr(_y_coord.labels, 'tolist') else list(_y_coord.labels)
                    label_categories = sorted(set(str(l) for l in raw))
                elif hasattr(_y_coord, 'data') and _y_coord.data is not None:
                    raw = _y_coord.data.tolist() if hasattr(_y_coord.data, 'tolist') else list(_y_coord.data)
                    str_labels = [str(l) for l in raw]
                    unique = sorted(set(str_labels))
                    if len(unique) < 20 and not _is_sequential_numeric(raw):
                        label_categories = unique
            except Exception:
                label_categories = None

        # Try to extract species names from input metadata (from BlendNode ground truth)
        species_names = None
        if hasattr(input_data, 'meta') and input_data.meta:
            spectra_meta = input_data.meta.get("spectra", {})
            if isinstance(spectra_meta, dict):
                species_list = spectra_meta.get("species", [])
                if species_list and len(species_list) >= n_components:
                    try:
                        names = []
                        for spec in species_list[:n_components]:
                            if isinstance(spec, dict):
                                names.append(spec.get("name", f"IC {len(names)+1}"))
                            elif hasattr(spec, "name"):
                                names.append(spec.name)
                            else:
                                names.append(f"IC {len(names)+1}")
                        species_names = names
                        print(f"[FastICA Node] Extracted species names from input metadata: {species_names}")
                    except Exception as e:
                        print(f"[FastICA Node] Warning: Could not extract species names: {e}")

        # Use species names if available, otherwise use generic labels
        component_labels = species_names or [f"IC {i+1}" for i in range(n_components)]
        spectrum_labels = species_names or [f"IC Spectrum {i+1}" for i in range(n_components)]

        # =====================================================================
        # Create proper NDDataset objects with coordinate coupling
        # This enables "smart array" behavior - slicing data also slices axes
        # =====================================================================

        # S (Sources): shape (n_samples, n_components)
        # X-axis = component labels, Y-axis = sample labels/time
        S_dataset = _create_spectral_dataset(
            data=S_data,
            x_coord=scp.Coord(component_labels, title="Independent Component"),
            y_coord=_y_coord,  # Preserve sample labels from input
            units="source signal",
            title="FastICA Source Signals",
        )

        # St (Spectral Profiles): shape (n_components, n_features)
        # X-axis = wavenumbers from input, Y-axis = component labels
        St_dataset = None
        if St_data is not None:
            St_dataset = _create_spectral_dataset(
                data=St_data,
                x_coord=_x_coord,
                y_coord=scp.Coord(spectrum_labels, title="Independent Component"),
                units=input_data.units if hasattr(input_data, 'units') else None,
                title="FastICA Spectral Profiles",
            )

        # A (Mixing Matrix): shape (n_samples, n_components) or similar
        A_dataset = None
        if A_data is not None:
            A_dataset = _create_spectral_dataset(
                data=A_data,
                x_coord=scp.Coord(component_labels, title="Independent Component"),
                y_coord=_y_coord,  # Preserve sample labels from input
                units="mixing coefficient",
                title="FastICA Mixing Matrix",
            )

        # Add processing history to NDDataset outputs
        copy_processing_history(input_data, S_dataset)
        add_processing_step(
            S_dataset,
            "model.ica.sources",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        if St_dataset is not None:
            copy_processing_history(input_data, St_dataset)
            add_processing_step(
                St_dataset,
                "model.ica.components",
                {"n_components": n_components},
                node_id=self.node_id,
            )

        if A_dataset is not None:
            copy_processing_history(input_data, A_dataset)
            add_processing_step(
                A_dataset,
                "model.ica.mixing_matrix",
                {"n_components": n_components},
                node_id=self.node_id,
            )

        # Store only scientific metadata that coordinates can't carry
        S_dataset.meta.update({
            "n_components": n_components,
            "label_categories": label_categories,
            "species_names": species_names,
        })

        return {
            "default": S_dataset,                # NDDataset: source signals + sample labels (y) + IC coords (x)
            "sources": S_dataset,                # Alias for default
            "components": St_dataset,            # NDDataset: spectral profiles + wavenumbers (x) + IC coords (y)
            "mixing_matrix": A_dataset,          # NDDataset: mixing matrix
            "model": ica,                        # Model port
        }


# =============================================================================
# Apply Model Nodes (Inference)
# =============================================================================


@register_node
class PLSPredictNode(Node):
    """
    Apply trained PLS model to predict new samples.
    
    Takes a trained PLS model and new data, returns predictions.
    Critical for train/test validation and production inference.
    """
    
    metadata = NodeMetadata(
        node_type="model.pls_predict",
        category="modeling",
        label="Apply PLS Model",
        description="Apply trained PLS model to predict concentrations for new spectra",
        parameters=[],
        input_ports=[
            PortMetadata(
                name="X_new",
                port_type="dataset",
                required=True,
                label="New Spectra",
                description="Spectral data to predict (preprocessed same as training data)",
            ),
            PortMetadata(
                name="model",
                port_type="model",
                required=True,
                label="PLS Model",
                description="Trained PLS model from PLS training node",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="y_pred",
                port_type="target",
                required=True,
                label="Predictions",
                description="Predicted concentration values",
            ),
        ],
        input_types=["NDDataset", "dict"],
        output_type="array",
    )
    
    async def execute(self, X_new: Any = None, model: Any = None, **kwargs: Any) -> dict[str, Any]:
        """
        Apply PLS model to new data.

        Args:
            X_new: New spectral data (NDDataset or SpectralResult)
            model: Trained PLS model dict from PLS node

        Returns:
            dict with 'y_pred' key containing predictions
        """
        if X_new is None or model is None:
            raise ValueError("Both X_new and model inputs are required")

        # X_new should already be NDDataset from DAG pipeline

        # Extract model from result dict
        if isinstance(model, dict):
            pls_model = model.get("model")
            if pls_model is None:
                raise ValueError("Model dict must contain 'model' key with trained PLS object")
        else:
            pls_model = model

        # Make predictions - SpectroChemPy PLSRegression can accept NDDataset or array
        try:
            # Prefer passing NDDataset for SpectroChemPy models (preserves metadata)
            if isinstance(X_new, NDDataset):
                y_pred = pls_model.predict(X_new)
            else:
                # Fallback to array for non-NDDataset inputs
                X_array = np.array(X_new)
                y_pred = pls_model.predict(X_array)

            # Extract underlying data if result is NDDataset
            if hasattr(y_pred, "data"):
                y_pred_array = np.array(y_pred.data)
            else:
                y_pred_array = np.array(y_pred)

            # Flatten if needed
            if y_pred_array.ndim > 1 and y_pred_array.shape[1] == 1:
                y_pred_array = y_pred_array.ravel()

            print(f"[PLS Predict] Generated {len(y_pred_array)} predictions")

            return {"y_pred": y_pred_array}

        except Exception as e:
            raise RuntimeError(f"PLS prediction failed: {str(e)}") from e


@register_node
class PCATransformNode(Node):
    """
    Transform new data using trained PCA model.
    
    Projects new samples into the principal component space
    defined by a trained PCA model.
    """
    
    metadata = NodeMetadata(
        node_type="model.pca_transform",
        category="modeling",
        label="Apply PCA Transform",
        description="Transform new data using trained PCA model (project to PC space)",
        parameters=[],
        input_ports=[
            PortMetadata(
                name="X_new",
                port_type="dataset",
                required=True,
                label="New Spectra",
                description="Spectral data to transform",
            ),
            PortMetadata(
                name="model",
                port_type="model",
                required=True,
                label="PCA Model",
                description="Trained PCA model from PCA training node",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="scores",
                port_type="target",
                required=True,
                label="PC Scores",
                description="Scores in principal component space",
            ),
        ],
        input_types=["NDDataset", "dict"],
        output_type="array",
    )
    
    async def execute(self, X_new: Any = None, model: Any = None, **kwargs: Any) -> dict[str, Any]:
        """
        Transform new data using PCA model.

        Args:
            X_new: New spectral data (NDDataset or SpectralResult)
            model: Trained PCA model dict from PCA node

        Returns:
            dict with 'scores' key containing PC scores
        """
        if X_new is None or model is None:
            raise ValueError("Both X_new and model inputs are required")

        # Extract PCA model and parameters
        if isinstance(model, dict):
            pca_model = model.get("model")
            n_components = model.get("n_components", 5)
        else:
            pca_model = model
            n_components = 5

        # Accept NDDataset or array
        if hasattr(X_new, "data"):
            X_array = np.array(X_new.data)
        else:
            X_array = np.array(X_new)
        
        # Transform data
        try:
            scores = pca_model.transform(X_array)
            
            # Limit to n_components
            if scores.shape[1] > n_components:
                scores = scores[:, :n_components]
            
            print(f"PCA Transform: Projected {len(scores)} samples to {scores.shape[1]} PCs")
            
            return {"scores": scores}
            
        except Exception as e:
            raise RuntimeError(f"PCA transform failed: {str(e)}") from e
