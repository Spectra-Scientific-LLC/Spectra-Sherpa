from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Optional, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.core.llm_registry import get_default_provider, get_provider
from spectra_sherpa.app.core.security import check_egress_permission
from spectra_sherpa.app.models.api_key import APIKey
from spectra_sherpa.app.models.llm_config import LLMConfig
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.encryption import decrypt_value

# Optional LLM SDK imports — available when extras are installed
try:
    from openai import AsyncOpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    AsyncOpenAI = None  # type: ignore

try:
    from anthropic import AsyncAnthropic

    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    AsyncAnthropic = None  # type: ignore

DEFAULT_SYSTEM_PROMPT = "You are a master of all things spectral data analysis."

DEFAULT_PROVIDER = "deepseek"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com"

MAX_HISTORY_MESSAGES = 40

# Cache for PDF reference content (loaded once)
_spectrochempy_pdf_cache: Optional[str] = None
_pdf_cache_loaded = False


class ConversationStore:
    """
    User-scoped conversation storage backed by a JSON file.

    SECURITY: Conversations are stored with user_id to prevent cross-user access.
    A user can only access conversations that belong to them.

    The file-backed design ensures:
    - Conversations survive worker/container restarts
    - State is visible across Gunicorn workers (file is shared)
    - Concurrent access is safe via fcntl file locking
    """

    MAX_CONVERSATIONS_PER_USER = 50
    CONVERSATION_TTL_HOURS = 72  # Auto-expire after 3 days of inactivity

    def __init__(self, state_path: Optional[Path] = None) -> None:
        from spectra_sherpa.app.core.config import settings

        self._state_path = state_path or (settings.data_dir / "conversations.json")
        self._state_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, dict[str, Any]]:
        """Load conversations from disk."""
        if not self._state_path.exists():
            return {}
        try:
            import json

            data = json.loads(self._state_path.read_text())
            # Expire old conversations
            now = time.time()
            ttl_sec = self.CONVERSATION_TTL_HOURS * 3600
            return {cid: conv for cid, conv in data.items() if now - conv.get("updated_at", 0) < ttl_sec}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        """Atomically write conversations to disk."""
        import json

        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, default=str))
        tmp.replace(self._state_path)

    @contextmanager
    def _locked(self):
        """File lock for concurrent worker access."""
        try:
            import fcntl

            lock_path = self._state_path.with_suffix(".lock")
            fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
        except ImportError:
            yield  # No locking on Windows — acceptable for local dev

    def get(self, conversation_id: str, user_id: Optional[int] = None) -> Optional[list[dict[str, str]]]:
        """Get conversation messages if user has access."""
        with self._locked():
            data = self._load()
        conv = data.get(conversation_id)
        if conv is None:
            return None
        if user_id is not None and conv.get("user_id") != user_id:
            return None
        return conv.get("messages")

    def get_or_create(self, conversation_id: Optional[str], user_id: int) -> tuple[str, list[dict[str, str]]]:
        """Get existing conversation (if owned by user) or create new one."""
        with self._locked():
            data = self._load()

            if conversation_id and conversation_id in data:
                conv = data[conversation_id]
                if conv.get("user_id") == user_id:
                    conv["updated_at"] = time.time()
                    self._save(data)
                    return conversation_id, conv["messages"]

            # Enforce per-user limit
            user_convs = [cid for cid, c in data.items() if c.get("user_id") == user_id]
            if len(user_convs) >= self.MAX_CONVERSATIONS_PER_USER:
                # Remove oldest
                oldest = min(user_convs, key=lambda cid: data[cid].get("updated_at", 0))
                del data[oldest]

            new_id = conversation_id if (conversation_id and conversation_id not in data) else str(uuid.uuid4())
            data[new_id] = {"user_id": user_id, "messages": [], "updated_at": time.time()}
            self._save(data)
            return new_id, data[new_id]["messages"]

    def save_messages(self, conversation_id: str, messages: list[dict[str, str]]) -> None:
        """Persist updated messages for a conversation."""
        with self._locked():
            data = self._load()
            if conversation_id in data:
                data[conversation_id]["messages"] = messages[-MAX_HISTORY_MESSAGES:]
                data[conversation_id]["updated_at"] = time.time()
                self._save(data)

    def delete(self, conversation_id: str, user_id: Optional[int] = None) -> bool:
        """Delete conversation if user has access."""
        with self._locked():
            data = self._load()
            conv = data.get(conversation_id)
            if conv is None:
                return False
            if user_id is not None and conv.get("user_id") != user_id:
                return False
            del data[conversation_id]
            self._save(data)
            return True

    def trim(self, conversation_id: str) -> None:
        """Trim conversation to max history length."""
        with self._locked():
            data = self._load()
            conv = data.get(conversation_id)
            if conv and len(conv["messages"]) > MAX_HISTORY_MESSAGES:
                conv["messages"] = conv["messages"][-MAX_HISTORY_MESSAGES:]
                self._save(data)


conversation_store = ConversationStore()


class LLMService:
    def __init__(self, session: AsyncSession, user: User) -> None:
        self.session = session
        self.user = user

    async def chat(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> tuple[str, str]:
        """Send chat message and get response (non-streaming)"""
        # Egress check for external LLM providers.
        # User-initiated BYOK chat bypasses the global egress flag — the user
        # explicitly provided their API key and typed a message, which is consent.
        config = await self._get_llm_config()
        if not self._is_local_provider(config["provider"]):
            if not await check_egress_permission(
                self.user,
                "allow_llm_context",
                data_type="metadata",
                destination="llm_context",
                session=self.session,
                skip_global_check=True,
            ):
                raise ValueError("LLM context sharing is disabled in user privacy settings.")

        user_id = self.user.id
        conversation_id, history = conversation_store.get_or_create(conversation_id, user_id)
        history.append({"role": "user", "content": message})

        client = await self._client(config)
        payload = self._build_messages(history, metadata, config)

        provider_meta = get_provider(config["provider"])

        # Use appropriate API format based on client type
        if provider_meta["client_type"] == "anthropic":
            # Anthropic format: separate system message from conversation
            system_msg = next((m["content"] for m in payload if m["role"] == "system"), DEFAULT_SYSTEM_PROMPT)
            user_msgs = [m for m in payload if m["role"] != "system"]

            response = await client.messages.create(
                model=config["model"], max_tokens=4096, system=system_msg, messages=user_msgs
            )
            content = response.content[0].text
        else:
            # OpenAI-compatible format
            response = await client.chat.completions.create(
                model=config["model"],
                messages=payload,
                stream=False,
            )
            content = response.choices[0].message.content or ""

        history.append({"role": "assistant", "content": content})
        conversation_store.trim(conversation_id)
        conversation_store.save_messages(conversation_id, history)
        return conversation_id, content

    async def stream_chat(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> tuple[str, AsyncIterator[str]]:
        """Stream chat response"""
        # Egress check for external LLM providers.
        # User-initiated BYOK chat bypasses the global egress flag.
        config = await self._get_llm_config()
        if not self._is_local_provider(config["provider"]):
            if not await check_egress_permission(
                self.user,
                "allow_llm_context",
                data_type="metadata",
                destination="llm_context",
                session=self.session,
                skip_global_check=True,
            ):
                raise ValueError("LLM context sharing is disabled in user privacy settings.")

        user_id = self.user.id
        conversation_id, history = conversation_store.get_or_create(conversation_id, user_id)
        history.append({"role": "user", "content": message})

        client = await self._client(config)
        payload = self._build_messages(history, metadata, config)

        provider_meta = get_provider(config["provider"])

        # Create appropriate stream based on client type
        if provider_meta["client_type"] == "anthropic":
            # Anthropic streaming format
            system_msg = next((m["content"] for m in payload if m["role"] == "system"), DEFAULT_SYSTEM_PROMPT)
            user_msgs = [m for m in payload if m["role"] != "system"]

            stream = await client.messages.create(
                model=config["model"], max_tokens=4096, system=system_msg, messages=user_msgs, stream=True
            )

            async def anthropic_generator() -> AsyncIterator[str]:
                chunks: list[str] = []
                try:
                    async for event in stream:
                        if event.type == "content_block_delta":
                            delta = event.delta.text
                            chunks.append(delta)
                            yield delta
                finally:
                    # Save conversation (full or partial) on completion or interruption
                    if chunks:
                        history.append({"role": "assistant", "content": "".join(chunks)})
                    conversation_store.trim(conversation_id)
                    conversation_store.save_messages(conversation_id, history)

            return conversation_id, anthropic_generator()
        else:
            # OpenAI-compatible streaming format
            stream = await client.chat.completions.create(
                model=config["model"],
                messages=payload,
                stream=True,
            )

            async def openai_generator() -> AsyncIterator[str]:
                chunks: list[str] = []
                try:
                    async for chunk in stream:
                        delta = chunk.choices[0].delta.content
                        if not delta:
                            continue
                        chunks.append(delta)
                        yield delta
                finally:
                    # Save conversation (full or partial) on completion or interruption
                    if chunks:
                        history.append({"role": "assistant", "content": "".join(chunks)})
                    conversation_store.trim(conversation_id)
                    conversation_store.save_messages(conversation_id, history)

            return conversation_id, openai_generator()

    async def stream_chat_with_tools(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        max_rounds: int = 5,
    ) -> tuple[str, "AsyncIterator[dict[str, Any]]"]:
        """Chat with tool-calling support for plugin generation.

        Returns (conversation_id, event_iterator) where events are dicts:
        - {"type": "tool_start", "tool_name": ..., "arguments": ...}
        - {"type": "tool_result", "tool_name": ..., "success": ..., "summary": ...}
        - {"type": "chunk", "text": ...}
        """
        import logging

        from spectra_sherpa.app.services.llm_prompts import PLUGIN_GEN_SYSTEM_PROMPT
        from spectra_sherpa.app.services.tools.executor import (
            ToolExecutionContext,
            execute_tool,
        )
        from spectra_sherpa.app.services.tools.registry import tool_registry
        from spectra_sherpa.app.services.tools.schemas import (
            ToolCategory,
            ToolInvocation,
        )

        logger = logging.getLogger(__name__)

        # Egress check
        config = await self._get_llm_config()
        if not self._is_local_provider(config["provider"]):
            if not await check_egress_permission(
                self.user,
                "allow_llm_context",
                data_type="metadata",
                destination="llm_context",
                session=self.session,
                skip_global_check=True,
            ):
                raise ValueError("LLM context sharing is disabled in user privacy settings.")

        user_id = self.user.id
        conversation_id, history = conversation_store.get_or_create(conversation_id, user_id)
        history.append({"role": "user", "content": message})

        client = await self._client(config)
        provider_meta = get_provider(config["provider"])
        is_anthropic = provider_meta["client_type"] == "anthropic"

        # Get tool definitions filtered to data category
        if is_anthropic:
            tools = tool_registry.to_anthropic_tools(category=ToolCategory.data)
        else:
            tools = tool_registry.to_openai_tools(category=ToolCategory.data)

        # Build conversation with plugin-gen system prompt
        system_prompt = PLUGIN_GEN_SYSTEM_PROMPT
        if not config.get("verbose", True):
            system_prompt += "\n\nProvide concise responses."

        tool_ctx = ToolExecutionContext(session=self.session, user=self.user)

        async def event_generator() -> AsyncIterator[dict[str, Any]]:
            # Working copy of messages for the LLM
            llm_messages: list[dict[str, Any]] = []
            llm_messages.append({"role": "user", "content": message})

            # Add metadata context if present
            if metadata:
                context_str = self._summarize_metadata(metadata)
                llm_messages.insert(0, {"role": "system", "content": f"Context:\n{context_str}"})

            final_text = ""

            for round_num in range(max_rounds):
                logger.info("Tool-calling round %d/%d", round_num + 1, max_rounds)

                try:
                    if is_anthropic:
                        response = await self._call_anthropic_with_tools(
                            client, config, system_prompt, llm_messages, tools
                        )
                        tool_calls, text = self._parse_anthropic_tool_response(response)
                    else:
                        response = await self._call_openai_with_tools(
                            client, config, system_prompt, llm_messages, tools
                        )
                        tool_calls, text = self._parse_openai_tool_response(response)
                except Exception as e:
                    logger.exception("LLM call failed in tool round %d", round_num + 1)
                    yield {"type": "chunk", "text": f"\n\nError calling LLM: {e}"}
                    break

                # If we got text, emit it
                if text:
                    final_text += text

                # If no tool calls, we're done — emit text and break
                if not tool_calls:
                    if text:
                        yield {"type": "chunk", "text": text}
                    break

                # Process tool calls
                if is_anthropic:
                    # Append the full assistant response to messages
                    llm_messages.append({
                        "role": "assistant",
                        "content": response.content,
                    })
                else:
                    # Append the assistant message with tool_calls
                    assistant_msg = response.choices[0].message
                    llm_messages.append({
                        "role": "assistant",
                        "content": assistant_msg.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in assistant_msg.tool_calls
                        ],
                    })

                tool_result_blocks: list[dict[str, Any]] = []
                for tc_id, tc_name, tc_args in tool_calls:
                    yield {
                        "type": "tool_start",
                        "tool_name": tc_name,
                        "arguments": tc_args,
                    }

                    invocation = ToolInvocation(
                        tool_name=tc_name,
                        arguments=tc_args,
                    )
                    result = await execute_tool(
                        invocation, tool_ctx, allow_internal=True
                    )

                    summary = ""
                    if result.success:
                        summary = json.dumps(result.result, default=str)[:500]
                    else:
                        summary = result.error or "Unknown error"

                    yield {
                        "type": "tool_result",
                        "tool_name": tc_name,
                        "success": result.success,
                        "summary": summary,
                    }

                    # Append tool result for next LLM round
                    if is_anthropic:
                        tool_result_blocks.append(
                            result.to_anthropic_block(tc_id)
                        )
                    else:
                        llm_messages.append(
                            result.to_openai_message(tc_id)
                        )

                # For Anthropic, batch tool results into a single user message
                if is_anthropic and tool_result_blocks:
                    llm_messages.append({
                        "role": "user",
                        "content": tool_result_blocks,
                    })

                # If there was intermediate text with tool calls, emit it
                if text:
                    yield {"type": "chunk", "text": text}

            # Save final assistant response to conversation history
            if final_text:
                history.append({"role": "assistant", "content": final_text})
            conversation_store.trim(conversation_id)
            conversation_store.save_messages(conversation_id, history)

        return conversation_id, event_generator()

    async def _call_openai_with_tools(
        self,
        client: Any,
        config: dict[str, Any],
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        """Make a non-streaming OpenAI-compatible call with tools."""
        payload = [{"role": "system", "content": system_prompt}] + messages
        return await client.chat.completions.create(
            model=config["model"],
            messages=payload,
            tools=tools or None,
            stream=False,
        )

    async def _call_anthropic_with_tools(
        self,
        client: Any,
        config: dict[str, Any],
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        """Make a non-streaming Anthropic call with tools."""
        # Filter out system messages — Anthropic uses a separate system param
        user_msgs = [m for m in messages if m["role"] != "system"]
        return await client.messages.create(
            model=config["model"],
            max_tokens=4096,
            system=system_prompt,
            messages=user_msgs,
            tools=tools or None,
        )

    @staticmethod
    def _parse_openai_tool_response(
        response: Any,
    ) -> tuple[list[tuple[str, str, dict[str, Any]]], str]:
        """Parse OpenAI response into (tool_calls, text).

        Returns:
            tool_calls: list of (tool_call_id, function_name, arguments_dict)
            text: any text content from the response
        """
        message = response.choices[0].message
        text = message.content or ""
        tool_calls: list[tuple[str, str, dict[str, Any]]] = []

        if message.tool_calls:
            for tc in message.tool_calls:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                tool_calls.append((tc.id, tc.function.name, args))

        return tool_calls, text

    @staticmethod
    def _parse_anthropic_tool_response(
        response: Any,
    ) -> tuple[list[tuple[str, str, dict[str, Any]]], str]:
        """Parse Anthropic response into (tool_calls, text).

        Returns:
            tool_calls: list of (tool_use_id, tool_name, input_dict)
            text: any text content from the response
        """
        text_parts: list[str] = []
        tool_calls: list[tuple[str, str, dict[str, Any]]] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append((block.id, block.name, block.input or {}))

        return tool_calls, "".join(text_parts)

    async def write_data_story(
        self,
        dataset_info: dict[str, Any],
    ) -> str:
        """Generate a narrative 'data story' for a reference dataset."""
        context = json.dumps(dataset_info, indent=2, default=str)

        prompt = (
            "Write a concise, informative narrative about the following spectroscopy dataset. "
            "Include what the data measures, its scientific context, typical applications, "
            "and any notable characteristics (sample count, spectral range, reference properties). "
            "Write 2-3 paragraphs in a professional scientific tone.\n\n"
            "Dataset info:\n" + context
        )
        return await self._single_turn(prompt, bypass_egress=True)

    async def _single_turn(self, prompt: str, bypass_egress: bool = False) -> str:
        """Single-turn LLM request (used for utility functions)"""
        # Egress check for external LLM providers.
        # User-initiated BYOK chat bypasses the global egress flag.
        config = await self._get_llm_config()
        if not bypass_egress and not self._is_local_provider(config["provider"]):
            if not await check_egress_permission(
                self.user,
                "allow_llm_context",
                data_type="metadata",
                destination="llm_context",
                session=self.session,
                skip_global_check=True,
            ):
                raise ValueError("LLM context sharing is disabled in user privacy settings.")

        client = await self._client(config)

        provider_meta = get_provider(config["provider"])

        if provider_meta["client_type"] == "anthropic":
            # Anthropic format
            response = await client.messages.create(
                model=config["model"],
                max_tokens=4096,
                system=DEFAULT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        else:
            # OpenAI-compatible format
            response = await client.chat.completions.create(
                model=config["model"],
                messages=[
                    {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
            )
            return response.choices[0].message.content or ""

    async def _get_llm_config(self) -> dict[str, Any]:
        """
        Get LLM configuration with priority:
        1. User database config
        2. Environment variables
        3. Application defaults from registry
        """
        if not self.user:
            raise ValueError("LLMService requires a user context for configuration lookup")

        user_id = self.user.id

        result = await self.session.execute(select(LLMConfig).where(LLMConfig.user_id == user_id))
        user_config = result.scalar_one_or_none()

        if user_config:
            # User has saved preferences
            provider_meta = get_provider(user_config.provider)
            return {
                "provider": user_config.provider,
                "base_url": user_config.base_url or provider_meta["base_url"],
                "model": user_config.model,
                "verbose": user_config.verbose,
            }

        # Use environment/defaults from registry
        provider_id = get_default_provider()
        provider_meta = get_provider(provider_id)

        return {
            "provider": provider_id,
            "base_url": os.getenv("LLM_BASE_URL", provider_meta["base_url"]),
            "model": os.getenv("LLM_MODEL", provider_meta["default_model"]),
            "verbose": True,
        }

    async def _client(self, config: dict[str, Any]) -> Union[AsyncOpenAI, AsyncAnthropic]:
        """
        Create appropriate LLM client based on provider type.

        Returns:
            AsyncOpenAI for OpenAI-compatible providers (OpenAI, DeepSeek, Gemini)
            AsyncAnthropic for Anthropic providers
        """
        provider = config["provider"]
        provider_meta = get_provider(provider)
        api_key = await self._resolve_api_key(provider)

        import logging

        logger = logging.getLogger(__name__)
        logger.info(f"Creating {provider_meta['client_type']} client for provider={provider}, model={config['model']}")

        if provider_meta["client_type"] == "anthropic":
            if not ANTHROPIC_AVAILABLE:
                raise ImportError("Anthropic SDK not installed. Install with: pip install spectra-sherpa[sherpa]")
            return AsyncAnthropic(api_key=api_key)
        else:
            # OpenAI-compatible providers
            if not OPENAI_AVAILABLE:
                raise ImportError("OpenAI SDK not installed. Install with: pip install spectra-sherpa[sherpa]")
            return AsyncOpenAI(api_key=api_key, base_url=config["base_url"])

    async def _resolve_api_key(self, provider: str) -> str:
        """
        Resolve API key with unified priority:
        1. Environment variable (system-wide)
        2. User's own key from database (BYOK)
        3. System key from database

        Managed keys from Spectra-Server are no longer used as a fallback.
        Server-managed keys stay server-side; free chat is BYOK-only.

        Args:
            provider: Provider identifier (e.g., 'openai', 'anthropic')

        Returns:
            API key string

        Raises:
            ValueError: If no API key found in any source
        """
        import logging

        logger = logging.getLogger(__name__)
        logger.info(f"Resolving API key for provider: {provider}")

        # Get provider metadata from registry
        provider_meta = get_provider(provider)

        # Priority 1: Check environment variable
        env_key = os.getenv(provider_meta["env_var"])
        if env_key:
            logger.info(f"Using {provider} API key from environment variable {provider_meta['env_var']}")
            return env_key

        # Priority 2: Check user's own key in database (BYOK)
        if hasattr(APIKey, "user_id"):
            user_key_query = select(APIKey).where(APIKey.service_name == provider, APIKey.user_id == self.user.id)
            result = await self.session.execute(user_key_query)
            user_key = result.scalar_one_or_none()

            if user_key:
                logger.info(f"Using {provider} API key from user's BYOK (id={user_key.id})")
                user_key.last_used_at = datetime.now(timezone.utc)
                await self.session.commit()
                return decrypt_value(user_key.key_encrypted)

        # Priority 3: Check system key in database
        system_key_query = select(APIKey).where(APIKey.service_name == provider, APIKey.user_id.is_(None))
        result = await self.session.execute(system_key_query)
        system_key = result.scalar_one_or_none()

        if system_key:
            logger.info(f"Using {provider} API key from system database (id={system_key.id})")
            system_key.last_used_at = datetime.now(timezone.utc)
            await self.session.commit()
            return decrypt_value(system_key.key_encrypted)

        # No key found anywhere
        logger.error(f"{provider} API key not found in any source")
        raise ValueError(
            f"No LLM API key configured. "
            f"Set {provider_meta['env_var']} environment variable or add a key in Settings."
        )

    @staticmethod
    def _has_full_context() -> bool:
        """Check if the subscription allows full DAG context in LLM prompts."""
        try:
            from spectra_sherpa.app.services.sherpa_advisor import get_sherpa_advisor

            return get_sherpa_advisor().has_feature("full_dag_context")
        except Exception as e:
            # Log error for debugging but return False gracefully
            import logging

            logger = logging.getLogger(__name__)
            logger.debug(f"Failed to check full_dag_context feature: {e}")
            return False

    @staticmethod
    def _extract_basic_context(metadata: dict[str, Any]) -> dict[str, Any]:
        """Return a minimal context with only technique and node types.

        Free-tier users get structure-level context (what nodes exist)
        but not parameter values or dataset specifics.
        """
        basic: dict[str, Any] = {}
        if "experiments" in metadata:
            summaries = []
            for exp in metadata["experiments"]:
                summary: dict[str, Any] = {}
                if exp.get("name"):
                    summary["name"] = exp["name"]
                if exp.get("technique"):
                    summary["technique"] = exp["technique"]
                # Include node types but strip parameter values
                if exp.get("nodes"):
                    summary["node_types"] = list(
                        {n.get("type") or n.get("node_type", "unknown") for n in exp["nodes"] if isinstance(n, dict)}
                    )
                if summary:
                    summaries.append(summary)
            if summaries:
                basic["experiments"] = summaries
        return basic

    # Maximum characters for serialized metadata injected into LLM context.
    # Prevents token blowups from large workflow states.
    _MAX_METADATA_CHARS = 8000

    def _summarize_metadata(self, metadata: dict[str, Any]) -> str:
        """Format metadata for LLM context, tier-aware and size-bounded."""
        if self._has_full_context():
            raw = json.dumps(metadata, default=str)
        else:
            raw = json.dumps(self._extract_basic_context(metadata), default=str)
        if len(raw) > self._MAX_METADATA_CHARS:
            return raw[: self._MAX_METADATA_CHARS] + "...(truncated)"
        return raw

    def _build_messages(
        self, history: list[dict[str, str]], metadata: Optional[dict[str, Any]], config: dict[str, Any]
    ) -> list[dict[str, str]]:
        system_prompt = DEFAULT_SYSTEM_PROMPT

        # Add brevity instruction if verbose mode is disabled
        if not config.get("verbose", True):
            system_prompt += " Provide concise responses limited to 2 paragraphs or less."

        messages = [{"role": "system", "content": system_prompt}]

        # Add experiment metadata context
        if metadata:
            # Extract spectrochempy info for better context
            context_parts = []
            if "experiments" in metadata:
                for exp in metadata["experiments"]:
                    if exp.get("name") == "SpectrochemPy Test Data":
                        # Add directory info and PDF availability (not content)
                        exp_meta = exp.get("metadata", {})
                        if exp_meta.get("base_path"):
                            pdf_note = ""
                            if exp_meta.get("reference_pdf"):
                                pdf_note = f"\nReference PDF: {exp_meta['reference_pdf']} (available on request)"
                            context_parts.append(
                                f"SpectrochemPy test data location: {exp_meta['base_path']}\n"
                                f"Subdirectories: {', '.join(exp_meta.get('subdirectories', []))}\n"
                                f"Total files: {exp_meta.get('file_count', 0)}"
                                f"{pdf_note}"
                            )

            # Apply context tiering and add metadata as JSON context
            context_parts.append(self._summarize_metadata(metadata))
            messages.append({"role": "system", "content": "Context:\n" + "\n\n".join(context_parts)})

        messages.extend(history[-MAX_HISTORY_MESSAGES:])
        return messages

    def _load_spectrochempy_reference(self) -> Optional[str]:
        """Load the SpectrochemPy reference PDF if it exists (cached)."""
        global _spectrochempy_pdf_cache, _pdf_cache_loaded

        # Return cached content if already loaded
        if _pdf_cache_loaded:
            return _spectrochempy_pdf_cache

        # Mark as loaded to prevent repeated attempts
        _pdf_cache_loaded = True

        try:
            pdf_path = Path.home() / ".spectrochempy" / "spectrochempy_testdata_reference.pdf"
            if not pdf_path.exists():
                _spectrochempy_pdf_cache = None
                return None

            # Try to extract text from PDF
            try:
                import logging

                from pypdf import PdfReader

                logger = logging.getLogger(__name__)

                logger.info(f"Loading SpectrochemPy reference PDF from {pdf_path}")
                with open(pdf_path, "rb") as pdf_file:
                    reader = PdfReader(pdf_file)
                    text_parts = []
                    for page in reader.pages:
                        text_parts.append(page.extract_text())
                    _spectrochempy_pdf_cache = "\n\n".join(text_parts)
                    logger.info(f"PDF loaded successfully ({len(_spectrochempy_pdf_cache)} chars)")
                    return _spectrochempy_pdf_cache
            except ImportError:
                # pypdf not available, provide file path instead
                _spectrochempy_pdf_cache = (
                    f"Reference PDF available at: {pdf_path}\n(PDF extraction not available - install pypdf)"
                )
                return _spectrochempy_pdf_cache
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(f"Failed to extract PDF content: {e}")
                _spectrochempy_pdf_cache = f"Reference PDF available at: {pdf_path}\n(PDF extraction failed)"
                return _spectrochempy_pdf_cache
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug(f"Could not load spectrochempy reference: {e}")
            _spectrochempy_pdf_cache = None
            return None

    def _is_local_provider(self, provider: str) -> bool:
        """Check if the provider is local (no egress)."""
        # Dictionary of known local providers
        # 'ollama', 'localai', 'llamafile' etc.
        # For now, we assume all providers in registry are external unless marked otherwise.
        # This is a safe default for "default no egress".
        return provider in ("ollama", "local", "test")
