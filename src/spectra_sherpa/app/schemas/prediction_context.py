"""Retained field meaning for prediction-only application to a new dataset."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PredictionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    role: Literal["prediction_only"] = Field(description="Predictions on new measurements, not an accuracy evaluation.")
    instrument_relation: Literal["different", "same", "unknown"]
    calibration_instrument: str | None = Field(max_length=128)
    prediction_instrument: str | None = Field(max_length=128)
    transfer_correction: Literal["none"] = Field(description="No instrument-transfer correction was applied.")
    held_out_accuracy_applies: Literal[False] = Field(
        description="The calibration held-out score does not establish accuracy on this prediction dataset."
    )


def retained_prediction_context(source_metadata: dict | None) -> dict | None:
    """Validated retained scope for Results and report exports, or None."""
    value = (source_metadata or {}).get("prediction_context")
    return None if value is None else PredictionContext.model_validate(value).model_dump(mode="json")
