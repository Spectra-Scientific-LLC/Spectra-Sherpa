"""Native CSV format plugin backed by Sherpa's existing CSV authority."""

from __future__ import annotations

import csv
import io
import tempfile
from collections.abc import Mapping
from pathlib import Path

from spectra_sherpa.app.lib.portable_csv import PORTABLE_CSV_PREFIX, portable_csv_envelope_decoded_size
from spectra_sherpa.core.prepared_data import CSV_LAYOUTS, csv_layout_settings
from spectra_sherpa.ingestion_errors import AmbiguousFormatError, UnreadableSpectrumError, UnsupportedFormatVariantError
from spectra_sherpa.io.base import BoundedSource
from spectra_sherpa.io.formats._helpers import dataset_asset, ingestion_result
from spectra_sherpa.io.formats._text_limits import require_csv_working_set
from spectra_sherpa.io.types import IngestionResult, ParserLimits, ProbeConfidence, ProbeResult


class CsvPlugin:
    format_id = "csv"
    display_name = "CSV"
    description = "Delimited numeric spectra or feature tables (.csv, .tsv, .txt, .dat)"
    extensions = (".csv", ".tsv", ".txt", ".dat")
    parser_id = "spectrasherpa.csv"
    parser_version = "3"

    def probe(self, source: BoundedSource) -> ProbeResult:
        prefix = source.probe_prefix()
        if source.extension not in self.extensions:
            return ProbeResult(self.format_id, None, ProbeConfidence.NO_MATCH, bytes_inspected=len(prefix))
        if b"\x00" in prefix:
            return ProbeResult(
                self.format_id,
                None,
                ProbeConfidence.NO_MATCH,
                ("NUL byte contradicts delimited text",),
                len(prefix),
            )
        try:
            text = prefix.decode("utf-8-sig")
        except UnicodeDecodeError:
            return ProbeResult(
                self.format_id,
                None,
                ProbeConfidence.NO_MATCH,
                ("prefix is not UTF-8 text",),
                len(prefix),
            )
        if source.extension in _GENERIC_TEXT_EXTENSIONS:
            # .txt and .dat are claimed only as a consistent table, and only
            # COMPATIBLE, so an instrument text format probing EXACT wins.
            if _text_table_delimiter(text) is None:
                return ProbeResult(
                    self.format_id,
                    None,
                    ProbeConfidence.NO_MATCH,
                    ("text is not a consistently delimited table",),
                    len(prefix),
                )
            return ProbeResult(
                self.format_id,
                "delimited-text",
                ProbeConfidence.COMPATIBLE,
                (f"consistently delimited {source.extension} table",),
                len(prefix),
            )
        first_line = text.splitlines()[0] if text.splitlines() else ""
        delimiters = tuple(separator for separator in (",", ";", "\t") if separator in first_line)
        confidence = ProbeConfidence.EXACT if delimiters else ProbeConfidence.COMPATIBLE
        evidence = (f"delimiters={''.join(delimiters)}",) if delimiters else ("CSV extension with textual prefix",)
        return ProbeResult(self.format_id, "delimited-text", confidence, evidence, len(prefix))

    def read(
        self,
        source: BoundedSource,
        *,
        limits: ParserLimits,
        parser_options: Mapping[str, str] | None = None,
    ) -> IngestionResult:
        options = dict(parser_options or {})
        unknown = set(options) - {"csv_layout"}
        if unknown:
            raise UnsupportedFormatVariantError(f"CSV parser options are not recognized: {sorted(unknown)}")
        csv_layout = options.get("csv_layout")
        if csv_layout not in {None, *CSV_LAYOUTS}:
            raise UnsupportedFormatVariantError(f"Unsupported CSV layout: {csv_layout!r}")
        structural_layout, decimal = csv_layout_settings(csv_layout)
        parser_layout = None if structural_layout == "auto" else structural_layout
        try:
            # Reject on source size before allocating decoded text.  A second
            # check charges every discovered cell before pandas materializes
            # its dataframe.
            require_csv_working_set(
                source_bytes=source.size_bytes,
                cell_count=0,
                limits=limits,
                format_id=self.format_id,
            )
            text = source.read_all(format_id=self.format_id).decode("utf-8-sig")
            first_line, separator, tabular_text = text.partition("\n")
            is_portable = first_line.startswith(PORTABLE_CSV_PREFIX)
            if is_portable:
                if not separator:
                    raise ValueError("portable CSV metadata envelope has no tabular body")
                source.require_metadata_bytes(
                    portable_csv_envelope_decoded_size(first_line),
                    format_id=self.format_id,
                )
                sample = tabular_text[: min(len(tabular_text), 8192)]
            else:
                tabular_text = text
                sample = text[: min(len(text), 8192)]
            detected = (
                _text_table_delimiter(sample, decimal=decimal)
                if source.extension in {".tsv", *_GENERIC_TEXT_EXTENSIONS} and not is_portable
                else None
            )
            if detected is not None:
                delimiter = detected
            else:
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=";\t" if decimal == "," else ",;\t")
                    delimiter = dialect.delimiter
                except csv.Error:
                    delimiter = ";" if decimal == "," else ","
            if delimiter == _WHITESPACE:
                # Runs of spaces or tabs separate fields; the shared parser
                # reads tab-delimited text, so present it that way.
                tabular_text = "\n".join("\t".join(line.split()) for line in tabular_text.splitlines()) + "\n"
                delimiter = "\t"
            cell_count = 0
            # The portable metadata envelope is one intentionally long line.
            # It is bounded above as metadata and decoded by its dedicated
            # parser; do not feed it through csv.reader's unrelated field-size
            # ceiling before the portable loader can inspect it.
            for row in csv.reader(io.StringIO(tabular_text), delimiter=delimiter):
                cell_count += len(row)
                source.require_elements(cell_count, format_id=self.format_id)
            require_csv_working_set(
                source_bytes=source.size_bytes,
                cell_count=cell_count,
                limits=limits,
                format_id=self.format_id,
            )
        except UnicodeDecodeError as exc:
            raise UnreadableSpectrumError(format_id=self.format_id, detail="CSV is not UTF-8 text") from exc
        try:
            from spectra_sherpa.app.lib.io import parse_csv_snapshot_as_sherpa

            with tempfile.TemporaryDirectory(prefix="sherpa-text-table-") as scratch:
                parse_path = source.snapshot_path
                if tabular_text is not text and not is_portable:
                    # Whitespace-normalized copy; keeps the source file name.
                    parse_path = Path(scratch) / source.path.name
                    parse_path.write_text(tabular_text, encoding="utf-8")
                dataset = parse_csv_snapshot_as_sherpa(
                    parse_path,
                    delimiter=delimiter,
                    csv_layout=parser_layout,
                    decimal=decimal,
                    csv_profile=csv_layout,
                    _infer_implicit_target=False,
                    _resolve_prepared_overrides=False,
                )
            dataset.set_extra("csv.profile", csv_layout or "auto")
            dataset.set_extra("csv.delimiter", delimiter)
            dataset.set_extra("csv.decimal", decimal)
        except Exception as exc:
            if isinstance(exc, (AmbiguousFormatError, UnreadableSpectrumError, UnsupportedFormatVariantError)):
                raise
            raise UnreadableSpectrumError(format_id=self.format_id, detail=source.exception_detail(exc)) from exc
        source.require_elements(int(dataset.X.size), format_id=self.format_id)
        dataset.meta["source_file"] = source.path.name
        return ingestion_result(
            source=source,
            format_id=self.format_id,
            variant="delimited-text",
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            assets=(dataset_asset(dataset, asset_id="table"),),
        )


_GENERIC_TEXT_EXTENSIONS = frozenset({".txt", ".dat"})
_WHITESPACE = "whitespace"


def _text_table_delimiter(text: str, *, decimal: str = ".") -> str | None:
    """Return the one delimiter that splits every leading line consistently.

    A header may have one field fewer than its rows (R row names). Returns
    ``"whitespace"`` for space-aligned columns, or None when the text is not
    a table of at least two columns.
    """

    raw_lines = text.splitlines()
    if len(raw_lines) > 2 and not text.endswith(("\n", "\r")):
        raw_lines = raw_lines[:-1]  # a bounded prefix may cut the last line short
    lines = [line for line in raw_lines[:20] if line.strip()]
    if len(lines) < 2:
        return None
    candidates = ("\t", ";") if decimal == "," else ("\t", ",", ";")
    for delimiter in (*candidates, _WHITESPACE):
        widths = [len(line.split()) if delimiter == _WHITESPACE else line.count(delimiter) + 1 for line in lines]
        body = set(widths[1:])
        if len(body) == 1 and min(body) >= 2 and (widths[0] == widths[1] or widths[0] == widths[1] - 1 >= 2):
            return delimiter
    return None


PLUGIN = CsvPlugin()
