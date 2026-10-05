"""Bounded reader for qualified Renishaw WiRE single-spectrum text exports.

WiRE's single-spectrum text export is a deliberately small tabular grammar:
the first line names ``#Wave`` and ``#Intensity`` and every remaining line
contains one Raman-shift coordinate and one intensity.  It is not a generic
``.txt`` reader.  Unknown text tables, maps, series, and metadata-bearing text
families remain unclaimed so they cannot be silently flattened into one
spectrum.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

import numpy as np

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset
from spectra_sherpa.ingestion_errors import UnreadableSpectrumError, UnsupportedFormatVariantError
from spectra_sherpa.io.base import BoundedSource
from spectra_sherpa.io.formats._helpers import dataset_asset, ingestion_result
from spectra_sherpa.io.formats._text_limits import require_csv_working_set
from spectra_sherpa.io.types import IngestionResult, ParserLimits, ProbeConfidence, ProbeResult

_HEADER = re.compile(r"^#Wave\t+#Intensity$")
_VARIANT = "wire-single-spectrum-tab"


def _decode(source: BoundedSource) -> str:
    try:
        return source.read_all(format_id="renishaw-text").decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UnreadableSpectrumError(
            format_id="renishaw-text",
            detail="Renishaw text export is not UTF-8-compatible text",
        ) from exc


def _rows(source: BoundedSource, text: str, *, limits: ParserLimits) -> tuple[np.ndarray, np.ndarray]:
    lines = text.splitlines()
    if not lines or _HEADER.fullmatch(lines[0]) is None:
        raise UnreadableSpectrumError(
            format_id="renishaw-text",
            detail="Renishaw single-spectrum text must begin with tab-separated #Wave and #Intensity",
        )
    if len(lines) < 3:
        raise UnreadableSpectrumError(
            format_id="renishaw-text",
            detail="Renishaw single-spectrum text requires at least two numeric rows",
        )

    point_count = len(lines) - 1
    cell_count = point_count * 2
    source.require_elements(cell_count, format_id="renishaw-text")
    source.require_decoded_bytes(point_count * 16, format_id="renishaw-text")
    require_csv_working_set(
        source_bytes=source.size_bytes,
        cell_count=cell_count,
        limits=limits,
        format_id="renishaw-text",
    )

    coordinates = np.empty(point_count, dtype=np.float64)
    intensities = np.empty(point_count, dtype=np.float64)
    for index, line in enumerate(lines[1:]):
        fields = line.split("\t")
        if len(fields) != 2 or not all(field.strip() for field in fields):
            raise UnreadableSpectrumError(
                format_id="renishaw-text",
                detail=f"Renishaw text data row {index + 2} must contain exactly two tab-separated numbers",
            )
        try:
            coordinates[index] = float(fields[0])
            intensities[index] = float(fields[1])
        except ValueError as exc:
            raise UnreadableSpectrumError(
                format_id="renishaw-text",
                detail=f"Renishaw text data row {index + 2} is not numeric",
            ) from exc

    if not np.all(np.isfinite(coordinates)) or not np.all(np.isfinite(intensities)):
        raise UnreadableSpectrumError(
            format_id="renishaw-text",
            detail="Renishaw text coordinates and intensities must be finite",
        )
    differences = np.diff(coordinates)
    if not (np.all(differences > 0) or np.all(differences < 0)):
        raise UnreadableSpectrumError(
            format_id="renishaw-text",
            detail="Renishaw text Raman-shift coordinates must be strictly monotonic",
        )
    return coordinates, intensities


class RenishawTextPlugin:
    format_id = "renishaw-text"
    display_name = "Renishaw WiRE text"
    description = "Qualified tab-separated Renishaw WiRE single-spectrum export"
    extensions = (".txt",)
    parser_id = "spectrasherpa.native.renishaw_text"
    parser_version = "1"

    def probe(self, source: BoundedSource) -> ProbeResult:
        prefix = source.probe_prefix()
        if source.extension != ".txt" or b"\x00" in prefix:
            return ProbeResult(self.format_id, None, ProbeConfidence.NO_MATCH, bytes_inspected=len(prefix))
        try:
            text = prefix.decode("utf-8-sig")
        except UnicodeDecodeError:
            return ProbeResult(self.format_id, None, ProbeConfidence.NO_MATCH, bytes_inspected=len(prefix))
        first_line = text.splitlines()[0] if text.splitlines() else ""
        if _HEADER.fullmatch(first_line) is None:
            return ProbeResult(self.format_id, None, ProbeConfidence.NO_MATCH, bytes_inspected=len(prefix))
        return ProbeResult(
            self.format_id,
            _VARIANT,
            ProbeConfidence.EXACT,
            ("Renishaw #Wave/#Intensity tab header",),
            min(len(prefix), len(first_line.encode("utf-8"))),
        )

    def read(
        self,
        source: BoundedSource,
        *,
        limits: ParserLimits,
        parser_options: Mapping[str, str] | None = None,
    ) -> IngestionResult:
        if parser_options:
            raise UnsupportedFormatVariantError("Renishaw text does not admit parser options")
        require_csv_working_set(
            source_bytes=source.size_bytes,
            cell_count=0,
            limits=limits,
            format_id=self.format_id,
        )
        coordinates, intensities = _rows(source, _decode(source), limits=limits)
        order = "ascending" if coordinates[-1] > coordinates[0] else "descending"
        dataset = SherpaDataset(
            X=intensities.reshape(1, -1),
            feature_axis=SpectralAxis(values=coordinates, title="Raman shift", units="cm-1"),
            sample_axis=SampleAxis(labels=[source.path.stem], title="Samples"),
            domain=DomainContext(
                technique="Raman",
                expected_units="cm-1",
                data_quantity="Raman intensity",
                instrument=None,
            ),
            title=source.path.stem,
            units=None,
            extra={
                "source_file": source.path.name,
                "renishaw_text.variant": _VARIANT,
                "renishaw_text.axis_order": order,
                "renishaw_text.export_software": "Renishaw WiRE",
            },
            data_role="X_spectra",
        )
        metadata = {
            "header": ["#Wave", "#Intensity"],
            "point_count": int(coordinates.size),
            "axis_order": order,
        }
        warning = (
            "Renishaw WiRE text export retains the Raman shift and intensity only; "
            "use the original WDF when acquisition settings, coordinates, or map topology are required."
        )
        return ingestion_result(
            source=source,
            format_id=self.format_id,
            variant=_VARIANT,
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            assets=(
                dataset_asset(
                    dataset,
                    asset_id="spectrum",
                    raw_metadata=metadata,
                    warnings=(warning,),
                ),
            ),
            raw_metadata=metadata,
            warnings=(warning,),
        )


PLUGIN = RenishawTextPlugin()
