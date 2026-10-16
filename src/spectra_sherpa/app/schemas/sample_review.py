"""Only a scientist can submit these workflow-scoped decisions."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SampleReviewAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    run_id: int
    expected_latest_run_id: int
    expected_revision: int = Field(ge=0)
    expected_graph_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    action: Literal["mark", "unmark", "exclude", "restore", "exclude_test", "restore_test"]
    sample_ids: list[str] = Field(min_length=1, max_length=1024)
    acknowledge_post_review: bool = False
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Give a scientific reason for this decision.")
        return value.strip()

    @field_validator("sample_ids")
    @classmethod
    def exact_ids(cls, value: list[str]) -> list[str]:
        if (
            len(set(value)) != len(value)
            or any(not x or x != x.strip() for x in value)
            or sum(len(x.encode("utf-8")) for x in value) > 4096
        ):
            raise ValueError("Select unique exact IDs within the 4,096-byte filter limit.")
        return value
