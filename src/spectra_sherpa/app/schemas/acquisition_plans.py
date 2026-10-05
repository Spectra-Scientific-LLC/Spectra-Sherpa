"""Complete contracts for multi-well experiment acquisition plans."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Scalar = str | int | float | bool | None
Identifier = Annotated[str, Field(min_length=1, max_length=100)]


class PlannedSample(BaseModel):
    """Acquisition-intent snapshot, optionally linked to its source specimen."""

    model_config = ConfigDict(extra="forbid")

    sample_id: Identifier
    source_specimen_uid: UUID | None = None
    name: str = Field(default="", max_length=255)
    sample_type: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


class MixtureComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: Identifier
    amount: float
    unit: str = Field(..., min_length=1, max_length=20)


class PlannedMixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mixture_id: Identifier
    name: str | None = Field(default=None, max_length=255)
    basis: str = Field(default="volume", min_length=1, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)
    components: list[MixtureComponent] = Field(default_factory=list, max_length=100)


class PlannedFactor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor_id: Identifier
    name: str = Field(..., min_length=1, max_length=100)
    scope: str = Field(..., min_length=1, max_length=20)
    factor_type: str = Field(..., min_length=1, max_length=20)
    unit: str | None = Field(default=None, max_length=50)
    levels: list[Scalar] = Field(default_factory=list, max_length=1000)


class AcquisitionPlanWell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    well_position: str = Field(..., min_length=2, max_length=10)
    planned_sample_label: str | None = Field(default=None, max_length=255)
    sample_id: str | None = Field(default=None, max_length=100)
    mixture_id: str | None = Field(default=None, max_length=100)
    factor_values: dict[str, Scalar] = Field(default_factory=dict)


class AcquisitionOrderStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence_order: int = Field(..., ge=0)
    factor_id: Identifier
    level_value: str = Field(..., max_length=100)
    path: str | None = Field(default=None, max_length=255)
    batch: int | None = None
    file_count: int | None = Field(default=None, ge=0)


class AcquisitionMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence_order: int = Field(..., ge=0)
    filename: str | None = Field(default=None, max_length=255)
    folder: str | None = Field(default=None, max_length=255)
    timestamp: int | None = None
    date: str | None = Field(default=None, max_length=50)
    batch: int | None = None
    sample_id: str | None = Field(default=None, max_length=100)
    well_position: str | None = Field(default=None, max_length=10)
    special: str | None = Field(default=None, max_length=100)
    factor_values: dict[str, Scalar] = Field(default_factory=dict)


class AcquisitionMatching(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: dict[str, object] = Field(default_factory=dict)
    matches: list[AcquisitionMatch] = Field(default_factory=list, max_length=100000)


class AcquisitionPlanDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["spectrasherpa-acquisition-plan/3"] = "spectrasherpa-acquisition-plan/3"
    plate_format_id: Literal["plate-96"] = "plate-96"
    samples: list[PlannedSample] = Field(default_factory=list, max_length=100000)
    mixtures: list[PlannedMixture] = Field(default_factory=list, max_length=10000)
    factors: list[PlannedFactor] = Field(default_factory=list, max_length=1000)
    wells: list[AcquisitionPlanWell] = Field(default_factory=list, max_length=96)
    acquisition_order: list[AcquisitionOrderStep] = Field(default_factory=list, max_length=100000)
    matching: AcquisitionMatching = Field(default_factory=AcquisitionMatching)


class AcquisitionPlanUpdate(BaseModel):
    """Partial aggregate replacement; omitted sections retain their current value."""

    model_config = ConfigDict(extra="forbid")

    plate_format_id: Literal["plate-96"] | None = None
    expected_revision: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    samples: list[PlannedSample] | None = Field(default=None, max_length=100000)
    mixtures: list[PlannedMixture] | None = Field(default=None, max_length=10000)
    factors: list[PlannedFactor] | None = Field(default=None, max_length=1000)
    wells: list[AcquisitionPlanWell] | None = Field(default=None, max_length=96)
    acquisition_order: list[AcquisitionOrderStep] | None = Field(default=None, max_length=100000)
    matching: AcquisitionMatching | None = None


class AcquisitionPlanOut(AcquisitionPlanDocument):
    experiment_id: int
    plate_format_label: str
    capacity: int
    revision: str


class AcquisitionPlanPresetOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset_key: str
    name: str
    description: str | None
    is_default: bool
    settings: dict


class WorkbenchPreferencesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_plate_format_id: Literal["plate-96"]


class WorkbenchPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_plate_format_id: Literal["plate-96"]
