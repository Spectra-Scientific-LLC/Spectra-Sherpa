"""
Clustering nodes: HCA, KMeans, DBSCAN.
"""

from __future__ import annotations

from typing import Any, cast

import numpy as np

from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    TargetAccess,
    WorkerCapability,
)

from ...io_contracts import (
    coerce_to_sherpa,
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
from ...stable_execution_contract import bind_stable_execution_contract
from . import hca_core, partition_clustering_core, saved_native_model
from .saved_native_model import build_native_model_artifact


@register_node
class HCANode(Node):
    """
    Hierarchical Cluster Analysis (HCA) node.

    Performs agglomerative clustering on spectral data.
    """

    metadata = NodeMetadata(
        policy=NodePolicy(),
        node_type="model.hca",
        category="clustering",
        label="Fit HCA Clustering",
        description="Fit hierarchical clustering (agglomerative) for unsupervised grouping",
        parameters=[
            NodeParameter(
                name="n_clusters",
                label="Number of Clusters",
                param_type="number",
                default=3,
                min_value=2,
                max_value=500,
                max_value_reason="Bounds the quadratic hierarchy and scientist-facing dendrogram output.",
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
                ],
                description="Distance metric (ward requires euclidean)",
                required=False,
                category="advanced",
            ),
        ],
        input_types=["SherpaDataset", "array"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Input Data Matrix",
                description="Spectral dataset, PCA scores, or multivariate feature table to cluster",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
        ],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Cluster Labels",
                description="Primary cluster-label output for direct node replacement",
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/FittedModel/1.0",
                required=True,
                label="Fitted HCA Clustering",
                description="Closed cohort hierarchy state; HCA does not classify new samples",
            ),
            PortMetadata(
                name="labels",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Cluster Labels",
                description="Assigned cluster labels for each sample",
            ),
            PortMetadata(
                name="cluster_assignment",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Cluster Assignment",
                description="Alias of labels for direct downstream comparison",
            ),
            PortMetadata(
                name="cluster_summary",
                type_ref="spectrasherpa://types/Any/1.0",
                required=True,
                label="Cluster Summary",
                description="Cluster counts, fractions, and sample previews",
            ),
            PortMetadata(
                name="linkage_matrix",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Linkage Matrix",
                description="SciPy linkage matrix (Z)",
            ),
            PortMetadata(
                name="dendrogram_data",
                type_ref="spectrasherpa://types/Visualization/1.0",
                required=True,
                label="Dendrogram Data",
                description="Plotly dendrogram payload derived from the linkage matrix",
            ),
            PortMetadata(
                name="embedding",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Embedding (2D)",
                description="2D projection of samples for cluster scatter visualization",
            ),
        ],
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate code that calls the same HCA authority as live execution."""
        del use_scp
        input_expression = inputs.get("default", "input_data")
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.modeling.hca_core import hca_export_outputs",
            f"{indent}results['{self.node_id}'] = hca_export_outputs(",
            f"{indent}    {input_expression}, parameters={self._resolve_params()!r},",
            f"{indent})",
        ]

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """
        Execute hierarchical clustering.

        Args:
            input_data: SherpaDataset, SpectralResult, or array (samples x features)

        Returns:
            Dict containing cluster labels and metadata
        """
        del kwargs
        input_ds = coerce_to_sherpa(
            input_data,
            input_name="input_data",
            allow_array=True,
            dataset_error_message=("input_data must be an dataset or array-like object"),
        )
        X_data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        state = hca_core.fit_hca(input_ds, parameters=self._resolve_params())
        outputs = hca_core.hca_outputs_from_state(input_ds, state)
        outputs["_model_artifact"] = build_native_model_artifact(
            self, coerce_to_sherpa(input_data, input_name="input_data", allow_array=True), state
        )
        quality_metrics = cast(dict[str, Any], state["quality"])
        parameters = cast(dict[str, Any], state["parameters"])
        observed_clusters = int(state["observed_clusters"])

        return NodeResult(
            outputs=outputs,
            diagnostics={
                "n_clusters": observed_clusters,
                "requested_clusters": int(state["requested_clusters"]),
                "linkage": parameters["linkage"],
                "metric": parameters["metric"],
                "silhouette_score": quality_metrics["silhouette_score"],
                "silhouette_reason": quality_metrics["silhouette_reason"],
                "davies_bouldin_score": quality_metrics["davies_bouldin_score"],
                "davies_bouldin_reason": quality_metrics["davies_bouldin_reason"],
                "n_samples": int(X_data.shape[0]),
            },
        )

    def fit_fitted_state(self, input_data: Any, target: Any = None) -> dict[str, Any]:
        del target
        return hca_core.fit_hca(input_data, parameters=self._resolve_params())

    def apply_fitted_state(self, input_data: Any, state: Any) -> np.ndarray:
        return hca_core.replay_hca_labels(input_data, state)


bind_stable_execution_contract(
    HCANode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_MODEL,
    implementation_id="spectrasherpa.model.hca",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 60, "cpu_seconds": 60, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/exploratory.md",
    implementation_modules=(hca_core, saved_native_model),
    implementation_distributions=("numpy", "scipy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1"), ("scikit-learn", "1.9.0")),
    citations=(
        "R stats::hclust hierarchical clustering reference implementation",
        "Murtagh & Legendre, Ward's Hierarchical Agglomerative Clustering Method: Which Algorithms "
        "Implement Ward's Criterion?, Journal of Classification 31 (2014) 274-295",
        "Mullner, fastcluster: Fast Hierarchical, Agglomerative Clustering Routines for R and Python, "
        "Journal of Statistical Software 53 (2013)",
    ),
    fitted_state_serializer=hca_core.HCA_STATE_SERIALIZER,
    deterministic=True,
    target_access=TargetAccess.NONE,
    group_access="none",
)


@register_node
class KMeansNode(Node):
    """
    K-Means clustering node.

    Performs k-means clustering on spectral data.
    """

    metadata = NodeMetadata(
        policy=NodePolicy(),
        node_type="model.kmeans",
        category="clustering",
        label="Fit K-Means Clustering",
        description="Fit K-Means clustering for unsupervised grouping",
        parameters=[
            NodeParameter(
                name="n_clusters",
                label="Number of Clusters",
                param_type="number",
                default=3,
                min_value=2,
                max_value=500,
                max_value_reason="Bounds K-means memory, fit cost, and the scientist-facing centroid table.",
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
                max_value=100,
                max_value_reason="Bounds repeated K-means fits while preserving robust multi-start use.",
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
                min_value=1,
                max_value=10000,
                max_value_reason="Bounds one initialization's iterative work and recorded convergence budget.",
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
                max_value=4294967295,
                max_value_reason="Matches the closed unsigned 32-bit seed domain used by the fitted implementation.",
                step=1,
                description="Random seed for reproducibility",
                required=False,
                category="advanced",
            ),
        ],
        input_types=["SherpaDataset", "array"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Input Data Matrix",
                description="Spectral dataset, PCA scores, or multivariate feature table to cluster",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
        ],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Cluster Labels",
                description="Primary cluster-label output for direct node replacement",
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/FittedModel/1.0",
                required=True,
                label="Fitted K-Means Clustering",
                description="Closed centroid state for deterministic fitted-model application",
            ),
            PortMetadata(
                name="labels",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Cluster Labels",
                description="Assigned cluster labels",
            ),
            PortMetadata(
                name="cluster_assignment",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Cluster Assignment",
                description="Alias of labels for direct downstream comparison",
            ),
            PortMetadata(
                name="cluster_summary",
                type_ref="spectrasherpa://types/Any/1.0",
                required=True,
                label="Cluster Summary",
                description="Cluster counts, fractions, and sample previews",
            ),
            PortMetadata(
                name="centroids",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Centroids",
                description="Cluster centers coordinates",
            ),
            PortMetadata(
                name="embedding",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Embedding (2D)",
                description="2D projection of samples for cluster scatter visualization",
            ),
            PortMetadata(
                name="visualization",
                type_ref="spectrasherpa://types/Visualization/1.0",
                required=True,
                label="Cluster Map",
                description=(
                    "Full-space cluster assignments shown on the declared two-dimensional " "presentation embedding"
                ),
            ),
            PortMetadata(
                name="inertia",
                type_ref="spectrasherpa://types/Scalar/1.0",
                required=True,
                label="Within-Cluster Sum of Squares",
                description="Sum of squared Euclidean distances to assigned centroids",
            ),
            PortMetadata(
                name="n_clusters",
                type_ref="spectrasherpa://types/Scalar/1.0",
                required=True,
                label="Cluster Count",
                description="Exact number of fitted K-means centroids",
            ),
            PortMetadata(
                name="metadata",
                type_ref="spectrasherpa://types/Any/1.0",
                required=True,
                label="Clustering Evidence",
                description="Closed assignment, presentation, and quality interpretation",
            ),
        ],
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python that calls the same K-means authority as live execution."""
        del use_scp
        input_expression = inputs.get("default", "input_data")
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.modeling."
            "partition_clustering_core import kmeans_export_outputs",
            f"{indent}results[{self.node_id!r}] = kmeans_export_outputs(",
            f"{indent}    {input_expression}, parameters={self._resolve_params()!r},",
            f"{indent})",
        ]

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """
        Execute K-Means clustering.

        Args:
            input_data: SherpaDataset, SpectralResult, or array (samples x features)

        Returns:
            Dict containing cluster labels and metadata
        """
        del kwargs
        state = partition_clustering_core.fit_kmeans(
            input_data,
            parameters=self._resolve_params(),
        )
        outputs = partition_clustering_core.kmeans_outputs_from_state(input_data, state)
        outputs["_model_artifact"] = build_native_model_artifact(
            self, coerce_to_sherpa(input_data, input_name="input_data", allow_array=True), state
        )
        quality = state["quality"]
        return NodeResult(
            outputs=outputs,
            diagnostics={
                "n_clusters": state["parameters"]["n_clusters"],
                "silhouette_score": quality["silhouette_score"],
                "davies_bouldin_score": quality["davies_bouldin_score"],
                "inertia": state["inertia"],
                "n_iter": state["n_iter"],
            },
        )

    def fit_fitted_state(self, input_data: Any, target: Any = None) -> dict[str, Any]:
        """Fit the closed centroid state consumed by graph and artifact application."""
        del target
        return partition_clustering_core.fit_kmeans(
            input_data,
            parameters=self._resolve_params(),
        )

    def apply_fitted_state(self, input_data: Any, state: Any) -> np.ndarray:
        """Assign new observations to the nearest canonical centroid."""
        return partition_clustering_core.apply_kmeans(input_data, state)


bind_stable_execution_contract(
    KMeansNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_MODEL,
    implementation_id="spectrasherpa.model.kmeans",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 60, "cpu_seconds": 60, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/exploratory.md",
    implementation_modules=(partition_clustering_core, saved_native_model),
    implementation_distributions=("numpy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scikit-learn", "1.9.0")),
    citations=(
        "MacQueen, Some Methods for Classification and Analysis of Multivariate Observations, "
        "Proceedings of the Fifth Berkeley Symposium on Mathematical Statistics and Probability "
        "(1967) 281-297",
        "R stats::kmeans reference implementation",
    ),
    fitted_state_serializer=partition_clustering_core.KMEANS_STATE_SERIALIZER,
    deterministic=True,
    target_access=TargetAccess.NONE,
    group_access="none",
)


@register_node
class DBSCANNode(Node):
    """
    DBSCAN clustering node.

    Performs density-based clustering and marks noise points as -1.
    """

    metadata = NodeMetadata(
        policy=NodePolicy(),
        node_type="model.dbscan",
        category="clustering",
        label="Fit DBSCAN Clustering",
        description="Fit density-based clustering for unsupervised grouping",
        parameters=[
            NodeParameter(
                name="eps",
                label="Epsilon",
                param_type="number",
                default=0.5,
                min_value=0.01,
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
                max_value=100000,
                max_value_reason="Bounds neighborhood support bookkeeping to a finite cohort-scale request.",
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
                options=["euclidean", "manhattan", "cosine"],
                description="Distance metric",
                required=False,
                category="advanced",
            ),
        ],
        input_types=["SherpaDataset", "array"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Input Data Matrix",
                description="Spectral dataset, PCA scores, or multivariate feature table to cluster",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
        ],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Cluster Labels",
                description="Primary cluster-label output for direct node replacement",
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/FittedModel/1.0",
                required=True,
                label="Fitted DBSCAN Clustering",
                description="Closed density-partition state for exact-cohort replay",
            ),
            PortMetadata(
                name="labels",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Cluster Labels",
                description="Assigned cluster labels (noise=-1)",
            ),
            PortMetadata(
                name="cluster_assignment",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Cluster Assignment",
                description="Alias of labels for direct downstream comparison",
            ),
            PortMetadata(
                name="cluster_summary",
                type_ref="spectrasherpa://types/Any/1.0",
                required=True,
                label="Cluster Summary",
                description="Cluster counts, fractions, and sample previews",
            ),
            PortMetadata(
                name="embedding",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Embedding (2D)",
                description="2D projection of samples for cluster scatter visualization",
            ),
            PortMetadata(
                name="visualization",
                type_ref="spectrasherpa://types/Visualization/1.0",
                required=True,
                label="Cluster Map",
                description=(
                    "Full-space cluster and noise assignments shown on the declared "
                    "two-dimensional presentation embedding"
                ),
            ),
            PortMetadata(
                name="n_clusters",
                type_ref="spectrasherpa://types/Scalar/1.0",
                required=True,
                label="Observed Cluster Count",
                description="Number of density-connected clusters, excluding noise",
            ),
            PortMetadata(
                name="metadata",
                type_ref="spectrasherpa://types/Any/1.0",
                required=True,
                label="Clustering Evidence",
                description="Closed density, noise, presentation, and quality interpretation",
            ),
        ],
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python that calls the same DBSCAN authority as live execution."""
        del use_scp
        input_expression = inputs.get("default", "input_data")
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.modeling."
            "partition_clustering_core import dbscan_export_outputs",
            f"{indent}results[{self.node_id!r}] = dbscan_export_outputs(",
            f"{indent}    {input_expression}, parameters={self._resolve_params()!r},",
            f"{indent})",
        ]

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """
        Execute DBSCAN clustering.

        Args:
            input_data: SherpaDataset, SpectralResult, or array (samples x features)

        Returns:
            Dict containing cluster labels and metadata
        """
        del kwargs
        state = partition_clustering_core.fit_dbscan(
            input_data,
            parameters=self._resolve_params(),
        )
        outputs = partition_clustering_core.dbscan_outputs_from_state(input_data, state)
        outputs["_model_artifact"] = build_native_model_artifact(
            self, coerce_to_sherpa(input_data, input_name="input_data", allow_array=True), state
        )
        quality = state["quality"]
        return NodeResult(
            outputs=outputs,
            diagnostics={
                "n_clusters": state["observed_clusters"],
                "eps": state["parameters"]["eps"],
                "min_samples": state["parameters"]["min_samples"],
                "noise_fraction": state["noise_count"] / state["n_samples"],
                "silhouette_score": quality["silhouette_score"],
                "davies_bouldin_score": quality["davies_bouldin_score"],
                "metric": state["parameters"]["metric"],
            },
        )

    def fit_fitted_state(self, input_data: Any, target: Any = None) -> dict[str, Any]:
        """Fit the closed cohort state consumed by exact-cohort replay."""
        del target
        return partition_clustering_core.fit_dbscan(
            input_data,
            parameters=self._resolve_params(),
        )

    def apply_fitted_state(self, input_data: Any, state: Any) -> np.ndarray:
        """Replay DBSCAN only for the exact cohort on which density was fitted."""
        return partition_clustering_core.replay_dbscan_labels(input_data, state)


bind_stable_execution_contract(
    DBSCANNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_MODEL,
    implementation_id="spectrasherpa.model.dbscan",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 60, "cpu_seconds": 60, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/exploratory.md",
    implementation_modules=(partition_clustering_core, saved_native_model),
    implementation_distributions=("numpy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scikit-learn", "1.9.0")),
    citations=(
        "Ester, Kriegel, Sander, and Xu, A Density-Based Algorithm for Discovering Clusters in "
        "Large Spatial Databases with Noise, Proceedings of KDD-96 (1996) 226-231",
        "R dbscan::dbscan reference implementation",
    ),
    fitted_state_serializer=partition_clustering_core.DBSCAN_STATE_SERIALIZER,
    deterministic=True,
    target_access=TargetAccess.NONE,
    group_access="none",
)
