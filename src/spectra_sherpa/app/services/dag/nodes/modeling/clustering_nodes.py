"""
Clustering nodes: HCA, KMeans, DBSCAN.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import numpy as np

from ...io_contracts import (
    coerce_to_sherpa,
    to_numpy_2d,
)
from ...node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodeResult,
    PortMetadata,
    register_node,
)

logger = logging.getLogger(__name__)


@register_node
class HCANode(Node):
    """
    Hierarchical Cluster Analysis (HCA) node.

    Performs agglomerative clustering on spectral data.
    """

    metadata = NodeMetadata(
        node_type="model.hca",
        category="clustering",
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
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral data to process",
            ),
        ],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/FittedModel/1.0",
                required=True,
                label="HCA Model",
                description="Cluster hierarchy (Linkage Matrix)",
            ),
            PortMetadata(
                name="labels",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Cluster Labels",
                description="Assigned cluster labels for each sample",
            ),
            PortMetadata(
                name="linkage_matrix",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Linkage Matrix",
                description="SciPy linkage matrix (Z)",
            ),
        ],
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for HCA clustering."""
        params = self._resolve_params()
        n_clusters = params.get("n_clusters", 3)
        linkage_method = params.get("linkage", "ward")
        metric = params.get("metric", "euclidean")

        X_expr = inputs.get("default", "input_data")

        lines: list[str] = []
        lines.append(f"{indent}# --- HCA ({self.node_id}) ---")
        lines.append(f"{indent}from scipy.cluster.hierarchy import linkage, fcluster")
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.array(")
        lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")
        lines.append(f"{indent}_Z = linkage(_X_data, method='{linkage_method}', metric='{metric}')")
        lines.append(f"{indent}_labels = fcluster(_Z, t={n_clusters}, criterion='maxclust')")
        lines.append(
            f'{indent}print(f"  HCA ({n_clusters} clusters,'
            f" {linkage_method} linkage, {metric}):"
            f' {{len(set(_labels))}} clusters found")'
        )
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'labels': _labels.tolist(),")
        lines.append(f"{indent}    'model': None,")
        lines.append(f"{indent}    'linkage_matrix': _Z.tolist(),")
        lines.append(f"{indent}}}")

        return lines

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """
        Execute hierarchical clustering.

        Args:
            input_data: NDDataset, SpectralResult, or array (samples x features)

        Returns:
            Dict containing cluster labels and metadata
        """
        from scipy.cluster.hierarchy import fcluster, linkage
        from scipy.spatial.distance import pdist
        from sklearn.decomposition import PCA as SkPCA

        input_ds = coerce_to_sherpa(
            input_data,
            input_name="input_data",
            allow_array=True,
            dataset_error_message=("input_data must be an dataset or array-like object"),
        )
        X_data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)

        n_clusters = self.parameters.get("n_clusters", 3)
        linkage_method = self.parameters.get("linkage", "ward")
        metric = self.parameters.get("metric", "euclidean")

        if linkage_method == "ward" and metric != "euclidean":
            raise ValueError("Ward linkage requires euclidean metric")

        logger.debug("[HCA Node] Executing with:")
        logger.debug("  - n_clusters: %s", n_clusters)
        logger.debug("  - linkage: %s", linkage_method)
        logger.debug("  - metric: %s", metric)
        logger.debug("  - X shape: %s", X_data.shape)

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
        labels = fcluster(Z, t=n_clusters, criterion="maxclust") - 1

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
        _y_coord = input_ds.sample_axis
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

            traces.append(
                {
                    "x": x_vals,
                    "y": y_vals,
                    "type": "scatter",
                    "mode": "lines",
                    "line": {"color": color, "width": 3},
                    "text": [f"Dist: {x:.2f}" for x in x_vals],  # Simple hover info
                    "hoverinfo": "text+x+y",
                    "showlegend": False,
                }
            )

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
            cast(dict, layout["yaxis"])["ticktext"] = leaf_labels
            # Extract actual Y-positions from icoord (leaf positions are at the bottom of links)
            # scipy dendrogram places leaves at y = 5, 15, 25, ... (spacing of 10, starting at 5)
            # We use the icoord values which represent actual positions
            leaf_positions = sorted(
                set(
                    coord
                    for link in icoord
                    for coord in [link[0], link[-1]]
                    if coord == link[0] or coord == link[-1]  # Only endpoints (leaf positions)
                )
            )
            # If we can't extract positions reliably, fall back to standard spacing
            if len(leaf_positions) != len(leaves):
                leaf_positions = list(range(5, len(leaves) * 10 + 5, 10))
            cast(dict, layout["yaxis"])["tickvals"] = leaf_positions

        if n_samples:
            min_height_per_sample = 15  # pixels per sample for readability
            total_height = max(1000, n_samples * min_height_per_sample)
            layout["height"] = total_height
            layout["margin"] = {"l": 50, "r": 150}  # Right margin for labels
            # Tight y-axis range: scipy uses 10 units per leaf, starting at 5
            cast(dict, layout["yaxis"])["range"] = [0, n_samples * 10]

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
        category="clustering",
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
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral data to process",
            ),
        ],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/FittedModel/1.0",
                required=True,
                label="KMeans Model",
                description="Fitted KMeans model object",
            ),
            PortMetadata(
                name="labels",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Cluster Labels",
                description="Assigned cluster labels",
            ),
            PortMetadata(
                name="centroids",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Centroids",
                description="Cluster centers coordinates",
            ),
        ],
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for KMeans clustering."""
        params = self._resolve_params()
        n_clusters = params.get("n_clusters", 3)
        n_init = params.get("n_init", 10)
        max_iter = params.get("max_iter", 300)
        random_state = params.get("random_state", 42)

        X_expr = inputs.get("default", "input_data")

        lines: list[str] = []
        lines.append(f"{indent}# --- KMeans ({self.node_id}) ---")
        lines.append(f"{indent}from sklearn.cluster import KMeans")
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.array(")
        lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")
        lines.append(
            f"{indent}_km = KMeans(n_clusters={n_clusters},"
            f" n_init={n_init}, max_iter={max_iter},"
            f" random_state={random_state})"
        )
        lines.append(f"{indent}_labels = _km.fit_predict(_X_data)")
        lines.append(f"{indent}_centroids = _km.cluster_centers_")
        lines.append(f'{indent}print(f"  KMeans ({n_clusters} clusters): inertia={{_km.inertia_:.4f}}")')
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'labels': _labels.tolist(),")
        lines.append(f"{indent}    'model': _km,")
        lines.append(f"{indent}    'centroids': _centroids.tolist(),")
        lines.append(f"{indent}}}")

        return lines

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """
        Execute K-Means clustering.

        Args:
            input_data: NDDataset, SpectralResult, or array (samples x features)

        Returns:
            Dict containing cluster labels and metadata
        """
        from sklearn.cluster import KMeans
        from sklearn.decomposition import PCA as SkPCA

        input_ds = coerce_to_sherpa(
            input_data,
            input_name="input_data",
            allow_array=True,
            dataset_error_message=("input_data must be an dataset or array-like object"),
        )
        X_data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)

        n_clusters = self.parameters.get("n_clusters", 3)
        n_init = self.parameters.get("n_init", 10)
        max_iter = self.parameters.get("max_iter", 300)
        random_state = self.parameters.get("random_state", 42)

        logger.debug("[KMeans Node] Executing with:")
        logger.debug("  - n_clusters: %s", n_clusters)
        logger.debug("  - n_init: %s", n_init)
        logger.debug("  - max_iter: %s", max_iter)
        logger.debug("  - X shape: %s", X_data.shape)

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
        _y_coord = input_ds.sample_axis
        if _y_coord is not None:
            if hasattr(_y_coord, "labels") and _y_coord.labels is not None:
                labels_data = _y_coord.labels
                source_labels = labels_data.tolist() if hasattr(labels_data, "tolist") else list(labels_data)
            elif hasattr(_y_coord, "data") and _y_coord.data is not None:
                data_values = _y_coord.data
                source_labels = data_values.tolist() if hasattr(data_values, "tolist") else list(data_values)

        # Compute silhouette score when meaningful (>1 cluster, >1 unique label)
        sil_score = None
        if n_clusters > 1 and len(set(label_list)) > 1:
            try:
                from sklearn.metrics import silhouette_score

                sil_score = float(silhouette_score(X_data, labels))
            except Exception:
                pass

        return NodeResult(
            outputs={
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
            },
            diagnostics={
                "n_clusters": int(n_clusters),
                "silhouette_score": sil_score,
                "inertia": float(model.inertia_),
            },
        )


@register_node
class DBSCANNode(Node):
    """
    DBSCAN clustering node.

    Performs density-based clustering and marks noise points as -1.
    """

    metadata = NodeMetadata(
        node_type="model.dbscan",
        category="clustering",
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
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral data to process",
            ),
        ],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/FittedModel/1.0",
                required=True,
                label="DBSCAN Model",
                description="Fitted DBSCAN model object",
            ),
            PortMetadata(
                name="labels",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Cluster Labels",
                description="Assigned cluster labels (noise=-1)",
            ),
        ],
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for DBSCAN clustering."""
        params = self._resolve_params()
        eps = params.get("eps", 0.5)
        min_samples = params.get("min_samples", 5)
        metric = params.get("metric", "euclidean")

        X_expr = inputs.get("default", "input_data")

        lines: list[str] = []
        lines.append(f"{indent}# --- DBSCAN ({self.node_id}) ---")
        lines.append(f"{indent}from sklearn.cluster import DBSCAN")
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.array(")
        lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")
        lines.append(f"{indent}_db = DBSCAN(eps={eps}, min_samples={min_samples}, metric='{metric}')")
        lines.append(f"{indent}_labels = _db.fit_predict(_X_data)")
        lines.append(
            f'{indent}print(f"  DBSCAN (eps={eps},'
            f" min_samples={min_samples}, {metric}):"
            f" {{len(set(_labels) - {{-1}})}} clusters,"
            f' {{(_labels == -1).sum()}} noise points")'
        )
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'labels': _labels.tolist(),")
        lines.append(f"{indent}    'model': _db,")
        lines.append(f"{indent}}}")

        return lines

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """
        Execute DBSCAN clustering.

        Args:
            input_data: NDDataset, SpectralResult, or array (samples x features)

        Returns:
            Dict containing cluster labels and metadata
        """
        from sklearn.cluster import DBSCAN
        from sklearn.decomposition import PCA as SkPCA

        input_ds = coerce_to_sherpa(
            input_data,
            input_name="input_data",
            allow_array=True,
            dataset_error_message=("input_data must be an dataset or array-like object"),
        )
        X_data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)

        eps = self.parameters.get("eps", 0.5)
        min_samples = self.parameters.get("min_samples", 5)
        metric = self.parameters.get("metric", "euclidean")

        logger.debug("[DBSCAN Node] Executing with:")
        logger.debug("  - eps: %s", eps)
        logger.debug("  - min_samples: %s", min_samples)
        logger.debug("  - metric: %s", metric)
        logger.debug("  - X shape: %s", X_data.shape)

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
        _y_coord = input_ds.sample_axis
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
