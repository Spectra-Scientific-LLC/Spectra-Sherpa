"""One useful model call, broad scope, and transport-independent refusal framing."""

from types import SimpleNamespace

import pytest

from spectra_sherpa.app.contracts.scientific_query import (
    REFUSAL,
    SYSTEM_PROMPT,
    RefusalStream,
    clean_attention,
    scoped_prompt,
)
from spectra_sherpa.app.services import basic_chat
from spectra_sherpa.app.services.chat_providers import ChatEndpointConfig


@pytest.mark.parametrize("split", range(len(REFUSAL) + 1))
def test_refusal_at_every_chunk_boundary(split):
    stream = RefusalStream()
    actual = stream.feed(" " + REFUSAL[:split]) + stream.feed(REFUSAL[split:])
    actual += stream.feed("Unwanted extra output") + stream.finish()
    assert actual == REFUSAL
    assert stream.rejected


@pytest.mark.parametrize(
    "text",
    ["Inspect the PCA scores.", "Spectra Sherpa supports PCA.", 'A refusal says "' + REFUSAL + '".', "Spectra", ""],
)
def test_ordinary_text_and_incomplete_prefix_are_preserved(text):
    stream = RefusalStream()
    assert "".join(stream.feed(char) for char in text) + stream.finish() == text
    assert not stream.rejected


def test_scope_is_idempotent_broad_and_attention_bounded():
    assert scoped_prompt(scoped_prompt("Task")) == scoped_prompt("Task")
    assert "When uncertain" in SYSTEM_PROMPT
    assert clean_attention({"window": "data", "raw_samples": [1]}) is None
    assert clean_attention({"window": "results", "surface": "plot", "node_id": "pca-1"}).node_id == "pca-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query,answer", [("Why?", "Because validation uses held-out data."), ("Write a romance", REFUSAL)]
)
async def test_local_allow_and_refuse_each_use_exactly_one_call(monkeypatch, query, answer):
    calls = []

    async def stream(config, request, url):
        calls.append(request)
        for char in answer:
            yield char

    config = ChatEndpointConfig(
        provider="openai_compatible", url="https://provider.example/v1", key="synthetic", model="test"
    )
    monkeypatch.setattr(basic_chat, "is_configured", lambda: True)
    monkeypatch.setattr(basic_chat, "_is_safe_outbound_url", lambda *a, **k: (True, ""))
    monkeypatch.setattr(basic_chat, "get_config", lambda: config)
    monkeypatch.setattr(
        basic_chat,
        "get_chat_provider",
        lambda _: SimpleNamespace(stream=stream, request_url=lambda url: url + "/chat/completions"),
    )
    result = "".join(
        [x async for x in basic_chat.stream_chat(query, metadata={"active_attention": {"window": "data"}})]
    )
    assert result == answer
    assert len(calls) == 1
    assert calls[0].message == query
    assert SYSTEM_PROMPT in calls[0].system_prompt
    assert '"window":"data"' in calls[0].system_prompt
    assert calls[0].max_tokens is None  # normal provider budget, no 32-token classifier


@pytest.mark.asyncio
async def test_local_unconfigured_refuses_without_egress(monkeypatch):
    monkeypatch.setattr(basic_chat, "is_configured", lambda: False)
    with pytest.raises(ValueError, match="not configured"):
        _ = [x async for x in basic_chat.stream_chat("Explain PCA")]


def test_optimize_attention_carries_identifiers_only_and_campaign_guidance():
    from spectra_sherpa.app.contracts.scientific_query import attention_guidance, clean_attention

    focus = clean_attention({"window": "optimization", "campaign_id": "campaign-pls-001", "candidate_id": "cand-12"})
    assert focus is not None and focus.campaign_id == "campaign-pls-001" and focus.candidate_id == "cand-12"
    assert clean_attention({"window": "optimization", "campaign_id": "bad id"}) is None
    assert clean_attention({"window": "optimization", "campaign_id": "c1", "metrics": {"rmse": 1}}) is None
    assert "worth running" in attention_guidance({"window": "optimization", "campaign_id": "c1"})[0]
    assert "baseline" in attention_guidance({"window": "optimization", "campaign_id": "c1", "candidate_id": "x"})[0]
