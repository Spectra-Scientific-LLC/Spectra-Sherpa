"""Persisted canonical facts, independent numeric oracle and disclosure refusals."""

import asyncio
import json
import threading
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from spectra_sherpa.app.services import inspection_science as science
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.services.inspection_bridge import InspectionRefused
from spectra_sherpa.app.services.inspection_grants import InspectionAccessDenied
from tests.test_inspection_runs import call, run_facts  # noqa: F401


@pytest.fixture
async def scientific_run(run_facts, tmp_path, monkeypatch):  # noqa: F811
    from spectra_sherpa.app.services.dag.regression_comparison import build_regression_comparison
    from spectra_sherpa.app.services.pca_review_evidence import SCHEMA

    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    sessions, grant, runs, user = run_facts
    run = runs[0]
    definition = {"schema_version": 1, "nodes": [], "edges": []}
    receipt = {
        "schema_version": SCHEMA,
        "model_kind": "pca",
        "graph_digest": "b" * 64,
        "n_components": 2,
        "calibration_t2_limit": 2.0,
        "application_t2_limit": 5.0,
        "q_limit": 4.0,
        "rows": [
            {"id": f"secret-observation-{i}", "role": "calibration", "t2": float(i), "q": float(i * 2)}
            for i in range(4)
        ],
    }
    comparison = build_regression_comparison(
        [1, 2, 3, 4],
        [2, 2, 3, 5],
        role="held_out_test",
        target_names=["concentration"],
        sample_labels=[f"secret-sample-{i}" for i in range(4)],
    )
    evidence = retention.retain_run_outputs(
        user.id,
        {
            "model": {"comparison": comparison},
            "__workflow__": {"definition": definition, "pca_review": {"model": receipt}},
        },
        {},
    )
    async with sessions() as session:
        persisted = await session.get(type(run), run.id)
        persisted.integrity_hash = "b" * 64
        persisted.evidence_completeness = evidence
        await session.commit()
    return run_facts, definition, evidence


async def test_metrics_match_workbench_and_independent_oracle(scientific_run):
    from spectra_sherpa.app.services.run_validation_summary import validation_summary

    facts, definition, _ = scientific_run
    sessions, _, runs, _ = facts
    result = await call(facts, "get_results", {"run_id": runs[0].id})
    assert result["availability"] == "available"
    record = result["regression_results"][0]
    assert record["role"] == "held_out_test"
    assert record["unit_context"] == {"state": "missing", "value": None}
    assert record["metrics"]["rmse"] == pytest.approx(0.5**0.5)
    assert record["metrics"]["bias"] == pytest.approx(0.5)
    assert record["metrics"]["r2"] == pytest.approx(0.6)
    assert record["metrics"]["sep"] == pytest.approx((1 / 3) ** 0.5)
    assert record["metrics"]["n_samples"] == 4
    async with sessions() as session:
        run = await session.get(type(runs[0]), runs[0].id)
        expected = await asyncio.to_thread(validation_summary, run, definition)
    for key in ("role", "units", "unit_context", "reference_min", "reference_max", "reference_sd"):
        assert record[key] == expected["regression_results"][0][key]
    expected_metrics = expected["regression_results"][0]["metrics"].copy()
    assert record["registry_version"] == expected_metrics.pop("registry_version")
    assert record["metrics"] == expected_metrics
    encoded = json.dumps(result)
    for secret in ("secret-sample", "secret-observation", "parameter", "observations", "params_snapshot"):
        assert secret not in encoded


async def test_diagnostics_whole_population_quantiles_without_sample_facts(scientific_run):
    facts, *_ = scientific_run
    result = await call(facts, "get_diagnostics", {"run_id": facts[2][0].id, "node_id": "model"})
    assert result["model_kind"] == "pca"
    assert result["facts"]["calibration.t2.median"]["value"] == 1.5
    assert result["facts"]["calibration.q.q1"]["value"] == 1.5
    assert result["facts"]["calibration.t2.valid"]["value"] == 4
    assert result["populations"] == {"calibration": {"total": 4, "selected": 4}}
    assert not any(key.startswith(("S", "review.", "report_subset.")) for key in result["facts"])
    assert "secret-" not in json.dumps(result)


async def test_legacy_results_are_unavailable_not_invented(run_facts):  # noqa: F811
    result = await call(run_facts, "get_results", {"run_id": run_facts[2][0].id})
    assert result["availability"] == "unavailable"
    assert result["regression_results"] == []


async def test_aggregate_read_budget_cannot_be_swallowed_by_summary(scientific_run, monkeypatch):
    facts, *_ = scientific_run
    monkeypatch.setattr(science, "MAX_FILE_READ_BYTES", 1)
    with pytest.raises(InspectionRefused, match="inspection_failed"):
        await call(facts, "get_results", {"run_id": facts[2][0].id})


async def test_metadata_budget_is_enforced_before_decode(scientific_run):
    facts, *_ = scientific_run
    sessions, _, runs, _ = facts
    async with sessions() as session:
        run = await session.get(type(runs[0]), runs[0].id)
        run.params_snapshot = {"large": "x" * science.MAX_FIELD_CHARS}
        await session.commit()
    with pytest.raises(InspectionRefused, match="inspection_failed"):
        await call(facts, "get_results", {"run_id": runs[0].id})


async def test_changed_retention_identity_refuses_disclosure(scientific_run, monkeypatch):
    facts, *_ = scientific_run
    sessions, _, runs, _ = facts
    original = science._metrics
    started, release = threading.Event(), threading.Event()

    def delayed(*args):
        result = original(*args)
        started.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(science, "_metrics", delayed)
    task = asyncio.create_task(call(facts, "get_results", {"run_id": runs[0].id}))
    assert await asyncio.to_thread(started.wait, 5)
    async with sessions() as session:
        run = await session.get(type(runs[0]), runs[0].id)
        run.integrity_hash = "c" * 64
        await session.commit()
    release.set()
    with pytest.raises(InspectionRefused, match="retained_evidence_changed"):
        await task


@pytest.mark.parametrize("operation", ["get_results", "get_diagnostics"])
async def test_scientific_read_requires_spectra_privacy(scientific_run, operation):
    from spectra_sherpa.app.models.data_egress import DataEgressPermission

    facts, *_ = scientific_run
    sessions, _, runs, user = facts
    async with sessions() as session:
        session.add(
            DataEgressPermission(user_id=user.id, data_type="spectra", destination="llm_context", allowed=False)
        )
        await session.commit()
    args = {"run_id": runs[0].id}
    if operation == "get_diagnostics":
        args["node_id"] = "model"
    with pytest.raises(InspectionRefused, match="privacy_denied"):
        await call(facts, operation, args)


@pytest.mark.parametrize("change", ["project", "privacy", "consent", "revocation", "disclosure"])
async def test_fresh_admission_after_scientific_read(scientific_run, monkeypatch, change):
    from sqlalchemy import select

    from spectra_sherpa.app.models.data_egress import UserEgressDefaults
    from spectra_sherpa.app.models.inspection_grant import InspectionGrant
    from spectra_sherpa.app.models.project import Project

    facts, *_ = scientific_run
    sessions, grant, runs, user = facts
    entered, release = threading.Event(), threading.Event()
    original = science._metrics

    def delayed(*args):
        result = original(*args)
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(science, "_metrics", delayed)
    task = asyncio.create_task(call(facts, "get_results", {"run_id": runs[0].id}))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        async with sessions() as session:
            if change == "project":
                other = Project(user_id=user.id, name="other")
                session.add(other)
                await session.flush()
                run = await session.get(type(runs[0]), runs[0].id)
                run.project_id = other.id
            elif change == "privacy":
                defaults = await session.scalar(select(UserEgressDefaults).where(UserEgressDefaults.user_id == user.id))
                defaults.allow_llm_context = False
            else:
                credential = await session.get(InspectionGrant, grant.identity.client_id)
                if change == "disclosure":
                    credential.disclosures = ["metadata"]
                elif change == "consent":
                    credential.retained_results = False
                else:
                    credential.revoked_at = datetime.now(timezone.utc)
            await session.commit()
        release.set()
        with pytest.raises((InspectionRefused, InspectionAccessDenied)):
            await task
    finally:
        release.set()
        if not task.done():
            await task


def test_inspection_file_budget_is_cumulative_and_restores_context(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    item = retention.retain_output(1, {"value": [1, 2, 3]})
    with pytest.raises(ValueError, match="budget"):
        with retention.retained_read_budget(item.byte_count + 1):
            assert retention.read_output(1, item) == {"value": [1, 2, 3]}
            # Swallowing a canonical reader's error cannot turn a partial result into success.
            try:
                retention.read_output(1, item)
            except ValueError:
                pass
    assert retention.read_output(1, item) == {"value": [1, 2, 3]}


@pytest.mark.parametrize("missing", ["metrics", "statistics"])
async def test_metadata_or_partial_disclosure_grants_cannot_read_science(scientific_run, missing):
    from spectra_sherpa.app.models.inspection_grant import InspectionGrant

    facts, *_ = scientific_run
    sessions, grant, runs, _ = facts
    async with sessions() as session:
        credential = await session.get(InspectionGrant, grant.identity.client_id)
        credential.disclosures = sorted({"metadata", "metrics", "statistics"} - {missing})
        await session.commit()
    for operation, extra in (("get_results", {}), ("get_diagnostics", {"node_id": "model"})):
        with pytest.raises(InspectionRefused, match="disclosure_denied"):
            await call(facts, operation, {"run_id": runs[0].id, **extra})
    # Retained navigation remains within the original metadata scope.
    assert (await call(facts, "get_run", {"run_id": runs[0].id}))["id"] == runs[0].id


async def test_missing_diagnostic_receipt_is_explicitly_unavailable(run_facts):  # noqa: F811
    result = await call(run_facts, "get_diagnostics", {"run_id": run_facts[2][0].id, "node_id": "old"})
    assert result["availability"] == "unavailable"
    assert result["facts"] == {} and result["populations"] == {}


async def test_recorded_target_units_follow_retained_graph_only(scientific_run):
    facts, _, evidence = scientific_run
    sessions, _, runs, user = facts
    definition = {"schema_version": 1, "nodes": [], "edges": [{"from_node_id": "loader", "to_node_id": "model"}]}
    evidence["outputs"]["__workflow__"]["definition"] = retention.retain_output(user.id, definition).model_dump()
    async with sessions() as session:
        run = await session.get(type(runs[0]), runs[0].id)
        run.evidence_completeness = evidence
        run.source_metadata = {
            "data_selection_revisions": [
                {
                    "source_node_id": "loader",
                    "revision_number": 1,
                    "selection": {"target_authority": {"column": "concentration", "units": "mg/L"}},
                }
            ]
        }
        await session.commit()
    result = await call(facts, "get_results", {"run_id": runs[0].id})
    assert result["regression_results"][0]["unit_context"] == {"state": "recorded", "value": "mg/L"}


async def test_pls_keeps_full_test_role_response_units_and_residual_sign(scientific_run):
    from spectra_sherpa.app.services.pca_review_evidence import SCHEMA
    from tests.test_diagnostic_review_summary import pls_receipt

    facts, _, evidence = scientific_run
    sessions, _, runs, user = facts
    receipt = pls_receipt()
    receipt["schema_version"] = SCHEMA
    evidence["outputs"]["__workflow__"]["pca_review"] = retention.retain_output(
        user.id, {"model": receipt}
    ).model_dump()
    async with sessions() as session:
        run = await session.get(type(runs[0]), runs[0].id)
        run.evidence_completeness = evidence
        await session.commit()
    result = await call(facts, "get_diagnostics", {"run_id": runs[0].id, "node_id": "model", "response_index": 1})
    assert result["response"] == {
        "index": 1,
        "name": "moisture",
        "units": "%",
        "unit_context": {"state": "recorded", "value": "%"},
    }
    assert result["populations"]["held_out_test"] == {"total": 2, "selected": 2}
    assert result["facts"]["held_out_test.residual.median"]["value"] == -1.0
    assert result["facts"]["held_out_test.residual.median"]["units"] == "%"
    assert "private-" not in json.dumps(result)
    assert not any(key.startswith("report_subset") for key in result["facts"])


async def test_diagnostic_graph_custody_mismatch_is_not_available(scientific_run):
    facts, *_ = scientific_run
    sessions, _, runs, _ = facts
    async with sessions() as session:
        run = await session.get(type(runs[0]), runs[0].id)
        run.integrity_hash = "c" * 64
        await session.commit()
    result = await call(facts, "get_diagnostics", {"run_id": runs[0].id, "node_id": "model"})
    assert result["availability"] == "unavailable" and result["facts"] == {}
