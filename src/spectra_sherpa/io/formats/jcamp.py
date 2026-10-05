"""Native JCAMP-DX format plugin."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.jcamp_reader import JCAMPData, count_declared_jcamp_points, parse_jcamp
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset
from spectra_sherpa.ingestion_errors import ParserLimitError, UnreadableSpectrumError, UnsupportedFormatVariantError
from spectra_sherpa.io.base import BoundedSource
from spectra_sherpa.io.formats._helpers import dataset_asset, ingestion_result
from spectra_sherpa.io.formats._text_limits import require_jcamp_working_set
from spectra_sherpa.io.types import IngestionResult, ParserLimits, ProbeConfidence, ProbeResult


def _optional_text(value: object) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


def _technique(data_type: str | None) -> str | None:
    normalized = " ".join(str(data_type or "").strip().lower().replace("-", " ").split())
    if "raman" in normalized:
        return "Raman"
    if "near infrared" in normalized or "nir" in normalized:
        return "NIR"
    if "ultraviolet" in normalized or "uv" in normalized or "visible" in normalized:
        return "UV-Vis"
    if "infrared" in normalized or normalized in {"ir", "infrared spectrum"}:
        return "IR"
    return None


def _axis_title(units: str | None, *, technique: str | None) -> str | None:
    text = (units or "").lower()
    if "nm" in text or "micrometer" in text or "um" in text or "µm" in text:
        return "Wavelength"
    if "cm-1" in text or "cm^-1" in text or "cm⁻¹" in text or "1/cm" in text:
        return "Raman Shift" if technique == "Raman" else "Wavenumber"
    return None


def _intensity_title(units: str | None) -> str | None:
    text = (units or "").lower()
    if "transmit" in text:
        return "Transmittance"
    if "absorb" in text:
        return "Absorbance"
    return _optional_text(units)


def _dataset(jcamp: JCAMPData, *, source_name: Path) -> SherpaDataset:
    y = np.asarray(jcamp.y, dtype=np.float64)
    x = np.asarray(jcamp.x, dtype=np.float64)
    if x.ndim != 1 or y.ndim != 1 or len(x) != len(y):
        raise ValueError(f"JCAMP must contain matching one-dimensional x/y arrays: {source_name.name}")
    axis_units = _optional_text(jcamp.xunits)
    technique = _technique(jcamp.data_type)
    title = jcamp.title or source_name.stem
    return SherpaDataset(
        X=y.reshape(1, -1),
        feature_axis=SpectralAxis(values=x, title=_axis_title(axis_units, technique=technique), units=axis_units),
        sample_axis=SampleAxis(labels=[title], title="Samples"),
        domain=DomainContext(
            technique=technique,
            expected_units=axis_units,
            data_quantity=_intensity_title(jcamp.yunits),
        ),
        title=title,
        units=_optional_text(jcamp.yunits),
        extra={"jcamp.data_type": jcamp.data_type, "jcamp.headers": dict(jcamp.headers)},
        data_role="X_spectra",
    )


class JcampPlugin:
    format_id = "jcamp-dx"
    display_name = "JCAMP-DX"
    description = "Open spectroscopy interchange format"
    extensions = (".jdx", ".dx", ".jcamp")
    parser_id = "spectrasherpa.jcamp"
    parser_version = "2"

    def probe(self, source: BoundedSource) -> ProbeResult:
        prefix = source.probe_prefix()
        upper = prefix.upper()
        data_markers = (b"##XYDATA=", b"##XYPOINTS=", b"##PEAK TABLE=")
        markers = tuple(marker.decode() for marker in (b"##TITLE=", *data_markers, b"##XUNITS=") if marker in upper)
        if b"##TITLE=" in upper and any(marker in upper for marker in data_markers):
            return ProbeResult(self.format_id, "dx-text", ProbeConfidence.EXACT, markers, len(prefix))
        if source.extension in self.extensions and b"##" in prefix:
            return ProbeResult(
                self.format_id,
                "dx-text",
                ProbeConfidence.COMPATIBLE,
                ("JCAMP extension and labelled records",),
                len(prefix),
            )
        return ProbeResult(self.format_id, None, ProbeConfidence.NO_MATCH, bytes_inspected=len(prefix))

    def read(
        self,
        source: BoundedSource,
        *,
        limits: ParserLimits,
        parser_options: Mapping[str, str] | None = None,
    ) -> IngestionResult:
        if parser_options:
            raise UnsupportedFormatVariantError("JCAMP-DX does not admit parser options")
        try:
            require_jcamp_working_set(
                source_bytes=source.size_bytes,
                point_count=0,
                limits=limits,
                format_id=self.format_id,
            )
            text = source.read_all(format_id=self.format_id).decode("utf-8", errors="replace")
            point_count = count_declared_jcamp_points(text)
            source.require_elements(point_count, format_id=self.format_id)
            require_jcamp_working_set(
                source_bytes=source.size_bytes,
                point_count=point_count,
                limits=limits,
                format_id=self.format_id,
            )
            dataset = _dataset(parse_jcamp(text), source_name=source.path)
        except ParserLimitError:
            raise
        except Exception as exc:
            raise UnreadableSpectrumError(format_id=self.format_id, detail=source.exception_detail(exc)) from exc
        source.require_elements(int(dataset.X.size), format_id=self.format_id)
        return ingestion_result(
            source=source,
            format_id=self.format_id,
            variant="dx-text",
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            assets=(
                dataset_asset(
                    dataset,
                    asset_id="spectrum",
                    raw_metadata={
                        key.removeprefix("jcamp."): value
                        for key, value in dataset.extra.items()
                        if str(key).startswith("jcamp.")
                    },
                ),
            ),
        )


PLUGIN = JcampPlugin()
