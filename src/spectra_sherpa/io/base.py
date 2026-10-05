"""Inspectable bounded-read primitives and parser protocol."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable

from spectra_sherpa.ingestion_errors import ParserLimitError, UnreadableSpectrumError
from spectra_sherpa.ingestion_formats import normalized_extension
from spectra_sherpa.io.types import IngestionResult, ParserLimits, ProbeResult, SourceMember


class BoundedSource:
    """Read-only local source whose ranges and declared allocations are checked.

    This is intentionally ordinary OSS parser code.  It performs no network,
    subprocess, authentication, plugin loading, or dynamic deserialization.
    """

    def __init__(self, path: str | Path, *, limits: ParserLimits) -> None:
        self.path = Path(path)
        self.limits = limits
        try:
            admitted = self.path.stat()
        except OSError as exc:
            raise UnreadableSpectrumError(format_id="unknown", detail=self.exception_detail(exc)) from exc
        if not stat.S_ISREG(admitted.st_mode):
            raise UnreadableSpectrumError(format_id="unknown", detail="source is not a regular file")
        if admitted.st_size > limits.max_source_bytes:
            raise ParserLimitError(
                f"Source is {admitted.st_size} bytes; parser limit is {limits.max_source_bytes} bytes"
            )
        self._snapshot_directory = tempfile.TemporaryDirectory(prefix="spectrasherpa-ingest-")
        self.snapshot_path = Path(self._snapshot_directory.name) / self.path.name
        try:
            self._initial_member = self._copy_immutable_snapshot(admitted)
        except Exception:
            self.close()
            raise
        self.size_bytes = self._initial_member.size_bytes

    @property
    def extension(self) -> str:
        # ``Path.suffix`` treats a legacy filename consisting only of an
        # extension (for example OMNIC's literal ``.SPA``) as suffixless.
        # The registry filename authority already admits this historical
        # spelling, so the immutable source snapshot must project it the same
        # way during probe and read.
        return normalized_extension(self.path.name)

    def read_at(self, offset: int, length: int, *, format_id: str = "unknown") -> bytes:
        if offset < 0 or length < 0:
            raise UnreadableSpectrumError(
                format_id=format_id,
                offset=max(offset, 0),
                detail="negative offset or length",
            )
        end = offset + length
        if end < offset or end > self.size_bytes:
            raise UnreadableSpectrumError(
                format_id=format_id,
                offset=offset,
                detail=f"declared {length}-byte range exceeds {self.size_bytes}-byte source",
            )
        with self.snapshot_path.open("rb") as stream:
            stream.seek(offset)
            payload = stream.read(length)
        if len(payload) != length:
            raise UnreadableSpectrumError(
                format_id=format_id,
                offset=offset,
                detail=f"truncated read: expected {length} bytes, received {len(payload)}",
            )
        return payload

    def probe_prefix(self) -> bytes:
        return self.read_at(0, min(self.size_bytes, self.limits.max_probe_bytes))

    def read_all(self, *, format_id: str) -> bytes:
        return self.read_at(0, self.size_bytes, format_id=format_id)

    def require_elements(self, count: int, *, format_id: str) -> None:
        if count < 0:
            raise UnreadableSpectrumError(format_id=format_id, detail="negative declared element count")
        if count > self.limits.max_decoded_elements:
            raise ParserLimitError(
                f"{format_id} declares {count} decoded elements; limit is {self.limits.max_decoded_elements}"
            )

    def require_decoded_bytes(self, count: int, *, format_id: str) -> None:
        if count < 0:
            raise UnreadableSpectrumError(format_id=format_id, detail="negative declared decoded byte count")
        if count > self.limits.max_decoded_bytes:
            raise ParserLimitError(
                f"{format_id} declares {count} decoded bytes; limit is {self.limits.max_decoded_bytes}"
            )

    def require_blocks(self, count: int, *, format_id: str) -> None:
        if count < 0:
            raise UnreadableSpectrumError(format_id=format_id, detail="negative declared block count")
        if count > self.limits.max_blocks:
            raise ParserLimitError(f"{format_id} declares {count} blocks; limit is {self.limits.max_blocks}")

    def require_metadata_bytes(self, count: int, *, format_id: str) -> None:
        if count < 0:
            raise UnreadableSpectrumError(format_id=format_id, detail="negative metadata byte count")
        if count > self.limits.max_metadata_bytes:
            raise ParserLimitError(
                f"{format_id} declares {count} metadata bytes; limit is {self.limits.max_metadata_bytes}"
            )

    @staticmethod
    def _identity(value: os.stat_result) -> tuple[int, ...]:
        identity = (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
        # Windows path stat and descriptor fstat can expose different ctime
        # semantics (creation versus metadata change). They are not comparable.
        # Keep file ID, size, and modification checks plus the byte digest check.
        return identity if os.name == "nt" else (*identity, value.st_ctime_ns)

    def exception_detail(self, exc: BaseException) -> str:
        """Project a parser failure without publishing local filesystem paths."""

        source_name = self.path.name or "source"
        if isinstance(exc, OSError):
            reason = exc.strerror or type(exc).__name__
            errno = f"[Errno {exc.errno}] " if exc.errno is not None else ""
            return f"{errno}{reason}: {source_name}"

        detail = str(exc) or type(exc).__name__
        candidates = (self.path, getattr(self, "snapshot_path", None))
        for candidate in candidates:
            if candidate is not None:
                detail = detail.replace(str(candidate), source_name)
        return detail

    def _copy_immutable_snapshot(self, admitted: os.stat_result) -> SourceMember:
        """Copy and digest one open descriptor into a private parser snapshot."""

        digest = hashlib.sha256()
        try:
            source_stream = self.path.open("rb")
        except OSError as exc:
            raise UnreadableSpectrumError(format_id="unknown", detail=self.exception_detail(exc)) from exc
        copied = 0
        try:
            descriptor_before = os.fstat(source_stream.fileno())
            if self._identity(descriptor_before) != self._identity(admitted):
                raise UnreadableSpectrumError(
                    format_id="unknown", detail="source identity changed before snapshot construction"
                )
            with self.snapshot_path.open("xb") as snapshot_stream:
                for chunk in iter(lambda: source_stream.read(1024 * 1024), b""):
                    copied += len(chunk)
                    if copied > self.limits.max_source_bytes:
                        raise ParserLimitError(f"Source exceeds parser limit of {self.limits.max_source_bytes} bytes")
                    snapshot_stream.write(chunk)
                    digest.update(chunk)
                snapshot_stream.flush()
            self.snapshot_path.chmod(0o400)
            descriptor_after = os.fstat(source_stream.fileno())
        finally:
            source_stream.close()
        if self._identity(descriptor_before) != self._identity(descriptor_after) or copied != descriptor_after.st_size:
            raise UnreadableSpectrumError(format_id="unknown", detail="source changed while snapshot was constructed")
        try:
            current = self.path.stat()
        except OSError as exc:
            raise UnreadableSpectrumError(format_id="unknown", detail=self.exception_detail(exc)) from exc
        if self._identity(current) != self._identity(admitted):
            raise UnreadableSpectrumError(
                format_id="unknown", detail="source path changed during snapshot construction"
            )
        return SourceMember(name=self.path.name, sha256=digest.hexdigest(), size_bytes=copied)

    def _current_member(self) -> SourceMember:
        digest = hashlib.sha256()
        copied = 0
        try:
            with self.path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    copied += len(chunk)
                    if copied > self.limits.max_source_bytes:
                        raise ParserLimitError(f"Source exceeds parser limit of {self.limits.max_source_bytes} bytes")
                    digest.update(chunk)
        except OSError as exc:
            raise UnreadableSpectrumError(format_id="unknown", detail=self.exception_detail(exc)) from exc
        return SourceMember(name=self.path.name, sha256=digest.hexdigest(), size_bytes=copied)

    def verify_unchanged(self) -> None:
        """Fail when path bytes changed between admission and parser completion."""
        current = self._current_member()
        if current.size_bytes != self._initial_member.size_bytes or current.sha256 != self._initial_member.sha256:
            raise UnreadableSpectrumError(format_id="unknown", detail="source bytes changed during parsing")

    def member(self) -> SourceMember:
        """Return the source identity frozen before probing or parsing began."""
        return self._initial_member

    def close(self) -> None:
        directory = getattr(self, "_snapshot_directory", None)
        if directory is not None:
            directory.cleanup()
            self._snapshot_directory = None

    def __enter__(self) -> BoundedSource:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


@runtime_checkable
class FormatPlugin(Protocol):
    """Closed protocol implemented by every audited built-in format module."""

    format_id: str
    display_name: str
    description: str
    extensions: tuple[str, ...]
    parser_id: str
    parser_version: str

    def probe(self, source: BoundedSource) -> ProbeResult: ...

    def read(
        self,
        source: BoundedSource,
        *,
        limits: ParserLimits,
        parser_options: Mapping[str, str] | None = None,
    ) -> IngestionResult: ...
