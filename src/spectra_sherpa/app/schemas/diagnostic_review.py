"""References to exact scientific evidence; these fields carry no numerical authority."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DiagnosticReviewReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    workflow_id: int = Field(gt=0)
    run_id: int = Field(gt=0)
    node_id: str = Field(min_length=1, max_length=255)
    graph_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_revision: int = Field(ge=0)
    selected_ids: list[str] = Field(default_factory=list, max_length=1024)
    select_all: bool = False
    response_index: int = Field(default=0, ge=0, le=15)
    variable_ids: list[str] = Field(default_factory=list, max_length=40)
    baseline_run_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def exact_selection(self):
        if self.select_all == bool(self.selected_ids):
            raise ValueError("Choose exact observations or the whole retained cohort.")
        for values in (self.selected_ids, self.variable_ids):
            if len(set(values)) != len(values) or any(not x or len(x) > 512 for x in values):
                raise ValueError("Selection identities must be unique and bounded.")
            if sum(len(x.encode("utf-8")) for x in values) > 4096:
                raise ValueError("Narrow this selection to the 4096-byte identity limit.")
        return self


class SavedPlsdaDiagnosticReference(BaseModel):
    """Identity-only request for exact saved-classifier diagnostic evidence."""

    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["saved_plsda"]
    artifact_uid: str = Field(min_length=1, max_length=255)
    workflow_id: int = Field(gt=0)
    run_id: int = Field(gt=0)
    node_id: str = Field(min_length=1, max_length=255)
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_ids: list[str] = Field(default_factory=list, max_length=1024)
    select_all: bool = False
    variable_ids: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def exact_selection(self):
        if self.select_all == bool(self.selected_ids):
            raise ValueError("Choose exact observations or the whole saved calibration cohort.")
        for values in (self.selected_ids, self.variable_ids):
            if len(set(values)) != len(values) or any(not x or len(x) > 512 for x in values):
                raise ValueError("Selection identities must be unique and bounded.")
            if sum(len(x.encode("utf-8")) for x in values) > 4096:
                raise ValueError("Narrow this selection to the 4096-byte identity limit.")
        return self


class SavedApplicationDiagnosticReference(BaseModel):
    """An exact retained application row, with no browser-supplied statistics."""

    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["saved_application"]
    artifact_uid: str = Field(min_length=1, max_length=255)
    workflow_id: int = Field(gt=0)
    run_id: int = Field(gt=0)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_index: int = Field(ge=0)


class SavedRunApplicationDiagnosticReference(BaseModel):
    """Exact retained per-file prediction screen from an owned operational run."""

    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["saved_run_application"]
    workflow_id: int = Field(gt=0)
    run_id: int = Field(gt=0)
    node_id: str = Field(min_length=1, max_length=255)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_index: int = Field(ge=0)


class SavedModelQualificationReference(BaseModel):
    """Identity-only reference; the Advisor resolves all values on the server."""

    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["saved_model_qualification"]
    artifact_uid: str = Field(min_length=1, max_length=255)
    workflow_id: int = Field(gt=0)
    run_id: int = Field(gt=0)
    dossier_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_view_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    response_index: int = Field(default=0, ge=0, le=15)
