"""
PCA training and transform nodes.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import (
    EvaluationResult,
)
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step, copy_processing_history

from ...io_contracts import (
    attach_evaluation,
    bind_X,
    to_numpy_2d,
)
from ...node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from .core_utils import (
    is_sequential_numeric as _is_sequential_numeric,
)
from .core_utils import (
    make_safe_coord as _make_safe_coord,
)
from .core_utils import (
    to_numpy_2d_any as _to_numpy_2d_any,
)

logger = logging.getLogger(__name__)

from spectra_sherpa.app.lib.adapters.scp_extractors import PCAExtract
from spectra_sherpa.app.lib.scp_compat import from_nddataset, scp, to_nddataset


@register_node
class PCANode(Node):
    """
    Principal Component Analysis node.

    Performs PCA decomposition on spectral data using SpectroChemPy.
    """

    metadata = NodeMetadata(
        node_type="model.pca",
        category="exploratory",
        label="PCA",
        description=(
            "Reduces spectral data to a small set of orthogonal principal components that capture "
            "the most variance, enabling visualisation, outlier detection, and feature compression. "
            "For most spectral datasets leave both scaling options off — SpectroChemPy mean-centers "
            "by default, which is the correct preprocessing for spectroscopy. "
            "Use '0.95' as n_components to automatically retain enough PCs for 95% variance, "
            "or check the Explained Variance output to choose the elbow point."
        ),
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="text",
                default="2",
                description=(
                    "Number of components: integer (e.g., '2'), 'mle'"
                    " (auto-select via Maximum Likelihood), or float 0-1"
                    " (e.g., '0.95' for 95% variance)"
                ),
                required=True,
                category="basic",
                hint=(
                    "Must be ≤ min(n_samples, n_features). "
                    "This is checked at execution time — a value that is too large will raise an error. "
                    "Use '0.95' to automatically retain enough components for 95% explained variance."
                ),
            ),
            NodeParameter(
                name="standardized",
                label="Mean Center + Unit Variance",
                param_type="boolean",
                default=False,
                description=(
                    "Subtract the column mean AND divide by column standard deviation before PCA "
                    "(full standardization). Use when variables have different units or scales, "
                    "e.g. mixing spectral and non-spectral predictors."
                ),
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="scaled",
                label="Unit Variance Only (No Mean Centering)",
                param_type="boolean",
                default=False,
                description=(
                    "Divide each variable by its standard deviation WITHOUT subtracting the mean. "
                    "Rarely appropriate for spectral data — prefer 'Mean Center + Unit Variance' "
                    "or leave both off to use mean-centering only (the spectroscopy default)."
                ),
                required=False,
                category="advanced",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Input spectral dataset for PCA decomposition",
            )
        ],
        output_ports=[
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/DecompositionResult/1.0",
                required=True,
                label="PCA Model",
                description="Trained PCA model object",
            ),
            PortMetadata(
                name="scores",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="Scores",
                description="Transformed scores (n_samples × n_components) with sample labels",
            ),
            PortMetadata(
                name="loadings",
                type_ref="spectrasherpa://types/LoadingMatrix/1.0",
                required=True,
                label="Loadings",
                description="Principal component loadings (n_components × n_features) with wavenumber axis",
            ),
            PortMetadata(
                name="explained_variance",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Explained Variance",
                description="Variance explained by each component",
            ),
        ],
        diagnostics=[
            "explained_variance_ratio",
            "cumulative_variance",
            "n_components_95pct",
            "hotelling_t2",
            "q_residuals",
            "t2_critical_95",
            "q_critical_95",
        ],
        requires_scp=True,
        help_url="https://www.spectrochempy.fr/reference/generated/spectrochempy.PCA.html",
        policy=NodePolicy(
            safe_for_auto_apply=False,
            requires_human_review=True,
            data_egress_risk="none",
        ),
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for PCA decomposition.

        Emits code that fits PCA, extracts scores/loadings/explained variance,
        and stores as a multi-port dict.
        """
        params = self._resolve_params()
        n_components = params.get("n_components", 2)
        standardized = params.get("standardized", False)
        scaled = params.get("scaled", False)

        X_expr = inputs.get("default", inputs.get("X", "input_data"))

        lines: list[str] = []
        lines.append(f"{indent}# --- PCA ({self.node_id}) ---")

        if use_scp:
            # Extract data
            lines.append(f"{indent}_X_input = {X_expr}")
            lines.append(f"{indent}_X_data = np.array(")
            lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
            lines.append(f"{indent}    dtype=np.float64,")
            lines.append(f"{indent})")
            # Fit PCA via SCP
            std_str = "True" if standardized else "False"
            scl_str = "True" if scaled else "False"
            lines.append(f"{indent}_X_ndd = scp.NDDataset(_X_data)")
            lines.append(
                f"{indent}_pca = scp.PCA(n_components={n_components}, standardized={std_str}, scaled={scl_str})"
            )
            lines.append(f"{indent}_pca.fit(_X_ndd)")
            # Extract results
            lines.append(f"{indent}_scores = np.asarray(_pca.transform().data, dtype=np.float64)")
            lines.append(f"{indent}_loadings = np.asarray(_pca.components.data, dtype=np.float64)")
            lines.append(f"{indent}_evr = np.asarray(_pca.explained_variance_ratio, dtype=np.float64).ravel()")
            lines.append(f"{indent}if _evr.max() > 1.0:")
            lines.append(f"{indent}    _evr = _evr / 100.0")
        else:
            # numpy mode via sklearn
            lines.append(f"{indent}from sklearn.decomposition import PCA as _PCA")
            lines.append(f"{indent}_X_input = {X_expr}")
            lines.append(f"{indent}_X_data = np.array(")
            lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
            lines.append(f"{indent}    dtype=np.float64,")
            lines.append(f"{indent})")
            lines.append(f"{indent}_pca = _PCA(n_components={n_components})")
            lines.append(f"{indent}_scores = _pca.fit_transform(_X_data)")
            lines.append(f"{indent}_loadings = _pca.components_")
            lines.append(f"{indent}_evr = _pca.explained_variance_ratio_")

        # Print summary
        lines.append(f'{indent}print(f"  PCA ({n_components} components):")')
        lines.append(f"{indent}for _i, _v in enumerate(_evr):")
        lines.append(f'{indent}    print(f"    PC{{_i+1}}: {{_v*100:.2f}}% variance")')
        lines.append(f'{indent}print(f"    Cumulative: {{np.cumsum(_evr)[-1]*100:.2f}}%")')

        # Store multi-port output
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'default': _scores,")
        lines.append(f"{indent}    'scores': _scores,")
        lines.append(f"{indent}    'loadings': _loadings,")
        lines.append(f"{indent}    'model': _pca,")
        lines.append(f"{indent}    'explained_variance': _evr,")
        lines.append(f"{indent}}}")

        return lines

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """
        Execute PCA on input dataset.

        Args:
            input_data: Dataset containing spectral data

        Returns:
            PCA model object with scores, loadings, and explained variance
        """
        input_ds = bind_X(
            input_data,
            missing_message="Missing required input: input_data (X)",
            dataset_error_message="input_data must be an dataset or array-like object",
            allow_array=True,
        )
        input_ndd = to_nddataset(input_ds)

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
        n_observations, n_features = input_ds.shape
        if n_components_parsed == "mle" and n_observations < n_features:
            raise ValueError(
                f"n_components='mle' requires n_observations >= n_features. "
                f"Got {n_observations} observations and {n_features} features. "
                f"Consider using a specific number of components or a variance threshold (0-1)."
            )

        logger.debug("[PCA Node] Executing with:")
        logger.debug("  - All parameters: %s", self.parameters)
        logger.debug("  - n_components parsed: %s (type: %s)", n_components_parsed, type(n_components_parsed).__name__)
        logger.debug("  - Data shape: %s observations x %s features", n_observations, n_features)

        # Perform PCA using SpectroChemPy
        pca = scp.PCA(n_components=n_components_parsed, standardized=standardized, scaled=scaled)
        pca.fit(input_ndd)

        # Extract results using typed extractor — all defensive unwrapping
        # and normalization logic lives in PCAExtract.from_scp()
        extracted = PCAExtract.from_scp(pca, input_ndd)

        # Use SpectroChemPy's native NDDataset outputs for coordinate preservation
        scores_dataset = pca.transform()
        loadings_dataset = pca.components

        if scores_dataset is None:
            raise ValueError("PCA transform() returned None — SCP model may not have fitted correctly")
        if loadings_dataset is None:
            raise ValueError("PCA components is None — SCP model may not have fitted correctly")

        scores_data = extracted.scores
        actual_n_components = extracted.n_components
        evr_ratio = extracted.explained_variance_ratio
        eigenvalues = extracted.explained_variance

        # Defensive guard — protect against SCP versions where extraction
        # silently yields None (manifests as "'NoneType' … 'tolist'").
        if evr_ratio is None:
            evr_ratio = np.zeros(actual_n_components, dtype=np.float64)
        if eigenvalues is None:
            eigenvalues = np.ones(actual_n_components, dtype=np.float64) * 1e-12

        pc_labels = [f"PC{i+1} ({evr_ratio[i] * 100:.1f}%)" for i in range(actual_n_components)]

        # Ensure PCA outputs expose explicit PC coordinate labels for frontend display.
        try:
            scores_dataset.x = _make_safe_coord(pc_labels, title="Principal Component")
        except Exception:
            pass
        try:
            loadings_dataset.y = _make_safe_coord(pc_labels, title="Principal Component")
        except Exception:
            pass

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
            eigenvalues_safe = np.maximum(eigenvalues, 1e-12)
            t2_stats = np.sum((scores_matrix**2) / eigenvalues_safe, axis=1)

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
                reconstructed_data = _to_numpy_2d_any(reconstructed, name="reconstructed", dtype=np.float64)
                input_matrix = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
                if reconstructed_data.shape == input_matrix.shape:
                    residuals = input_matrix - reconstructed_data
                    spe_stats = np.sum(residuals**2, axis=1)

        # Extract label_categories for categorical coloring
        label_categories = None
        _y_coord = input_ds.sample_axis
        if _y_coord is not None:
            try:

                def _label_to_string(label: Any) -> str:
                    if label is None:
                        return ""
                    if isinstance(label, (list, tuple)):
                        for item in reversed(label):
                            if isinstance(item, str) and item.strip():
                                return item.strip()
                        return " | ".join(part for part in (_label_to_string(item) for item in label) if part)
                    if isinstance(label, np.ndarray):
                        if label.ndim == 0:
                            return _label_to_string(label.item())
                        return _label_to_string(label.tolist())
                    if hasattr(label, "isoformat"):
                        try:
                            return label.isoformat()
                        except Exception:
                            pass
                    return str(label)

                if hasattr(_y_coord, "labels") and _y_coord.labels is not None:
                    raw = _y_coord.labels.tolist() if hasattr(_y_coord.labels, "tolist") else list(_y_coord.labels)
                    str_labels = [_label_to_string(l) for l in raw]
                    unique_labels = sorted(set(str_labels))
                    # Keep categories only when they provide real grouping signal.
                    # If almost every sample is unique, treat as unlabeled for coloring.
                    if 1 < len(unique_labels) <= 12 and len(unique_labels) <= max(3, int(0.5 * len(str_labels))):
                        label_categories = unique_labels
                elif hasattr(_y_coord, "data") and _y_coord.data is not None:
                    raw = _y_coord.data.tolist() if hasattr(_y_coord.data, "tolist") else list(_y_coord.data)
                    str_labels = [str(l) for l in raw]
                    unique = sorted(set(str_labels))
                    if len(unique) < 20 and not _is_sequential_numeric(raw):
                        label_categories = unique
            except Exception:
                label_categories = None

        # scores_dataset and loadings_dataset are already SpectroChemPy NDDatasets
        # from pca.transform() / pca.components — coordinates inherited from input.
        # Add processing history for provenance tracking.
        copy_processing_history(input_ds, scores_dataset)
        add_processing_step(
            scores_dataset,
            "model.pca.scores",
            {"n_components": actual_n_components},
            node_id=self.node_id,
        )

        copy_processing_history(input_ds, loadings_dataset)
        add_processing_step(
            loadings_dataset,
            "model.pca.loadings",
            {"n_components": actual_n_components},
            node_id=self.node_id,
        )

        t2_p95 = float(np.percentile(t2_stats, 95)) if t2_stats is not None else None
        spe_p95 = float(np.percentile(spe_stats, 95)) if spe_stats is not None else None

        # Store only scientific metadata that coordinates can't carry.
        # serialize_for_api() extracts wavenumbers, sample_labels, x_title, etc.
        # from SherpaDataset coordinates automatically at the API boundary.
        scores_dataset.meta.update(
            {
                "type": "PCA",
                "isPCA": True,
                "pc_labels": pc_labels,
                "explained_variance_ratio": evr_ratio.tolist(),
                "n_components": actual_n_components,
                "t2": t2_stats.tolist() if t2_stats is not None else [],
                "spe": spe_stats.tolist() if spe_stats is not None else [],
                "t2_p95": t2_p95,
                "spe_p95": spe_p95,
                "t2_mean": float(np.mean(t2_stats)) if t2_stats is not None else None,
                "spe_mean": float(np.mean(spe_stats)) if spe_stats is not None else None,
                "label_categories": label_categories,
            }
        )

        # Convert NDDataset outputs to SherpaDataset for DAG uniformity
        scores_dataset = from_nddataset(scores_dataset)
        loadings_dataset = from_nddataset(loadings_dataset)

        # Fix feature axes that from_nddataset() may leave with values=None
        # (SCP sometimes omits the component axis on PCA outputs).
        from spectra_sherpa.app.lib.axes import FeatureAxis

        if scores_dataset.feature_axis is None or scores_dataset.feature_axis.data is None:
            scores_dataset.feature_axis = FeatureAxis(
                values=np.arange(actual_n_components, dtype=np.float64),
                labels=pc_labels,
                title="Principal Component",
            )
        if loadings_dataset.feature_axis is None or loadings_dataset.feature_axis.data is None:
            # Loadings rows = components, cols = features (wavenumbers)
            loadings_dataset.feature_axis = FeatureAxis(
                values=np.arange(n_features, dtype=np.float64),
                title="Feature",
            )

        # Defensive shape check — guard against future SCP API orientation changes.
        # SCP 0.8.1 returns scores=(n_samples, n_components), loadings=(n_components, n_features).
        if scores_dataset.data.shape != (n_observations, actual_n_components):
            logger.warning(
                "PCA scores shape %s != expected (%s, %s) — SCP API may have changed",
                scores_dataset.data.shape,
                n_observations,
                actual_n_components,
            )
        if loadings_dataset.data.shape != (actual_n_components, n_features):
            logger.warning(
                "PCA loadings shape %s != expected (%s, %s) — SCP API may have changed",
                loadings_dataset.data.shape,
                actual_n_components,
                n_features,
            )

        attach_evaluation(
            scores_dataset,
            EvaluationResult(
                evaluation_id=str(uuid.uuid4()),
                model_type="PCA",
                n_components=actual_n_components,
                hotelling_t2=t2_stats.tolist() if t2_stats is not None else None,
                q_residuals=spe_stats.tolist() if spe_stats is not None else None,
                t2_limit=t2_p95,
                q_limit=spe_p95,
            ),
        )

        logger.debug(
            "[PCA Node] Requested n_components=%s, fitted with %s components", n_components_parsed, actual_n_components
        )
        logger.debug("[PCA Node] Scores shape: %s, Loadings shape: %s", scores_dataset.shape, loadings_dataset.shape)

        cumulative_variance = np.cumsum(evr_ratio).tolist()
        n_components_95pct = None
        above_95 = np.where(np.cumsum(evr_ratio) >= 0.95)[0]
        if len(above_95) > 0:
            n_components_95pct = int(above_95[0]) + 1

        diagnostics = {
            "explained_variance_ratio": evr_ratio.tolist(),
            "cumulative_variance": cumulative_variance,
            "n_components_95pct": n_components_95pct,
            "hotelling_t2": t2_stats.tolist() if t2_stats is not None else [],
            "q_residuals": spe_stats.tolist() if spe_stats is not None else [],
            "t2_critical_95": t2_p95,
            "q_critical_95": spe_p95,
        }

        return NodeResult(
            outputs={
                "default": scores_dataset,  # Backwards-compatible default port
                "scores": scores_dataset,
                "loadings": loadings_dataset,
                "model": pca,
                "explained_variance": evr_ratio.tolist(),
                "_internal": {
                    "input_data": input_data,
                    "input_data_ds": input_ds,
                },
            },
            diagnostics=diagnostics,
        )


@register_node
class PCATransformNode(Node):
    """
    Transform new data using trained PCA model.

    Projects new samples into the principal component space
    defined by a trained PCA model.
    """

    metadata = NodeMetadata(
        node_type="model.pca_transform",
        category="exploratory",
        label="Apply PCA Transform",
        description="Transform new data using trained PCA model (project to PC space)",
        parameters=[],
        input_ports=[
            PortMetadata(
                name="X_new",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="New Spectra",
                description="Spectral data to transform",
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/DecompositionResult/1.0",
                required=True,
                label="PCA Model",
                description="Trained PCA model from PCA training node",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="scores",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
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
            X_new: New spectral data (dataset)
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

        X_new_ds = bind_X(
            X_new,
            missing_message="Missing required input: X_new (new spectra)",
            dataset_error_message="X_new must be an dataset object",
            allow_array=True,
        )
        X_array = to_numpy_2d(X_new_ds, name="X_new", dtype=np.float64)

        # Transform data
        try:
            try:
                scores = pca_model.transform(to_nddataset(X_new_ds))
            except Exception:
                scores = pca_model.transform(X_array)

            # Limit to n_components
            if scores.shape[1] > n_components:
                scores = scores[:, :n_components]

            logger.debug("PCA Transform: Projected %s samples to %s PCs", len(scores), scores.shape[1])

            return {"scores": scores}

        except Exception as e:
            raise RuntimeError(f"PCA transform failed: {str(e)}") from e
