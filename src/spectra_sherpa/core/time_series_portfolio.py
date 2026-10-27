"""Versioned, immutable OES selection contract for v0.6.5.

References require application admission before loading. No filesystem paths,
implicit wafer selection, or averaging are carried in a source selection.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Positive = Annotated[int, Field(gt=0, strict=True)]


class FrozenContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AcquisitionInterval(FrozenContract):
    """Inclusive, one-based original acquisition numbers; never plot indices."""

    first: Positive
    last: Positive
    phase: str = Field(min_length=1)
    cycle: Positive | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.last < self.first:
            raise ValueError("Acquisition range is reversed")
        return self


class StepPartition(FrozenContract):
    experiment_id: Positive
    file_id: Positive
    process_file_id: Positive
    source_sha256: Digest
    process_sha256: Digest
    oes_dictionary_sha256: Digest
    process_dictionary_sha256: Digest
    segmentation_sha256: Digest
    day: date
    wafer: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    recipe: str = Field(min_length=1)
    intervals: tuple[AcquisitionInterval, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def disjoint(self):
        previous = 0
        for interval in self.intervals:
            if interval.first <= previous:
                raise ValueError("Acquisition intervals must be ordered and non-overlapping")
            previous = interval.last
        return self


class TimeSeriesPortfolio(FrozenContract):
    schema_version: Literal["spectrasherpa-time-series-portfolio/1"] = "spectrasherpa-time-series-portfolio/1"
    project_id: Positive
    partitions: tuple[StepPartition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_membership(self):
        occupied: dict[tuple, list[tuple[int, int]]] = {}
        for part in self.partitions:
            key = (part.experiment_id, part.file_id, part.asset_id)
            ranges = occupied.setdefault(key, [])
            for interval in part.intervals:
                if any(interval.first <= end and interval.last >= start for start, end in ranges):
                    raise ValueError("A source acquisition cannot occur twice in one portfolio")
                ranges.append((interval.first, interval.last))
        return self

    def sha256(self) -> str:
        data = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(data.encode()).hexdigest()


class AveragingMode(str, Enum):
    STEP = "step"
    PHASE = "phase_across_cycles"
    CYCLE_PHASE = "cycle_phase"


class AveragingParameters(FrozenContract):
    """Explicit downstream operation, deliberately outside the source receipt."""

    mode: AveragingMode
    statistic: Literal["mean", "median"] = "mean"
    weighting: Literal["equal_acquisition"] = "equal_acquisition"
    transition_trim_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)

    def group_key(self, partition: StepPartition, interval: AcquisitionInterval) -> tuple:
        identity = (
            partition.experiment_id,
            partition.file_id,
            partition.asset_id,
            partition.day.isoformat(),
            partition.wafer,
            partition.step_id,
        )
        if self.mode == AveragingMode.STEP:
            return identity
        if self.mode == AveragingMode.PHASE:
            return (*identity, interval.phase)
        # Noncyclic or pre-first-cycle observations remain explicitly unassigned.
        # They must not be dropped or silently assigned to cycle 1.
        return (*identity, interval.cycle, interval.phase)


def acquisition_batches(partition: StepPartition, *, batch_rows: int = 256):
    """Bounded original row slices; callers must admit and verify source hashes.

    Yields (interval, zero-based half-open slice). No decoding or averaging occurs.
    Partition boundaries remain intact, regardless of total collection size.
    """
    if isinstance(batch_rows, bool) or not isinstance(batch_rows, int) or not 1 <= batch_rows <= 4096:
        raise ValueError("batch_rows must be an integer between 1 and 4096")
    for interval in partition.intervals:
        for start in range(interval.first - 1, interval.last, batch_rows):
            yield interval, slice(start, min(start + batch_rows, interval.last))
