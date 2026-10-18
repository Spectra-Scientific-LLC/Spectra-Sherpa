"""Leakage, exact pairing and truthful local robustness boundaries."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
from spectra_sherpa.app.services import paired_evaluation as subject
from spectra_sherpa.app.services.serialization import serialize_result


def fixtures(monkeypatch, *, components=2, heldout_shift=0, port="X_train"):
    rng = np.random.default_rng(31)
    x = rng.normal(size=(32, 6))
    y = 2 * x[:, 0] - x[:, 2] + rng.normal(scale=0.05, size=32)
    y[24:] += heldout_shift
    dataset = SherpaDataset(X=x, target=y, feature_axis=SpectralAxis(values=np.arange(6)))
    definition = {
        "schema_version": 1,
        "nodes": [
            {"node_id": "raw", "node_type": "data.file_load", "parameters": {}},
            {"node_id": "split", "node_type": "data.train_test_split", "parameters": {}},
            {
                "node_id": "scale",
                "node_type": "preprocess.scale",
                "parameters": {"method": "autoscale", "center": True},
            },
            {
                "node_id": "model",
                "node_type": "model.fitted_pls",
                "parameters": {"n_components": components, "scale": True},
            },
        ],
        "edges": [
            {"from_node_id": "raw", "to_node_id": "split", "from_output": "default", "to_input": "default"},
            {"from_node_id": "split", "to_node_id": "scale", "from_output": port, "to_input": "default"},
            {"from_node_id": "scale", "to_node_id": "model", "from_output": "default", "to_input": "default"},
        ],
    }
    saved = {
        ("__workflow__", "definition"): definition,
        ("raw", "default"): serialize_result(dataset, retain_full=True),
        ("split", "train_indices"): list(range(24)),
        ("split", "test_indices"): list(range(24, 32)),
    }
    monkeypatch.setattr(subject, "retained_reader", lambda run: lambda node, port: deepcopy(saved[node, port]))
    request = subject.PairedEvaluationRequest(
        recipes=[{"run_id": 1, "model_node_id": "model"}, {"run_id": 2, "model_node_id": "model"}],
        population_run_id=1,
        folds=4,
        repetitions=3,
    )
    recipes = [subject.load_recipe(SimpleNamespace(id=s.run_id), s) for s in request.recipes]
    return request, recipes, saved


async def test_identical_recipes_have_identical_scores_on_exact_paired_folds(monkeypatch):
    request, recipes, _ = fixtures(monkeypatch)
    result = await subject.evaluate_pair(recipes, request)
    assert result["paired_rmsecv_differences"] == [0, 0, 0]
    assert result["population"]["development_count"] == 24
    assert result["population"]["held_out_count"] == 8
    assert len({s["digest"] for s in result["splits"]}) == 3
    for i in range(3):
        left, right = result["results"][i * 2 : i * 2 + 2]
        assert left["execution"]["split_plan_digest"] == right["execution"]["split_plan_digest"]
        assert left["execution"]["capability_content_digest"] == right["execution"]["capability_content_digest"]
    assert result["resume_supported"] is False


async def test_changing_held_out_targets_cannot_change_training_cv(monkeypatch):
    request, recipes, _ = fixtures(monkeypatch)
    before = await subject.evaluate_pair(recipes, request)
    request, recipes, _ = fixtures(monkeypatch, heldout_shift=1e8)
    after = await subject.evaluate_pair(recipes, request)
    assert [r["execution"] for r in before["results"]] == [r["execution"] for r in after["results"]]
    assert before["paired_rmsecv_differences"] == after["paired_rmsecv_differences"]
    for original, shifted in zip(before["results"], after["results"]):
        left, right = original["local_application"], shifted["local_application"]
        assert left["fit"] == right["fit"] and left["fit_digest"] == right["fit_digest"]
        assert left["calibration"] == right["calibration"]
        assert left["held_out"]["predictions"] == right["held_out"]["predictions"]
        assert np.asarray(right["held_out"]["observations"]) - np.asarray(
            left["held_out"]["observations"]
        ) == pytest.approx(1e8)


def test_refuses_the_held_out_branch(monkeypatch):
    with pytest.raises(ValueError, match="never held-out"):
        fixtures(monkeypatch, port="X_test")


def test_refuses_infeasible_pls_components_without_reducing_them(monkeypatch):
    request, recipes, _ = fixtures(monkeypatch, components=7)
    with pytest.raises(ValueError, match="component count is infeasible"):
        subject.prepare_protocol(recipes, request)


def test_different_training_memberships_are_not_pooled(monkeypatch):
    from dataclasses import replace

    request, recipes, _ = fixtures(monkeypatch)
    recipes[1] = replace(recipes[1], development_indices=tuple(range(23)))
    with pytest.raises(ValueError, match="populations differ"):
        subject.prepare_protocol(recipes, request)


def test_group_repetitions_refused_and_single_group_plan_keeps_groups_intact(monkeypatch):
    request, recipes, _ = fixtures(monkeypatch)
    groups = np.repeat(np.arange(6), 4)
    monkeypatch.setattr(subject, "_supervised_inputs", lambda ds: (ds.target, groups, None))
    with pytest.raises(ValueError, match="randomized grouped"):
        subject.prepare_protocol(recipes, request)
    request.repetitions = 1
    _, _, _, _, splits = subject.prepare_protocol(recipes, request)
    for fold in splits[0].folds:
        assert not set(groups[fold.train]) & set(groups[fold.test])
    request.folds = 7
    with pytest.raises(ValueError, match="distinct groups"):
        subject.prepare_protocol(recipes, request)


async def test_cancellation_never_returns_completed_evidence(monkeypatch):
    request, recipes, _ = fixtures(monkeypatch)
    seen = []

    async def cancel_after_first(done, total):
        seen.append(done)
        if done == 1:
            raise ValueError("cancelled")

    with pytest.raises(ValueError, match="cancelled"):
        await subject.evaluate_pair(recipes, request, cancel_after_first)
    assert seen == [0, 1]


def test_retained_source_corruption_is_refused(monkeypatch):
    _, _, saved = fixtures(monkeypatch)
    wire = saved["raw", "default"]
    wire["data"][0][0] += 1
    with pytest.raises(ValueError, match="scientific identity"):
        subject.restore_dataset(wire)


async def test_route_preflight_checks_access_and_does_not_mutate_runs(monkeypatch, test_session, test_user):
    from datetime import datetime, timezone

    from fastapi import HTTPException

    from spectra_sherpa.app.api.v1.routes import paired_evaluations as routes
    from spectra_sherpa.app.models.execution_run import ExecutionRun

    request, _, _ = fixtures(monkeypatch)
    source_runs = []
    for identifier in (1, 2):
        run = ExecutionRun(
            id=identifier,
            user_id=test_user.id,
            name=f"Source {identifier}",
            status="completed",
            params_snapshot={"original": identifier},
            results_summary={"unchanged": identifier},
            executed_at=datetime.now(timezone.utc),
            run_kind="training",
        )
        test_session.add(run)
        source_runs.append(run)
    await test_session.commit()
    before = [(r.params_snapshot.copy(), r.results_summary.copy(), r.status) for r in source_runs]
    preview = await routes.preview(request, test_session, test_user)
    assert preview["fits"] == 24
    assert preview["development_count"] == 24 and preview["held_out_count"] == 8
    assert [(r.params_snapshot, r.results_summary, r.status) for r in source_runs] == before
    with pytest.raises(HTTPException) as denied:
        await routes._authorized_run(test_session, 1, test_user.id + 900, "execute")
    assert denied.value.status_code in (403, 404)


async def test_actual_job_retains_new_evidence_and_original_runs(monkeypatch, test_session, test_user, test_engine):
    import asyncio
    from datetime import datetime, timezone

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from spectra_sherpa.app.api.v1.routes import paired_evaluations as routes
    from spectra_sherpa.app.models.background_job import BackgroundJob
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.services import job_manager as jobs

    request, _, _ = fixtures(monkeypatch)
    request.repetitions = 1
    for identifier in (1, 2):
        test_session.add(
            ExecutionRun(
                id=identifier,
                user_id=test_user.id,
                name=f"Source {identifier}",
                status="completed",
                params_snapshot={"original": identifier},
                results_summary={"original": identifier},
                executed_at=datetime.now(timezone.utc),
                run_kind="training",
            )
        )
    await test_session.commit()
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(routes, "async_session", factory)
    monkeypatch.setattr(jobs, "async_session", factory)

    async def silent(*args, **kwargs):
        pass

    monkeypatch.setattr(jobs.job_manager, "_broadcast_job", silent)
    started = await routes.start(request, test_session, test_user)
    for _ in range(100):
        await asyncio.sleep(0.05)
        async with factory() as check:
            state = await check.get(BackgroundJob, started["job_id"])
            if state.status in {"completed", "failed"}:
                assert state.status == "completed", state.error_message
                saved = await routes.result(started["run_id"], check, test_user)
                assert saved["record"]["paired_rmsecv_differences"] == [0]
                assert saved["record"]["population"]["held_out_count"] == 8
                source = await check.get(ExecutionRun, 1)
                assert source.params_snapshot == {"original": 1}
                assert source.results_summary == {"original": 1}
                return
    pytest.fail("Local paired evaluation job did not complete")


def test_independent_loader_event_times_keep_the_same_population(monkeypatch):
    from spectra_sherpa.app.lib.sherpa_dataset import Provenance

    request, _, saved = fixtures(monkeypatch)
    original = subject.restore_dataset(saved["raw", "default"])
    original.provenance.append("data.file_load", {"source_sha256": "a" * 64}, node_id="raw")
    reloaded = original.copy()
    entries = reloaded.provenance.to_list()
    entries[0]["timestamp"] = "2026-10-17T01:00:00+00:00"
    reloaded.provenance = Provenance.from_list(entries)
    assert original.scientific_digest != reloaded.scientific_digest

    def reader(run):
        def exact(node, port):
            if (node, port) == ("raw", "default"):
                return serialize_result(original if run.id == 1 else reloaded, retain_full=True)
            return deepcopy(saved[node, port])

        return exact

    monkeypatch.setattr(subject, "retained_reader", reader)
    recipes = [subject.load_recipe(SimpleNamespace(id=s.run_id), s) for s in request.recipes]
    subject.prepare_protocol(recipes, request)
    assert recipes[0].source_digest == recipes[1].source_digest


def test_source_sample_mask_is_not_lost_when_selecting_training_rows(monkeypatch):
    from spectra_sherpa.app.lib.axes import SampleAxis

    request, _, saved = fixtures(monkeypatch)
    source = subject.restore_dataset(saved["raw", "default"])
    source.sample_axis = SampleAxis(labels=[str(i) for i in range(32)], include_mask=[False] + [True] * 31)
    saved["raw", "default"] = serialize_result(source, retain_full=True)
    with pytest.raises(ValueError, match="Materialize declared sample"):
        subject.load_recipe(SimpleNamespace(id=1), request.recipes[0])


async def test_local_oof_rows_are_from_scored_applications_and_compare_after_retention(monkeypatch, tmp_path):
    from dataclasses import replace

    from spectra_sherpa.app.schemas.execution_runs import EvaluationSelection
    from spectra_sherpa.app.services import run_output_retention as retention
    from spectra_sherpa.app.services.scientific_comparison import resolve_run_evidence
    from spectra_sherpa.sdk import validate

    request, recipes, _ = fixtures(monkeypatch)
    record = await subject.evaluate_pair(recipes, request)
    for selected in record["results"]:
        rows = selected["local_oof"]
        assert len(rows["observations"]) == len(rows["predictions"]) == 24
        assert rows["validation_execution_digest"] == selected["execution_digest"]
        assert "observations" not in selected["execution"] and "predictions" not in selected["execution"]
        assert validate.metrics(rows["observations"], rows["predictions"]).rmse == pytest.approx(
            selected["execution"]["metrics"]["rmse"]
        )
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    run = SimpleNamespace(
        id=10,
        user_id=1,
        name="Saved paired evaluation",
        status="completed",
        source_type="paired_evaluation",
        source_metadata={},
        diagnostics={},
    )
    run.evidence_completeness = retention.retain_run_outputs(1, {"__evaluation__": {"record": record}}, {})
    compared = subject.paired_comparison(run, repetition=2)
    cv = next(s for s in compared.pairs[0].sections if s.role == "training_cv")
    assert cv.state == "comparable"
    assert len(compared.items[0].sections["training_cv"].predictions) == 24
    assert compared.items[0].reference.selected_output.presentation_id == "repetition:2"
    for role, count in (("calibration", 24), ("held_out", 8)):
        section = next(s for s in compared.pairs[0].sections if s.role == role)
        assert section.state == "comparable"
        assert len(compared.items[0].sections[role].predictions) == count
    assert len({r["local_application"]["fit_digest"] for r in record["results"] if r["recipe_index"] == 0}) == 1
    selected = resolve_run_evidence(run, EvaluationSelection(node_id="recipe:1", presentation_id="repetition:2"))
    assert {e.role for e in selected.evaluations} == {"calibration", "training_cv", "held_out"}
    assert selected.evaluations[0].predictions == tuple(record["results"][5]["local_oof"]["predictions"])
    record["results"][5]["local_oof"]["predictions"][0] += 100
    run.evidence_completeness = retention.retain_run_outputs(1, {"__evaluation__": {"record": record}}, {})
    with pytest.raises(ValueError, match="reproduce"):
        subject.paired_comparison(run, repetition=2)


async def test_common_evaluation_does_not_invent_holdout_when_no_split(monkeypatch):
    from dataclasses import replace

    request, recipes, _ = fixtures(monkeypatch)
    request.repetitions = 1
    recipes = [replace(r, held_out_indices=(), held_out_dataset=None) for r in recipes]
    record = await subject.evaluate_pair(recipes, request)
    assert all(r["local_application"]["held_out"] is None for r in record["results"])
    assert all(len(r["local_application"]["calibration"]["predictions"]) == 24 for r in record["results"])
