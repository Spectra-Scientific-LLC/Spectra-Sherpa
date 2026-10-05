"""SQLite UTC timestamps must not become browser-local wall times."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import TypeAdapter

from spectra_sherpa.app.schemas.deploy import BatchPredictionOut, FolderWatchOut
from spectra_sherpa.app.schemas.execution_runs import ExecutionRunOut, RunListItem
from spectra_sherpa.app.schemas.timestamps import UtcTimestamp


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 9, 11, 20, 41, 59),
        datetime(2026, 9, 11, 20, 41, 59, tzinfo=timezone.utc),
        datetime(2026, 9, 11, 13, 41, 59, tzinfo=timezone(timedelta(hours=-7))),
    ],
)
def test_naive_and_offset_dates_represent_the_same_instant(value):
    assert TypeAdapter(UtcTimestamp).dump_json(value) == b'"2026-09-11T20:41:59Z"'


@pytest.mark.parametrize(
    "schema, fields",
    [
        (ExecutionRunOut, ["executed_at", "created_at"]),
        (RunListItem, ["executed_at", "created_at"]),
        (FolderWatchOut, ["last_poll_at", "created_at", "updated_at"]),
        (BatchPredictionOut, ["created_at"]),
    ],
)
def test_response_timestamp_fields_use_utc_serialization(schema, fields):
    timestamp = datetime(2026, 9, 11, 20, 41, 59)
    # Focus on the real response schema's serializers without unrelated fields.
    result = schema.model_construct(**dict.fromkeys(fields, timestamp)).model_dump(mode="json", include=set(fields))
    assert result == dict.fromkeys(fields, "2026-09-11T20:41:59Z")
