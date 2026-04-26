"""JSON Schema validator for Sherpa WebSocket events.

Loads the published ``sherpa-ws-v1.json`` schema from package data and
exposes a ``validate_ws_event`` function used by contract tests in
both spectra-sherpa (OSS) and server extensions.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

import jsonschema


@lru_cache(maxsize=1)
def load_ws_schema() -> dict[str, Any]:
    """Load and cache the WS event JSON Schema from package data."""
    schema_ref = resources.files("spectra_sherpa") / "contracts" / "sherpa-ws-v1.json"
    schema_text = schema_ref.read_text(encoding="utf-8")
    return json.loads(schema_text)


def validate_ws_event(event: dict[str, Any]) -> None:
    """Validate a single WS event dict against the published schema.

    Raises ``jsonschema.ValidationError`` if the event does not conform.
    """
    schema = load_ws_schema()
    jsonschema.validate(instance=event, schema=schema)
