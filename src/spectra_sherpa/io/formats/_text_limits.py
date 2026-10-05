"""Conservative working-set admission for native text parsers.

Text parsing retains more than the final NumPy arrays: immutable source bytes,
decoded Unicode, token/row objects, numeric arrays, and parser-specific
temporary storage can coexist. The CSV projection is calibrated against the
complete registry path at 400x1500, 1000x1500, and 2000x1500; JCAMP retains its
separate Python-list projection. These are admission estimates, not claims
about a particular Python allocator.
"""

from __future__ import annotations

from spectra_sherpa.ingestion_errors import ParserLimitError
from spectra_sherpa.io.types import ParserLimits

_CSV_WORKING_SET_CEILING_BYTES = 512 * 1024 * 1024
_CSV_FIXED_OVERHEAD_BYTES = 96 * 1024 * 1024
_CSV_SOURCE_EXPANSION_BYTES_PER_BYTE = 3
_CSV_BYTES_PER_CELL = 80
_JCAMP_WORKING_SET_CEILING_BYTES = 256 * 1024 * 1024
_JCAMP_SOURCE_EXPANSION_BYTES_PER_BYTE = 8
_JCAMP_BYTES_PER_POINT = 160


def require_text_working_set(
    *,
    source_bytes: int,
    decoded_items: int,
    bytes_per_item: int,
    fixed_overhead_bytes: int,
    source_expansion_bytes_per_byte: int,
    working_set_ceiling_bytes: int,
    limits: ParserLimits,
    format_id: str,
    remediation: str,
) -> int:
    """Reject text whose conservative projected parser working set is unsafe."""
    budget = min(int(limits.max_decoded_bytes), int(working_set_ceiling_bytes))
    projected = (
        int(fixed_overhead_bytes)
        + int(source_bytes) * int(source_expansion_bytes_per_byte)
        + int(decoded_items) * int(bytes_per_item)
    )
    if projected > budget:
        raise ParserLimitError(
            f"{format_id} projected text-parser working set {projected} bytes exceeds the {budget}-byte format budget",
            remediation=remediation,
        )
    return projected


def require_csv_working_set(*, source_bytes: int, cell_count: int, limits: ParserLimits, format_id: str) -> int:
    return require_text_working_set(
        source_bytes=source_bytes,
        decoded_items=cell_count,
        bytes_per_item=_CSV_BYTES_PER_CELL,
        fixed_overhead_bytes=_CSV_FIXED_OVERHEAD_BYTES,
        source_expansion_bytes_per_byte=_CSV_SOURCE_EXPANSION_BYTES_PER_BYTE,
        working_set_ceiling_bytes=_CSV_WORKING_SET_CEILING_BYTES,
        limits=limits,
        format_id=format_id,
        remediation=("Split the CSV by samples, remove unused columns, or export the dense numeric matrix as NPY/NPZ."),
    )


def require_jcamp_working_set(*, source_bytes: int, point_count: int, limits: ParserLimits, format_id: str) -> int:
    return require_text_working_set(
        source_bytes=source_bytes,
        decoded_items=point_count,
        bytes_per_item=_JCAMP_BYTES_PER_POINT,
        fixed_overhead_bytes=0,
        source_expansion_bytes_per_byte=_JCAMP_SOURCE_EXPANSION_BYTES_PER_BYTE,
        working_set_ceiling_bytes=_JCAMP_WORKING_SET_CEILING_BYTES,
        limits=limits,
        format_id=format_id,
        remediation="Split the JCAMP source into smaller spectra or reduce the exported point count.",
    )
