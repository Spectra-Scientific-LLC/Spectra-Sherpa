"""
Adaptive Statistics node.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, cast

import numpy as np

from spectra_sherpa.app.lib.scp_compat import NDDataset
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa

from ...node_base import Node, NodeMetadata, NodeParameter, PortMetadata, register_node


@register_node
class StatsSummaryNode(Node):
    """
    Adaptive Statistics node.

    Computes contextual statistics based on input type:
    - NDDataset: spectral statistics, per-sample/feature analysis
    - PCA results: scores/loadings stats, outlier detection
    - MCR results: concentration/spectra statistics
    - Generic arrays: basic descriptive statistics
    """

    metadata = NodeMetadata(
        node_type="stats.summary",
        category="validation",
        label="Statistics",
        description="Compute adaptive statistics based on input type",
        parameters=[
            NodeParameter(
                name="compute_outliers",
                label="Detect Outliers",
                param_type="boolean",
                default=True,
                description="Compute outlier statistics (for PCA data)",
                required=False,
            ),
            NodeParameter(
                name="outlier_threshold",
                label="Outlier Threshold",
                param_type="number",
                default=0.95,
                min_value=0.8,
                max_value=0.99,
                description="Confidence level for outlier detection",
                required=False,
            ),
            NodeParameter(
                name="max_samples",
                label="Max Sample Rows",
                param_type="number",
                default=100,
                min_value=10,
                max_value=500,
                description="Maximum rows in per-sample statistics table",
                required=False,
            ),
        ],
        input_types=["NDDataset", "dict", "array"],
        output_type="dict",
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Any/1.0",
                required=True,
                label="Input Data",
                description="Input data to process",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="statistics",
                type_ref="spectrasherpa://types/ValidationResult/1.0",
                required=True,
                label="Statistics",
                description="Computed statistics and summary",
            ),
        ],
    )

    def generate_python(
        self,
        inputs: Dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> List[str]:
        """Generate Python code for statistics summary."""
        input_expr = inputs.get("default", next(iter(inputs.values()), "input_data"))

        lines: List[str] = []
        lines.append(f"{indent}# --- Statistics ({self.node_id}) ---")
        lines.append(f"{indent}_stats_input = {input_expr}")
        lines.append(f"{indent}if hasattr(_stats_input, 'data'):")
        lines.append(f"{indent}    _stats_data = np.atleast_2d(np.asarray(_stats_input.data, dtype=np.float64))")
        lines.append(f"{indent}elif isinstance(_stats_input, dict):")
        lines.append(f"{indent}    if 'scores' in _stats_input:")
        lines.append(f"{indent}        _sc = _stats_input['scores']")
        lines.append(f"{indent}        _stats_data = np.atleast_2d(")
        lines.append(f"{indent}            np.asarray(")
        lines.append(f"{indent}                _sc.data if hasattr(_sc, 'data') else _sc,")
        lines.append(f"{indent}                dtype=np.float64,")
        lines.append(f"{indent}            )")
        lines.append(f"{indent}        )")
        lines.append(f"{indent}    elif 'data' in _stats_input:")
        lines.append(f"{indent}        _stats_data = np.atleast_2d(np.asarray(_stats_input['data'], dtype=np.float64))")
        lines.append(f"{indent}    else:")
        lines.append(f"{indent}        _stats_data = np.zeros((1, 1))")
        lines.append(f"{indent}else:")
        lines.append(f"{indent}    _stats_data = np.atleast_2d(np.asarray(_stats_input, dtype=np.float64))")
        lines.append(f"{indent}_n_samples, _n_features = _stats_data.shape")
        lines.append(f"{indent}_summary = {{")
        lines.append(f"{indent}    'n_samples': _n_samples, 'n_features': _n_features,")
        lines.append(f"{indent}    'mean': float(np.mean(_stats_data)),")
        lines.append(f"{indent}    'std': float(np.std(_stats_data)),")
        lines.append(f"{indent}    'min': float(np.min(_stats_data)),")
        lines.append(f"{indent}    'max': float(np.max(_stats_data)),")
        lines.append(f"{indent}    'median': float(np.median(_stats_data)),")
        lines.append(f"{indent}}}")
        lines.append(f"{indent}results['{self.node_id}'] = {{'statistics': _summary}}")
        lines.append(
            f'{indent}print(f"  Statistics: {{_n_samples}} samples x {{_n_features}} features, '
            f"mean={{_summary['mean']:.4f}}, std={{_summary['std']:.4f}}\")"
        )

        return lines

    async def execute(self, input_data: Any) -> Dict[str, Any]:
        """
        Compute adaptive statistics based on input type.

        Args:
            input_data: SherpaDataset, PCA/MCR dict, or array data

        Returns:
            Dict with comprehensive statistics and visualization data
        """
        # Detect input type and route to appropriate handler
        if isinstance(input_data, dict):
            if "accuracy" in input_data or input_data.get("task_type") in ("classification", "regression"):
                return await self._stats_evaluation(input_data)
            elif "scores" in input_data or "isPCA" in input_data.get("metadata", {}):
                return await self._stats_pca(input_data)
            elif "C" in input_data or "St" in input_data:
                return await self._stats_mcr(input_data)
            elif "data" in input_data:
                meta = input_data.get("metadata") or {}
                if meta.get("type") == "PeakFinding":
                    return await self._stats_peaks(input_data["data"], meta)
                return await self._stats_array(input_data["data"], meta)

        # Coerce NDDataset -> SherpaDataset so all dataset paths work
        if isinstance(input_data, NDDataset):
            input_data = coerce_to_sherpa(input_data)

        if isinstance(input_data, SherpaDataset):
            return await self._stats_dataset(input_data)

        # Fallback to array statistics
        return await self._stats_array(np.array(input_data), None)

    async def _stats_dataset(self, dataset: Any) -> Dict[str, Any]:
        """Compute per-wavelength mean and std for spectral data."""
        data = np.array(dataset.data)
        if data.ndim == 1:
            data = data.reshape(1, -1)

        n_samples, n_features = data.shape

        # Per-wavelength statistics — the core output
        feature_means = np.mean(data, axis=0)
        feature_stds = np.std(data, axis=0)

        # Get feature axis (wavelength, wavenumber, channel, etc.)
        x_coord = dataset.feature_axis
        if x_coord is not None:
            feature_values = np.array(x_coord.data).tolist()
        else:
            feature_values = list(range(n_features))

        # Build per-wavelength table rows for DataTable display
        table_rows = []
        for i in range(n_features):
            table_rows.append(
                {
                    "wavelength": feature_values[i],
                    "mean": float(feature_means[i]),
                    "std": float(feature_stds[i]),
                }
            )

        return {
            "statistics": {
                "input_type": "NDDataset",
                "summary": {
                    "n_samples": n_samples,
                    "n_features": n_features,
                    "global_mean": float(np.mean(data)),
                    "global_std": float(np.std(data)),
                },
                "plots": {
                    "mean_spectrum": {
                        "x": feature_values,
                        "y": feature_means.tolist(),
                        "type": "scatter",
                    },
                    "std_spectrum": {
                        "x": feature_values,
                        "y": feature_stds.tolist(),
                        "type": "scatter",
                    },
                },
                "data": table_rows,
                "metadata": {
                    "type": "NDDataset",
                    "shape": [n_samples, n_features],
                    "has_wavenumbers": x_coord is not None,
                },
            }
        }

    async def _stats_pca(self, pca_data: dict) -> Dict[str, Any]:
        """Compute statistics for PCA results."""
        # Extract PCA components
        metadata = pca_data.get("metadata", {})
        scores_data = np.array(pca_data.get("data", []))

        if scores_data.ndim == 1:
            scores_data = scores_data.reshape(-1, 1)

        n_obs, n_comp = scores_data.shape

        # Scores statistics per PC
        pc_stats = []
        for i in range(n_comp):
            pc_stats.append(
                {
                    "pc": i + 1,
                    "mean": float(np.mean(scores_data[:, i])),
                    "std": float(np.std(scores_data[:, i])),
                    "min": float(np.min(scores_data[:, i])),
                    "max": float(np.max(scores_data[:, i])),
                    "range": float(np.ptp(scores_data[:, i])),
                }
            )

        # Outlier detection using Hotelling's T-squared (if enabled)
        outliers = []
        if self.parameters.get("compute_outliers", True):
            # Simplified T-squared calculation
            cov = np.cov(scores_data.T)
            try:
                inv_cov = np.linalg.inv(cov)
                means = np.mean(scores_data, axis=0)

                threshold = self.parameters.get("outlier_threshold", 0.95)
                from scipy.stats import chi2

                t2_limit = chi2.ppf(threshold, n_comp)

                for i in range(n_obs):
                    diff = scores_data[i] - means
                    t2 = diff @ inv_cov @ diff
                    if t2 > t2_limit:
                        outliers.append(
                            {
                                "sample": i + 1,
                                "t2_statistic": float(t2),
                                "threshold": float(t2_limit),
                            }
                        )
            except (np.linalg.LinAlgError, ValueError):
                # Singular covariance or insufficient data -- skip outlier detection
                pass

        # Explained variance
        evr = metadata.get("explained_variance_ratio", [])
        cumulative_var = np.cumsum(evr).tolist() if evr else []
        spe = pca_data.get("spe") or metadata.get("spe") or []
        t2 = pca_data.get("t2") or metadata.get("t2") or []
        spe_mean = metadata.get("spe_mean")
        spe_p95 = metadata.get("spe_p95")
        t2_mean = metadata.get("t2_mean")
        t2_p95 = metadata.get("t2_p95")

        return {
            "statistics": {
                "input_type": "PCA",
                "summary": {
                    "n_observations": n_obs,
                    "n_components": n_comp,
                    "total_variance_explained": float(sum(evr)) if evr else 0.0,
                    "n_outliers": len(outliers),
                    "spe_mean": float(spe_mean) if spe_mean is not None else None,
                    "spe_p95": float(spe_p95) if spe_p95 is not None else None,
                    "t2_mean": float(t2_mean) if t2_mean is not None else None,
                    "t2_p95": float(t2_p95) if t2_p95 is not None else None,
                },
                "detailed": {
                    "by_pc": pc_stats,
                    "outliers": outliers,
                    "variance": {
                        "explained_variance_ratio": evr,
                        "cumulative": cumulative_var,
                    },
                    "diagnostics": {
                        "t2": t2,
                        "spe": spe,
                    },
                },
                "plots": {
                    "scree": {
                        "x": list(range(1, len(evr) + 1)),
                        "y": evr,
                        "type": "bar",
                    },
                    "cumulative_variance": {
                        "x": list(range(1, len(cumulative_var) + 1)),
                        "y": cumulative_var,
                        "type": "scatter",
                    },
                },
                "data": pc_stats,  # For DataTable
                "metadata": {
                    "type": "PCA",
                    "shape": [n_obs, n_comp],
                    "has_outliers": len(outliers) > 0,
                },
            }
        }

    async def _stats_mcr(self, mcr_data: dict) -> Dict[str, Any]:
        """Compute statistics for MCR-ALS results."""
        # Extract concentration (C) and spectra (St) matrices
        C = np.array(mcr_data.get("C", mcr_data.get("concentrations", {}).get("data", [])))
        St = np.array(mcr_data.get("St", mcr_data.get("spectra", {}).get("data", [])))

        n_obs, n_comp = C.shape if C.size > 0 else (0, 0)

        # Concentration statistics
        conc_stats = []
        for i in range(n_comp):
            conc_stats.append(
                {
                    "component": i + 1,
                    "mean_conc": float(np.mean(C[:, i])),
                    "max_conc": float(np.max(C[:, i])),
                    "min_conc": float(np.min(C[:, i])),
                    "range": float(np.ptp(C[:, i])),
                }
            )

        # Pure spectra statistics
        spectra_stats = []
        for i in range(n_comp):
            spectra_stats.append(
                {
                    "component": i + 1,
                    "max_absorbance": float(np.max(St[i])) if St.size > 0 else 0.0,
                    "mean_absorbance": float(np.mean(St[i])) if St.size > 0 else 0.0,
                }
            )

        return {
            "statistics": {
                "input_type": "MCR",
                "summary": {
                    "n_observations": n_obs,
                    "n_components": n_comp,
                    "n_wavenumbers": St.shape[1] if St.size > 0 else 0,
                },
                "detailed": {
                    "concentrations": conc_stats,
                    "pure_spectra": spectra_stats,
                },
                "plots": {
                    "concentration_ranges": {
                        "components": [f"Comp {i+1}" for i in range(n_comp)],
                        "max_values": [float(np.max(C[:, i])) for i in range(n_comp)],
                        "type": "bar",
                    },
                },
                "data": conc_stats,  # For DataTable
                "metadata": {
                    "type": "MCR",
                    "shape": [n_obs, n_comp],
                },
            }
        }

    async def _stats_peaks(self, rows: list, metadata: dict) -> Dict[str, Any]:
        """Compute statistics for peak-finding consensus results.

        Each row is a dict with keys: median_pos, mean_pos, std_pos, min_pos,
        max_pos, count, detected, median_height, q1_height, q3_height.

        Two axes of variation are reported:
        - **Horizontal (positional)**: within each cluster, how much do
          detected positions scatter across samples (std_pos, min-max range).
        - **Vertical (intensity)**: across clusters, how do median heights
          compare and how tight is the IQR (q1-q3).
        """
        n_peaks = len(rows)
        n_samples = metadata.get("n_samples", 0)
        x_title = metadata.get("x_title", "Position")
        x_units = metadata.get("x_units", "")
        unit_suffix = f" ({x_units})" if x_units else ""

        # Build per-peak table rows for DataTable display
        table_rows = []
        horizontal_stats = []  # positional scatter per cluster
        vertical_stats = []  # intensity variation per cluster

        for i, row in enumerate(rows):
            median_pos = float(row.get("median_pos", 0))
            std_pos = float(row.get("std_pos", 0))
            min_pos = float(row.get("min_pos", median_pos))
            max_pos = float(row.get("max_pos", median_pos))
            count = int(row.get("count", 0))
            fraction = row.get("detected", f"{count}/{n_samples}")
            med_h = float(row.get("median_height", 0))
            q1_h = float(row.get("q1_height", med_h))
            q3_h = float(row.get("q3_height", med_h))

            label = f"Peak {i + 1}"

            table_rows.append(
                {
                    "peak": i + 1,
                    "position": median_pos,
                    "pos_std": std_pos,
                    "pos_range": f"{min_pos:.1f}\u2013{max_pos:.1f}",
                    "height": med_h,
                    "height_iqr": f"{q1_h:.4f}\u2013{q3_h:.4f}",
                    "detected": fraction,
                    "detection_rate": f"{count / n_samples * 100:.0f}%" if n_samples else "\u2013",
                }
            )

            # Horizontal: positional scatter within this cluster
            horizontal_stats.append(
                {
                    "label": label,
                    "median_pos": median_pos,
                    "std_pos": std_pos,
                    "min_pos": min_pos,
                    "max_pos": max_pos,
                    "range": max_pos - min_pos,
                }
            )

            # Vertical: intensity variation within this cluster
            vertical_stats.append(
                {
                    "label": label,
                    "median_pos": median_pos,
                    "median_height": med_h,
                    "q1_height": q1_h,
                    "q3_height": q3_h,
                    "iqr": q3_h - q1_h,
                }
            )

        # Global summary
        if n_peaks > 0:
            heights = [cast(float, v["median_height"]) for v in vertical_stats]
            pos_stds = [cast(float, h["std_pos"]) for h in horizontal_stats]
            summary = {
                "n_peaks": n_peaks,
                "n_samples": n_samples,
                "n_total_detections": metadata.get("n_total_detections", 0),
                "position_range": [horizontal_stats[0]["median_pos"], horizontal_stats[-1]["median_pos"]],
                "mean_height": float(np.mean(heights)),
                "std_height": float(np.std(heights)),
                "max_positional_std": float(max(pos_stds)),
                "mean_positional_std": float(np.mean(pos_stds)),
            }
        else:
            summary = {"n_peaks": 0}

        summary["x_label"] = f"{x_title}{unit_suffix}"

        return {
            "statistics": {
                "input_type": "PeakFinding",
                "summary": summary,
                "data": table_rows,
                "horizontal": horizontal_stats,
                "vertical": vertical_stats,
                "metadata": metadata,
            }
        }

    async def _stats_evaluation(self, metrics: dict) -> Dict[str, Any]:
        """Summarize holdout evaluation metrics (classification or regression)."""
        task_type = metrics.get("task_type", "unknown")

        if task_type == "classification":
            table_rows = []
            per_class = metrics.get("per_class", [])
            for entry in per_class:
                table_rows.append(
                    {
                        "class": entry.get("class", "?"),
                        "sensitivity": round(float(entry.get("sensitivity", 0)), 4),
                        "specificity": round(float(entry.get("specificity", 0)), 4),
                        "precision": round(float(entry.get("precision", 0)), 4),
                        "f1": round(float(entry.get("f1", 0)), 4),
                    }
                )

            summary = {
                "task_type": "classification",
                "accuracy": metrics.get("accuracy"),
                "n_classes": metrics.get("n_classes"),
                "classes": metrics.get("classes"),
                "n_samples": metrics.get("n_samples"),
            }

            return {
                "statistics": {
                    "input_type": "EvaluationClassification",
                    "summary": summary,
                    "data": table_rows if table_rows else [summary],
                    "metadata": {"type": "EvaluationClassification"},
                }
            }
        else:
            # Regression metrics
            scalar_keys = (
                "RMSEP",
                "R2",
                "MAE",
                "bias",
                "SEP",
                "RER",
                "n_samples",
                "n_valid_samples",
                "n_invalid_predictions",
                "status",
            )
            summary = {k: metrics[k] for k in scalar_keys if k in metrics}
            summary["task_type"] = "regression"

            return {
                "statistics": {
                    "input_type": "EvaluationRegression",
                    "summary": summary,
                    "data": [summary],
                    "metadata": {"type": "EvaluationRegression"},
                }
            }

    async def _stats_array(self, data: np.ndarray, metadata: Optional[dict]) -> Dict[str, Any]:
        """Compute basic statistics for generic array data."""
        data = np.array(data)
        if data.ndim == 1:
            data = data.reshape(1, -1)

        summary = {
            "n_samples": data.shape[0],
            "n_features": data.shape[1],
            "mean": float(np.mean(data)),
            "std": float(np.std(data)),
            "min": float(np.min(data)),
            "max": float(np.max(data)),
            "median": float(np.median(data)),
        }

        return {
            "statistics": {
                "input_type": "array",
                "summary": summary,
                "data": [summary],  # For DataTable
                "metadata": metadata or {},
            }
        }
