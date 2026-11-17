"""Closed projections of existing retained classification and population authorities."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.services.dag.nodes.classification.core_utils import (
    CLASSIFICATION_METRIC_NAMES,
    flatten_classification_metrics_contract,
)
from spectra_sherpa.app.services.run_output_retention import read_output
from spectra_sherpa.app.services.run_population_summary import SCOPE, retained_population_summary

Text = Annotated[str, Field(max_length=256)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ClassificationFact(ClosedModel):
    node_id: Text
    source_port: Text
    primary_split: Literal["train", "cv", "test"]
    n_classes: int = Field(gt=0)
    splits: dict[str, dict[str, float]]


class ReadGap(ClosedModel):
    node_id: Text
    port: Text
    reason: Literal["Retained classification evidence is unavailable or unverified."]


class RetainedOutputFact(ClosedModel):
    node_id: Text
    port: Text
    state: Literal["exact", "reduced", "missing", "unverified"]
    sha256: Digest | None
    byte_count: int | None


class PopulationFact(ClosedModel):
    node_id: Text
    availability: Literal["available", "unavailable"]
    source_count: int | None = Field(default=None, ge=0)
    active_count: int | None = Field(default=None, ge=0)
    source_excluded_count: int | None = Field(default=None, ge=0)
    workflow_excluded_count: int | None = Field(default=None, ge=0)
    excluded_count: int | None = Field(default=None, ge=0)


class RetainedContext(ClosedModel):
    graph_digest: Digest | None
    workflow_id: int | None
    retention_qualification: Literal["unverified", "qualified"]
    outputs: list[RetainedOutputFact] = Field(max_length=128)
    population_scope: str
    source_inventory_notes: list[Text]
    source_populations: list[PopulationFact] = Field(max_length=32)


def retained_context(run, evidence: RunEvidence, definition_reader) -> RetainedContext:
    population = retained_population_summary(run, definition_read=definition_reader)
    return RetainedContext(
        graph_digest=run.integrity_hash,
        workflow_id=run.workflow_id,
        retention_qualification=evidence.qualification,
        outputs=[
            RetainedOutputFact(
                node_id=node, port=port, state=item.state, sha256=item.sha256, byte_count=item.byte_count
            )
            for node, ports in evidence.outputs.items()
            for port, item in ports.items()
            if not port.startswith("_")
        ],
        population_scope=SCOPE,
        source_inventory_notes=[row["value"] for row in population["rows"] if row["label"] == "Source inventory"],
        source_populations=[
            PopulationFact(**{key: source[key] for key in PopulationFact.model_fields if key in source})
            for source in population["sources"]
        ],
    )


def _classification_fact(node, port, value):
    if (
        type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or value.get("task_type") != "classification"
    ):
        return None
    splits = value.get("splits")
    if not isinstance(splits, dict) or not splits or not set(splits) <= {"train", "cv", "test"}:
        raise ValueError("Unsupported retained classification population")
    if value.get("primary_split") not in splits or type(value.get("n_classes")) is not int:
        raise ValueError("Retained classification scope is incomplete")
    for values in splits.values():
        if not isinstance(values, dict):
            raise ValueError("Invalid retained classification statistics")
        for name in CLASSIFICATION_METRIC_NAMES:
            metric = values.get(name)
            if metric is not None and (
                type(metric) not in (int, float) or not math.isfinite(metric) or not 0 <= metric <= 1
            ):
                raise ValueError("Invalid retained classification statistic")
    flat = flatten_classification_metrics_contract(value)
    projected = {
        split: {name: flat[f"{split}_{name}"] for name in CLASSIFICATION_METRIC_NAMES if f"{split}_{name}" in flat}
        for split in splits
    }
    if any(not metrics for metrics in projected.values()):
        raise ValueError("Retained classification split has no supported statistics")
    return ClassificationFact(
        node_id=node,
        source_port=port,
        primary_split=value["primary_split"],
        n_classes=value["n_classes"],
        splits=projected,
    )


def classification_facts(run, evidence: RunEvidence):
    """Read only exact canonical contracts; never infer role from an accuracy key."""
    records, gaps = [], []
    if evidence.qualification != "qualified":
        return records, gaps
    for node, ports in evidence.outputs.items():
        for port, item in ports.items():
            if port not in {"metrics", "classification_metrics", "default"}:
                continue
            if item.state != "exact" or item.storage != "file" or not item.byte_count:
                continue
            if item.byte_count > 16 * 1024 * 1024:
                raise ValueError("Retained classification output exceeds inspection budget")
            try:
                value = read_output(run.user_id, item)
            except (ValueError, OSError, TypeError):
                gaps.append(
                    ReadGap(
                        node_id=node, port=port, reason="Retained classification evidence is unavailable or unverified."
                    )
                )
                continue
            if not isinstance(value, dict):
                continue
            candidates = [(port, value)] + [
                (f"{port}/{key}", value[key])
                for key in ("metrics", "classification_metrics")
                if isinstance(value.get(key), dict)
            ]
            for locator, candidate in candidates:
                record = _classification_fact(node, locator, candidate)
                if record is not None:
                    records.append(record)
                    if len(records) > 128:
                        raise ValueError("Too many retained classification records")
    return records, gaps
