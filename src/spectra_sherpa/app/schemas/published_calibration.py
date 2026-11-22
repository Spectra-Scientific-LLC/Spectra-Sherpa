"""Public sample-result semantics; synthetic demonstrations are not performance claims."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PublishedCalibration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    sample_id: str
    title: str
    source: str
    target: str
    units: str
    training_count: int = Field(gt=0)
    evaluation_count: int = Field(gt=0)
    evaluation_role: Literal["held_out"]
    rmse: float = Field(
        ge=0,
        description="Root mean squared prediction error in target units for this fixture and data regime.",
    )
    data_regime: Literal["idealized_noiseless_synthetic"] = Field(
        description="Exactly proportional synthetic signals without measurement noise or instrument variation."
    )
    expected_zero_error: Literal[True] = Field(
        description="Zero error is expected for this constructed fixture; it is not evidence of real-world accuracy."
    )
    real_data_performance_claim: Literal[False] = Field(
        description="This sample result makes no claim about performance on real measurements."
    )
    nodes: list[str] = Field(min_length=1, max_length=10)
