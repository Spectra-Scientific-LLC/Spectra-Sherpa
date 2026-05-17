"""Process-boot identifier for the audit subsystem.

Generated once per app process (via FastAPI lifespan startup) and stable
for the lifetime of that process only. Pairs with ``app_monotonic_ns``
in each audit event to give investigators strict forensic ordering even
when wall clocks skew.

Design doc decision: random UUID at app startup. **Not** derived from
cgroup / container / host id — those leak infrastructure identifiers,
behave poorly in local/dev, and add no ISO value. Optional environment
metadata (``hostname``, ``pid``, ``container_id``, ``runtime_image``)
is captured separately on the reproducibility record for forensic
context.

See ``the audit-subsystem design specification`` decision
#4 and §8.
"""

from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)

_process_boot_id: str | None = None


def init_process_boot_id() -> str:
    """Mint a fresh process-boot UUID and remember it for this process.

    Call once from the FastAPI lifespan startup phase **before** any
    audit emitter can fire. Re-calling resets the value (useful for
    dev hot-reload and tests; not for production reuse).

    Format: canonical 36-char UUID with hyphens (``str(uuid.uuid4())``),
    matching the ``TEXT(36)`` schema column shape declared in the
    design doc.

    Returns the generated id so tests and observability hooks can
    capture it.
    """
    global _process_boot_id
    _process_boot_id = str(uuid.uuid4())
    logger.info("Audit: minted process_boot_id=%s", _process_boot_id)
    return _process_boot_id


def get_process_boot_id() -> str:
    """Return the current process-boot id.

    If no id has been initialised yet (e.g. ad-hoc script that imports
    the audit subsystem without running the FastAPI lifespan), mint a
    one-off lazily so emitter code never crashes. Logs a warning so the
    misconfiguration is visible — the events will still link within
    this lazily-initialised window, just not with the id the operator
    expected.
    """
    if _process_boot_id is None:
        logger.warning(
            "Audit: get_process_boot_id called before init_process_boot_id; "
            "minting lazy id. This is a configuration bug if it happens in a "
            "real ASGI process."
        )
        return init_process_boot_id()
    return _process_boot_id


def _reset_process_boot_id_for_tests() -> None:
    """Test helper — clear the cached boot id so the next call mints fresh.

    Intentionally underscored: only test code should ever call this.
    """
    global _process_boot_id
    _process_boot_id = None
