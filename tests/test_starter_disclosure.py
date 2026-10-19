"""Starter context consent: real permission rows and a recording model hook."""

import pytest
from sqlalchemy import update

from spectra_sherpa.app.api.v1.routes import starter
from spectra_sherpa.app.contracts.starter_planning import GoalClassification, set_goal_classifier
from spectra_sherpa.app.core import security
from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.models.data_egress import DataEgressPermission, UserEgressDefaults
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.schemas.starter import StarterPlanRequest
from spectra_sherpa.app.services import starter_disclosure

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def consent_environment(monkeypatch):
    monkeypatch.setattr(app_config, "site_profile", "org")
    monkeypatch.setattr(security, "is_egress_enabled", lambda: True)
    monkeypatch.setattr(starter_disclosure, "is_egress_enabled", lambda: True)
    set_goal_classifier(None)
    yield
    set_goal_classifier(None)


@pytest.mark.parametrize(
    "context,override,allowed",
    [
        (False, None, False),
        (False, ("metadata", True), False),
        (True, ("metadata", False), False),
        (True, ("experiments", False), False),
        (True, None, True),
        (True, ("metadata", True), True),
    ],
)
async def test_route_filters_only_model_candidates(test_session, test_user, monkeypatch, context, override, allowed):
    defaults = UserEgressDefaults(user_id=test_user.id, allow_llm_chat=True, allow_llm_context=context)
    test_user.egress_defaults = defaults
    test_session.add(defaults)
    if override:
        test_session.add(
            DataEgressPermission(
                user_id=test_user.id, data_type=override[0], destination="llm_context", allowed=override[1]
            )
        )
    experiment = Experiment(
        user_id=test_user.id, name="Private sample batch", description="Confidential formula", metadata_path="{}"
    )
    test_session.add(experiment)
    await test_session.flush()
    test_session.add(ExperimentFile(experiment_id=experiment.id, file_path="raw/synthetic.csv", stage="raw"))
    await test_session.commit()
    public = {"key": "reference:public", "label": "Public reference", "kind": "reference", "supports": ["explore"]}
    monkeypatch.setattr(starter, "_reference_candidates", lambda _: [public])
    captured = []

    async def classifier(**kwargs):
        captured.extend(kwargs["datasets"])
        # Attempt to name an omitted key; the contract must discard it.
        return GoalClassification(intent="explore", confidence=0.5, dataset_key=f"experiment:{experiment.id}")

    set_goal_classifier(classifier)
    plan = await starter.plan_goal(StarterPlanRequest(goal="Explore my own data"), test_session, test_user)
    private = [row for row in captured if row["kind"] == "experiment"]
    assert bool(private) is allowed
    assert any(row["key"] == public["key"] for row in captured)
    assert plan.dataset.experiment_id == experiment.id
    if not allowed:
        assert plan.dataset.chosen_by != "model"
        assert "Confidential formula" not in str(captured)


async def test_fresh_defaults_and_overrides_override_cached_consent(test_session, test_user):
    defaults = UserEgressDefaults(user_id=test_user.id, allow_llm_chat=True, allow_llm_context=True)
    test_user.egress_defaults = defaults
    test_session.add(defaults)
    await test_session.commit()
    assert await starter_disclosure.private_starter_context_allowed(test_session, test_user.id)
    await test_session.execute(
        update(UserEgressDefaults)
        .where(UserEgressDefaults.user_id == test_user.id)
        .values(allow_llm_context=False)
        .execution_options(synchronize_session=False)
    )
    await test_session.commit()
    assert defaults.allow_llm_context is True
    assert not await starter_disclosure.private_starter_context_allowed(test_session, test_user.id)


async def test_no_defaults_or_global_egress_denies(test_session, test_user, monkeypatch):
    assert not await starter_disclosure.private_starter_context_allowed(test_session, test_user.id)
    test_session.add(UserEgressDefaults(user_id=test_user.id, allow_llm_chat=True, allow_llm_context=True))
    await test_session.commit()
    assert await starter_disclosure.private_starter_context_allowed(test_session, test_user.id)
    monkeypatch.setattr(starter_disclosure, "is_egress_enabled", lambda: False)
    assert not await starter_disclosure.private_starter_context_allowed(test_session, test_user.id)


async def test_policy_store_failure_denies():
    class BrokenSession:
        async def execute(self, _):
            raise RuntimeError("synthetic policy failure")

    assert not await starter_disclosure.private_starter_context_allowed(BrokenSession(), 1)


async def test_chat_denial_cannot_be_overridden(test_session, test_user):
    test_session.add(UserEgressDefaults(user_id=test_user.id, allow_llm_chat=False, allow_llm_context=True))
    test_session.add(
        DataEgressPermission(user_id=test_user.id, data_type="metadata", destination="llm_context", allowed=True)
    )
    await test_session.commit()
    assert not await starter_disclosure.private_starter_context_allowed(test_session, test_user.id)
