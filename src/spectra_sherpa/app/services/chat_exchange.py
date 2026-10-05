"""Bounded, process-local history of basic BYOK exchanges; never a remote log."""

from __future__ import annotations

import copy
import json
import re
import time
from collections import deque
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import uuid4

from spectra_sherpa.app.core.logging import redact_message

MAX_RECORDS = 20
MAX_TEXT = 48_000
_records: deque[tuple[int, dict]] = deque(maxlen=MAX_RECORDS)
_active: ContextVar["Exchange | None"] = ContextVar("basic_chat_exchange", default=None)
_sensitive = re.compile(
    r'(?i)(["\']?(?:api[_-]?key|password|secret|access[_-]?token|authorization|cookie)["\']?\s*[:=]\s*)'
    r'(?:"[^"\n]*"|\'[^\'\n]*\'|[^\s,;}]+)'
)
_url_credentials = re.compile(r"(https?://)[^\s/@]+:[^\s/@]+@", re.I)
_url_query = re.compile(r"(https?://[^\s?]+)\?[^\s]+", re.I)
_credential_header = re.compile(r"(?im)(\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*:\s*)[^\r\n]+")


class Exchange:
    """Capture only actual provider payloads and output, after secret redaction."""

    def __init__(self, owner: int, provider: str, model: str, secrets: tuple[str, ...]):
        self.owner = owner
        self.secrets = tuple(value for value in secrets if value)
        self.started = time.monotonic()
        self.record = {
            "id": str(uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "provider": self.clean(provider),
            "model": self.clean(model),
            "request": None,
            "response": "",
            "usage": None,
            "status": "started",
            "truncated": False,
        }

    def clean(self, text: str) -> str:
        for value in sorted(self.secrets, key=len, reverse=True):
            text = text.replace(value, "[REDACTED]")
        text = _credential_header.sub(r"\1[REDACTED]", text)
        text = redact_message(text)
        text = _sensitive.sub(r"\1[REDACTED]", text)
        text = _url_credentials.sub(r"\1[REDACTED]@", text)
        return _url_query.sub(r"\1?[REDACTED]", text)

    def payload(self, body: dict) -> None:
        # The transport passes its JSON body, never headers, URL or metadata.
        def redact(value):
            if isinstance(value, str):
                return self.clean(value)
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items()}
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value

        text = json.dumps(redact(body), ensure_ascii=False)
        self.record["request"] = text[:MAX_TEXT]
        self.record["truncated"] |= len(text) > MAX_TEXT

    def append(self, text: str) -> None:
        # Redact the accumulated stream so secrets split across deltas never
        # reach the readable history. In-progress records are not exposed.
        self.raw_response = (getattr(self, "raw_response", "") + text)[: MAX_TEXT + 4096]
        self.record["truncated"] |= len(self.raw_response) > MAX_TEXT

    def finish(self, status: str) -> None:
        self.record["response"] = self.clean(getattr(self, "raw_response", ""))[:MAX_TEXT]
        self.record["status"] = status
        self.record["duration_ms"] = round((time.monotonic() - self.started) * 1000)
        _records.append((self.owner, self.record))
        self.raw_response = ""


def observe_payload(body: dict) -> None:
    if exchange := _active.get():
        exchange.payload(body)


def observe_usage(usage: object) -> None:
    if (exchange := _active.get()) and isinstance(usage, dict):
        allowed = {"prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens"}
        counts = {k: v for k, v in usage.items() if k in allowed and type(v) is int and v >= 0}
        if counts:
            exchange.record["usage"] = {**(exchange.record["usage"] or {}), **counts}


def history(owner: int) -> list[dict]:
    return [copy.deepcopy(record) for identity, record in reversed(_records) if identity == owner]


def clear(owner: int) -> None:
    retained = [(identity, record) for identity, record in _records if identity != owner]
    _records.clear()
    _records.extend(retained)
