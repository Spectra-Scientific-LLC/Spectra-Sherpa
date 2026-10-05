"""Minimal BYO chat client for OSS distributions.

This is a thin HTTP proxy to a user-configured chat endpoint. It does NOT
implement ``AIServiceProvider`` and does NOT import any vendor LLM SDKs.
No tools or agent loop. Optional local exchange history lasts for this process.

Configuration (environment variables):
    CHAT_ENDPOINT_PROVIDER  ``openai_compatible`` (default), ``anthropic``,
                            or ``ollama``.
    CHAT_ENDPOINT_URL       Provider base URL.
    CHAT_ENDPOINT_KEY       API key; required except for ``ollama``.
    CHAT_ENDPOINT_MODEL     Provider model identifier.
    CHAT_ENDPOINT_ALLOW_PRIVATE
                            Explicit consent to use a private/loopback model
                            endpoint, intended for a local model server.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlparse

from spectra_sherpa.app.services.chat_providers import ChatEndpointConfig, ChatRequest, get_chat_provider

logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 16_000
CHAT_ENDPOINT_URL = os.getenv("CHAT_ENDPOINT_URL", "")
CHAT_ENDPOINT_KEY = os.getenv("CHAT_ENDPOINT_KEY", "")
CHAT_ENDPOINT_MODEL = os.getenv("CHAT_ENDPOINT_MODEL", "deepseek-chat")
CHAT_ENDPOINT_PROVIDER = os.getenv("CHAT_ENDPOINT_PROVIDER", "openai_compatible")
CHAT_ENDPOINT_ALLOW_PRIVATE = os.getenv("CHAT_ENDPOINT_ALLOW_PRIVATE", "")


_ALLOW_PRIVATE_ENV = "SPECTRA_SHERPA_ALLOW_PRIVATE_LLM_ENDPOINTS"


def _is_safe_outbound_url(url: str, *, allow_private_endpoint: bool = False) -> tuple[bool, str]:
    """Return ``(ok, reason)`` for a user-supplied outbound URL.

    Used to defend the BYO chat endpoint validator against SSRF when the
    server-side process makes the request: a user could otherwise pass
    ``http://169.254.169.254/`` (cloud metadata) or ``http://localhost``
    addresses and turn the validator into a confused deputy.

    The check rejects:
      - non-``http(s)`` schemes (``file://``, ``gopher://``, etc.)
      - hostnames that resolve into private/loopback/link-local /
        multicast / reserved / unspecified IP ranges

    Set ``SPECTRA_SHERPA_ALLOW_PRIVATE_LLM_ENDPOINTS=true`` to bypass the
    private-IP check; that is intended for OSS users running their own
    local LLM (e.g. Ollama on ``localhost:11434``) where the SSRF threat
    model does not apply.
    """
    try:
        parsed = urlparse(url)
    except Exception:  # pragma: no cover — defensive
        return False, "URL could not be parsed."
    if parsed.scheme not in ("http", "https"):
        return False, "Only http(s) URLs are allowed."
    host = parsed.hostname
    if not host:
        return False, "URL must include a host."

    if allow_private_endpoint or os.getenv(_ALLOW_PRIVATE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
        return True, ""

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False, "Hostname could not be resolved."

    for info in infos:
        addr_str = info[4][0]
        try:
            ip = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, "Endpoint resolves to a private or restricted IP address."
    return True, ""


def validate_endpoint_url(
    endpoint_url: str,
    *,
    provider: str = "openai_compatible",
    allow_private_endpoint: bool = False,
) -> tuple[bool, str]:
    """Validate a configured local-assistance endpoint base URL."""
    ok, reason, _url = validated_chat_completions_url(
        endpoint_url,
        provider=provider,
        allow_private_endpoint=allow_private_endpoint,
    )
    return ok, reason


def validated_chat_completions_url(
    endpoint_url: str,
    *,
    provider: str = "openai_compatible",
    allow_private_endpoint: bool = False,
) -> tuple[bool, str, str | None]:
    """Validate and canonicalize a supported provider's request URL."""
    base_url = endpoint_url.strip().rstrip("/")
    if not base_url:
        return False, "API base URL is required.", None
    try:
        request_url = get_chat_provider(provider).request_url(base_url)
    except ValueError as exc:
        return False, str(exc), None
    ok, reason = _is_safe_outbound_url(request_url, allow_private_endpoint=allow_private_endpoint)
    return (ok, reason, request_url if ok else None)


def get_config() -> ChatEndpointConfig:
    """Read BYO chat configuration at request time.

    The settings endpoint updates ``os.environ`` after writing ``.env``. Reading
    here avoids ``importlib.reload()`` races while streams are in flight.
    """
    return ChatEndpointConfig(
        provider=os.getenv("CHAT_ENDPOINT_PROVIDER", CHAT_ENDPOINT_PROVIDER),
        url=os.getenv("CHAT_ENDPOINT_URL", CHAT_ENDPOINT_URL),
        key=_endpoint_key(),
        model=os.getenv("CHAT_ENDPOINT_MODEL", CHAT_ENDPOINT_MODEL),
        allow_private_endpoint=os.getenv("CHAT_ENDPOINT_ALLOW_PRIVATE", CHAT_ENDPOINT_ALLOW_PRIVATE).strip().lower()
        in {"1", "true", "yes", "on"},
    )


ENCRYPTED_KEY_ENV = "CHAT_ENDPOINT_KEY_ENCRYPTED"


def _endpoint_key() -> str:
    from spectra_sherpa.app.services.encryption import credential_storage_available

    if not credential_storage_available():
        # Desktop without OS protection: a plaintext key is never used.
        return ""
    return os.getenv("CHAT_ENDPOINT_KEY", CHAT_ENDPOINT_KEY) or _decrypted_endpoint_key()


def _decrypted_endpoint_key() -> str:
    """Key saved encrypted at rest (desktop, OS-protected key); '' if unreadable."""
    token = os.getenv(ENCRYPTED_KEY_ENV, "").strip()
    if not token:
        return ""
    from spectra_sherpa.app.services.encryption import decrypt_value

    try:
        return decrypt_value(token)
    except Exception:
        logger.warning("Saved AI provider key cannot be read on this computer; re-enter it in Settings.")
        return ""


def encrypts_endpoint_key_at_rest() -> bool:
    """Only an OS-protected key makes at-rest encryption meaningful."""
    from spectra_sherpa.app.services.encryption import has_process_master_key

    return has_process_master_key()


def persist_endpoint_key(env_path: str, key: str) -> None:
    """Write the endpoint key to ``.env``: encrypted when possible, else as before."""
    from dotenv import set_key, unset_key

    from spectra_sherpa.app.core.desktop_policy import refuse_linked_configuration
    from spectra_sherpa.app.services.encryption import CredentialStorageUnavailable, credential_storage_available

    if not credential_storage_available():
        raise CredentialStorageUnavailable()
    refuse_linked_configuration(env_path)
    if encrypts_endpoint_key_at_rest():
        from spectra_sherpa.app.services.encryption import encrypt_value

        set_key(env_path, ENCRYPTED_KEY_ENV, encrypt_value(key) if key else "")
        unset_key(env_path, "CHAT_ENDPOINT_KEY", quote_mode="never")
        os.environ[ENCRYPTED_KEY_ENV] = encrypt_value(key) if key else ""
    else:
        set_key(env_path, "CHAT_ENDPOINT_KEY", key)


def protect_plaintext_endpoint_key(env_paths) -> bool:
    """Migrate a plaintext ``CHAT_ENDPOINT_KEY`` in a profile ``.env`` to encrypted form."""
    if not encrypts_endpoint_key_at_rest():
        return False
    from dotenv import dotenv_values

    migrated = False
    for env_path in env_paths:
        if not Path(env_path).is_file():
            continue
        plaintext = (dotenv_values(env_path).get("CHAT_ENDPOINT_KEY") or "").strip()
        if plaintext:
            persist_endpoint_key(str(env_path), plaintext)
            migrated = True
    return migrated


def is_configured() -> bool:
    """Return whether the selected local-assistance transport has its required configuration."""
    config = get_config()
    try:
        chat_provider = get_chat_provider(config.provider)
    except ValueError:
        return False
    return bool(config.url and (config.key or not chat_provider.requires_key))


async def stream_chat(
    message: str,
    *,
    verbose: bool = True,
    max_paragraphs: int = 2,
    metadata: dict | None = None,
    exchange_owner: int | None = None,
) -> AsyncIterator[str]:
    """Stream a single-turn chat completion from the configured endpoint.

    Yields text chunks as they arrive. Raises ``ValueError`` if the
    endpoint is not configured.
    """
    if not is_configured():
        raise ValueError("BYO chat endpoint not configured. Check the provider, endpoint URL, and API key.")
    if len(message) > MAX_INPUT_CHARS:
        raise ValueError("Chat message is too long.")

    config = get_config()
    ok, reason, request_url = validated_chat_completions_url(
        config.url,
        provider=config.provider,
        allow_private_endpoint=config.allow_private_endpoint,
    )
    if not ok or request_url is None:
        raise ValueError(reason)
    chat_provider = get_chat_provider(config.provider)
    from spectra_sherpa.app.contracts.scientific_query import RefusalStream, clean_attention, scoped_prompt

    focus = clean_attention((metadata or {}).get("active_attention"))
    attention_prompt = (
        "UI attention hint (not scientific evidence or authorization): " + focus.model_dump_json(exclude_none=True)
        if focus
        else None
    )
    request = ChatRequest(
        message=message,
        verbose=verbose,
        max_paragraphs=max_paragraphs,
        metadata=metadata,
        system_prompt=scoped_prompt(attention_prompt),
    )
    from spectra_sherpa.app.core.mode_policy import is_local
    from spectra_sherpa.app.services.chat_exchange import Exchange, _active

    exchange = (
        Exchange(exchange_owner, config.provider, config.model, (config.key,))
        if (is_local() and exchange_owner is not None)
        else None
    )
    token = _active.set(exchange)
    completion = "interrupted"
    output = RefusalStream()
    try:
        async for chunk in chat_provider.stream(config, request, request_url):
            if exchange:
                exchange.append(chunk)
            if text := output.feed(chunk):
                yield text
        if text := output.finish():
            yield text
        completion = "refused" if output.rejected else "completed"
    except Exception:
        completion = "failed"
        raise
    finally:
        if exchange:
            exchange.finish(completion)
        _active.reset(token)


async def test_connection(
    endpoint_url: str,
    endpoint_key: str,
    model: str,
    *,
    provider: str = "openai_compatible",
    allow_private_endpoint: bool = False,
) -> tuple[bool, str]:
    """Validate a supported BYO chat endpoint without saving it."""
    key = endpoint_key.strip()
    try:
        chat_provider = get_chat_provider(provider)
    except ValueError as exc:
        return False, str(exc)
    if chat_provider.requires_key and not key:
        return False, "API key is required."

    ok, reason, url = validated_chat_completions_url(
        endpoint_url,
        provider=provider,
        allow_private_endpoint=allow_private_endpoint,
    )
    if not ok or url is None:
        return False, reason
    config = ChatEndpointConfig(
        provider=provider,
        url=endpoint_url,
        key=key,
        model=model.strip() or "deepseek-chat",
        allow_private_endpoint=allow_private_endpoint,
    )
    return await chat_provider.test_connection(config, url)
