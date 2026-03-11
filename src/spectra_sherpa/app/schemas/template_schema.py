"""
Pydantic schema models for declarative YAML workflow templates.

These models define the canonical schema for template files stored in
``spectra_sherpa/data/templates/*.yaml``. The loader validates every
template against these models at load time using ``model_validate()``.

Schema version 1 — introduced in the YAML template migration.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums as Literal unions (kept inline for single-file clarity)
# ---------------------------------------------------------------------------

DataRoleType = Literal[
    "X_spectra",
    "Y_reference",
    "class_labels",
    "wavelength_axis",
    "validation_set",
    "sample_metadata",
    "background_spectrum",
]

BindingMode = Literal[
    "embedded",  # target column(s) in the same file as X
    "separate_source",  # needs its own data.source node
    "port_output",  # wired from an upstream node output
]

TargetType = Literal["continuous", "categorical"]


# ---------------------------------------------------------------------------
# Template sub-models
# ---------------------------------------------------------------------------


class TemplateDataRole(BaseModel):
    """Scientific data role within a chemometrics template.

    Describes *what* data a template needs, *where* it connects, and *how*
    the wizard should prompt the user to supply it.
    """

    role_type: DataRoleType
    node_binding: str = Field(..., description="node_id that receives this data")
    required: bool = True
    binding_mode: BindingMode = "embedded"
    target_type: TargetType | None = Field(None, description="For Y_reference / class_labels")
    connects_to_port: str | None = Field(None, description="Specific input port name (e.g. 'y', 'X')")
    description: str = ""
    accepted_techniques: list[str] | None = None


class TemplateNode(BaseModel):
    """A single node in a template DAG."""

    node_id: str
    node_type: str
    label: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    position_x: int | float = 0
    position_y: int | float = 0


class TemplateEdge(BaseModel):
    """A directed edge between two nodes in a template DAG."""

    from_node_id: str
    to_node_id: str
    from_output: str = "default"
    to_input: str = "default"


class TemplateData(BaseModel):
    """The inner ``template_data`` payload of a workflow template."""

    nodes: list[TemplateNode]
    edges: list[TemplateEdge]
    canvas_state: dict[str, Any] = Field(default_factory=dict)
    data_roles: dict[str, TemplateDataRole] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Top-level file models
# ---------------------------------------------------------------------------


TemplateStatus = Literal["ready", "wip"]


class TemplateFile(BaseModel):
    """Schema for a single ``{slug}.yaml`` template file."""

    schema_version: int = Field(..., description="Must be 1 for current schema")
    name: str
    slug: str
    description: str
    category: str
    is_active: bool = True
    status: TemplateStatus = "ready"
    template_data: TemplateData


class TemplateCategoryEntry(BaseModel):
    """Presentation metadata for a single template category."""

    label: str
    icon: str
    display_order: int
    featured: bool = False


class TemplateCategoryFile(BaseModel):
    """Schema for the ``_categories.yaml`` file."""

    schema_version: int = Field(..., description="Must be 1 for current schema")
    categories: dict[str, TemplateCategoryEntry]
