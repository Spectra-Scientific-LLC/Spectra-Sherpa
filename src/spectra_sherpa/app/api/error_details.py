"""Response boundary for reviewed validation/storage error handlers.

This is not a sanitizer for arbitrary exception messages. Callers may preserve
ValueError text only where that handler already owns user-facing validation.
Storage failures (including wrapped ones) and unexpected exceptions use a fixed
recovery message; full diagnostics stay in the server log.
"""

from __future__ import annotations

import logging


def has_storage_cause(exc: BaseException) -> bool:
    """Inspect both exception chains (including suppressed context and groups)."""
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, OSError):
            return True
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)
        # Include suppressed context: ``raise ValueError(str(exc)) from None``
        # still contains storage details even though its traceback hides them.
        for nested in (current.__cause__, current.__context__):
            if nested is not None:
                pending.append(nested)
    return False


def validation_or_storage_detail(exc: Exception, *, fallback: str, logger: logging.Logger) -> str:
    """Keep a validation refusal, never interpolate a storage exception chain."""
    if isinstance(exc, ValueError) and not has_storage_cause(exc):
        return str(exc)
    logger.warning(fallback, exc_info=(type(exc), exc, exc.__traceback__))
    return fallback
