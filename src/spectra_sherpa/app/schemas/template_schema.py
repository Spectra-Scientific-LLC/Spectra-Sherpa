"""
Pydantic schema models for declarative YAML workflow templates.

These models define the canonical schema for template files stored in
``spectra_sherpa/data/templates/*.yaml``. The loader validates every
template against these models at load time using ``model_validate()``.

Schema version 1 — introduced in the YAML template migration.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from spectra_sherpa.app.lib.data_roles import normalize_modalities

# ---------------------------------------------------------------------------
# Enums as Literal unions (kept inline for single-file clarity)
# ---------------------------------------------------------------------------

DataRoleType = Literal[
    "X_spectra",
    "X_features",
    "X_hsi",
    "Y_reference",
    "class_labels",
    "wavelength_axis",
    "validation_set",
    "sample_metadata",
    "background_spectrum",
]

BindingMode = Literal[
    "embedded",  # target column(s) in the same file as X
    "separate_source",  # needs its own explicit canonical source node
    "port_output",  # wired from an upstream node output
]

TargetType = Literal["continuous", "categorical"]
DataModalityType = Literal["spectra", "features", "hsi"]
ExampleDatasetSource = Literal["eigenvector", "sklearn", "oes", "synthetic"]


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
    technique_match: Literal["advisory", "required"] | None = None
    accepted_data_roles: list[DataRoleType] | None = None
    is_time_series: bool | None = None


class TemplateExampleBinding(BaseModel):
    """Template-only selector for materializing a bundled reference dataset.

    This selector is never persisted as a workflow-node parameter. Template
    instantiation resolves it to the same exact ``data.file_load`` identity
    used for scientist-owned files.
    """

    source: ExampleDatasetSource
    dataset_name: str = Field(..., min_length=1)
    selected_target: str | None = Field(None, min_length=1)
    target_type: TargetType | None = None


class TemplateNode(BaseModel):
    """A single node in a template DAG."""

    node_id: str
    node_type: str
    label: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    example_binding: TemplateExampleBinding | None = None
    position_x: int | float = 0
    position_y: int | float = 0


class TemplateEdge(BaseModel):
    """A directed edge between two nodes in a template DAG."""

    from_node_id: str
    to_node_id: str
    from_output: str = "default"
    to_input: str = "default"


class CertifiedDataset(BaseModel):
    """A (source, name) pair that has been end-to-end tested for this template."""

    source: str = Field(..., description="Dataset source: synthetic | eigenvector | sklearn | oes")
    name: str = Field(..., description="Dataset name within that source catalog")


class TemplateManagedCandidate(BaseModel):
    """Explicit persisted DAG used as the managed optimization baseline.

    This is a second visible workflow sheet, not a projection inferred from the
    scientist-facing workflow.  Keeping the complete node and edge identity in
    the template makes the saved DAG the authority presented to Harness.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["spectra-managed-candidate-template/1"]
    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    scientist_source_node_id: str = Field(..., min_length=1)
    source_node_id: str = Field(..., min_length=1)
    nodes: list[TemplateNode] = Field(..., min_length=2)
    edges: list[TemplateEdge] = Field(..., min_length=1)
    canvas_state: dict[str, Any] = Field(default_factory=dict)


class TemplateCanonicalProject(BaseModel):
    """Closed project-level contract for a canonical starter project."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["spectra-canonical-starter-project/1"]
    scientific_objective: Literal["quantitative_regression"]
    qualification_dataset_ids: list[str] = Field(..., min_length=1)
    managed_candidate: TemplateManagedCandidate


class TemplateData(BaseModel):
    """The inner ``template_data`` payload of a workflow template."""

    nodes: list[TemplateNode]
    edges: list[TemplateEdge]
    canvas_state: dict[str, Any] = Field(default_factory=dict)
    data_roles: dict[str, TemplateDataRole] = Field(default_factory=dict)
    certified_datasets: list[CertifiedDataset] = Field(
        default_factory=list,
        description=(
            "Datasets that have passed end-to-end execution tests for this template. "
            "When non-empty, the wizard dropdown is restricted to these entries."
        ),
    )
    canonical_project: TemplateCanonicalProject | None = Field(
        None,
        description=(
            "Optional closed project contract that persists a separate, visible managed-candidate "
            "workflow alongside the scientist-facing workflow."
        ),
    )


# ---------------------------------------------------------------------------
# Top-level file models
# ---------------------------------------------------------------------------


TemplateStatus = Literal["ready", "pending_data", "pending_qualification", "wip"]


class TemplateFile(BaseModel):
    """Schema for a single ``{slug}.yaml`` template file."""

    schema_version: int = Field(..., description="Must be 1 for current schema")
    name: str
    slug: str
    description: str
    category: str
    is_active: bool = True
    status: TemplateStatus
    status_detail: str | None = Field(None, min_length=1, max_length=512)
    data_modalities: list[DataModalityType] = Field(default_factory=lambda: ["spectra"])
    template_data: TemplateData

    @model_validator(mode="after")
    def _require_exact_status_detail(self) -> "TemplateFile":
        if self.status == "ready" and self.status_detail is not None:
            raise ValueError("ready templates must not declare status_detail")
        if self.status != "ready" and (
            self.status_detail is None
            or not self.status_detail.strip()
            or self.status_detail != self.status_detail.strip()
        ):
            raise ValueError(f"{self.status} templates must declare status_detail")
        return self

    @field_validator("data_modalities", mode="before")
    @classmethod
    def _normalize_data_modalities(cls, value: Any) -> list[DataModalityType]:
        return normalize_modalities(value)  # type: ignore[return-value]


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
