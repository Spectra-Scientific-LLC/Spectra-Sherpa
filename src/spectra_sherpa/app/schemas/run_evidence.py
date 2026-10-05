"""Versioned retention declarations, independent of execution outcome."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OutputEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["exact", "reduced", "missing", "unverified"] = "unverified"
    reason: str | None = None
    role: str | None = None
    storage: Literal["file"] | None = None
    sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    byte_count: int | None = Field(None, ge=0)
    format_version: Literal[1] | None = None

    @model_validator(mode="after")
    def require_explanation(self):
        if self.state != "exact" and not (self.reason or "").strip():
            raise ValueError("Non-exact evidence requires a specific explanation")
        if self.storage == "file" and (self.sha256 is None or self.byte_count is None or self.format_version != 1):
            raise ValueError("File evidence requires checksum, byte count and supported format")
        return self


class EvidenceGap(BaseModel):
    """One scientist-facing omission from a durable run record."""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    output: str
    role: str | None = None
    state: Literal["reduced", "missing", "unverified"]
    category: Literal["reduced", "session_only", "storage_limit", "unavailable", "unverified"]
    reason: str
    recovery: str


def _gap_category(item: OutputEvidence) -> tuple[str, str]:
    reason = (item.reason or "Durable evidence is incomplete.").strip()
    lowered = reason.lower()
    if item.state == "reduced":
        return "reduced", "Inspect the retained preview or rerun to recreate the complete output."
    if item.state == "unverified":
        return "unverified", "Rerun this workflow to create a qualified durable record."
    if "private runtime output excluded by policy" in lowered:
        return "session_only", "Rerun the workflow to recreate this session-only output."
    if any(token in lowered for token in ("budget", "quota", "free space", "storage", "too large")):
        return (
            "storage_limit",
            "Increase retained-output capacity or reduce the output size, then rerun the workflow.",
        )
    return "unavailable", "Rerun the workflow and inspect the new saved run."


class RunEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    qualification: Literal["unverified", "qualified"] = "unverified"
    reason: str | None = "Result retention has not been qualified for this run."
    outputs: dict[str, dict[str, OutputEvidence]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_inventory(self):
        if self.qualification == "qualified" and not any(self.outputs.values()):
            raise ValueError("Qualified evidence requires an explicit output inventory")
        return self

    def gaps(self) -> list[EvidenceGap]:
        """Return a stable node/output inventory for every non-exact value."""

        gaps: list[EvidenceGap] = []
        for node_id in sorted(self.outputs):
            for output in sorted(self.outputs[node_id]):
                item = self.outputs[node_id][output]
                if item.state == "exact":
                    continue
                category, recovery = _gap_category(item)
                gaps.append(
                    EvidenceGap(
                        node_id=node_id,
                        output=output,
                        role=item.role,
                        state=item.state,
                        category=category,
                        reason=(item.reason or "Durable evidence is incomplete.").strip(),
                        recovery=recovery,
                    )
                )
        if not gaps and self.qualification != "qualified":
            gaps.append(
                EvidenceGap(
                    node_id="__workflow__",
                    output="retention",
                    state="unverified",
                    category="unverified",
                    reason=(self.reason or "Historical evidence completeness is unavailable or unsupported.").strip(),
                    recovery="Rerun this workflow to create a qualified durable record.",
                )
            )
        return gaps
