"""The Dashboard planner uses configured local assistance without a hosted engine."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from spectra_sherpa.app.contracts import starter_planning
from spectra_sherpa.app.services import basic_chat, local_starter

INTENTS = [{"key": "calibrate", "label": "Predict a value", "summary": "PLS"}]
DATASETS = [{"key": "corn", "kind": "reference", "supports": ["calibrate"]}]


@pytest.fixture(autouse=True)
def local_model(monkeypatch):
    starter_planning.set_goal_classifier(None)
    monkeypatch.setattr(local_starter, "is_local", lambda: True)
    monkeypatch.setattr(basic_chat, "is_configured", lambda: True)
    monkeypatch.setattr(basic_chat, "chat_limiter", SimpleNamespace(allow=lambda _: True))
    yield
    starter_planning.set_goal_classifier(None)


@pytest.mark.asyncio
async def test_local_transport_returns_validated_choice_and_records_owner(monkeypatch):
    calls = []

    async def stream(message, **kwargs):
        calls.append((message, kwargs))
        yield '{"intent":"calibrate","confidence":0.9,'
        yield '"dataset_key":"corn"}'

    monkeypatch.setattr(basic_chat, "stream_chat", stream)
    assert starter_planning.goal_classifier_available()
    answer = await starter_planning.classify_goal_with_model(
        "How wet is my corn?", intents=INTENTS, datasets=DATASETS, user_id=7
    )
    assert answer.dataset_key == "corn"
    assert calls[0][1] == {"verbose": True, "exchange_owner": 7, "max_tokens": 400}
    assert "How wet is my corn?" in calls[0][0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply", ["not JSON", '{"intent":"invented","confidence":1}', '{"intent":"calibrate","confidence":2}']
)
async def test_local_invalid_answer_keeps_rule_fallback(monkeypatch, reply):
    async def stream(*args, **kwargs):
        yield reply

    monkeypatch.setattr(basic_chat, "stream_chat", stream)
    assert await starter_planning.classify_goal_with_model("goal", intents=INTENTS, user_id=7) is None


@pytest.mark.asyncio
async def test_local_key_never_substitutes_for_hosted_admission(monkeypatch):
    monkeypatch.setattr(local_starter, "is_local", lambda: False)
    stream = AsyncMock()
    monkeypatch.setattr(basic_chat, "stream_chat", stream)
    assert not starter_planning.goal_classifier_available()
    assert await starter_planning.classify_goal_with_model("goal", intents=INTENTS, user_id=7) is None
    stream.assert_not_called()


@pytest.mark.asyncio
async def test_shared_local_rate_limit_prevents_provider_call(monkeypatch):
    keys = []
    monkeypatch.setattr(basic_chat, "chat_limiter", SimpleNamespace(allow=lambda key: keys.append(key) or False))
    stream = AsyncMock()
    monkeypatch.setattr(basic_chat, "stream_chat", stream)
    assert await starter_planning.classify_goal_with_model("goal", intents=INTENTS, user_id=7) is None
    assert keys == ["user:7"]
    stream.assert_not_called()


@pytest.mark.asyncio
async def test_hosted_registration_retains_precedence_and_refusal(monkeypatch):
    registered = AsyncMock()
    starter_planning.set_goal_classifier(registered, is_available=lambda: False)
    assert not starter_planning.goal_classifier_available()
    assert await starter_planning.classify_goal_with_model("goal", intents=INTENTS, user_id=7) is None
    registered.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [False, True])
async def test_private_context_is_rechecked_before_local_provider_call(monkeypatch, allowed):
    from spectra_sherpa.app.db import session as db_session
    from spectra_sherpa.app.services import starter_disclosure

    session = object()

    @asynccontextmanager
    async def session_factory():
        yield session

    permission = AsyncMock(return_value=allowed)
    monkeypatch.setattr(db_session, "async_session", session_factory)
    monkeypatch.setattr(starter_disclosure, "private_starter_context_allowed", permission)
    messages = []

    async def stream(message, **kwargs):
        messages.append(message)
        yield '{"intent":"calibrate","confidence":0.9,"dataset_key":"corn"}'

    monkeypatch.setattr(basic_chat, "stream_chat", stream)
    await local_starter.classify_local_goal(
        goal="Predict moisture",
        intents=INTENTS,
        datasets=DATASETS + [{"key": "private-customer-batch", "kind": "project", "supports": ["calibrate"]}],
        user_id=7,
    )
    permission.assert_awaited_once_with(session, 7)
    assert ("private-customer-batch" in messages[0]) is allowed
    assert "corn" in messages[0]
