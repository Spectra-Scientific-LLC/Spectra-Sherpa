import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from spectra_sherpa.app.api.v1.routes import chat
from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.services import basic_chat, byok_reply
from spectra_sherpa.app.services.byok_evidence import InspectionRefused, WorkbenchView
from spectra_sherpa.app.services.chat_providers import ChatEndpointConfig
from tests.test_inspection_runs import run_facts  # noqa: F401


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setattr(app_config, "mode", "local")
    config = ChatEndpointConfig("ollama", "http://127.0.0.1:11434/v1", "", "fixture", True)
    monkeypatch.setattr(basic_chat, "get_config", lambda: config)
    monkeypatch.setattr(chat._chat_limiter, "allow", lambda *_: True)
    monkeypatch.delenv("SPECTRA_BYOK_CONTEXT_TOKENS", raising=False)
    return config


async def events(body):
    async def receive():
        return {"type": "http.request", "body": json.dumps(body).encode()}

    request = Request({"type": "http"}, receive)
    response = await chat.chat_stream(request, SimpleNamespace(id=77))
    return [json.loads(chunk.removeprefix("data: ")) async for chunk in response.body_iterator]


def reading(screen, **selection):
    return {"screen": screen, "project_id": 10, **selection}


async def test_missing_pair_and_privacy_refuse_without_provider(local, monkeypatch):
    monkeypatch.setattr(basic_chat, "stream_chat", AsyncMock(side_effect=AssertionError("provider called")))
    read = AsyncMock(side_effect=InspectionRefused("privacy_denied"))
    monkeypatch.setattr(chat, "read_workbench_evidence", read)
    missing = await events(
        {"message": "Can I compare this with my previous run?", "workbench_view": reading("results", run_id=42)}
    )
    assert missing[0] == {"type": "facts", "lines": [byok_reply.CHOOSE_PAIR]}
    unselected = await events({"message": "Explain the dataset", "workbench_view": reading("dataset")})
    assert unselected[0] == {"type": "notice", "text": byok_reply.DATASET_NOT_READY}
    read.assert_not_awaited()
    blocked = await events(
        {"message": "Compare absorbance and transmittance", "workbench_view": reading("dataset", dataset_id="data")}
    )
    assert blocked[0] == {"type": "notice", "text": byok_reply.PRIVACY_BLOCKED}
    assert read.await_args.args[1] == 77


async def test_facts_sources_and_provider_body_are_separate(local, monkeypatch):
    facts = {
        "get_run": {},
        "get_results": {
            "regression_results": [
                {
                    "role": "held_out_test",
                    "node_id": "eval",
                    "target": "protein",
                    "unit_context": {"value": "%", "state": "recorded"},
                    "metrics": {"rmse": 0.42, "r2": 0.93},
                }
            ],
            "classification_results": [],
        },
    }
    evidence = SimpleNamespace(
        view=WorkbenchView.model_validate(reading("results", run_id=42)),
        facts=facts,
        prediction={},
        revalidate=AsyncMock(),
    )
    monkeypatch.setattr(chat, "read_workbench_evidence", AsyncMock(return_value=evidence))
    captured = []

    async def handler(request):
        captured.append(json.loads(request.content))
        output = {"choices": [{"delta": {"content": "The other run is better."}}]}
        return httpx.Response(200, text=f"data: {json.dumps(output)}\n\ndata: [DONE]\n\n")

    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handler), **kw))
    body = {
        "message": "Explain what this means",
        "workbench_view": reading("results", run_id=42),
        "metadata": {"workflow_context": {"workflow_name": "Earlier private turn"}},
        "history": [{"role": "user", "content": "This must not be forwarded"}],
    }
    reply = await events(body)
    assert reply[0]["lines"] == ["Based on Run #42", "Held-out test · protein · RMSE 0.42 %, R² 0.93"]
    assert reply[0]["provider"] == "ollama" and reply[0]["model"] == "fixture"
    assert reply[1] == {"type": "chunk", "text": "The other run is better."}
    assert len(captured) == 1
    assert "Earlier private turn" not in str(captured)
    assert "This must not be forwarded" not in str(captured)
    assert "Based on Run #42" in captured[0]["messages"][0]["content"]
    assert captured[0]["messages"][-1] == {"role": "user", "content": body["message"]}
    assert evidence.revalidate.await_count == 2

    monkeypatch.setenv("SPECTRA_BYOK_CONTEXT_TOKENS", "256")
    captured.clear()
    reply = await events(body)
    assert reply[0]["lines"][-1] == byok_reply.CONTEXT_TOO_SMALL
    assert not captured


async def test_destination_change_prevents_dispatch(local, monkeypatch):
    altered = ChatEndpointConfig("ollama", "http://127.0.0.1:11435/v1", "", "fixture", True)
    current = local

    async def revalidate(_sessions):
        nonlocal current
        if evidence.revalidate.await_count == 2:
            current = altered

    evidence = SimpleNamespace(
        view=WorkbenchView.model_validate(reading("dataset", dataset_id="dataset")),
        facts={"describe_dataset": {"n_samples": 20}},
        prediction={},
        revalidate=AsyncMock(side_effect=revalidate),
    )
    monkeypatch.setattr(basic_chat, "get_config", lambda: current)
    monkeypatch.setattr(chat, "read_workbench_evidence", AsyncMock(return_value=evidence))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: pytest.fail("provider called after endpoint change"))
    reply = await events({"message": "Explain the dataset", "workbench_view": reading("dataset", dataset_id="dataset")})
    assert {"type": "notice", "text": byok_reply.CONFIG_CHANGED} in reply


async def test_hosted_route_does_not_process_view(local, monkeypatch):
    monkeypatch.setattr(app_config, "mode", "enterprise")
    read = AsyncMock()
    monkeypatch.setattr(chat, "read_workbench_evidence", read)
    with pytest.raises(HTTPException) as exc:
        await events({"message": "What is this?", "workbench_view": reading("results", run_id=42)})
    assert exc.value.status_code == 404
    read.assert_not_awaited()


async def test_fixed_pair_and_prediction_use_mcp_evidence_unchanged(run_facts):  # noqa: F811
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.services.byok_evidence import read_workbench_evidence
    from tests.test_inspection_runs import call

    sessions, grant, runs, actor = run_facts
    prediction = {
        "role": "prediction_only",
        "instrument_relation": "different",
        "calibration_instrument": "M5",
        "prediction_instrument": "MP5",
        "transfer_correction": "none",
        "held_out_accuracy_applies": False,
    }
    async with sessions() as session:
        run = await session.get(ExecutionRun, runs[0].id)
        run.source_metadata = {"prediction_context": prediction, "internal": "PRIVATE"}
        await session.commit()
    selected = [item.id for item in runs[:2]]
    view = WorkbenchView(screen="compare", project_id=grant.identity.project_id, run_ids=selected)
    pair = await read_workbench_evidence(sessions, actor.id, view)
    await pair.revalidate(sessions)
    expected = await call(run_facts, "compare_runs", {"run_ids": selected})
    assert pair.facts == {"compare_runs": expected}
    assert pair.prediction == {selected[0]: prediction}
    lines = byok_reply.reply_facts(pair)
    assert lines[0] == f"Based on Run #{selected[0]} and Run #{selected[1]}"
    assert any("different instrument" in line and "MP5" in line for line in lines)
    assert "PRIVATE" not in str(pair.facts)


@pytest.mark.parametrize("state", byok_reply.COMPARISON_LINES)
def test_each_comparison_state_has_fixed_copy(state):
    evidence = SimpleNamespace(
        view=WorkbenchView(screen="compare", project_id=1, run_ids=[1, 2]),
        facts={"compare_runs": {"sections": [{"role": "held_out", "state": state, "metric_values": {}}]}},
        prediction={},
    )
    assert byok_reply.reply_facts(evidence)[1] == f"Held-out · {byok_reply.COMPARISON_LINES[state]}"


def test_haiku_bounded_explanations_reserve_tokens_for_visible_text():
    from spectra_sherpa.app.services.chat_providers import ChatRequest
    from spectra_sherpa.app.services.chat_providers.anthropic import AnthropicMessagesProvider

    config = ChatEndpointConfig("anthropic", "https://api.anthropic.com/v1", "", "claude-haiku-5-5")
    compact = ChatRequest("Explain this result.", True, 1, None, max_tokens=256, bounded_explanation=True)
    plain = ChatRequest("Explain this result.", True, 1, None)
    assert AnthropicMessagesProvider._body(config, compact, stream=True)["thinking"] == {"type": "disabled"}
    assert "thinking" not in AnthropicMessagesProvider._body(config, plain, stream=True)


def test_chat_openapi_uses_runtime_workbench_view_schema():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(chat.router, prefix="/api/v1")
    request_schema = app.openapi()["paths"]["/api/v1/chat/stream"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    assert request_schema["required"] == ["message"]
    expected_view = WorkbenchView.model_json_schema()
    # FastAPI omits null defaults when serializing the OpenAPI document.
    for field in expected_view["properties"].values():
        if field.get("default") is None:
            field.pop("default", None)
    assert request_schema["properties"]["workbench_view"]["anyOf"] == [expected_view, {"type": "null"}]


async def test_plain_chat_remains_valid_without_workbench_view(local, monkeypatch):
    read = AsyncMock()
    monkeypatch.setattr(chat, "read_workbench_evidence", read)

    async def stream(message, **kwargs):
        assert message == "Explain PCA"
        assert "evidence_prompt" not in kwargs
        yield "Synthetic plain reply."

    monkeypatch.setattr(basic_chat, "stream_chat", stream)
    assert await events({"message": "Explain PCA"}) == [
        {"type": "chunk", "text": "Synthetic plain reply."},
        {"type": "done"},
    ]
    read.assert_not_awaited()


@pytest.mark.parametrize(
    ("screen", "selected"),
    [
        ("dataset", {"dataset_id": "dataset-a"}),
        ("workflow", {"workflow_id": 3}),
        ("results", {"run_id": 7}),
        ("compare", {"run_ids": [7, 8]}),
    ],
)
async def test_chat_accepts_each_workbench_view_and_rejects_cross_screen_selection(
    local, monkeypatch, screen, selected
):
    read = AsyncMock(side_effect=InspectionRefused("privacy_denied"))
    monkeypatch.setattr(chat, "read_workbench_evidence", read)
    valid = reading(screen, **selected)
    reply = await events({"message": "Explain this", "workbench_view": valid})
    assert reply[0] == {"type": "notice", "text": byok_reply.PRIVACY_BLOCKED}
    assert read.await_args.args[2] == WorkbenchView.model_validate(valid)

    foreign_field = {"workflow_id": 3} if screen == "dataset" else {"dataset_id": "dataset-a"}
    with pytest.raises(HTTPException) as exc:
        await events({"message": "Explain this", "workbench_view": {**valid, **foreign_field}})
    assert exc.value.status_code == 422
    assert read.await_count == 1
