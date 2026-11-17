"""Bounded two-run projection of the existing public comparison authority."""

from __future__ import annotations

import asyncio
from typing import Literal

from pydantic import Field, model_validator

from spectra_sherpa.app.schemas.scientific_comparison import EvaluationRole
from spectra_sherpa.app.services.inspection_science import (
    MAX_FILE_READ_BYTES,
    ClosedModel,
    Number,
    ScientificArguments,
    Text,
    authorize_scientific_reader,
)
from spectra_sherpa.sdk.validate import REGRESSION_METRIC_FIELDS


class ComparisonArguments(ClosedModel):
    run_ids: list[int] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def distinct_positive_runs(self):
        if len(set(self.run_ids)) != 2 or any(value <= 0 for value in self.run_ids):
            raise ValueError("Select two distinct positive run IDs")
        return self


class Population(ClosedModel):
    source_count: int | None
    admitted_count: int | None
    excluded_count: int | None
    development_count: int | None
    held_out_count: int | None
    evaluation_count: int | None
    group_count: int | None
    grouped: bool | None
    response: Text | None
    units: Text | None
    fold_count: int | None
    verification: Literal["verified", "partial", "unknown"]


class Section(ClosedModel):
    role: EvaluationRole
    state: Literal["verified", "descriptive_only", "unavailable"]
    population: Population
    metrics: dict[str, Number]


class ComparedRun(ClosedModel):
    run_id: int
    evidence_identity: str
    sections: list[Section] = Field(max_length=4)


class ComparisonSection(ClosedModel):
    role: EvaluationRole
    state: Literal["comparable", "descriptive_only", "reevaluation_needed", "unavailable"]
    metric_values: dict[str, dict[Literal["left", "right"], Number]]


class ComparisonSummary(ClosedModel):
    runs: list[ComparedRun] = Field(min_length=2, max_length=2)
    sections: list[ComparisonSection] = Field(max_length=4)
    limitations: list[str]


async def authorize_comparison(session, identity, arguments, result=None):
    snapshots = []
    for index, run_id in enumerate(arguments.run_ids):
        previous = result["runs"][index] if result is not None else None
        snapshots.append(
            await authorize_scientific_reader(session, identity, ScientificArguments(run_id=run_id), previous)
        )
    return snapshots


def _comparison(snapshots):
    from spectra_sherpa.app.services.run_output_retention import retained_read_budget
    from spectra_sherpa.app.services.scientific_comparison import compare_saved_run_evidence

    with retained_read_budget(MAX_FILE_READ_BYTES):
        comparison = compare_saved_run_evidence([run for run, _ in snapshots])
        # Never forward the authority's row arrays, identifiers or free-form
        # failure reasons. Qualification states and scalar facts retain meaning.
        return ComparisonSummary(
            runs=[
                ComparedRun(
                    run_id=run.id,
                    evidence_identity=digest,
                    sections=[
                        Section(
                            role=section.role,
                            state=section.state,
                            population=Population(
                                **{name: getattr(section.population, name) for name in Population.model_fields}
                            ),
                            metrics={
                                key: value for key, value in section.metrics.items() if key in REGRESSION_METRIC_FIELDS
                            },
                        )
                        for section in item.sections.values()
                    ],
                )
                for (run, digest), item in zip(snapshots, comparison.items, strict=True)
            ],
            sections=[
                ComparisonSection(
                    role=section.role,
                    state=section.state,
                    metric_values={
                        key: value for key, value in section.metric_values.items() if key in REGRESSION_METRIC_FIELDS
                    },
                )
                for section in comparison.pairs[0].sections
            ],
            limitations=[
                "OSS comparison qualification stays separate for each evaluation role; no recommendation or ranking.",
                "Descriptive statistics do not establish comparability; unavailable evidence is not a zero score.",
                "Sample identities, row values and free-form reasons are withheld; inspect Workbench for details.",
                "Classification results remain inspectable; classification evaluation ranking is unsupported.",
                "Ambiguous outputs require inspection in Workbench; this interface does not choose a result pairing.",
            ],
        ).model_dump(mode="json")


async def read_comparison(sessions, identity, arguments):
    async with sessions() as session:
        snapshots = await authorize_comparison(session, identity, arguments)
    return await asyncio.to_thread(_comparison, snapshots)


async def compare_runs(run_ids, *, sessions, identity):
    return await read_comparison(sessions, identity, ComparisonArguments(run_ids=run_ids))


def register_comparison_catalog(registry):
    from spectra_sherpa.app.services.tools.schemas import ToolCategory, ToolDefinition

    registry.register(
        ToolDefinition(
            name="compare_runs",
            description="Compare two retained runs with existing OSS comparability rules; no ranking or execution.",
            category=ToolCategory.workflow,
            requires_user=True,
            requires_session=True,
            version="1.0",
            mutation="read",
            distribution="oss",
            disclosure=["metadata", "metrics", "statistics"],
            mcp_name="compare_runs",
            parameters=ComparisonArguments.model_json_schema(),
            output_schema=ComparisonSummary.model_json_schema(),
        ),
        compare_runs,
    )
