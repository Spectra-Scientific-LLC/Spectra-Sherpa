"""
Pydantic schemas for workflow API requests/responses.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# Node schemas
class WorkflowNodeBase(BaseModel):
    """Base schema for workflow nodes."""

    node_id: str = Field(..., description="Unique node ID within workflow")
    node_type: str = Field(..., description="Node type (e.g., 'model.pca')")
    label: str | None = Field(None, description="Custom node label")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Node parameters")
    annotation: str | None = Field(None, description="Markdown annotation/comment for node")
    position_x: float | None = Field(None, description="Canvas X coordinate")
    position_y: float | None = Field(None, description="Canvas Y coordinate")


class WorkflowNodeCreate(WorkflowNodeBase):
    """Schema for creating a workflow node."""

    pass


class WorkflowNodeOut(WorkflowNodeBase):
    """Schema for workflow node response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    execution_order: int | None
    status: str
    created_at: datetime
    updated_at: datetime


# Edge schemas
class WorkflowEdgeBase(BaseModel):
    """Base schema for workflow edges."""

    from_node_id: str = Field(..., description="Source node ID")
    to_node_id: str = Field(..., description="Target node ID")
    from_output: str = Field(default="default", description="Output port name")
    to_input: str = Field(default="default", description="Input port name")


class WorkflowEdgeCreate(WorkflowEdgeBase):
    """Schema for creating a workflow edge."""

    pass


class WorkflowEdgeOut(WorkflowEdgeBase):
    """Schema for workflow edge response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    created_at: datetime


# Workflow tag schemas (defined before workflows to avoid forward reference)
class WorkflowTagBase(BaseModel):
    """Base schema for workflow tags."""

    name: str = Field(..., min_length=1, max_length=100)
    color: str | None = Field(None, description="Hex color code (e.g., #FF5733)")


class WorkflowTagCreate(WorkflowTagBase):
    """Schema for creating a workflow tag."""

    pass


class WorkflowTagUpdate(BaseModel):
    """Schema for updating a workflow tag."""

    name: str | None = Field(None, min_length=1, max_length=100)
    color: str | None = Field(None)


class WorkflowTagOut(WorkflowTagBase):
    """Schema for workflow tag response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime


# Workflow folder schemas (defined before workflows to avoid forward reference)
class WorkflowFolderBase(BaseModel):
    """Base schema for workflow folders."""

    name: str = Field(..., min_length=1, max_length=255)
    parent_id: int | None = Field(None, description="Parent folder ID for nesting")


class WorkflowFolderCreate(WorkflowFolderBase):
    """Schema for creating a workflow folder."""

    pass


class WorkflowFolderUpdate(BaseModel):
    """Schema for updating a workflow folder."""

    name: str | None = Field(None, min_length=1, max_length=255)
    parent_id: int | None = Field(None)


class WorkflowFolderOut(WorkflowFolderBase):
    """Schema for workflow folder response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime


# Workflow schemas
class WorkflowBase(BaseModel):
    """Base schema for workflows."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None)
    status: str = Field(default="draft", description="draft, active, or archived")
    canvas_state: dict[str, Any] | None = Field(None, description="UI state (zoom, pan, etc.)")
    notes: str | None = Field(None, description="Markdown notes/documentation for workflow")
    technique: str | None = Field(
        None, max_length=50, description="Spectral technique (e.g. FTIR, Raman, NMR, UV-Vis, NIR)"
    )
    sample_type: str | None = Field(
        None, max_length=100, description="Sample type (e.g. polymer blend, pharmaceutical tablet, wine)"
    )


class WorkflowCreate(WorkflowBase):
    """Schema for creating a workflow."""

    nodes: list[WorkflowNodeCreate] = Field(default_factory=list)
    edges: list[WorkflowEdgeCreate] = Field(default_factory=list)


class WorkflowUpdate(BaseModel):
    """Schema for updating a workflow."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None)
    status: str | None = Field(None)
    canvas_state: dict[str, Any] | None = Field(None)
    notes: str | None = Field(None, description="Markdown notes/documentation for workflow")
    technique: str | None = Field(None, max_length=50)
    sample_type: str | None = Field(None, max_length=100)
    folder_id: int | None = Field(None, description="Folder ID to organize workflow")
    nodes: list[WorkflowNodeCreate] | None = Field(None)
    edges: list[WorkflowEdgeCreate] | None = Field(None)
    tag_ids: list[int] | None = Field(None, description="Tag IDs to apply to workflow")
    change_description: str | None = Field(None, description="Optional description of changes for version history")


class WorkflowSummary(WorkflowBase):
    """Schema for workflow list response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    project_id: int | None = Field(None, description="Project owning this workflow")
    folder_id: int | None
    created_at: datetime
    updated_at: datetime
    last_executed_at: datetime | None
    integrity_hash: str | None = Field(None, description="SHA-256 integrity hash of workflow definition")
    node_count: int = Field(0, description="Number of nodes in workflow")
    edge_count: int = Field(0, description="Number of edges in workflow")
    tags: list[WorkflowTagOut] = Field(default_factory=list, description="Tags applied to workflow")
    folder: WorkflowFolderOut | None = Field(None, description="Folder containing workflow")


class WorkflowDetail(WorkflowSummary):
    """Schema for detailed workflow response."""

    nodes: list[WorkflowNodeOut] = Field(default_factory=list)
    edges: list[WorkflowEdgeOut] = Field(default_factory=list)


# Validation schemas
class WorkflowValidationIssue(BaseModel):
    """A single validation issue."""

    level: str = Field(..., description="'error' or 'warning'")
    node_id: str | None = Field(None, description="Node ID (null for graph-level)")
    port: str | None = Field(None, description="Port name if applicable")
    message: str = Field(..., description="Human-readable description")


class WorkflowValidationResponse(BaseModel):
    """Response from workflow validation endpoint."""

    is_valid: bool = Field(..., description="True if no errors (warnings OK)")
    issues: list[WorkflowValidationIssue] = Field(default_factory=list, description="Validation issues")
    error_count: int = Field(0, description="Number of errors")
    warning_count: int = Field(0, description="Number of warnings")


# Execution schemas
class WorkflowExecuteRequest(BaseModel):
    """Schema for workflow execution request."""

    initial_data: dict[str, Any] | None = Field(None, description="Initial data for source nodes (node_id -> data)")
    node_id: str | None = Field(None, description="Execute specific node only")


class WorkflowExecuteResponse(BaseModel):
    """Schema for workflow execution response."""

    workflow_id: int
    status: str = Field(..., description="Execution status")
    results: dict[str, Any] = Field(default_factory=dict, description="Node results (node_id -> result)")
    diagnostics: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="Per-node diagnostic measurements (node_id -> metrics)"
    )
    node_statuses: dict[str, str] = Field(default_factory=dict, description="Individual node statuses")
    executed_at: datetime
    error: str | None = Field(None, description="Error message if execution failed")
    integrity_hash: str | None = Field(None, description="SHA-256 integrity hash of executed workflow")


# Node library schemas
class NodeParameterInfo(BaseModel):
    """Schema for node parameter metadata."""

    name: str
    label: str
    param_type: str
    default: Any | None
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    options: list[str] | list[dict[str, Any]] | None = None  # Supports both string lists and {label, value} dicts
    description: str | None = None
    required: bool = False
    category: str | None = "basic"  # "basic" or "advanced" - controls Inspector display
    visible_when: dict[str, list[str]] | None = None  # Conditional visibility rules


class NodePortInfo(BaseModel):
    """Schema for node port metadata (input/output connectors)."""

    name: str = Field(..., description="Port identifier (e.g., 'X_train', 'y_class')")
    type_ref: str = Field(..., description="Type registry URI (e.g., 'spectrasherpa://types/SpectralDataset/1.0')")
    required: bool = Field(True, description="Whether this port must be connected")
    label: str = Field(..., description="Display label for UI")
    description: str | None = Field(None, description="Port description")
    variadic: bool = Field(False, description="True if port accepts multiple edges (list input)")


class NodeMetadataInfo(BaseModel):
    """Schema for node metadata."""

    node_type: str
    category: str
    label: str
    description: str
    parameters: list[NodeParameterInfo]
    input_types: list[str]  # Legacy - for backwards compatibility
    output_type: str  # Legacy - for backwards compatibility
    input_ports: list[NodePortInfo] | None = Field(None, description="Named input ports")
    output_ports: list[NodePortInfo] | None = Field(None, description="Named output ports")
    diagnostics: list[str] = Field(
        default_factory=list,
        description="Diagnostic metric keys emitted by this node at execution time",
    )
    help_url: str | None = Field(None, description="Link to external documentation")


class NodeLibraryResponse(BaseModel):
    """Schema for node library response."""

    nodes: list[NodeMetadataInfo] = Field(..., description="Available node types")
    total: int = Field(..., description="Total number of nodes")
    version: str = Field(default="1.0.0", description="Backend API version for cache invalidation")


# Trial execution schemas (for DetailView independent execution)
class TrialNodeDefinition(BaseModel):
    """Schema for a node in trial execution."""

    node_id: str = Field(..., description="Unique node ID")
    node_type: str = Field(..., description="Node type (e.g., 'model.pca')")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Node parameters")


class TrialEdgeDefinition(BaseModel):
    """Schema for an edge in trial execution."""

    from_node_id: str = Field(..., description="Source node ID")
    to_node_id: str = Field(..., description="Target node ID")
    from_output: str = Field(default="default", description="Output port name")
    to_input: str = Field(default="default", description="Input port name")


class TrialExecuteRequest(BaseModel):
    """
    Schema for trial execution request.

    Trial execution runs a node with trial parameters without persisting
    anything to the database. Used by DetailView for "Run Trial" functionality.
    """

    target_node_id: str = Field(..., description="The node to execute (with trial params)")
    trial_params: dict[str, Any] = Field(..., description="Trial parameters for target node")
    nodes: list[TrialNodeDefinition] = Field(..., description="All workflow nodes")
    edges: list[TrialEdgeDefinition] = Field(default_factory=list, description="Workflow edges")
    initial_data: dict[str, Any] | None = Field(None, description="Initial data for source nodes (node_id -> data)")
    project_id: int | None = Field(None, description="Project ID for validating custom algo (ualgo.*) ownership")


class TrialExecuteResponse(BaseModel):
    """Schema for trial execution response."""

    target_node_id: str
    status: str = Field(..., description="Execution status: completed or error")
    result: dict[str, Any] | None = Field(None, description="Execution result for target node")
    error: str | None = Field(None, description="Error message if execution failed")


# Workflow version history schemas
class WorkflowVersionSummary(BaseModel):
    """Schema for workflow version list item."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    version_number: int
    created_at: datetime
    created_by: int
    change_description: str | None


class WorkflowVersionDetail(WorkflowVersionSummary):
    """Schema for detailed workflow version with full snapshot."""

    snapshot: dict[str, Any] = Field(..., description="Complete workflow state snapshot")


class WorkflowVersionListResponse(BaseModel):
    """Schema for list of workflow versions."""

    versions: list[WorkflowVersionSummary] = Field(..., description="Version history")
    total: int = Field(..., description="Total number of versions")
