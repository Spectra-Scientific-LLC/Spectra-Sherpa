"""Comparison reuses public scientific qualification without identity disclosure."""

import asyncio
import json
from dataclasses import replace

import pytest

from spectra_sherpa.app.services import inspection_comparison as comparison
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.services.inspection_bridge import InspectionRefused
from tests.test_inspection_runs import call, run_facts  # noqa: F401
from tests.test_run_evaluation_comparison import saved_run


@pytest.fixture
async def compared_runs(run_facts, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    sessions, _, runs, user = run_facts
    assert user.id == 1  # Shared canonical fixture stores exact files for actor1.
    async with sessions() as session:
        for index, run in enumerate(runs[:2]):
            retained = saved_run(run.id, delta=(index + 1) / 10)
            current = await session.get(type(run), run.id)
            current.evidence_completeness = retained.evidence_completeness
            current.diagnostics = retained.diagnostics
        await session.commit()
    return run_facts


async def test_comparison_matches_authority_and_independent_rmse(compared_runs):
    from spectra_sherpa.app.services.scientific_comparison import compare_saved_run_evidence

    sessions, _, runs, _ = compared_runs
    result = await call(compared_runs, "compare_runs", {"run_ids": [run.id for run in runs[:2]]})
    async with sessions() as session:
        stored = [await session.get(type(run), run.id) for run in runs[:2]]
        expected = await asyncio.to_thread(compare_saved_run_evidence, stored)
    for actual, canonical in zip(result["sections"], expected.pairs[0].sections, strict=True):
        assert actual["role"] == canonical.role and actual["state"] == canonical.state
        assert actual["metric_values"] == canonical.metric_values
    cv = next(section for section in result["sections"] if section["role"] == "training_cv")
    assert cv["state"] == "comparable"
    assert cv["metric_values"]["rmse"] == pytest.approx({"left": 0.1, "right": 0.2})
    encoded = json.dumps(result)
    for secret in (
        "sample_ids",
        "observations",
        "predictions",
        "source:0",
        "parameters",
        "different-node",
        "partition_digest",
    ):
        assert secret not in encoded


@pytest.mark.parametrize("changed", ["folds", "source"])
async def test_mismatched_evidence_requires_reevaluation(compared_runs, changed):
    sessions, _, runs, _ = compared_runs
    replacement = saved_run(
        runs[1].id,
        changed_input=changed == "source",
        folds=([{"train": [0, 2], "test": [1, 3]}, {"train": [1, 3], "test": [0, 2]}] if changed == "folds" else None),
    )
    async with sessions() as session:
        run = await session.get(type(runs[1]), runs[1].id)
        run.evidence_completeness = replacement.evidence_completeness
        run.diagnostics = replacement.diagnostics
        await session.commit()
    result = await call(compared_runs, "compare_runs", {"run_ids": [run.id for run in runs[:2]]})
    cv = next(section for section in result["sections"] if section["role"] == "training_cv")
    assert cv["state"] == "reevaluation_needed" and cv["metric_values"] == {}


async def test_legacy_evidence_is_unavailable_not_zero(run_facts):  # noqa: F811
    result = await call(run_facts, "compare_runs", {"run_ids": [run.id for run in run_facts[2][:2]]})
    assert all(section["state"] == "unavailable" and not section["metric_values"] for section in result["sections"])
    assert all(
        section["population"]["evaluation_count"] is None for run in result["runs"] for section in run["sections"]
    )


@pytest.mark.parametrize("ids", [[1], [1, 1], [1, 2, 3], [True, 2], [0, 2], ["1", 2]])
async def test_two_distinct_typed_runs_required(run_facts, ids):  # noqa: F811
    with pytest.raises(InspectionRefused, match="invalid_arguments"):
        await call(run_facts, "compare_runs", {"run_ids": ids})


async def test_every_selected_run_requires_project_custody(compared_runs):
    sessions, _, runs, _ = compared_runs
    async with sessions() as session:
        run = await session.get(type(runs[1]), runs[1].id)
        run.project_id = None
        await session.commit()
    with pytest.raises(InspectionRefused):
        await call(compared_runs, "compare_runs", {"run_ids": [run.id for run in runs[:2]]})


async def test_combined_budget_cannot_be_swallowed_by_authority(compared_runs, monkeypatch):
    monkeypatch.setattr(comparison, "MAX_FILE_READ_BYTES", 1)
    with pytest.raises(InspectionRefused, match="inspection_failed"):
        await call(compared_runs, "compare_runs", {"run_ids": [run.id for run in compared_runs[2][:2]]})


async def test_changed_second_run_refuses_computed_disclosure(compared_runs, monkeypatch):
    sessions, _, runs, _ = compared_runs
    original = comparison.read_comparison

    async def changed(*args):
        result = await original(*args)
        async with sessions() as session:
            run = await session.get(type(runs[1]), runs[1].id)
            run.diagnostics = {"changed": True}
            await session.commit()
        return result

    monkeypatch.setattr("spectra_sherpa.app.services.inspection_bridge.read_comparison", changed)
    with pytest.raises(InspectionRefused, match="retained_evidence_changed"):
        await call(compared_runs, "compare_runs", {"run_ids": [run.id for run in runs[:2]]})
