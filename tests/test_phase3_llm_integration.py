"""Phase 3: LLM Integration + MCP tests.

LLM service/orchestration test classes were removed — that functionality
is not part of the OSS distribution.
"""

from __future__ import annotations

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import (
    DomainContext,
    EvaluationResult,
    SampleAxis,
    SherpaDataset,
    SpectralAxis,
    TargetContext,
)
from spectra_sherpa.app.services.dataset_registry import dataset_registry

# ---------------------------------------------------------------------------
# Slice 2: Dataset tool registration
# ---------------------------------------------------------------------------


class TestDatasetTools:
    def test_describe_dataset_registered(self):
        """describe_dataset tool is in the global registry."""
        import spectra_sherpa.app.services.tools.builtin  # noqa: F401
        from spectra_sherpa.app.services.tools.registry import tool_registry

        assert "describe_dataset" in tool_registry

    def test_get_dataset_quality_registered(self):
        """get_dataset_quality tool is in the global registry."""
        import spectra_sherpa.app.services.tools.builtin  # noqa: F401
        from spectra_sherpa.app.services.tools.registry import tool_registry

        assert "get_dataset_quality" in tool_registry

    def test_compute_dataset_statistics_registered(self):
        """compute_dataset_statistics tool is in the global registry."""
        import spectra_sherpa.app.services.tools.builtin  # noqa: F401
        from spectra_sherpa.app.services.tools.registry import tool_registry

        assert "compute_dataset_statistics" in tool_registry

    def test_describe_dataset_returns_summary(self):
        """describe_dataset returns both summary and structured."""
        from spectra_sherpa.app.services.tools.builtin.datasets import describe_dataset

        ds = SherpaDataset(
            X=np.ones((5, 100)),
            feature_axis=SpectralAxis(values=np.linspace(400, 4000, 100), units="cm-1"),
            domain=DomainContext(technique="IR"),
            title="Test Spectra",
        )
        dataset_id = dataset_registry.register(ds)
        result = describe_dataset(dataset_id=dataset_id, tier=1)

        assert "summary" in result
        assert "structured" in result
        assert "Test Spectra" in result["summary"]
        assert result["structured"]["domain"]["technique"] == "IR"
        assert result["dataset_id"] == dataset_id

    def test_describe_dataset_tier0(self):
        """Tier 0 returns shape and domain only."""
        from spectra_sherpa.app.services.tools.builtin.datasets import describe_dataset

        ds = SherpaDataset(
            X=np.zeros((3, 50)),
            domain=DomainContext(technique="NIR"),
            title="NIR Data",
        )
        dataset_id = dataset_registry.register(ds)
        result = describe_dataset(dataset_id=dataset_id, tier=0)
        assert "3 samples" in result["summary"]
        assert "NIR" in result["summary"]

    def test_get_dataset_quality_empty(self):
        """get_dataset_quality with no evaluations."""
        from spectra_sherpa.app.services.tools.builtin.datasets import get_dataset_quality

        ds = SherpaDataset(X=np.zeros((5, 10)))
        dataset_id = dataset_registry.register(ds)
        result = get_dataset_quality(dataset_id=dataset_id)
        assert result["n_evaluations"] == 0
        assert result["snr"] is None
        assert result["dataset_id"] == dataset_id

    def test_get_dataset_quality_with_evaluation(self):
        """get_dataset_quality returns latest evaluation."""
        from spectra_sherpa.app.services.tools.builtin.datasets import get_dataset_quality

        ds = SherpaDataset(X=np.zeros((5, 10)))
        ev = EvaluationResult(evaluation_id="ev1", model_type="PLS", r2=0.95)
        ds.quality.add_evaluation(ev)
        dataset_id = dataset_registry.register(ds)
        result = get_dataset_quality(dataset_id=dataset_id)
        assert result["n_evaluations"] == 1
        assert result["latest"]["model_type"] == "PLS"
        assert result["latest"]["r2"] == 0.95

    def test_compute_dataset_statistics_feature_medians(self):
        """compute_dataset_statistics computes requested per-feature values from raw data."""
        from spectra_sherpa.app.services.tools.builtin.datasets import compute_dataset_statistics

        ds = SherpaDataset(
            X=np.array(
                [
                    [5.1, 3.5, 1.4, 0.2],
                    [4.9, 3.0, 1.4, 0.2],
                    [6.2, 3.4, 5.4, 2.3],
                ]
            ),
            feature_axis=SpectralAxis(
                labels=[
                    "sepal length (cm)",
                    "sepal width (cm)",
                    "petal length (cm)",
                    "petal width (cm)",
                ]
            ),
            title="Iris subset",
        )
        dataset_id = dataset_registry.register(ds)

        result = compute_dataset_statistics(
            dataset_id=dataset_id,
            statistics=["median"],
            axis="features",
        )

        assert result["dataset_id"] == dataset_id
        assert result["shape"] == [3, 4]
        assert result["truncated"] is False
        assert result["features"] == [
            {"index": 0, "label": "sepal length (cm)", "median": 5.1},
            {"index": 1, "label": "sepal width (cm)", "median": 3.4},
            {"index": 2, "label": "petal length (cm)", "median": 1.4},
            {"index": 3, "label": "petal width (cm)", "median": 0.2},
        ]

        scalar_stat_result = compute_dataset_statistics(
            dataset_id=dataset_id,
            statistics="median",
            axis="FEATURES",
        )
        assert scalar_stat_result["features"][0]["median"] == 5.1
        assert scalar_stat_result["feature_axis"]["n_points"] == 4
        assert scalar_stat_result["data_values"]["title"] == "value"

    def test_compute_dataset_statistics_samples_overall_limit_and_nan(self):
        """compute_dataset_statistics supports sample/overall axes, truncation, and NaNs."""
        from spectra_sherpa.app.services.tools.builtin.datasets import compute_dataset_statistics

        ds = SherpaDataset(
            X=np.array(
                [
                    [1.0, np.nan, 3.0],
                    [4.0, 5.0, 6.0],
                    [7.0, 8.0, 9.0],
                ]
            ),
            sample_axis=SampleAxis(labels=["a", "b", "c"], classes=["low", "mid", "high"]),
            units="absorbance",
        )
        dataset_id = dataset_registry.register(ds)

        sample_result = compute_dataset_statistics(
            dataset_id=dataset_id,
            statistics=["mean", "std", "min", "max", "q1", "q3"],
            axis="samples",
            limit=2,
        )
        assert sample_result["truncated"] is True
        assert sample_result["data_values"]["units"] == "absorbance"
        assert sample_result["samples"][0]["label"] == "a"
        assert sample_result["samples"][0]["class"] == "low"
        assert sample_result["samples"][0]["mean"] == 2.0
        assert sample_result["samples"][0]["min"] == 1.0
        assert sample_result["samples"][0]["max"] == 3.0

        overall_result = compute_dataset_statistics(
            dataset_id=dataset_id,
            statistics=["median"],
            axis="overall",
        )
        assert overall_result["statistics"]["median"] == 5.5

    def test_compute_dataset_statistics_feature_selectors(self):
        """Feature selectors let Sherpa compute stats for named or coordinate-selected features."""
        from spectra_sherpa.app.services.tools.builtin.datasets import compute_dataset_statistics

        ds = SherpaDataset(
            X=np.array(
                [
                    [1.0, 10.0, 100.0, 1000.0],
                    [2.0, 20.0, 200.0, 2000.0],
                    [3.0, 30.0, 300.0, 3000.0],
                ]
            ),
            feature_axis=SpectralAxis(
                values=np.array([1100.0, 1722.0, 2850.0, 3401.0]),
                labels=["baseline", "carbonyl band", "alkyl band", "hydroxyl band"],
                units="cm-1",
            ),
        )
        dataset_id = dataset_registry.register(ds)

        result = compute_dataset_statistics(
            dataset_id=dataset_id,
            statistics=["median"],
            axis="features",
            feature_selectors=[
                {"label": "carbonyl"},
                {"coordinate": 3400.0},
                0,
            ],
        )

        assert result["truncated"] is False
        assert result["selection"]["unresolved"] == []
        assert [row["index"] for row in result["features"]] == [1, 3, 0]
        assert [row["median"] for row in result["features"]] == [20.0, 2000.0, 2.0]
        assert result["features"][1]["coordinate"] == 3401.0
        assert result["selection"]["resolved"][1]["matched_by"] == "coordinate"

    def test_compute_dataset_statistics_sample_selectors_and_unresolved_items(self):
        """Sample selectors support labels while reporting unmatched selectors."""
        from spectra_sherpa.app.services.tools.builtin.datasets import compute_dataset_statistics

        ds = SherpaDataset(
            X=np.array(
                [
                    [1.0, 2.0],
                    [10.0, 20.0],
                    [100.0, 200.0],
                ]
            ),
            sample_axis=SampleAxis(labels=["blank", "standard A", "unknown"], classes=["qc", "cal", "test"]),
        )
        dataset_id = dataset_registry.register(ds)

        result = compute_dataset_statistics(
            dataset_id=dataset_id,
            statistics=["mean"],
            axis="samples",
            sample_selectors=["standard", "missing"],
        )

        assert result["samples"] == [{"index": 1, "label": "standard A", "class": "cal", "mean": 15.0}]
        assert result["selection"]["unresolved"] == ["missing"]

        try:
            compute_dataset_statistics(
                dataset_id=dataset_id,
                statistics=["mean"],
                axis="samples",
                sample_selectors=["not present"],
            )
        except ValueError as exc:
            assert "No samples selectors matched" in str(exc)
        else:
            raise AssertionError("expected ValueError for unmatched sample selector")

    def test_compute_dataset_statistics_selector_cap_and_label_normalization(self):
        """Oversized selector lists are bounded; label matching still
        resolves via the precomputed normalized labels."""
        from spectra_sherpa.app.services.tools.builtin.datasets import MAX_SELECTOR_ITEMS, compute_dataset_statistics

        ds = SherpaDataset(
            X=np.array([[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]]),
            feature_axis=SpectralAxis(labels=["Sepal Length", "Sepal Width", "Petal Length", "Petal Width"]),
        )
        dataset_id = dataset_registry.register(ds)

        # One resolvable selector followed by far more than the cap of
        # unresolvable ones: resolution, the echoed ``requested`` list,
        # and ``unresolved`` are all bounded; ``selectors_truncated`` set.
        oversized = [{"label": "Sepal Length"}] + [f"nope_{i}" for i in range(MAX_SELECTOR_ITEMS + 60)]
        result = compute_dataset_statistics(
            dataset_id=dataset_id,
            statistics=["mean"],
            axis="features",
            feature_selectors=oversized,
        )
        selection = result["selection"]
        assert selection["selectors_truncated"] is True
        assert len(selection["requested"]) == MAX_SELECTOR_ITEMS
        assert len(selection["unresolved"]) == MAX_SELECTOR_ITEMS - 1
        assert [row["index"] for row in result["features"]] == [0]

        # Exact (case-insensitive) and partial label matches still work
        # against the once-normalized label list.
        normalized = compute_dataset_statistics(
            dataset_id=dataset_id,
            statistics=["mean"],
            axis="features",
            feature_selectors=[{"label": "sepal length"}, "petal"],
        )
        assert [row["index"] for row in normalized["features"]] == [0, 2]

    def test_compute_dataset_statistics_target_numeric_and_categorical(self):
        """compute_dataset_statistics exposes target/Y summaries for numeric and categorical targets."""
        from spectra_sherpa.app.services.tools.builtin.datasets import compute_dataset_statistics

        numeric = SherpaDataset(
            X=np.ones((4, 2)),
            target=np.array([1.0, 2.0, 4.0, 8.0]),
            target_context=TargetContext(
                target_type="continuous",
                target_name="concentration",
                target_units="mg/L",
            ),
        )
        numeric_id = dataset_registry.register(numeric)
        numeric_result = compute_dataset_statistics(numeric_id, statistics=["median"], axis="target")
        numeric_target = numeric_result["target_summary"]["targets"][0]
        assert numeric_result["target_summary"]["target_units"] == "mg/L"
        assert numeric_target["kind"] == "numeric"
        assert numeric_target["statistics"]["median"] == 3.0

        categorical = SherpaDataset(
            X=np.ones((4, 2)),
            target=np.array(["setosa", "virginica", "setosa", "versicolor"]),
            target_context=TargetContext(target_type="categorical", target_name="species"),
        )
        categorical_id = dataset_registry.register(categorical)
        categorical_result = compute_dataset_statistics(categorical_id, axis="target")
        categorical_target = categorical_result["target_summary"]["targets"][0]
        assert categorical_target["kind"] == "categorical"
        assert categorical_target["counts"][0] == {"value": "setosa", "count": 2}

    def test_compute_dataset_statistics_error_paths(self):
        """compute_dataset_statistics reports invalid handles and unsupported stats clearly."""
        from spectra_sherpa.app.services.tools.builtin.datasets import compute_dataset_statistics

        ds = SherpaDataset(X=np.ones((2, 2)))
        dataset_id = dataset_registry.register(ds)

        try:
            compute_dataset_statistics(dataset_id=dataset_id, statistics=["variance"])
        except ValueError as exc:
            assert "No supported statistics" in str(exc)
        else:
            raise AssertionError("expected ValueError for unsupported statistics")

        try:
            compute_dataset_statistics(dataset_id="missing-dataset")
        except ValueError as exc:
            assert "Unknown dataset_id" in str(exc)
        else:
            raise AssertionError("expected ValueError for missing dataset")

    def test_compute_dataset_statistics_uses_bounded_sampling_for_large_overall(self, monkeypatch):
        """Large overall reductions are sampled instead of computed over every cell."""
        from spectra_sherpa.app.services.tools.builtin import datasets
        from spectra_sherpa.app.services.tools.builtin.datasets import compute_dataset_statistics

        monkeypatch.setattr(datasets, "MAX_EXACT_STAT_CELLS", 10)
        monkeypatch.setattr(datasets, "MAX_OVERALL_SAMPLE_CELLS", 5)

        ds = SherpaDataset(X=np.arange(100, dtype=float).reshape(10, 10))
        dataset_id = dataset_registry.register(ds)
        result = compute_dataset_statistics(dataset_id=dataset_id, statistics=["mean"], axis="overall")

        assert result["approximate"] is True
        assert result["sampled"] is True
        assert result["sample_plan"]["source_cells"] == 100

    def test_tools_have_data_category(self):
        """Both tools are in the data category."""
        import spectra_sherpa.app.services.tools.builtin  # noqa: F401
        from spectra_sherpa.app.services.tools.registry import tool_registry

        defn1, _ = tool_registry.get("describe_dataset")
        defn2, _ = tool_registry.get("get_dataset_quality")
        defn3, _ = tool_registry.get("compute_dataset_statistics")
        assert defn1.category.value == "data"
        assert defn2.category.value == "data"
        assert defn3.category.value == "data"


# ---------------------------------------------------------------------------
# Slice 3: WorkflowContextNode domain fields
# ---------------------------------------------------------------------------


class TestWorkflowContextNodeDomain:
    def test_new_fields_serialize(self):
        """New domain fields serialize correctly."""
        from spectra_sherpa.app.schemas.sherpa import WorkflowContextNode

        node = WorkflowContextNode(
            node_id="n1",
            node_type="data.eigenvector",
            domain_technique="IR",
            domain_data_quantity="Absorbance",
            processing_stage="preprocessed",
            processing_effects=["normalized", "baseline_corrected"],
        )
        d = node.model_dump()
        assert d["domain_technique"] == "IR"
        assert d["domain_data_quantity"] == "Absorbance"
        assert d["processing_stage"] == "preprocessed"
        assert d["processing_effects"] == ["normalized", "baseline_corrected"]

    def test_new_fields_default_none(self):
        """New domain fields default to None."""
        from spectra_sherpa.app.schemas.sherpa import WorkflowContextNode

        node = WorkflowContextNode(node_id="n1", node_type="model.pca")
        assert node.domain_technique is None
        assert node.domain_data_quantity is None
        assert node.processing_stage is None
        assert node.processing_effects is None

    def test_roundtrip_json(self):
        """Domain fields survive JSON round-trip."""
        from spectra_sherpa.app.schemas.sherpa import WorkflowContextNode

        node = WorkflowContextNode(
            node_id="n1",
            node_type="preprocess.normalize",
            domain_technique="NIR",
            processing_effects=["normalized"],
        )
        json_str = node.model_dump_json()
        restored = WorkflowContextNode.model_validate_json(json_str)
        assert restored.domain_technique == "NIR"
        assert restored.processing_effects == ["normalized"]

    def test_existing_fields_preserved(self):
        """Existing fields still work alongside new domain fields."""
        from spectra_sherpa.app.schemas.sherpa import WorkflowContextNode

        node = WorkflowContextNode(
            node_id="n1",
            node_type="model.pca",
            label="PCA",
            parameters={"n_components": 3},
            result_shape=[10, 3],
            domain_technique="IR",
        )
        assert node.label == "PCA"
        assert node.parameters == {"n_components": 3}
        assert node.result_shape == [10, 3]
        assert node.domain_technique == "IR"


# ---------------------------------------------------------------------------
# Slice 4: NodePolicy
# ---------------------------------------------------------------------------


class TestNodePolicy:
    def test_node_policy_defaults(self):
        """NodePolicy has safe defaults."""
        from spectra_sherpa.app.services.dag.node_base import NodePolicy

        policy = NodePolicy()
        assert policy.safe_for_auto_apply is False
        assert policy.requires_human_review is True
        assert policy.data_egress_risk == "none"

    def test_node_metadata_without_policy(self):
        """NodeMetadata without policy defaults to None."""
        from spectra_sherpa.app.services.dag.node_base import NodeMetadata

        meta = NodeMetadata(
            node_type="test.node",
            category="test",
            label="Test",
            description="A test node",
        )
        assert meta.policy is None

    def test_node_metadata_with_policy(self):
        """NodeMetadata accepts a policy."""
        from spectra_sherpa.app.services.dag.node_base import NodeMetadata, NodePolicy

        policy = NodePolicy(
            safe_for_auto_apply=True,
            requires_human_review=False,
            data_egress_risk="metadata",
        )
        meta = NodeMetadata(
            node_type="test.node",
            category="test",
            label="Test",
            description="A test node",
            policy=policy,
        )
        assert meta.policy.safe_for_auto_apply is True
        assert meta.policy.requires_human_review is False
        assert meta.policy.data_egress_risk == "metadata"

    def test_snv_node_has_preprocessing_policy(self):
        """SNV node is tagged as safe for auto-apply."""
        from spectra_sherpa.app.services.dag.node_base import node_registry

        meta = node_registry.get_metadata("preprocess.normalize")
        assert meta.policy is not None
        assert meta.policy.safe_for_auto_apply is True
        assert meta.policy.requires_human_review is False
        assert meta.policy.data_egress_risk == "none"

    def test_export_node_has_output_policy(self):
        """Export node requires human review with full data egress."""
        from spectra_sherpa.app.services.dag.node_base import node_registry

        meta = node_registry.get_metadata("output.export")
        assert meta.policy is not None
        assert meta.policy.safe_for_auto_apply is False
        assert meta.policy.requires_human_review is True
        assert meta.policy.data_egress_risk == "full_data"

    def test_pca_node_has_modeling_policy(self):
        """PCA node requires human review, no data egress."""
        from spectra_sherpa.app.services.dag.node_base import node_registry

        meta = node_registry.get_metadata("model.pca")
        assert meta.policy is not None
        assert meta.policy.safe_for_auto_apply is False
        assert meta.policy.requires_human_review is True
        assert meta.policy.data_egress_risk == "none"

    def test_untagged_node_no_policy(self):
        """Nodes without explicit policy have None."""
        from spectra_sherpa.app.services.dag.node_base import node_registry

        # Plot node should not have a policy
        meta = node_registry.get_metadata("output.plot")
        assert meta.policy is None
