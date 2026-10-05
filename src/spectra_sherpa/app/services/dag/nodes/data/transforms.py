"""TrainTestSplitNode -- split datasets into training and test sets.

Registered as ``data.train_test_split``.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import numpy as np

from spectra_sherpa.app.services.dag import io_contracts as dag_io_contracts
from spectra_sherpa.app.services.dag import meta_helpers as dag_meta_helpers
from spectra_sherpa.app.services.dag import supervision_binding
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.core.target_authority import admit_target_authority
from spectra_sherpa.execution_contract_vocabulary import (
    DatasetRankPolicy,
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from ...io_contracts import bind_X, to_numpy_2d
from ...node_base import Node, NodeMetadata, NodeParameter, NodePolicy, PortMetadata, register_node
from . import _utils as data_utils
from . import sample_preparation, sample_table, split_planner
from .sample_preparation import attach_target_dataset, explicit_filter_values, filter_samples_dataset
from .split_planner import bind_split_groups, bind_split_target, materialize_split_outputs, plan_train_test_split

logger = logging.getLogger(__name__)


def _canonical_attach_target_parameters(values: dict[str, object]) -> dict[str, object]:
    authority = admit_target_authority(values.get("target_authority"))
    values["target_authority"] = authority.canonical_dict() if authority is not None else None
    source = str(values["target_source"])
    target_column = str(values["target_column"])
    group_column = str(values["group_column"])
    if source == "sample_table_column":
        if not target_column or target_column != target_column.strip():
            raise ValueError("sample-table target attachment requires one exact target column")
        if group_column and group_column != group_column.strip():
            raise ValueError("validation group column must use an exact non-empty spelling")
        if group_column == target_column:
            raise ValueError("target and validation group columns must be different")
    elif source == "connected_target":
        if target_column or group_column:
            raise ValueError("connected target attachment may not carry sample-table column parameters")
    else:
        raise ValueError(f"Unsupported target source: {source!r}")
    if authority is not None:
        if authority.target_type != values["target_type"]:
            raise ValueError("target authority type differs from the attachment type")
        if source == "sample_table_column" and authority.column != target_column:
            raise ValueError("target authority column differs from the sample-table column")
    return values


def _canonical_filter_parameters(values: dict[str, object]) -> dict[str, object]:
    """Close cross-field semantics that the generic parameter grammar cannot express."""

    field = str(values["field"])
    exact_values = values["filter_values"]
    if field == "sample_table" and not str(values["sample_table_column"]).strip():
        raise ValueError("sample_table filtering requires one explicit metadata column")
    if field == "intensity" and str(values["pattern"]).strip():
        raise ValueError("intensity filtering may not carry an inactive text pattern")
    if field == "source_inclusion" and (str(values["pattern"]).strip() or exact_values is not None):
        raise ValueError("source inclusion filtering does not admit a text or exact-value rule")
    if exact_values is not None:
        if field not in {"sample_label", "sample_class", "sample_table"}:
            raise ValueError("exact-value filtering is available only for labels, classes, or metadata")
        if str(values["pattern"]).strip():
            raise ValueError("exact-value filtering may not also carry a text pattern")
        values["match_mode"] = "in_list"
        values["case_sensitive"] = True
    return values


def _managed_filter_parameters(values: dict[str, object]) -> dict[str, object]:
    """Keep hosted row selection explicit and avoid unbounded regex matching."""
    if values["match_mode"] == "regex":
        raise ValueError("managed sample filtering does not admit regular expressions")
    if values["field"] == "sample_index":
        raise ValueError("managed sample filtering does not admit sample-index range expansion")
    if values["allow_empty"]:
        raise ValueError("managed sample filtering requires a non-empty selected population")
    for key in ("pattern", "sample_table_column"):
        if len(str(values[key]).encode("utf-8")) > 4096:
            raise ValueError(f"managed sample filter {key} exceeds 4096 UTF-8 bytes")
    selected = values["filter_values"]
    if isinstance(selected, list):
        if len(selected) > 1024 or sum(len(str(item).encode("utf-8")) for item in selected) > 4096:
            raise ValueError("managed sample filter values exceed 1024 items or 4096 UTF-8 bytes")
    return values


# Each of these settings belongs to a bounded family of split methods, exactly as
# the node's ``visible_when`` declarations state: a random seed governs only the
# two methods that draw at random, and a distance space governs only the two that
# measure sample dissimilarity. The chosen method therefore decides whether the
# setting has any meaning, and a value carried over from a different method is a
# leftover rather than a scientific instruction: the sheet that ships
# ``kennard_stone`` with five PCA components leaves those five components behind
# when a scientist switches to stratified sampling, in a field the contract has
# already declared inapplicable and the Workbench no longer shows. Resetting it
# to the declared default is what makes the stored parameters agree with that
# declaration. Nothing meaningful is discarded, because a stratified split has no
# distance space for the value to describe, and spxy's published raw-space
# Euclidean definition admits no alternative either.
#
# ``plan_train_test_split`` still refuses the same combinations when they are
# passed to it directly. There the argument was written deliberately by a caller
# who named both the method and the setting in one call, which is a mistake worth
# reporting rather than a stale field worth normalizing.
_SPLIT_METHOD_SCOPED_PARAMETERS: tuple[tuple[str, frozenset[str], object], ...] = (
    ("test_size", frozenset({"random", "stratified", "sequential", "kennard_stone", "duplex", "spxy"}), 0.2),
    ("random_seed", frozenset({"random", "stratified"}), 42),
    ("distance_metric", frozenset({"kennard_stone", "duplex"}), "euclidean"),
    ("n_components", frozenset({"kennard_stone", "duplex"}), 0),
    ("held_out_groups", frozenset({"group_holdout"}), []),
)


def _canonical_split_parameters(values: dict[str, object]) -> dict[str, object]:
    """Close the scientific parameter vocabulary before planning a split."""

    seed = values["random_seed"]
    if isinstance(seed, bool) or not isinstance(seed, (int, float)) or not float(seed).is_integer():
        raise ValueError("random_seed must be an integer")
    values["random_seed"] = int(seed)
    n_components = values["n_components"]
    if (
        isinstance(n_components, bool)
        or not isinstance(n_components, (int, float))
        or not float(n_components).is_integer()
    ):
        raise ValueError("n_components must be an integer")
    values["n_components"] = int(n_components)
    # Graphs saved before this parameter existed carry no key for it.
    values.setdefault("held_out_groups", [])
    method = values["split_method"]
    for name, applicable_methods, declared_default in _SPLIT_METHOD_SCOPED_PARAMETERS:
        if method not in applicable_methods:
            values[name] = declared_default
    if method == "group_holdout":
        requested = values["held_out_groups"]
        if not isinstance(requested, list) or not requested:
            raise ValueError("group_holdout requires at least one named group to hold out")
        for entry in requested:
            if isinstance(entry, bool) or not isinstance(entry, (str, int, float)):
                raise ValueError("held_out_groups must name exact scalar group values")
    return values


@register_node
class FilterSamplesNode(Node):
    """Filter or subsample dataset rows using sample metadata."""

    metadata = NodeMetadata(
        policy=NodePolicy(),
        node_type="data.filter_samples",
        category="data",
        label="Filter Samples",
        description="Filter dataset rows using sample labels, classes, metadata, intensity, or row numbers",
        input_types=["SpectralDataset"],
        output_type="SpectralDataset",
        parameters=[
            NodeParameter(
                name="field",
                label="Filter Field",
                param_type="select",
                options=[
                    {"label": "Sample Label", "value": "sample_label"},
                    {"label": "Sample Class", "value": "sample_class"},
                    {"label": "Sample Table", "value": "sample_table"},
                    {"label": "Sample Index", "value": "sample_index"},
                    {"label": "Source Inclusion", "value": "source_inclusion"},
                    {"label": "Intensity", "value": "intensity"},
                ],
                default="sample_label",
                description="Sample metadata field used to select rows. Hosted execution excludes sample-index ranges.",
                required=True,
            ),
            NodeParameter(
                name="pattern",
                label="Pattern",
                param_type="text",
                default="",
                description=(
                    "Text, comma-separated values, or regular expression to match. Hosted managed execution "
                    "admits at most 4096 UTF-8 bytes; exact-value lists admit at most 1024 items and 4096 bytes."
                ),
                required=False,
            ),
            NodeParameter(
                name="match_mode",
                label="Match Mode",
                param_type="select",
                options=[
                    {"label": "Contains", "value": "contains"},
                    {"label": "Equals", "value": "equals"},
                    {"label": "In List", "value": "in_list"},
                    {"label": "Regex", "value": "regex"},
                ],
                default="contains",
                description="How the pattern is matched against each sample. Hosted managed execution excludes regex.",
                required=True,
            ),
            NodeParameter(
                name="case_sensitive",
                label="Case Sensitive",
                param_type="boolean",
                default=False,
                description="Require exact letter case when matching text",
                required=False,
            ),
            NodeParameter(
                name="invert",
                label="Invert Selection",
                param_type="boolean",
                default=False,
                description="Keep samples that do not match the filter",
                required=False,
            ),
            NodeParameter(
                name="sample_table_column",
                label="Sample Table Column",
                param_type="text",
                default="",
                description="Metadata column to use when Filter Field is sample_table",
                required=False,
                visible_when={"field": ["sample_table"]},
            ),
            NodeParameter(
                name="intensity_metric",
                label="Intensity Metric",
                param_type="select",
                options=[
                    {"label": "Mean Intensity", "value": "mean"},
                    {"label": "Max Intensity", "value": "max"},
                    {"label": "Min Intensity", "value": "min"},
                    {"label": "Any Point", "value": "any"},
                    {"label": "All Points", "value": "all"},
                ],
                default="max",
                description="How each sample spectrum is summarized for intensity filtering",
                required=False,
                visible_when={"field": ["intensity"]},
            ),
            NodeParameter(
                name="intensity_operator",
                label="Intensity Operator",
                param_type="select",
                options=[
                    {"label": "Greater Than", "value": "gt"},
                    {"label": "Greater Than or Equal", "value": "gte"},
                    {"label": "Less Than", "value": "lt"},
                    {"label": "Less Than or Equal", "value": "lte"},
                    {"label": "Equal", "value": "eq"},
                    {"label": "Not Equal", "value": "neq"},
                    {"label": "Between", "value": "between"},
                ],
                default="gte",
                description="Numeric comparison used for intensity filtering",
                required=False,
                visible_when={"field": ["intensity"]},
            ),
            NodeParameter(
                name="intensity_threshold",
                label="Intensity Threshold",
                param_type="number",
                default=0.0,
                description="Numeric threshold for intensity filtering",
                required=False,
                visible_when={"field": ["intensity"]},
            ),
            NodeParameter(
                name="intensity_upper_threshold",
                label="Upper Threshold",
                param_type="number",
                default=1.0,
                description="Upper threshold used by the Between operator",
                required=False,
                visible_when={"field": ["intensity"]},
            ),
            NodeParameter(
                name="allow_empty",
                label="Allow Empty Result",
                param_type="boolean",
                default=False,
                description="Allow a zero-sample result. Hosted managed execution requires this option to remain off.",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="filter_values",
                label="Exact Values",
                param_type="string_list",
                default=None,
                description="Exact UI-selected labels, classes, or metadata values; null uses the text rule",
                required=False,
                category="advanced",
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Dataset",
                description="Dataset whose samples should be filtered",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Filtered Dataset",
                description="Dataset containing only selected samples",
            ),
        ],
        canonical_parameter_validator=_canonical_filter_parameters,
        managed_parameter_validator=_managed_filter_parameters,
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python that calls the same canonical filter authority."""
        params = self._resolve_params()
        X_expr = inputs.get("X", inputs.get("default", "input_data"))
        arguments = {
            "field": str(params.get("field", "sample_label")),
            "pattern": str(params.get("pattern", "")),
            "match_mode": str(params.get("match_mode", "contains")),
            "case_sensitive": bool(params.get("case_sensitive", False)),
            "invert": bool(params.get("invert", False)),
            "sample_table_column": str(params.get("sample_table_column", "")),
            "allow_empty": bool(params.get("allow_empty", False)),
            "intensity_metric": str(params.get("intensity_metric", "max")),
            "intensity_operator": str(params.get("intensity_operator", "gte")),
            "intensity_threshold": float(params.get("intensity_threshold", 0.0)),
            "intensity_upper_threshold": float(params.get("intensity_upper_threshold", 1.0)),
            "filter_values": explicit_filter_values(params.get("filter_values")),
            "node_id": self.node_id,
        }
        return [
            f"{indent}# --- Filter Samples ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import filter_samples_dataset",
            f"{indent}results[{self.node_id!r}] = filter_samples_dataset(",
            f"{indent}    {X_expr},",
            *(f"{indent}    {name}={value!r}," for name, value in arguments.items()),
            f"{indent})",
        ]

    async def execute(self, X: Any = None, **kwargs: Any) -> dict[str, Any]:
        """Filter dataset samples by labels or aligned sample metadata."""
        result = filter_samples_dataset(
            X,
            field=str(self.parameters.get("field", "sample_label")),
            pattern=str(self.parameters.get("pattern", "")),
            match_mode=str(self.parameters.get("match_mode", "contains")),
            case_sensitive=bool(self.parameters.get("case_sensitive", False)),
            invert=bool(self.parameters.get("invert", False)),
            sample_table_column=str(self.parameters.get("sample_table_column", "")),
            allow_empty=bool(self.parameters.get("allow_empty", False)),
            intensity_metric=str(self.parameters.get("intensity_metric", "max")),
            intensity_operator=str(self.parameters.get("intensity_operator", "gte")),
            intensity_threshold=float(self.parameters.get("intensity_threshold", 0.0)),
            intensity_upper_threshold=float(self.parameters.get("intensity_upper_threshold", 1.0)),
            filter_values=explicit_filter_values(self.parameters.get("filter_values")),
            node_id=self.node_id,
        )
        return {"default": result}


@register_node
class TrainTestSplitNode(Node):
    """
    Split dataset into training and test sets.

    Enables proper ML workflow with separate train/test evaluation.
    Supports statistical and reference-defined chemometric splitting strategies.

    Multi-output node with 6 output ports:
    - X_train: Training feature data
    - X_test: Test feature data
    - y_train: Training targets (if y provided)
    - y_test: Test targets (if y provided)
    - train_indices: Exact training-row membership
    - test_indices: Exact test-row membership
    """

    metadata = NodeMetadata(
        policy=NodePolicy(),
        node_type="data.train_test_split",
        category="data",
        label="Train/Test Split",
        description="Create one digest-bound train/test partition using statistical or chemometric designs",
        parameters=[
            NodeParameter(
                name="test_size",
                label="Test Size",
                param_type="number",
                default=0.2,
                min_value=0.01,
                max_value=0.99,
                max_value_reason="A split fraction must remain below 1 so the training partition is non-empty.",
                step=0.05,
                description="Fraction of data to use for testing (0.2 = 20%)",
                required=True,
                visible_when={
                    "split_method": ["random", "stratified", "sequential", "kennard_stone", "duplex", "spxy"]
                },
            ),
            NodeParameter(
                name="split_method",
                label="Split Method",
                param_type="select",
                options=[
                    {"label": "Random", "value": "random"},
                    {"label": "Stratified", "value": "stratified"},
                    {"label": "Sequential", "value": "sequential"},
                    {"label": "Group Holdout (selected groups)", "value": "group_holdout"},
                    {"label": "Kennard–Stone", "value": "kennard_stone"},
                    {"label": "DUPLEX", "value": "duplex"},
                    {"label": "SPXY (joint X–Y)", "value": "spxy"},
                ],
                default="random",
                description="Published or statistical rule used to construct the partition",
                required=True,
            ),
            NodeParameter(
                name="held_out_groups",
                label="Held-Out Groups",
                param_type="string_list",
                default=[],
                description=(
                    "Exact values of the bound grouping column to place in the test partition, "
                    "comma-separated (e.g. MP5). Every other group trains."
                ),
                required=False,
                visible_when={"split_method": ["group_holdout"]},
            ),
            NodeParameter(
                name="random_seed",
                label="Random Seed",
                param_type="number",
                default=42,
                min_value=0,
                max_value=4_294_967_295,
                max_value_reason="NumPy RandomState seeds are unsigned 32-bit integers.",
                step=1,
                description="Seed for reproducible random splits",
                required=False,
                visible_when={"split_method": ["random", "stratified"]},
            ),
            NodeParameter(
                name="distance_metric",
                label="Distance Metric",
                param_type="select",
                options=["euclidean", "mahalanobis"],
                default="euclidean",
                description="Sample dissimilarity for Kennard–Stone and DUPLEX",
                required=False,
                category="advanced",
                visible_when={"split_method": ["kennard_stone", "duplex"]},
            ),
            NodeParameter(
                name="n_components",
                label="PCA Components",
                param_type="number",
                default=0,
                min_value=0,
                max_value=10_000,
                max_value_reason="The runtime additionally limits components to the smaller data dimension.",
                step=1,
                description="Optional centered PCA projection before Kennard–Stone or DUPLEX distances (0 = raw X)",
                required=False,
                category="advanced",
                visible_when={"split_method": ["kennard_stone", "duplex"]},
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
            PortMetadata(
                name="train_indices",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Training Indices",
                description="Exact training-row membership in the input dataset",
            ),
            PortMetadata(
                name="test_indices",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Test Indices",
                description="Exact test-row membership in the input dataset",
            ),
        ],
        input_types=["SherpaDataset"],
        output_type="dict",  # Returns dict with multiple outputs
        canonical_parameter_validator=_canonical_split_parameters,
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for train/test splitting."""
        params = self._resolve_params()
        test_size = params.get("test_size", 0.2)
        split_method = params.get("split_method", "random")
        random_seed = params.get("random_seed", 42)
        distance_metric = params.get("distance_metric", "euclidean")
        n_components = params.get("n_components", 0)
        held_out_groups = params.get("held_out_groups", [])

        X_expr = inputs.get("X", inputs.get("default", "input_data"))
        y_expr = inputs.get("y")

        lines: list[str] = []
        lines.append(f"{indent}# --- Train/Test Split ({self.node_id}) ---")

        # Extract X
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.array(")
        lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")

        lines.append(f"{indent}_y_input = {y_expr}" if y_expr else f"{indent}_y_input = None")

        # One imported authority is used by generated and live execution.
        lines.append(f"{indent}from spectra_sherpa.app.services.dag.nodes.data.split_planner import (")
        lines.append(
            f"{indent}    bind_split_groups, bind_split_target, materialize_split_outputs, plan_train_test_split,"
        )
        lines.append(f"{indent})")
        lines.append(f"{indent}_y_data, _target_context = bind_split_target(_X_input, _y_input)")
        lines.append(f"{indent}_split_groups = bind_split_groups(_X_input)")
        lines.append(f"{indent}_split_plan = plan_train_test_split(")
        lines.append(f"{indent}    _X_data, _y_data,")
        lines.append(f"{indent}    method={split_method!r}, test_size={float(test_size)!r},")
        lines.append(f"{indent}    random_seed={int(random_seed)}, distance_metric={distance_metric!r},")
        lines.append(f"{indent}    n_components={int(n_components)},")
        lines.append(f"{indent}    groups=_split_groups, held_out_groups={list(held_out_groups)!r},")
        lines.append(f"{indent})")
        lines.append(f"{indent}results['{self.node_id}'] = materialize_split_outputs(")
        lines.append(
            f"{indent}    _X_input, _X_data, _y_data, _split_plan, "
            f"node_id={self.node_id!r}, target_context=_target_context, groups=_split_groups,"
        )
        lines.append(f"{indent})")
        lines.append(
            f'{indent}print(f"  Split: {{len(_split_plan.train_indices)}} train, '
            f'{{len(_split_plan.test_indices)}} test ({float(test_size) * 100:.0f}% test)")'
        )

        return lines

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> dict[str, Any]:
        """
        Split data into train and test sets.

        Args:
            X: Input dataset (SherpaDataset or SpectralResult)
            y: Optional target array for stratification
            **kwargs: Additional inputs (ignored)

        Returns:
            dict with keys: X_train, X_test, y_train (if y provided), y_test (if y provided)
        """
        test_size = self.parameters.get("test_size", 0.2)
        split_method = self.parameters.get("split_method", "random")
        random_seed = self.parameters.get("random_seed", 42)
        distance_metric = self.parameters.get("distance_metric", "euclidean")
        n_components = self.parameters.get("n_components", 0)
        held_out_groups = self.parameters.get("held_out_groups", [])

        X_ds = bind_X(
            X,
            missing_message="Missing required input: X (dataset)",
            dataset_error_message="X must be a SherpaDataset object",
            allow_array=True,
        )
        X_array = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_array, target_context = bind_split_target(X_ds, y)
        groups = bind_split_groups(X_ds)

        plan = plan_train_test_split(
            X_array,
            y_array,
            method=str(split_method),
            test_size=float(test_size),
            random_seed=int(random_seed),
            distance_metric=str(distance_metric),
            n_components=int(n_components),
            groups=groups,
            held_out_groups=held_out_groups if isinstance(held_out_groups, list) else [],
        )
        result = materialize_split_outputs(
            X_ds,
            X_array,
            y_array,
            plan,
            node_id=self.node_id,
            target_context=target_context,
            groups=groups,
        )
        logger.debug(
            "Train/Test Split: %s train, %s test samples (%.0f%% test)",
            plan.train_indices.size,
            plan.test_indices.size,
            float(test_size) * 100,
        )
        return cast(dict[str, Any], result)


@register_node
class AttachTargetNode(Node):
    """Attach target values to a dataset for supervised modeling.

    Use this when target data comes from a different source than X,
    or when you need to override the embedded target.
    """

    metadata = NodeMetadata(
        policy=NodePolicy(),
        node_type="data.attach_target",
        category="data",
        label="Attach Target",
        description="Attach target values to a dataset for supervised modeling",
        input_types=["SpectralDataset", "TargetMatrix", "SampleTable"],
        output_type="SpectralDataset",
        parameters=[
            NodeParameter(
                name="target_source",
                label="Target Source",
                param_type="select",
                options=[
                    {"label": "Connected Target", "value": "connected_target"},
                    {"label": "Sample Table Column", "value": "sample_table_column"},
                ],
                default="connected_target",
                description="Use a connected target or explicitly select an aligned sample-table column",
            ),
            NodeParameter(
                name="target_type",
                label="Target Type",
                param_type="select",
                options=["continuous", "categorical"],
                default="continuous",
                description="Type of target variable",
            ),
            NodeParameter(
                name="target_column",
                label="Target Column",
                param_type="text",
                default="",
                required=False,
                description="Exact sample-table column used when Target Source is Sample Table Column",
            ),
            NodeParameter(
                name="group_column",
                label="Validation Group Column",
                param_type="text",
                default="",
                required=False,
                description="Optional aligned grouping context; never appended to X or used as a predictor",
            ),
            NodeParameter(
                name="target_authority",
                label="Target Authority",
                param_type="json",
                default=None,
                required=False,
                category="internal",
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
                required=False,
                label="Target Values",
                description="Target values (1D or 2D array, or dataset with target)",
            ),
            PortMetadata(
                name="sample_table",
                type_ref="spectrasherpa://types/SampleTable/2.0",
                required=False,
                label="Sample Table",
                description=(
                    "Optional exact source-row identities, inclusion decisions, target identity, "
                    "and sample annotations produced by data.file_load"
                ),
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
        canonical_parameter_validator=_canonical_attach_target_parameters,
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python that calls the same canonical attachment authority."""
        X_expr = inputs.get("X", inputs.get("default", "input_data"))
        y_expr = inputs.get("y")
        sample_table_expr = inputs.get("sample_table")
        target_type = str(self._resolve_params().get("target_type", "continuous"))
        target_source = str(self._resolve_params().get("target_source", "connected_target"))
        target_column = str(self._resolve_params().get("target_column", ""))
        group_column = str(self._resolve_params().get("group_column", ""))
        target_authority = self._resolve_params().get("target_authority")
        return [
            f"{indent}# --- Attach Target ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_target_dataset",
            f"{indent}from spectra_sherpa.core.target_authority import admit_target_authority",
            f"{indent}results[{self.node_id!r}] = attach_target_dataset(",
            f"{indent}    {X_expr},",
            f"{indent}    {y_expr or 'None'},",
            f"{indent}    target_type={target_type!r},",
            f"{indent}    node_id={self.node_id!r},",
            f"{indent}    sample_table={sample_table_expr or 'None'},",
            f"{indent}    target_source={target_source!r},",
            f"{indent}    target_column={target_column!r},",
            f"{indent}    group_column={group_column!r},",
            f"{indent}    target_authority=admit_target_authority({target_authority!r}),",
            f"{indent})",
        ]

    async def execute(
        self,
        X: Any = None,
        y: Any = None,
        sample_table: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Attach target to dataset."""
        result = attach_target_dataset(
            X,
            y,
            target_type=str(self.parameters.get("target_type", "continuous")),
            node_id=self.node_id,
            sample_table=sample_table,
            target_source=str(self.parameters.get("target_source", "connected_target")),
            target_column=str(self.parameters.get("target_column", "")),
            group_column=str(self.parameters.get("group_column", "")),
            target_authority=admit_target_authority(self.parameters.get("target_authority")),
        )
        return {"default": result}


bind_stable_execution_contract(
    FilterSamplesNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.data.filter_samples",
    implementation_version="2.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="filters_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(dag_io_contracts, dag_meta_helpers, data_utils, sample_preparation),
    implementation_distributions=("numpy", "pandas"),
    runtime_requirements=(("numpy", "1.26.4"), ("pandas", "2.3.3")),
    input_rank_policy=DatasetRankPolicy.PRESERVES_ND,
)

bind_stable_execution_contract(
    TrainTestSplitNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.data.train_test_split",
    implementation_version="4.2.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="filters_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(dag_io_contracts, dag_meta_helpers, data_utils, split_planner),
    implementation_distributions=("numpy", "scikit-learn", "scipy"),
    runtime_requirements=(
        ("numpy", "1.26.4"),
        ("scikit-learn", "1.9.0"),
        ("scipy", "1.17.1"),
    ),
    deterministic=False,
    seed_parameter="random_seed",
    target_access="optional",
    citations=(
        "Kennard and Stone, Technometrics 11 (1969) 137-148, doi:10.1080/00401706.1969.10490666",
        "Snee, Technometrics 19 (1977) 415-428, doi:10.1080/00401706.1977.10489581",
        "Galvao et al., Talanta 67 (2005) 736-740, doi:10.1016/j.talanta.2005.03.025",
        "Pedregosa et al., Journal of Machine Learning Research 12 (2011) 2825-2830 (LeavePGroupsOut)",
    ),
    input_rank_policy=DatasetRankPolicy.PRESERVES_ND,
)

bind_stable_execution_contract(
    AttachTargetNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.data.attach_target",
    implementation_version="4.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(
        dag_io_contracts,
        dag_meta_helpers,
        sample_preparation,
        sample_table,
        supervision_binding,
    ),
    implementation_distributions=("numpy", "pandas"),
    runtime_requirements=(("numpy", "1.26.4"), ("pandas", "2.3.3")),
    target_access="required",
    input_rank_policy=DatasetRankPolicy.PRESERVES_ND,
)
