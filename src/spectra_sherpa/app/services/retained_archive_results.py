"""Bounded, inert transport of original saved-run records and output envelopes.

These records describe historical evidence. They grant no execution, publisher,
approval or unobserved-population authority. Export callers own resource access
and any required disclosure transaction before releasing archive bytes.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from spectra_sherpa.app.schemas.execution_runs import ExecutionRunOut
from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.services.run_output_retention import (
    FORMAT_OUTPUT_BYTES_LIMIT,
    admit_retained_value,
    read_output_bytes,
    retained_read_budget,
)
from spectra_sherpa.app.services.sherpa_object import ArchiveMember, inspect_archive_bytes, validate_archive_bytes
from spectra_sherpa.core.pack_manifest import Frozen

RESULT_INDEX = "retained-results.json"
MAX_INDEX_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_RUNS = 256


class ArchivedRun(Frozen):
    source_run_id: int = Field(gt=0)
    source_workflow_id: int | None = Field(default=None, gt=0)
    source_project_id: int | None = Field(default=None, gt=0)
    record_json: str = Field(max_length=MAX_INDEX_BYTES)
    evidence: RunEvidence

    @field_validator("record_json")
    @classmethod
    def bounded_record(cls, value: str) -> str:
        record = _read_json(value.encode("utf-8"), max_bytes=MAX_INDEX_BYTES)
        if not isinstance(record, dict):
            raise ValueError("Archived run record must be an object")
        return value

    @model_validator(mode="after")
    def bound_inventory(self):
        if len(self.evidence.outputs) > 1024 or sum(len(ports) for ports in self.evidence.outputs.values()) > 1024:
            raise ValueError("Archived run has too many outputs")
        record = _read_json(self.record_json.encode("utf-8"), max_bytes=MAX_INDEX_BYTES)
        for field, expected in (
            ("id", self.source_run_id),
            ("workflow_id", self.source_workflow_id),
            ("project_id", self.source_project_id),
        ):
            if field in record and record[field] != expected:
                raise ValueError("Archived run record disagrees with its source identity")
        return self


class ArchivedResults(Frozen):
    schema_version: Literal["spectra-retained-results/1"] = "spectra-retained-results/1"
    inspection_only: Literal[True] = True
    prior_unrecorded_history: Literal["unknown"] = "unknown"
    runs: Annotated[tuple[ArchivedRun, ...], Field(max_length=MAX_ARCHIVE_RUNS)]

    @model_validator(mode="after")
    def unique_runs(self):
        identities = [run.source_run_id for run in self.runs]
        if len(set(identities)) != len(identities):
            raise ValueError("Archive repeats a source run identity")
        return self


def capture_archived_runs(
    runs: tuple[ExecutionRunOut, ...], *, max_bytes: int
) -> tuple[ArchivedResults, list[ArchiveMember]]:
    """Capture previously authorized records; never substitute absent output data.

    The requesting transport must separately authorize every source run and any
    private disclosure. This byte collector cannot grant either permission.
    """
    if len(runs) > MAX_ARCHIVE_RUNS or max_bytes < 0:
        raise ValueError("Retained archive run or byte limit exceeded")
    index = ArchivedResults(
        runs=tuple(
            ArchivedRun(
                source_run_id=run.id,
                source_workflow_id=run.workflow_id,
                source_project_id=run.project_id,
                record_json=run.model_dump_json(exclude={"evidence_completeness", "evidence_gaps"}),
                evidence=run.evidence_completeness or RunEvidence(),
            )
            for run in runs
        )
    )
    encoded_index = index.model_dump_json().encode("utf-8")
    if len(encoded_index) > min(MAX_INDEX_BYTES, max_bytes):
        raise ValueError("Retained archive metadata exceeds its byte limit")
    members = {RESULT_INDEX: encoded_index}
    total = len(encoded_index)
    verified = {}
    # The budget also bounds repeated reads across different original owners.
    with retained_read_budget(max_bytes + MAX_ARCHIVE_RUNS * 1024):
        for run, archived in zip(runs, index.runs):
            for ports in archived.evidence.outputs.values():
                for evidence in ports.values():
                    if evidence.storage != "file" or evidence.sha256 is None:
                        continue
                    key = (run.user_id, evidence.sha256)
                    data = verified.get(key)
                    if data is None:
                        if evidence.byte_count is None or evidence.byte_count > max_bytes - total:
                            raise ValueError("Retained archive output exceeds its byte limit")
                        data = read_output_bytes(run.user_id, evidence)
                        verified[key] = data
                    if len(data) != evidence.byte_count:
                        raise ValueError("Retained archive repeats conflicting output custody")
                    path = retained_output_member(evidence.sha256)
                    if path not in members:
                        total += len(data)
                        members[path] = data
    return index, [ArchiveMember(path, data) for path, data in sorted(members.items())]


def retained_output_member(sha256: str) -> str:
    # OutputEvidence validates the digest before this mapping is used.
    if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
        raise ValueError("Invalid retained output identity")
    return f"retained-results/{sha256}.json"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Retained evidence repeats a JSON field")
        result[key] = value
    return result


def _read_json(encoded: bytes, *, max_bytes: int):
    if len(encoded) > max_bytes:
        raise ValueError("Retained JSON exceeds its byte limit")

    def reject_constant(value):
        raise ValueError("Retained JSON contains a non-finite number")

    try:
        value = json.loads(encoded, object_pairs_hook=_unique_object, parse_constant=reject_constant)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("Retained JSON is malformed or too deeply nested") from exc
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 24 or count > 200_000:
            raise ValueError("Retained JSON exceeds its structure limit")
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("Retained JSON contains a non-finite number")
        if isinstance(item, dict):
            pending.extend((nested, depth + 1) for nested in item.values())
        elif isinstance(item, list):
            pending.extend((nested, depth + 1) for nested in item)
    return value


def _read_member(archive, name, limit):
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise ValueError("Retained archive member is unavailable") from exc
    if info.file_size > limit:
        raise ValueError("Retained archive member exceeds its read limit")
    with archive.open(info) as stream:
        value = stream.read(limit + 1)
    if len(value) > limit or len(value) != info.file_size:
        raise ValueError("Retained archive member exceeds its read limit")
    return value


def read_archived_results(payload: bytes, *, max_uncompressed_bytes: int) -> ArchivedResults:
    report = inspect_archive_bytes(
        payload,
        max_uncompressed_bytes=max_uncompressed_bytes,
        max_project_bytes=8 * 1024 * 1024,
        max_manifest_bytes=8 * 1024 * 1024,
    )
    if not report.valid_zip or not report.has_project or not report.has_manifest or report.errors:
        raise ValueError("Archive has no verified retained-result inventory")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        encoded = _read_member(archive, RESULT_INDEX, MAX_INDEX_BYTES)
    # Duplicate-field rejection precedes Pydantic's strict JSON-mode parser,
    # which correctly admits JSON arrays for immutable tuple fields.
    _read_json(encoded, max_bytes=MAX_INDEX_BYTES)
    index = ArchivedResults.model_validate_json(encoded)
    validation = validate_archive_bytes(payload, max_uncompressed_bytes=max_uncompressed_bytes)
    if not validation["valid"]:
        raise ValueError("Retained archive manifest integrity mismatch")
    return index


def read_archived_output(payload: bytes, *, run_id: int, node_id: str, port: str, max_uncompressed_bytes: int) -> bytes:
    """Return the exact original envelope, never another port or a recomputation."""
    index = read_archived_results(payload, max_uncompressed_bytes=max_uncompressed_bytes)
    run = next((run for run in index.runs if run.source_run_id == run_id), None)
    if run is None:
        raise ValueError("Archived run is unavailable")
    evidence = run.evidence.outputs.get(node_id, {}).get(port)
    if evidence is None or evidence.storage != "file" or evidence.sha256 is None:
        raise ValueError("Archived output was not retained")
    if evidence.byte_count is None or evidence.byte_count > FORMAT_OUTPUT_BYTES_LIMIT:
        raise ValueError("Archived output exceeds its read limit")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        encoded = _read_member(archive, retained_output_member(evidence.sha256), evidence.byte_count)
    if len(encoded) != evidence.byte_count or hashlib.sha256(encoded).hexdigest() != evidence.sha256:
        raise ValueError("Archived output checksum mismatch")
    value = _read_json(encoded, max_bytes=FORMAT_OUTPUT_BYTES_LIMIT)
    if not isinstance(value, dict) or value.get("format_version") != evidence.format_version or "value" not in value:
        raise ValueError("Archived output envelope is invalid")
    admit_retained_value(value["value"])
    return encoded
