from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Optional, Union

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import APIKey
from app.models.llm_config import LLMConfig
from app.models.user import User
from app.services.encryption import decrypt_value
from app.core.llm_registry import get_provider, get_default_provider
from app.core.security import check_egress_permission, is_egress_enabled

# Anthropic import - will be available when installed
try:
    from anthropic import AsyncAnthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    AsyncAnthropic = None  # type: ignore

DEFAULT_SYSTEM_PROMPT = "You are a master of all things spectral data analysis."

# Default LLM configurations (cost-effective choices)
# - DeepSeek: deepseek-chat ($0.27/M input, $1.10/M output)
# - OpenAI: gpt-5-mini
# - Gemini: gemini-2.5-flash
DEFAULT_PROVIDER = "deepseek"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com"

MAX_HISTORY_MESSAGES = 40

# Cache for PDF reference content (loaded once)
_spectrochempy_pdf_cache: Optional[str] = None
_pdf_cache_loaded = False


class ConversationStore:
    """
    User-scoped conversation storage.

    SECURITY: Conversations are stored with user_id to prevent cross-user access.
    A user can only access conversations that belong to them.
    """

    def __init__(self) -> None:
        # {conversation_id: {"user_id": int, "messages": [...]}}
        self._conversations: dict[str, dict[str, Any]] = {}

    def get(self, conversation_id: str, user_id: Optional[int] = None) -> Optional[list[dict[str, str]]]:
        """Get conversation messages if user has access."""
        conv = self._conversations.get(conversation_id)
        if conv is None:
            return None
        # If user_id provided, validate ownership
        if user_id is not None and conv.get("user_id") != user_id:
            return None  # Access denied - wrong user
        return conv.get("messages")

    def get_or_create(
        self, conversation_id: Optional[str], user_id: int
    ) -> tuple[str, list[dict[str, str]]]:
        """Get existing conversation (if owned by user) or create new one."""
        if conversation_id and conversation_id in self._conversations:
            conv = self._conversations[conversation_id]
            # Validate ownership before returning
            if conv.get("user_id") == user_id:
                return conversation_id, conv["messages"]
            # Wrong user - create new conversation instead of denying
            # (the old conversation_id was for a different user)

        new_id = conversation_id if conversation_id and conversation_id not in self._conversations else str(uuid.uuid4())
        self._conversations[new_id] = {"user_id": user_id, "messages": []}
        return new_id, self._conversations[new_id]["messages"]

    def delete(self, conversation_id: str, user_id: Optional[int] = None) -> bool:
        """Delete conversation if user has access."""
        conv = self._conversations.get(conversation_id)
        if conv is None:
            return False
        # If user_id provided, validate ownership
        if user_id is not None and conv.get("user_id") != user_id:
            return False  # Access denied - wrong user
        return self._conversations.pop(conversation_id, None) is not None

    def trim(self, conversation_id: str) -> None:
        """Trim conversation to max history length."""
        conv = self._conversations.get(conversation_id)
        if conv and len(conv["messages"]) > MAX_HISTORY_MESSAGES:
            conv["messages"] = conv["messages"][-MAX_HISTORY_MESSAGES:]


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
        # Egress check for external LLM providers
        config = await self._get_llm_config()
        if not self._is_local_provider(config["provider"]):
            if not is_egress_enabled():
                raise ValueError(
                    "Network egress is disabled. Enable EGRESS_ENABLED=true or set APP_MODE=hybrid "
                    "to use external LLM providers."
                )
            if not await check_egress_permission(
                self.user,
                "allow_llm_context",
                data_type="metadata",
                destination="llm_context",
                session=self.session,
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
            system_msg = next(
                (m["content"] for m in payload if m["role"] == "system"),
                DEFAULT_SYSTEM_PROMPT
            )
            user_msgs = [m for m in payload if m["role"] != "system"]

            response = await client.messages.create(
                model=config["model"],
                max_tokens=4096,
                system=system_msg,
                messages=user_msgs
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
        return conversation_id, content

    async def stream_chat(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> tuple[str, AsyncIterator[str]]:
        """Stream chat response"""
        # Egress check for external LLM providers
        config = await self._get_llm_config()
        if not self._is_local_provider(config["provider"]):
            if not is_egress_enabled():
                raise ValueError(
                    "Network egress is disabled. Enable EGRESS_ENABLED=true or set APP_MODE=hybrid "
                    "to use external LLM providers."
                )
            if not await check_egress_permission(
                self.user,
                "allow_llm_context",
                data_type="metadata",
                destination="llm_context",
                session=self.session,
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
            system_msg = next(
                (m["content"] for m in payload if m["role"] == "system"),
                DEFAULT_SYSTEM_PROMPT
            )
            user_msgs = [m for m in payload if m["role"] != "system"]

            stream = await client.messages.create(
                model=config["model"],
                max_tokens=4096,
                system=system_msg,
                messages=user_msgs,
                stream=True
            )

            async def anthropic_generator() -> AsyncIterator[str]:
                chunks: list[str] = []
                async for event in stream:
                    if event.type == "content_block_delta":
                        delta = event.delta.text
                        chunks.append(delta)
                        yield delta
                history.append({"role": "assistant", "content": "".join(chunks)})
                conversation_store.trim(conversation_id)

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
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if not delta:
                        continue
                    chunks.append(delta)
                    yield delta
                history.append({"role": "assistant", "content": "".join(chunks)})
                conversation_store.trim(conversation_id)

            return conversation_id, openai_generator()

    async def suggest_name(self, components: list[str]) -> str:
        prompt = (
            "Generate a concise experiment name (<=5 words) for these components: "
            + ", ".join(components)
        )
        return await self._single_turn(prompt)

    async def identify_peaks(
        self, wavenumbers: list[float], absorbance: list[float]
    ) -> str:
        payload = {
            "wavenumbers": wavenumbers,
            "absorbance": absorbance,
            "instructions": "Identify likely peaks with approximate positions.",
        }
        prompt = f"Analyze this spectrum data and identify peaks:\n{json.dumps(payload)[:8000]}"
        return await self._single_turn(prompt)

    async def generate_code(self, task_description: str) -> str:
        prompt = f"Write Python code for the following task:\n{task_description}"
        return await self._single_turn(prompt)

    async def write_report(self, experiment: dict[str, Any]) -> str:
        prompt = (
            "Write a concise scientific report for the following experiment context:\n"
            + json.dumps(experiment, default=str)[:8000]
        )
        return await self._single_turn(prompt)

    async def _single_turn(self, prompt: str) -> str:
        """Single-turn LLM request (used for utility functions)"""
        # Egress check for external LLM providers
        config = await self._get_llm_config()
        if not self._is_local_provider(config["provider"]):
            if not is_egress_enabled():
                raise ValueError(
                    "Network egress is disabled. Enable EGRESS_ENABLED=true or set APP_MODE=hybrid "
                    "to use external LLM providers."
                )
            if not await check_egress_permission(
                self.user,
                "allow_llm_context",
                data_type="metadata",
                destination="llm_context",
                session=self.session,
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
                messages=[{"role": "user", "content": prompt}]
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

        result = await self.session.execute(
            select(LLMConfig).where(LLMConfig.user_id == user_id)
        )
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
                raise ImportError(
                    "Anthropic SDK not installed. Install with: pip install anthropic"
                )
            return AsyncAnthropic(api_key=api_key)
        else:
            # OpenAI-compatible providers
            return AsyncOpenAI(api_key=api_key, base_url=config["base_url"])

    async def _resolve_api_key(self, provider: str) -> str:
        """
        Resolve API key with unified priority:
        1. Environment variable (system-wide)
        2. User's own key from database (BYOK)
        3. SpectraSherpa managed key (HYBRID mode)
        4. System key from database

        Args:
            provider: Provider identifier (e.g., 'openai', 'anthropic')

        Returns:
            API key string

        Raises:
            ValueError: If no API key found in any source
        """
        import logging
        from app.core.config import app_config

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
            user_key_query = select(APIKey).where(
                APIKey.service_name == provider,
                APIKey.user_id == self.user.id
            )
            result = await self.session.execute(user_key_query)
            user_key = result.scalar_one_or_none()

            if user_key:
                logger.info(f"Using {provider} API key from user's BYOK (id={user_key.id})")
                user_key.last_used_at = datetime.now(timezone.utc)
                await self.session.commit()
                return decrypt_value(user_key.key_encrypted)

        # Priority 3: Check SpectraSherpa managed keys (HYBRID and DEMO modes)
        if app_config.mode in ("hybrid", "demo"):
            try:
                from app.services.spectrasherpa import get_spectrasherpa_service
                spectrasherpa = get_spectrasherpa_service()

                if spectrasherpa.is_configured:
                    managed_keys = await spectrasherpa.get_managed_llm_keys()
                    for key in managed_keys:
                        if key.provider == provider:
                            # Check if key is expired
                            if key.expires_at and key.expires_at < datetime.now(timezone.utc):
                                logger.warning(f"SpectraSherpa managed key for {provider} is expired")
                                continue
                            logger.info(f"Using {provider} API key from SpectraSherpa managed keys")
                            return key.api_key
            except Exception as e:
                logger.warning(f"Failed to fetch SpectraSherpa managed keys: {e}")

        # Priority 4: Check system key in database
        system_key_query = select(APIKey).where(
            APIKey.service_name == provider,
            APIKey.user_id == None
        )
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
            f"{provider_meta['name']} API key not configured. "
            f"Set {provider_meta['env_var']} environment variable or add via /api/v1/api-keys"
        )

    def _build_messages(
        self,
        history: list[dict[str, str]],
        metadata: Optional[dict[str, Any]],
        config: dict[str, Any]
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

            # Add full metadata
            context_parts.append(json.dumps(metadata, default=str))
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
                from pypdf import PdfReader
                import logging
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
                _spectrochempy_pdf_cache = f"Reference PDF available at: {pdf_path}\n(PDF extraction not available - install pypdf)"
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
