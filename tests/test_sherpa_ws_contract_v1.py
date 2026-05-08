"""Consumer-driven contract tests for Sherpa WS events (OSS side).

Validates that:
1. The published sherpa-ws-v1.json schema is loadable and well-formed.
2. Every event type constant in ws_events.py has a matching schema definition.
3. DisabledAIProvider error responses match the published schema.
4. Sample valid and invalid events are correctly accepted/rejected.
"""

from __future__ import annotations

import pytest

from spectra_sherpa.app.contracts.ws_schema_validator import load_ws_schema, validate_ws_event
from spectra_sherpa.app.ws_events import SHERPA_WS_EVENTS


def test_schema_loads_successfully():
    """The published schema file exists and parses as valid JSON."""
    schema = load_ws_schema()
    assert schema["title"] == "Sherpa WebSocket Events v1"
    assert "definitions" in schema
    assert "oneOf" in schema


def test_all_event_types_have_schema_definitions():
    """Every event constant in ws_events.py has a matching definition."""
    schema = load_ws_schema()
    defined = set(schema["definitions"].keys()) - {"timing"}
    event_constants = set(SHERPA_WS_EVENTS)

    missing = event_constants - defined
    assert not missing, f"Event types missing schema definitions: {missing}"


def test_valid_chat_start_event():
    validate_ws_event(
        {
            "type": "sherpa_chat_start",
            "request_id": "abc123",
            "conversation_id": "conv-1",
        }
    )


def test_valid_chat_chunk_event():
    validate_ws_event(
        {
            "type": "sherpa_chat_chunk",
            "request_id": "abc123",
            "conversation_id": "conv-1",
            "chunk": "Hello, ",
        }
    )


def test_valid_chat_done_event():
    validate_ws_event(
        {
            "type": "sherpa_chat_done",
            "request_id": "abc123",
            "conversation_id": "conv-1",
            "chunk_count": 5,
            "first_chunk_ms": 120,
        }
    )


def test_valid_error_event():
    validate_ws_event(
        {
            "type": "sherpa_error",
            "request_id": "abc123",
            "detail": "Something went wrong",
            "code": "feature_disabled",
        }
    )


def test_valid_status_event():
    validate_ws_event(
        {
            "type": "sherpa_status",
            "request_id": "abc123",
            "payload": {
                "connected": True,
                "stage": "model_dispatch",
                "detail": "Preparing request...",
            },
        }
    )


def test_valid_subscription_required_event():
    validate_ws_event(
        {
            "type": "sherpa_subscription_required",
            "detail": "Feature requires a subscription",
        }
    )


def test_valid_recommendations_event():
    validate_ws_event(
        {
            "type": "sherpa_recommendations",
            "request_id": "abc123",
            "payload": [{"suggestion_id": "s1", "category": "preprocessing", "title": "Add SNV"}],
        }
    )


def test_valid_decision_ack_event():
    validate_ws_event(
        {
            "type": "sherpa_decision_ack",
            "request_id": "abc123",
            "payload": {"delivered": True, "suggestion_id": "s1"},
        }
    )


def test_invalid_event_missing_required_field():
    """An error event without 'detail' should fail validation."""
    from jsonschema import ValidationError

    with pytest.raises(ValidationError):
        validate_ws_event(
            {
                "type": "sherpa_error",
                "request_id": "abc123",
                # missing 'detail'
            }
        )


def test_invalid_event_wrong_chunk_type():
    """A chat chunk with non-string chunk should fail validation."""
    from jsonschema import ValidationError

    with pytest.raises(ValidationError):
        validate_ws_event(
            {
                "type": "sherpa_chat_chunk",
                "chunk": 42,  # should be string
            }
        )


@pytest.mark.asyncio
async def test_byo_chat_stream_sse_events_are_well_formed():
    """The OSS basic_chat /chat/stream SSE output is machine-parseable.

    This is the only OSS-emitted chat surface post-yank. Validates that
    the SSE frames use the {type, text}/{type: done}/{type, detail: error}
    envelope the frontend expects.
    """
    import json
    from collections.abc import AsyncIterator
    from unittest.mock import patch

    async def _fake_stream(
        message: str,
        *,
        verbose: bool = True,
        max_paragraphs: int = 2,
        metadata: dict | None = None,
    ) -> AsyncIterator[str]:
        yield "chunk one"
        yield " chunk two"

    with patch("spectra_sherpa.app.core.mode_policy.is_local", return_value=True):
        with patch("spectra_sherpa.app.services.basic_chat.is_configured", return_value=True):
            with patch("spectra_sherpa.app.services.basic_chat.stream_chat", side_effect=_fake_stream):
                from spectra_sherpa.app.api.v1.routes.chat import chat_stream

                # Build a minimal fake request
                class FakeRequest:
                    async def json(self):
                        return {"message": "test"}

                class FakeUser:
                    id = 1

                response = await chat_stream(request=FakeRequest(), user=FakeUser())

                # Collect SSE frames from the streaming response body
                frames = []
                async for chunk in response.body_iterator:
                    if chunk.startswith("data: "):
                        frames.append(json.loads(chunk[6:].strip()))

    assert len(frames) == 3  # 2 chunks + 1 done
    assert frames[0]["type"] == "chunk"
    assert isinstance(frames[0]["text"], str)
    assert frames[1]["type"] == "chunk"
    assert frames[2]["type"] == "done"
