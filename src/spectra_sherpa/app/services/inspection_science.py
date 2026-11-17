"""Closed, bounded projections of existing public retained scientific facts."""

from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, String, cast, func, select

from spectra_sherpa.app.models.data_egress import DataType
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.services.inspection_readers import authorize_policy
from spectra_sherpa.app.services.inspection_runs import authorize_run_reader
from spectra_sherpa.app.services.tools.builtin.runs import RunArguments
from spectra_sherpa.sdk.validate import REGRESSION_METRIC_FIELDS

MAX_FIELD_CHARS = 256 * 1024
MAX_FILE_READ_BYTES = 64 * 1024 * 1024
Text = Annotated[str, Field(max_length=256)]
Number = Annotated[float | int, Field(allow_inf_nan=False)]


class ScientificArguments(RunArguments):
    pass


class DiagnosticArguments(ScientificArguments):
    node_id: str = Field(min_length=1, max_length=128)
    response_index: int = Field(default=0, ge=0, le=127)


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class UnitContext(ClosedModel):
    state: Literal["recorded", "missing", "ambiguous"]
    value: Text | None


class RegressionFact(ClosedModel):
    node_id: Text
    source_port: Text
    target: Text
    role: Literal["calibration", "cross_validation", "held_out_test", "unqualified_evaluation"]
    units: Text
    unit_context: UnitContext
    bias_definition: Literal["predicted_minus_reference"]
    registry_version: Text
    metrics: dict[str, Number | None]
    reference_min: Number | None
    reference_max: Number | None
    reference_sd: Number | None
    reference_mean: Number | None


class MetricSummary(ClosedModel):
    run_id: int
    evidence_identity: str
    availability: Literal["available", "unavailable"]
    reason: str | None
    regression_results: list[RegressionFact] = Field(max_length=128)
    limitations: list[str]


class DiagnosticFact(ClosedModel):
    value: Number | None
    meaning: Text
    population: Text | None = None
    units: Text | None = None


class DiagnosticResponse(ClosedModel):
    index: int
    name: Text | None
    units: Text | None
    unit_context: UnitContext


class DiagnosticSummary(ClosedModel):
    run_id: int
    node_id: Text
    evidence_identity: str
    availability: Literal["available", "unavailable"]
    reason: str | None
    model_kind: Literal["pca", "pls"] | None
    response: DiagnosticResponse | None
    populations: dict[str, dict[str, int]]
    facts: dict[str, DiagnosticFact]
    limitations: list[str]


async def _snapshot(session, identity, run_id):
    # Never load full ORM rows or decode unbounded historical JSON.
    names = (
        "id",
        "user_id",
        "project_id",
        "workflow_id",
        "status",
        "integrity_hash",
        "evidence_completeness",
        "params_snapshot",
        "source_metadata",
        "node_statuses",
    )
    columns = {name: getattr(ExecutionRun, name) for name in names}
    query = select(
        *[
            (
                func.substr(cast(column, String), 1, MAX_FIELD_CHARS + 1).label(name)
                if isinstance(column.type, (JSON, String))
                else column
            )
            for name, column in columns.items()
        ]
    ).where(
        ExecutionRun.id == run_id,
        ExecutionRun.user_id == identity.actor_id,
        ExecutionRun.project_id == identity.project_id,
    )
    row = (await session.execute(query)).mappings().one_or_none()
    if row is None:
        raise ValueError("Run unavailable")
    values = dict(row)
    for name, value in values.items():
        if isinstance(value, str) and len(value) > MAX_FIELD_CHARS:
            raise ValueError("Retained metadata exceeds inspection budget")
        if isinstance(columns[name].type, JSON) and value is not None:
            values[name] = json.loads(value)
    digest = hashlib.sha256(json.dumps(values, sort_keys=True, allow_nan=False).encode()).hexdigest()
    evidence = RunEvidence.model_validate(values["evidence_completeness"] or {})
    if len(evidence.outputs) > 128 or sum(map(len, evidence.outputs.values())) > 128:
        raise ValueError("Retained inventory exceeds inspection budget")
    return SimpleNamespace(**values), digest


async def authorize_scientific_reader(session, identity, arguments, result=None):
    from spectra_sherpa.app.services.inspection_bridge import InspectionRefused

    if not {"metadata", "metrics", "statistics"} <= identity.disclosures:
        raise InspectionRefused("disclosure_denied")
    await authorize_run_reader(session, identity, RunArguments(run_id=arguments.run_id))
    await authorize_policy(session, identity, [DataType.SPECTRA])
    try:
        snapshot, digest = await _snapshot(session, identity, arguments.run_id)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise InspectionRefused("inspection_failed") from exc
    if result is not None and result["evidence_identity"] != digest:
        raise InspectionRefused("retained_evidence_changed")
    return snapshot, digest


def _metrics(run, digest):
    from spectra_sherpa.app.services.run_output_retention import retained_read_budget
    from spectra_sherpa.app.services.run_population_summary import RetainedDefinitionRead
    from spectra_sherpa.app.services.run_validation_summary import validation_summary

    with retained_read_budget(MAX_FILE_READ_BYTES):
        reader = RetainedDefinitionRead()
        evidence = RunEvidence.model_validate(run.evidence_completeness or {})
        try:
            definition = reader.read(run.user_id, evidence.outputs.get("__workflow__", {}).get("definition"))
        except (ValueError, OSError):
            definition = None
        summary = validation_summary(run, definition, population_definition_read=reader)
        records = []
        for record in summary["regression_results"]:
            # Report records may contain future fields or raw observations.
            # Select a closed scientific projection, never forward **record.
            metrics = record["metrics"]
            records.append(
                RegressionFact(
                    **{
                        key: record[key]
                        for key in (
                            "node_id",
                            "source_port",
                            "target",
                            "role",
                            "units",
                            "unit_context",
                            "bias_definition",
                            "reference_min",
                            "reference_max",
                            "reference_sd",
                        )
                    },
                    reference_mean=record.get("reference_mean"),
                    registry_version=metrics["registry_version"],
                    metrics={key: metrics.get(key) for key in sorted(REGRESSION_METRIC_FIELDS - {"registry_version"})},
                )
            )
        return MetricSummary(
            run_id=run.id,
            evidence_identity=digest,
            availability="available" if records else "unavailable",
            reason=None if records else "No supported qualified regression statistics were retained.",
            regression_results=records,
            limitations=[
                "Validation metrics are retained canonical statistics; "
                "reference means are descriptive retained-value arithmetic.",
                "No validation metric reconstruction or fit.",
                "Cross-validation is not an external held-out test; population roles remain separate.",
                "Missing or ambiguous units are not inferred. Missing metrics are not zero.",
                "This projection covers retained regression statistics, not every result family or validation claim.",
            ],
        ).model_dump(mode="json")


async def _diagnostics(run, digest, arguments):
    from spectra_sherpa.app.services.diagnostic_review_summary import ROLES, build_summary
    from spectra_sherpa.app.services.retained_review_receipt import retained_review_receipt
    from spectra_sherpa.app.services.run_output_retention import retained_read_budget

    with retained_read_budget(MAX_FILE_READ_BYTES):
        try:
            receipt = await retained_review_receipt(run, arguments.node_id)
        except (ValueError, OSError, TypeError, AttributeError):
            return DiagnosticSummary(
                run_id=run.id,
                node_id=arguments.node_id,
                evidence_identity=digest,
                availability="unavailable",
                reason="Exact supported diagnostic evidence is unavailable or unverified.",
                model_kind=None,
                response=None,
                populations={},
                facts={},
                limitations=[],
            ).model_dump(mode="json")
        if receipt.get("model_kind", "pca") not in {"pca", "pls"}:
            return DiagnosticSummary(
                run_id=run.id,
                node_id=arguments.node_id,
                evidence_identity=digest,
                availability="unavailable",
                reason="This retained diagnostic family is not supported.",
                model_kind=None,
                response=None,
                populations={},
                facts={},
                limitations=[],
            ).model_dump(mode="json")
        rows = receipt.get("rows")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 5000:
            raise ValueError("Unsupported diagnostic population")
        summary = await asyncio.to_thread(
            build_summary,
            receipt,
            selected_ids=[row["id"] for row in rows],
            response_index=arguments.response_index,
        )
        # No S1/etc. sample facts, variable profiles, current review state or
        # report-subset interpretation. Only whole retained population facts.
        facts = {
            key: DiagnosticFact.model_validate(value)
            for key, value in summary["facts"].items()
            if key.startswith(tuple(role + "." for role in (*ROLES, "model")))
            and (value["value"] is None or type(value["value"]) in (int, float))
        }
        return DiagnosticSummary(
            run_id=run.id,
            node_id=arguments.node_id,
            evidence_identity=digest,
            availability="available",
            reason=None,
            model_kind=summary["model_kind"],
            response=summary["response"],
            populations=summary["populations"],
            facts=facts,
            limitations=[
                "Saved whole-population diagnostic facts; no raw observation values or identities.",
                "Quartiles use linear interpolation on finite values within each execution population.",
                "Statistical screening does not identify a cause or establish suitability.",
                "Current review decisions and private interpretation are outside this projection.",
            ],
        ).model_dump(mode="json")


async def read_scientific_facts(sessions, identity, arguments):
    async with sessions() as session:
        run, digest = await authorize_scientific_reader(session, identity, arguments)
    if isinstance(arguments, DiagnosticArguments):
        return await _diagnostics(run, digest, arguments)
    return await asyncio.to_thread(_metrics, run, digest)


async def get_results(run_id, *, sessions, identity):
    return await read_scientific_facts(sessions, identity, ScientificArguments(run_id=run_id))


async def get_diagnostics(run_id, node_id, response_index=0, *, sessions, identity):
    return await read_scientific_facts(
        sessions, identity, DiagnosticArguments(run_id=run_id, node_id=node_id, response_index=response_index)
    )


def register_scientific_catalog(registry):
    """Register in the isolated MCP instance only, never ordinary providers."""
    from spectra_sherpa.app.services.tools.schemas import ToolCategory, ToolDefinition

    for name, arguments, output, handler, description in (
        (
            "get_results",
            ScientificArguments,
            MetricSummary,
            get_results,
            "Read retained regression statistics with population roles and target units; no raw rows or refit.",
        ),
        (
            "get_diagnostics",
            DiagnosticArguments,
            DiagnosticSummary,
            get_diagnostics,
            "Read whole-population saved PCA/PLS diagnostic facts; no sample identities, raw values or interpretation.",
        ),
    ):
        registry.register(
            ToolDefinition(
                name=name,
                description=description,
                category=ToolCategory.workflow,
                requires_user=True,
                requires_session=True,
                version="1.0",
                mutation="read",
                distribution="oss",
                disclosure=["metadata", "metrics", "statistics"],
                mcp_name=name,
                parameters=arguments.model_json_schema(),
                output_schema=output.model_json_schema(),
            ),
            handler,
        )
