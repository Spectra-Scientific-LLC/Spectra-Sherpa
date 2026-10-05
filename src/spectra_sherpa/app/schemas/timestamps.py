"""UTC wire timestamps, including historical SQLite values without tzinfo."""

from datetime import datetime, timezone
from typing import Annotated

from pydantic import PlainSerializer


def utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


UtcTimestamp = Annotated[datetime, PlainSerializer(utc_timestamp, return_type=str, when_used="json")]
