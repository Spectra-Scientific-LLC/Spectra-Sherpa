"""Pin the published audit-events JSON Schema against the runtime model.

The schema at ``contracts/audit_events_v1.json`` is the public wire
contract for two surfaces:

  * ``GET /api/v1/audit/events`` — the OSS query endpoint.
  * ``audit_export.jsonl`` inside report-pack ZIPs — server-side, but
    the schema is bundled in the pack so external reviewers can validate
    the JSONL without any service running.

If ``AuditEventOut`` (the Pydantic source of truth) drifts from the
published schema, the contract advertised to external consumers becomes
a lie. This test catches drift in both directions:

  1. Every field on the Pydantic model has a matching property in the
     schema definition (and vice versa) — name, requiredness, and
     nullability.
  2. A live row built from realistic emitter output validates against
     the schema (round-trip).
  3. A query response envelope validates against the schema (round-trip).
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from jsonschema import Draft7Validator

from spectra_sherpa.app.schemas.audit import AuditEventOut, AuditEventQueryResponse

_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "src" / "spectra_sherpa" / "contracts" / "audit_events_v1.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text())


@pytest.fixture(scope="module")
def event_validator(schema: dict) -> Draft7Validator:
    Draft7Validator.check_schema(schema)
    resolver = jsonschema.RefResolver.from_schema(schema)
    return Draft7Validator(schema["definitions"]["audit_event"], resolver=resolver)


@pytest.fixture(scope="module")
def response_validator(schema: dict) -> Draft7Validator:
    resolver = jsonschema.RefResolver.from_schema(schema)
    return Draft7Validator(schema["definitions"]["audit_event_query_response"], resolver=resolver)


def test_schema_file_is_valid_draft7(schema: dict) -> None:
    """The published schema must itself be a valid Draft-07 JSON Schema."""
    Draft7Validator.check_schema(schema)


def test_event_field_set_matches_pydantic_model(schema: dict) -> None:
    """No drift between AuditEventOut and the published event definition.

    Catches: a new field added on the Pydantic model without updating
    the schema (silent contract break for external consumers), or a
    field renamed in the schema without updating the model.
    """
    schema_props = set(schema["definitions"]["audit_event"]["properties"].keys())
    pydantic_props = set(AuditEventOut.model_fields.keys())
    assert schema_props == pydantic_props, (
        "Drift between AuditEventOut and audit_events_v1.json. "
        f"Only-in-schema: {sorted(schema_props - pydantic_props)}; "
        f"only-in-model: {sorted(pydantic_props - schema_props)}. "
        "Update both sides together."
    )


def test_event_required_fields_match_pydantic_model(schema: dict) -> None:
    """Schema 'required' must match the Pydantic non-Optional set.

    A field is 'required' iff it has no default AND its annotation is
    not Optional (X | None).
    """
    schema_required = set(schema["definitions"]["audit_event"]["required"])
    pydantic_required: set[str] = set()
    for name, field in AuditEventOut.model_fields.items():
        if not field.is_required():
            continue
        annotation_str = str(field.annotation)
        if "None" in annotation_str:
            continue
        pydantic_required.add(name)
    assert schema_required == pydantic_required, (
        "Required-field drift between AuditEventOut and "
        "audit_events_v1.json. "
        f"Only-in-schema: {sorted(schema_required - pydantic_required)}; "
        f"only-in-model: {sorted(pydantic_required - schema_required)}."
    )


def _sample_event_payload() -> dict:
    """A realistic audit event payload, exercising all fields."""
    return {
        "id": 42,
        "tenant_id": "default",
        "actor_id": 1,
        "actor_kind": "user",
        "action": "workflow.run.completed",
        "target_type": "Workflow",
        "target_id": "17",
        "before_state": {"status": "running"},
        "after_state": {"status": "completed", "duration_ms": 1234},
        "context": {
            "run_id": "run-abc",
            "workflow_version_id": 3,
        },
        "request_id": "11111111-1111-1111-1111-111111111111",
        "ts_app_utc": "2026-05-13T12:00:00.000000+00:00",
        "ts_db_utc": "2026-05-13T12:00:00.123456+00:00",
    }


def test_realistic_event_validates(event_validator: Draft7Validator) -> None:
    """A populated event payload must validate cleanly."""
    errors = sorted(event_validator.iter_errors(_sample_event_payload()), key=lambda e: e.path)
    assert errors == [], [str(e) for e in errors]


def test_minimal_event_validates(event_validator: Draft7Validator) -> None:
    """An event with all nullable fields null still validates."""
    payload = _sample_event_payload()
    for nullable_field in ("actor_id", "before_state", "after_state", "context"):
        payload[nullable_field] = None
    errors = sorted(event_validator.iter_errors(payload), key=lambda e: e.path)
    assert errors == [], [str(e) for e in errors]


def test_unknown_field_rejected(event_validator: Draft7Validator) -> None:
    """additionalProperties=false — schema rejects fields the model doesn't have."""
    payload = _sample_event_payload()
    payload["mystery_field"] = "should not validate"
    errors = list(event_validator.iter_errors(payload))
    assert errors, "Schema must reject unknown fields"


def test_invalid_actor_kind_rejected(event_validator: Draft7Validator) -> None:
    """actor_kind enum is the on-wire contract for actor type."""
    payload = _sample_event_payload()
    payload["actor_kind"] = "robot"
    errors = list(event_validator.iter_errors(payload))
    assert errors, "actor_kind enum must reject unknown values"


def test_query_response_envelope_validates(response_validator: Draft7Validator) -> None:
    """The full query-response envelope (events[] + cursor + has_more)
    validates against its schema definition.
    """
    response = AuditEventQueryResponse(
        events=[AuditEventOut.model_validate(_sample_event_payload())],
        next_cursor="42",
        has_more=False,
    )
    payload = response.model_dump(mode="json")
    errors = sorted(response_validator.iter_errors(payload), key=lambda e: e.path)
    assert errors == [], [str(e) for e in errors]
