"""Phase 3: LLM Integration + MCP tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

import numpy as np
import pytest
from fastapi import HTTPException

from spectra_sherpa.app.lib.sherpa_dataset import (
    DomainContext,
    EvaluationResult,
    SherpaDataset,
    SpectralAxis,
)
from spectra_sherpa.app.services.dataset_registry import dataset_registry

# ---------------------------------------------------------------------------
# Slice 1: _summarize_metadata
# ---------------------------------------------------------------------------


class TestSummarizeMetadata:
    def test_full_context_returns_full_json(self):
        """Full subscribers get complete JSON metadata."""
        from spectra_sherpa.app.services.llm import LLMService

        with patch.object(LLMService, "__init__", return_value=None):
            svc = LLMService.__new__(LLMService)

        metadata = {"experiments": [{"name": "Test", "nodes": [{"type": "model.pca"}]}]}
        with patch.object(LLMService, "_has_full_context", return_value=True):
            result = svc._summarize_metadata(metadata)
        assert "model.pca" in result
        parsed = json.loads(result)
        assert parsed["experiments"][0]["name"] == "Test"

    def test_basic_context_strips_details(self):
        """Free-tier users get only technique + node types."""
        from spectra_sherpa.app.services.llm import LLMService

        with patch.object(LLMService, "__init__", return_value=None):
            svc = LLMService.__new__(LLMService)

        metadata = {
            "experiments": [
                {
                    "name": "Test",
                    "technique": "IR",
                    "nodes": [{"type": "model.pca", "parameters": {"n_components": 5}}],
                }
            ]
        }
        with patch.object(LLMService, "_has_full_context", return_value=False):
            result = svc._summarize_metadata(metadata)
        parsed = json.loads(result)
        # Should have technique but not parameter values
        assert parsed["experiments"][0]["technique"] == "IR"
        assert "node_types" in parsed["experiments"][0]
        # Parameters should be stripped
        assert "nodes" not in parsed["experiments"][0]


class TestLlmStorage:
    def test_conversation_store_uses_llm_dialog_subdirectory(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import spectra_sherpa.app.core.config as config_mod
        from spectra_sherpa.app.services.llm import ConversationStore

        monkeypatch.setattr(config_mod, "settings", SimpleNamespace(data_dir=tmp_path))

        store = ConversationStore()

        assert store._state_path == tmp_path / "llm_dialogs" / "conversations.json"

    def test_load_reference_pdf_uses_explicit_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import spectra_sherpa.app.services.llm as llm_mod
        from spectra_sherpa.app.services.llm import LLMService

        class _FakePage:
            def extract_text(self) -> str:
                return "Reference content"

        class _FakeReader:
            def __init__(self, _fh) -> None:
                self.pages = [_FakePage()]

        pdf_path = tmp_path / "references" / "example.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4\n%fake\n")

        monkeypatch.setattr(llm_mod, "_reference_pdf_cache", {})
        monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=_FakeReader))

        with patch.object(LLMService, "__init__", return_value=None):
            svc = LLMService.__new__(LLMService)

        assert svc._load_reference_pdf(pdf_path) == "Reference content"


# ---------------------------------------------------------------------------
# Slice 1b: local BYOK vs server contextual channel
# ---------------------------------------------------------------------------


class TestChatContextRouting:
    def test_prepare_metadata_for_local_chat_drops_context_in_local_mode(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import spectra_sherpa.app.core.config as config_mod
        from spectra_sherpa.app.services.llm import LLMService

        monkeypatch.setattr(config_mod, "app_config", SimpleNamespace(mode="local"))

        metadata = {
            "workflow_context": {"nodes": [{"node_id": "n1"}]},
            "project_id": 42,
        }

        assert LLMService._prepare_metadata_for_local_chat(metadata) is None

    def test_prepare_metadata_for_local_chat_preserves_metadata_in_non_local_mode(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import spectra_sherpa.app.core.config as config_mod
        from spectra_sherpa.app.services.llm import LLMService

        monkeypatch.setattr(config_mod, "app_config", SimpleNamespace(mode="hybrid"))

        metadata = {
            "workflow_context": {"nodes": [{"node_id": "n1"}]},
            "project_id": 42,
        }

        assert LLMService._prepare_metadata_for_local_chat(metadata) == metadata

    @pytest.mark.asyncio
    async def test_handle_llm_chat_local_route_keeps_metadata_and_skips_context_gate(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectra_sherpa.app.services import ws_handlers

        ws = SimpleNamespace(send_json=AsyncMock())
        user = SimpleNamespace(id=7)
        rate_limiter = SimpleNamespace(allow=lambda _key: True)
        local_chat = AsyncMock()
        permission_calls: list[str] = []

        async def _check_permission(_user, permission: str, **_kwargs):
            permission_calls.append(permission)
            return True

        monkeypatch.setattr(ws_handlers, "_should_use_server_chat", lambda: False)
        monkeypatch.setattr(ws_handlers, "_local_llm_chat", local_chat)
        monkeypatch.setattr(ws_handlers, "check_egress_permission", _check_permission)

        payload = {
            "message": "hello",
            "metadata": {
                "workflow_context": {"nodes": [{"node_id": "n1"}]},
                "project_id": 42,
            },
        }

        await ws_handlers.handle_llm_chat(ws, payload, user, rate_limiter)

        local_chat.assert_awaited_once()
        metadata = local_chat.await_args.args[3]
        assert metadata["project_id"] == 42
        assert metadata["workflow_context"]["nodes"][0]["node_id"] == "n1"
        assert permission_calls == ["allow_llm_chat"]

    @pytest.mark.asyncio
    async def test_handle_llm_chat_blocks_when_ai_chat_disabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectra_sherpa.app.services import ws_handlers

        ws = SimpleNamespace(send_json=AsyncMock())
        user = SimpleNamespace(id=7)
        rate_limiter = SimpleNamespace(allow=lambda _key: True)
        local_chat = AsyncMock()

        async def _check_permission(_user, permission: str, **_kwargs):
            assert permission == "allow_llm_chat"
            return False

        monkeypatch.setattr(ws_handlers, "_should_use_server_chat", lambda: False)
        monkeypatch.setattr(ws_handlers, "_local_llm_chat", local_chat)
        monkeypatch.setattr(ws_handlers, "check_egress_permission", _check_permission)

        await ws_handlers.handle_llm_chat(ws, {"message": "hello"}, user, rate_limiter)

        local_chat.assert_not_awaited()
        ws.send_json.assert_awaited_once_with(
            {
                "type": "error",
                "detail": "AI chat is disabled in user privacy settings.",
            }
        )

    @pytest.mark.asyncio
    async def test_handle_llm_chat_server_route_applies_context_gate(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectra_sherpa.app.services import ws_handlers

        ws = SimpleNamespace(send_json=AsyncMock())
        user = SimpleNamespace(id=7)
        rate_limiter = SimpleNamespace(allow=lambda _key: True)
        server_chat = AsyncMock()
        permission_calls: list[str] = []

        async def _check_permission(_user, permission: str, **_kwargs):
            permission_calls.append(permission)
            if permission == "allow_llm_chat":
                return True
            if permission == "allow_llm_context":
                return False
            raise AssertionError(f"Unexpected permission check: {permission}")

        monkeypatch.setattr(ws_handlers, "_should_use_server_chat", lambda: True)
        monkeypatch.setattr(ws_handlers, "_proxy_server_chat", server_chat)
        monkeypatch.setattr(ws_handlers, "check_egress_permission", _check_permission)

        payload = {
            "message": "hello",
            "metadata": {
                "workflow_context": {"nodes": [{"node_id": "n1"}]},
                "project_id": 42,
                "experiments": [{"name": "Corn"}],
            },
        }

        await ws_handlers.handle_llm_chat(ws, payload, user, rate_limiter)

        server_chat.assert_awaited_once()
        metadata = server_chat.await_args.args[3]
        assert metadata["project_id"] == 42
        assert metadata["experiments"][0]["name"] == "Corn"
        assert "workflow_context" not in metadata
        assert permission_calls == ["allow_llm_chat", "allow_llm_context"]

    @pytest.mark.asyncio
    async def test_handle_llm_chat_superuser_bypasses_rate_limit(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectra_sherpa.app.services import ws_handlers

        ws = SimpleNamespace(send_json=AsyncMock())
        user = SimpleNamespace(id=7, is_superuser=True)
        rate_limiter = SimpleNamespace(allow=lambda _key: False)
        local_chat = AsyncMock()

        async def _check_permission(_user, permission: str, **_kwargs):
            assert permission == "allow_llm_chat"
            return True

        monkeypatch.setattr(ws_handlers, "_should_use_server_chat", lambda: False)
        monkeypatch.setattr(ws_handlers, "_local_llm_chat", local_chat)
        monkeypatch.setattr(ws_handlers, "check_egress_permission", _check_permission)

        await ws_handlers.handle_llm_chat(ws, {"message": "hello"}, user, rate_limiter)

        local_chat.assert_awaited_once()
        ws.send_json.assert_not_awaited()


class TestHttpLlmRateLimits:
    def test_superuser_bypasses_http_llm_rate_limit(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectra_sherpa.app.api.v1.routes import llm as llm_routes

        monkeypatch.setattr(llm_routes._llm_rate_limiter, "allow", lambda _key: False)

        llm_routes._check_llm_rate_limit(SimpleNamespace(id=1, is_superuser=True))

    @pytest.mark.asyncio
    async def test_handle_llm_chat_server_route_keeps_context_when_allowed(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectra_sherpa.app.services import ws_handlers

        ws = SimpleNamespace(send_json=AsyncMock())
        user = SimpleNamespace(id=7)
        rate_limiter = SimpleNamespace(allow=lambda _key: True)
        server_chat = AsyncMock()
        permission_calls: list[str] = []

        async def _check_permission(_user, permission: str, **_kwargs):
            permission_calls.append(permission)
            return True

        monkeypatch.setattr(ws_handlers, "_should_use_server_chat", lambda: True)
        monkeypatch.setattr(ws_handlers, "_proxy_server_chat", server_chat)
        monkeypatch.setattr(ws_handlers, "check_egress_permission", _check_permission)

        payload = {
            "message": "hello",
            "metadata": {
                "workflow_context": {"nodes": [{"node_id": "n1"}]},
                "project_id": 42,
            },
        }

        await ws_handlers.handle_llm_chat(ws, payload, user, rate_limiter)

        server_chat.assert_awaited_once()
        metadata = server_chat.await_args.args[3]
        assert metadata["workflow_context"]["nodes"][0]["node_id"] == "n1"
        assert permission_calls == ["allow_llm_chat", "allow_llm_context"]

    @pytest.mark.asyncio
    async def test_handle_llm_chat_server_route_skips_context_gate_without_workflow_context(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectra_sherpa.app.services import ws_handlers

        ws = SimpleNamespace(send_json=AsyncMock())
        user = SimpleNamespace(id=7)
        rate_limiter = SimpleNamespace(allow=lambda _key: True)
        server_chat = AsyncMock()
        permission_calls: list[str] = []

        async def _check_permission(_user, permission: str, **_kwargs):
            permission_calls.append(permission)
            return True

        monkeypatch.setattr(ws_handlers, "_should_use_server_chat", lambda: True)
        monkeypatch.setattr(ws_handlers, "_proxy_server_chat", server_chat)
        monkeypatch.setattr(ws_handlers, "check_egress_permission", _check_permission)

        payload = {
            "message": "hello",
            "metadata": {
                "project_id": 42,
                "experiments": [{"name": "Corn"}],
            },
        }

        await ws_handlers.handle_llm_chat(ws, payload, user, rate_limiter)

        server_chat.assert_awaited_once()
        metadata = server_chat.await_args.args[3]
        assert metadata["project_id"] == 42
        assert metadata["experiments"][0]["name"] == "Corn"
        assert permission_calls == ["allow_llm_chat"]

    @pytest.mark.asyncio
    async def test_proxy_server_chat_forwards_project_context_and_translates_sse(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectra_sherpa.app.services import ws_handlers

        ws = SimpleNamespace(send_json=AsyncMock())
        captured: dict[str, object] = {}

        async def _fake_stream_llm_chat(
            self, *, message, conversation_id=None, workflow_context=None, local_user_id=None, project_id=None
        ):
            captured["message"] = message
            captured["conversation_id"] = conversation_id
            captured["local_user_id"] = local_user_id
            captured["project_id"] = project_id
            yield {"type": "start", "conversation_id": "conv-1"}
            yield {"type": "chunk", "conversation_id": "conv-1", "text": "Hello"}
            yield {"type": "done", "conversation_id": "conv-1"}

        class _Advisor:
            is_available = True
            stream_llm_chat = _fake_stream_llm_chat

        monkeypatch.setattr(
            "spectra_sherpa.app.services.sherpa_advisor.get_sherpa_advisor",
            lambda: _Advisor(),
        )

        metadata = {
            "project_id": 42,
            "workflow_context": {"nodes": [{"node_id": "n1"}]},
        }
        user = SimpleNamespace(id=7)

        await ws_handlers._proxy_server_chat(ws, "hello", "conv-1", metadata, user)

        assert captured["message"] == "hello"
        assert captured["local_user_id"] == 7
        assert captured["project_id"] == 42
        assert ws.send_json.await_args_list == [
            call({"type": "llm_start", "conversation_id": "conv-1"}),
            call({"type": "llm_chunk", "conversation_id": "conv-1", "chunk": "Hello"}),
            call({"type": "llm_done", "conversation_id": "conv-1"}),
        ]

    @pytest.mark.asyncio
    async def test_proxy_server_chat_stops_after_done_event(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectra_sherpa.app.services import ws_handlers

        ws = SimpleNamespace(send_json=AsyncMock())

        async def _fake_stream_llm_chat(self, **_kwargs):
            yield {"type": "start", "conversation_id": "conv-1"}
            yield {"type": "chunk", "conversation_id": "conv-1", "text": "Hello"}
            yield {"type": "done", "conversation_id": "conv-1"}
            raise AssertionError("proxy continued reading after done")

        class _Advisor:
            is_available = True
            stream_llm_chat = _fake_stream_llm_chat

        monkeypatch.setattr(
            "spectra_sherpa.app.services.sherpa_advisor.get_sherpa_advisor",
            lambda: _Advisor(),
        )

        await ws_handlers._proxy_server_chat(
            ws,
            "hello",
            "conv-1",
            {"project_id": 42, "workflow_context": {"nodes": [{"node_id": "n1"}]}},
            SimpleNamespace(id=7),
        )

        assert ws.send_json.await_args_list == [
            call({"type": "llm_start", "conversation_id": "conv-1"}),
            call({"type": "llm_chunk", "conversation_id": "conv-1", "chunk": "Hello"}),
            call({"type": "llm_done", "conversation_id": "conv-1"}),
        ]

    @pytest.mark.asyncio
    async def test_proxy_server_chat_forwards_warning_events_without_stopping_stream(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectra_sherpa.app.services import ws_handlers

        ws = SimpleNamespace(send_json=AsyncMock())

        async def _fake_stream_llm_chat(self, **_kwargs):
            yield {"type": "start", "conversation_id": "conv-1"}
            yield {
                "type": "warning",
                "conversation_id": "conv-1",
                "code": "history_load_failed",
                "message": "Conversation history could not be loaded.",
            }
            yield {"type": "chunk", "conversation_id": "conv-1", "text": "Hello"}
            yield {"type": "done", "conversation_id": "conv-1"}

        class _Advisor:
            is_available = True
            stream_llm_chat = _fake_stream_llm_chat

        monkeypatch.setattr(
            "spectra_sherpa.app.services.sherpa_advisor.get_sherpa_advisor",
            lambda: _Advisor(),
        )

        await ws_handlers._proxy_server_chat(
            ws,
            "hello",
            "conv-1",
            {"project_id": 42},
            SimpleNamespace(id=7),
        )

        assert ws.send_json.await_args_list == [
            call({"type": "llm_start", "conversation_id": "conv-1"}),
            call(
                {
                    "type": "llm_warning",
                    "conversation_id": "conv-1",
                    "detail": "Conversation history could not be loaded.",
                    "code": "history_load_failed",
                }
            ),
            call({"type": "llm_chunk", "conversation_id": "conv-1", "chunk": "Hello"}),
            call({"type": "llm_done", "conversation_id": "conv-1"}),
        ]

    @pytest.mark.asyncio
    async def test_proxy_server_chat_surfaces_upstream_error_detail(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectra_sherpa.app.services import ws_handlers
        from spectra_sherpa.app.services.ai_provider_errors import SherpaAuthorizationError

        ws = SimpleNamespace(send_json=AsyncMock())

        async def _fake_stream_llm_chat(self, **_kwargs):
            raise SherpaAuthorizationError("Invalid deployment key")
            yield  # make it an async generator  # noqa: E501

        class _Advisor:
            is_available = True
            stream_llm_chat = _fake_stream_llm_chat

        monkeypatch.setattr(
            "spectra_sherpa.app.services.sherpa_advisor.get_sherpa_advisor",
            lambda: _Advisor(),
        )

        await ws_handlers._proxy_server_chat(
            ws,
            "hello",
            "conv-1",
            {"project_id": 42},
            SimpleNamespace(id=7),
        )

        ws.send_json.assert_awaited_once_with(
            {"type": "error", "detail": "Server chat authorization failed: Invalid deployment key"}
        )

    @pytest.mark.asyncio
    async def test_proxy_server_chat_does_not_raise_when_client_disconnects_during_error_reporting(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectra_sherpa.app.services import ws_handlers
        from spectra_sherpa.app.services.ai_provider_errors import SherpaAuthorizationError

        ws = SimpleNamespace(send_json=AsyncMock(side_effect=RuntimeError("WebSocket disconnected")))

        async def _fake_stream_llm_chat(self, **_kwargs):
            raise SherpaAuthorizationError("Invalid deployment key")
            yield  # pragma: no cover

        class _Advisor:
            is_available = True
            stream_llm_chat = _fake_stream_llm_chat

        monkeypatch.setattr(
            "spectra_sherpa.app.services.sherpa_advisor.get_sherpa_advisor",
            lambda: _Advisor(),
        )

        await ws_handlers._proxy_server_chat(
            ws,
            "hello",
            "conv-1",
            {"project_id": 42},
            SimpleNamespace(id=7),
        )

    @pytest.mark.asyncio
    async def test_local_llm_chat_closes_stream_after_completion(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectra_sherpa.app.services import ws_handlers

        class _NullAsyncSessionContext:
            async def __aenter__(self):
                return None

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _Stream:
            def __init__(self) -> None:
                self._chunks = iter(["Hello"])
                self.closed = False

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self._chunks)
                except StopIteration:
                    raise StopAsyncIteration

            async def aclose(self) -> None:
                self.closed = True

        stream = _Stream()

        class _LLMService:
            def __init__(self, _session, user=None) -> None:
                self.user = user

            async def stream_chat(self, *, message, conversation_id=None, metadata=None):
                assert message == "hello"
                return ("conv-1", stream)

        monkeypatch.setattr(ws_handlers, "async_session", lambda: _NullAsyncSessionContext())
        monkeypatch.setattr(ws_handlers, "LLMService", _LLMService)

        ws = SimpleNamespace(send_json=AsyncMock())

        await ws_handlers._local_llm_chat(
            ws,
            "hello",
            "conv-1",
            {"project_id": 42},
            SimpleNamespace(id=7),
        )

        assert stream.closed is True
        assert ws.send_json.await_args_list == [
            call({"type": "llm_start", "conversation_id": "conv-1"}),
            call({"type": "llm_chunk", "conversation_id": "conv-1", "chunk": "Hello"}),
            call({"type": "llm_done", "conversation_id": "conv-1"}),
        ]

    @pytest.mark.asyncio
    async def test_llm_server_proxy_maps_upstream_auth_failure_to_service_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import httpx

        from spectra_sherpa.app.api.v1.routes import llm as llm_routes
        from spectra_sherpa.app.services import spectrasherpa as sherpa_cfg_mod

        class _FakeResponse:
            status_code = 401
            text = '{"detail":"invalid deployment key"}'

            def json(self):
                return {"detail": "invalid deployment key"}

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def request(self, *args, **kwargs):
                return _FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: _FakeClient())
        monkeypatch.setattr(
            sherpa_cfg_mod,
            "spectrasherpa_config",
            SimpleNamespace(api_base_url="https://sherpa.example.com", api_key="deploy-key"),
        )

        with pytest.raises(HTTPException) as exc_info:
            await llm_routes._proxy_server_request(
                "GET",
                "/conversations",
                params={"local_user_id": 7, "project_id": 42},
            )

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == "Sherpa subscription service authorization failed."

    # Premium Sherpa WS handler tests (handle_sherpa_chat, handle_sherpa_chat_with_tools,
    # _sherpa_proxy_preamble, unary actions) moved to spectra-server test suite —
    # those handlers now live in spectrasherpa_server.ws_handlers.


class TestDeploymentAIProvider:
    def test_has_feature_matches_managed_server_capabilities(self) -> None:
        from spectra_sherpa.app.services.deployment_ai_provider import DeploymentAIProvider

        advisor = DeploymentAIProvider()

        assert advisor.has_feature("full_dag_context") is True
        assert advisor.has_feature("identify_peaks") is True
        assert advisor.has_feature("generate_code") is True
        assert advisor.has_feature("write_report") is True
        assert advisor.has_feature("data_story") is True
        assert advisor.has_feature("agentic_tools") is True
        assert advisor.has_feature("nonexistent_feature") is False

    @pytest.mark.asyncio
    async def test_chat_followup_streams_chunks_from_server(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import httpx

        from spectra_sherpa.app.services import spectrasherpa as sherpa_cfg_mod
        from spectra_sherpa.app.services.deployment_ai_provider import DeploymentAIProvider

        captured: dict[str, object] = {}

        class _FakeResponse:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def aiter_lines(self):
                yield 'data: {"type":"start","conversation_id":"conv-1"}'
                yield ""
                yield 'data: {"type":"chunk","text":"Hello"}'
                yield ""
                yield 'data: {"type":"chunk","text":" world"}'
                yield ""
                yield 'data: {"type":"done","conversation_id":"conv-1"}'
                yield ""

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, method, url, json, headers):
                captured["method"] = method
                captured["url"] = url
                captured["json"] = json
                captured["headers"] = headers
                return _FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: _FakeClient())
        monkeypatch.setattr(
            sherpa_cfg_mod,
            "spectrasherpa_config",
            SimpleNamespace(api_base_url="https://sherpa.example.com", api_key="deploy-key"),
        )

        advisor = DeploymentAIProvider()
        chunks = [
            chunk
            async for chunk in advisor.chat_followup(
                message="What does this show?",
                workflow_id=14,
                history=[{"role": "user", "content": "Earlier"}],
                workflow_context={"nodes": [{"node_id": "n1"}]},
            )
        ]

        assert chunks == ["Hello", " world"]
        assert captured["method"] == "POST"
        assert captured["url"] == "https://sherpa.example.com/api/v1/sherpa/chat"
        assert captured["headers"] == {"X-Deployment-Key": "deploy-key"}
        assert captured["json"] == {
            "message": "What does this show?",
            "workflow_id": 14,
            "history": [{"role": "user", "content": "Earlier"}],
            "workflow_context": {"nodes": [{"node_id": "n1"}]},
        }

    @pytest.mark.asyncio
    async def test_chat_followup_stops_on_done_without_waiting_for_socket_close(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import httpx

        from spectra_sherpa.app.services import spectrasherpa as sherpa_cfg_mod
        from spectra_sherpa.app.services.deployment_ai_provider import DeploymentAIProvider

        class _FakeResponse:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def aiter_lines(self):
                yield 'data: {"type":"start","conversation_id":"conv-1"}'
                yield ""
                yield 'data: {"type":"chunk","text":"Hello"}'
                yield ""
                yield 'data: {"type":"done","conversation_id":"conv-1"}'
                yield ""
                raise AssertionError("advisor continued reading after done")

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, method, url, json, headers):
                return _FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: _FakeClient())
        monkeypatch.setattr(
            sherpa_cfg_mod,
            "spectrasherpa_config",
            SimpleNamespace(api_base_url="https://sherpa.example.com", api_key="deploy-key"),
        )

        advisor = DeploymentAIProvider()
        chunks = [chunk async for chunk in advisor.chat_followup(message="What does this show?")]

        assert chunks == ["Hello"]

    @pytest.mark.asyncio
    async def test_chat_followup_parses_standard_multiline_sse_frames(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import httpx

        from spectra_sherpa.app.services import spectrasherpa as sherpa_cfg_mod
        from spectra_sherpa.app.services.deployment_ai_provider import DeploymentAIProvider

        class _FakeResponse:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def aiter_lines(self):
                yield 'data: {"type":"chunk",'
                yield 'data:"text":"Hello"}'
                yield ""
                yield 'data:{"type":"done"}'
                yield ""

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, method, url, json, headers):
                return _FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: _FakeClient())
        monkeypatch.setattr(
            sherpa_cfg_mod,
            "spectrasherpa_config",
            SimpleNamespace(api_base_url="https://sherpa.example.com", api_key="deploy-key"),
        )

        advisor = DeploymentAIProvider()
        chunks = [chunk async for chunk in advisor.chat_followup(message="What does this show?")]

        assert chunks == ["Hello"]

    @pytest.mark.asyncio
    async def test_request_json_maps_unauthorized_to_authorization_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import httpx

        from spectra_sherpa.app.services import spectrasherpa as sherpa_cfg_mod
        from spectra_sherpa.app.services.ai_provider_errors import SherpaAuthorizationError
        from spectra_sherpa.app.services.deployment_ai_provider import DeploymentAIProvider

        class _FakeResponse:
            status_code = 401

            def json(self):
                return {"detail": "Invalid deployment key"}

        class _FakeClient:
            async def request(self, method, url, json, headers):
                return _FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: _FakeClient())
        monkeypatch.setattr(
            sherpa_cfg_mod,
            "spectrasherpa_config",
            SimpleNamespace(api_base_url="https://sherpa.example.com", api_key="deploy-key"),
        )

        advisor = DeploymentAIProvider()
        with pytest.raises(SherpaAuthorizationError, match="Invalid deployment key"):
            await advisor._request_json("POST", "/sherpa/chat", json_body={"message": "hello"})

    @pytest.mark.asyncio
    async def test_sync_workflow_parses_recommendations(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import httpx

        from spectra_sherpa.app.schemas.sherpa import (
            EgressTier,
            WorkflowContextEdge,
            WorkflowContextNode,
            WorkflowStateSync,
        )
        from spectra_sherpa.app.services import spectrasherpa as sherpa_cfg_mod
        from spectra_sherpa.app.services.deployment_ai_provider import DeploymentAIProvider

        captured: dict[str, object] = {}

        class _FakeResponse:
            status_code = 200

            def json(self):
                return {
                    "recommendations": [
                        {
                            "suggestion_id": "s1",
                            "workflow_id": 14,
                            "category": "workflow_structure",
                            "title": "Sherpa Analysis",
                            "explanation": "Use PCA first.",
                            "patch": None,
                            "confidence": 0.85,
                            "status": "pending",
                        }
                    ]
                }

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def request(self, method, url, json, headers):
                captured["method"] = method
                captured["url"] = url
                captured["json"] = json
                captured["headers"] = headers
                return _FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: _FakeClient())
        monkeypatch.setattr(
            sherpa_cfg_mod,
            "spectrasherpa_config",
            SimpleNamespace(api_base_url="https://sherpa.example.com", api_key="deploy-key"),
        )

        advisor = DeploymentAIProvider()
        sync_msg = WorkflowStateSync(
            workflow_id=14,
            workflow_name="Demo",
            nodes=[WorkflowContextNode(node_id="n1", node_type="model.pca")],
            edges=[WorkflowContextEdge(from_node_id="n1", to_node_id="n2")],
        )

        recommendations = await advisor.sync_workflow(sync_msg, tier=EgressTier.SUMMARIES)

        assert len(recommendations) == 1
        assert recommendations[0].title == "Sherpa Analysis"
        assert captured["method"] == "POST"
        assert captured["url"] == "https://sherpa.example.com/api/v1/sherpa/sync"
        assert captured["headers"] == {"X-Deployment-Key": "deploy-key"}
        assert captured["json"]["workflow_id"] == 14
        assert captured["json"]["tier"] == "summaries"

    # test_advisor_is_available moved to spectra-server test suite.


# ---------------------------------------------------------------------------
# Slice 2: Dataset tool registration
# ---------------------------------------------------------------------------


class TestDatasetTools:
    def test_describe_dataset_registered(self):
        """describe_dataset tool is in the global registry."""
        import spectra_sherpa.app.services.tools.builtin  # noqa: F401
        from spectra_sherpa.app.services.tools.registry import tool_registry

        assert "describe_dataset" in tool_registry

    def test_get_dataset_quality_registered(self):
        """get_dataset_quality tool is in the global registry."""
        import spectra_sherpa.app.services.tools.builtin  # noqa: F401
        from spectra_sherpa.app.services.tools.registry import tool_registry

        assert "get_dataset_quality" in tool_registry

    def test_describe_dataset_returns_summary(self):
        """describe_dataset returns both summary and structured."""
        from spectra_sherpa.app.services.tools.builtin.datasets import describe_dataset

        ds = SherpaDataset(
            X=np.ones((5, 100)),
            feature_axis=SpectralAxis(values=np.linspace(400, 4000, 100), units="cm-1"),
            domain=DomainContext(technique="IR"),
            title="Test Spectra",
        )
        dataset_id = dataset_registry.register(ds)
        result = describe_dataset(dataset_id=dataset_id, tier=1)

        assert "summary" in result
        assert "structured" in result
        assert "Test Spectra" in result["summary"]
        assert result["structured"]["domain"]["technique"] == "IR"
        assert result["dataset_id"] == dataset_id

    def test_describe_dataset_tier0(self):
        """Tier 0 returns shape and domain only."""
        from spectra_sherpa.app.services.tools.builtin.datasets import describe_dataset

        ds = SherpaDataset(
            X=np.zeros((3, 50)),
            domain=DomainContext(technique="NIR"),
            title="NIR Data",
        )
        dataset_id = dataset_registry.register(ds)
        result = describe_dataset(dataset_id=dataset_id, tier=0)
        assert "3 samples" in result["summary"]
        assert "NIR" in result["summary"]

    def test_get_dataset_quality_empty(self):
        """get_dataset_quality with no evaluations."""
        from spectra_sherpa.app.services.tools.builtin.datasets import get_dataset_quality

        ds = SherpaDataset(X=np.zeros((5, 10)))
        dataset_id = dataset_registry.register(ds)
        result = get_dataset_quality(dataset_id=dataset_id)
        assert result["n_evaluations"] == 0
        assert result["snr"] is None
        assert result["dataset_id"] == dataset_id

    def test_get_dataset_quality_with_evaluation(self):
        """get_dataset_quality returns latest evaluation."""
        from spectra_sherpa.app.services.tools.builtin.datasets import get_dataset_quality

        ds = SherpaDataset(X=np.zeros((5, 10)))
        ev = EvaluationResult(evaluation_id="ev1", model_type="PLS", r2=0.95)
        ds.quality.add_evaluation(ev)
        dataset_id = dataset_registry.register(ds)
        result = get_dataset_quality(dataset_id=dataset_id)
        assert result["n_evaluations"] == 1
        assert result["latest"]["model_type"] == "PLS"
        assert result["latest"]["r2"] == 0.95

    def test_tools_have_data_category(self):
        """Both tools are in the data category."""
        import spectra_sherpa.app.services.tools.builtin  # noqa: F401
        from spectra_sherpa.app.services.tools.registry import tool_registry

        defn1, _ = tool_registry.get("describe_dataset")
        defn2, _ = tool_registry.get("get_dataset_quality")
        assert defn1.category.value == "data"
        assert defn2.category.value == "data"


# ---------------------------------------------------------------------------
# Slice 3: WorkflowContextNode domain fields
# ---------------------------------------------------------------------------


class TestWorkflowContextNodeDomain:
    def test_new_fields_serialize(self):
        """New domain fields serialize correctly."""
        from spectra_sherpa.app.schemas.sherpa import WorkflowContextNode

        node = WorkflowContextNode(
            node_id="n1",
            node_type="data.eigenvector",
            domain_technique="IR",
            domain_data_quantity="Absorbance",
            processing_stage="preprocessed",
            processing_effects=["normalized", "baseline_corrected"],
        )
        d = node.model_dump()
        assert d["domain_technique"] == "IR"
        assert d["domain_data_quantity"] == "Absorbance"
        assert d["processing_stage"] == "preprocessed"
        assert d["processing_effects"] == ["normalized", "baseline_corrected"]

    def test_new_fields_default_none(self):
        """New domain fields default to None."""
        from spectra_sherpa.app.schemas.sherpa import WorkflowContextNode

        node = WorkflowContextNode(node_id="n1", node_type="model.pca")
        assert node.domain_technique is None
        assert node.domain_data_quantity is None
        assert node.processing_stage is None
        assert node.processing_effects is None

    def test_roundtrip_json(self):
        """Domain fields survive JSON round-trip."""
        from spectra_sherpa.app.schemas.sherpa import WorkflowContextNode

        node = WorkflowContextNode(
            node_id="n1",
            node_type="preprocess.normalize",
            domain_technique="NIR",
            processing_effects=["normalized"],
        )
        json_str = node.model_dump_json()
        restored = WorkflowContextNode.model_validate_json(json_str)
        assert restored.domain_technique == "NIR"
        assert restored.processing_effects == ["normalized"]

    def test_existing_fields_preserved(self):
        """Existing fields still work alongside new domain fields."""
        from spectra_sherpa.app.schemas.sherpa import WorkflowContextNode

        node = WorkflowContextNode(
            node_id="n1",
            node_type="model.pca",
            label="PCA",
            parameters={"n_components": 3},
            result_shape=[10, 3],
            domain_technique="IR",
        )
        assert node.label == "PCA"
        assert node.parameters == {"n_components": 3}
        assert node.result_shape == [10, 3]
        assert node.domain_technique == "IR"


# ---------------------------------------------------------------------------
# Slice 4: NodePolicy
# ---------------------------------------------------------------------------


class TestNodePolicy:
    def test_node_policy_defaults(self):
        """NodePolicy has safe defaults."""
        from spectra_sherpa.app.services.dag.node_base import NodePolicy

        policy = NodePolicy()
        assert policy.safe_for_auto_apply is False
        assert policy.requires_human_review is True
        assert policy.data_egress_risk == "none"

    def test_node_metadata_without_policy(self):
        """NodeMetadata without policy defaults to None."""
        from spectra_sherpa.app.services.dag.node_base import NodeMetadata

        meta = NodeMetadata(
            node_type="test.node",
            category="test",
            label="Test",
            description="A test node",
        )
        assert meta.policy is None

    def test_node_metadata_with_policy(self):
        """NodeMetadata accepts a policy."""
        from spectra_sherpa.app.services.dag.node_base import NodeMetadata, NodePolicy

        policy = NodePolicy(
            safe_for_auto_apply=True,
            requires_human_review=False,
            data_egress_risk="metadata",
        )
        meta = NodeMetadata(
            node_type="test.node",
            category="test",
            label="Test",
            description="A test node",
            policy=policy,
        )
        assert meta.policy.safe_for_auto_apply is True
        assert meta.policy.requires_human_review is False
        assert meta.policy.data_egress_risk == "metadata"

    def test_snv_node_has_preprocessing_policy(self):
        """SNV node is tagged as safe for auto-apply."""
        from spectra_sherpa.app.services.dag.node_base import node_registry

        meta = node_registry.get_metadata("preprocess.normalize")
        assert meta.policy is not None
        assert meta.policy.safe_for_auto_apply is True
        assert meta.policy.requires_human_review is False
        assert meta.policy.data_egress_risk == "none"

    def test_export_node_has_output_policy(self):
        """Export node requires human review with full data egress."""
        from spectra_sherpa.app.services.dag.node_base import node_registry

        meta = node_registry.get_metadata("output.export")
        assert meta.policy is not None
        assert meta.policy.safe_for_auto_apply is False
        assert meta.policy.requires_human_review is True
        assert meta.policy.data_egress_risk == "full_data"

    def test_pca_node_has_modeling_policy(self):
        """PCA node requires human review, no data egress."""
        from spectra_sherpa.app.services.dag.node_base import node_registry

        meta = node_registry.get_metadata("model.pca")
        assert meta.policy is not None
        assert meta.policy.safe_for_auto_apply is False
        assert meta.policy.requires_human_review is True
        assert meta.policy.data_egress_risk == "none"

    def test_untagged_node_no_policy(self):
        """Nodes without explicit policy have None."""
        from spectra_sherpa.app.services.dag.node_base import node_registry

        # Plot node should not have a policy
        meta = node_registry.get_metadata("output.plot")
        assert meta.policy is None
