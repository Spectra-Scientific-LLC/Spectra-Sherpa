"""Native reader for the closed SherpaDataset JSON wire format."""

from __future__ import annotations

from collections.abc import Mapping

from spectra_sherpa.app.lib.portable_json import decode_portable_json, inspect_portable_json_header
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.ingestion_errors import ParserLimitError, UnreadableSpectrumError, UnsupportedFormatVariantError
from spectra_sherpa.io.base import BoundedSource
from spectra_sherpa.io.formats._helpers import dataset_asset, ingestion_result
from spectra_sherpa.io.types import IngestionResult, ParserLimits, ProbeConfidence, ProbeResult


class SherpaJsonPlugin:
    """Read only the versioned dataset wire emitted by ``output.export``."""

    format_id = "sherpa-json"
    display_name = "SpectraSherpa JSON"
    description = "Versioned SpectraSherpa dataset interchange"
    extensions = (".json",)
    parser_id = "spectrasherpa.sherpa-json"
    parser_version = "1"

    def probe(self, source: BoundedSource) -> ProbeResult:
        prefix = source.probe_prefix()
        if source.extension != ".json":
            return ProbeResult(self.format_id, None, ProbeConfidence.NO_MATCH, bytes_inspected=len(prefix))
        try:
            text = prefix.decode("utf-8-sig").lstrip()
        except UnicodeDecodeError:
            return ProbeResult(
                self.format_id,
                None,
                ProbeConfidence.NO_MATCH,
                ("prefix is not UTF-8 text",),
                len(prefix),
            )
        if not text.startswith("{"):
            return ProbeResult(
                self.format_id,
                None,
                ProbeConfidence.NO_MATCH,
                ("source is not a JSON object",),
                len(prefix),
            )
        # Canonical export sorts keys, so a wide data array can place the
        # discriminator beyond the bounded probe prefix. Extension + object
        # structure is therefore a compatible claim; the closed wire validator
        # supplies exact admission during read.
        return ProbeResult(
            self.format_id,
            "dataset-wire",
            ProbeConfidence.COMPATIBLE,
            ("JSON object with .json extension",),
            len(prefix),
        )

    def read(
        self,
        source: BoundedSource,
        *,
        limits: ParserLimits,
        parser_options: Mapping[str, str] | None = None,
    ) -> IngestionResult:
        if parser_options:
            raise UnsupportedFormatVariantError("SpectraSherpa JSON does not accept parser options")
        try:
            payload_bytes = source.read_all(format_id=self.format_id)
            _shape, x_element_count, decoded_nodes = inspect_portable_json_header(payload_bytes)
            source.require_elements(decoded_nodes, format_id=self.format_id)
            # Charge a conservative upper bound for the transient JSON text,
            # Python scalar/list tree, and final contiguous numeric array
            # before any of those decoded objects are materialized.
            source.require_decoded_bytes(
                len(payload_bytes) * 4 + decoded_nodes * 256,
                format_id=self.format_id,
            )
            payload = decode_portable_json(payload_bytes)
            dataset = SherpaDataset.from_dict(payload)
        except Exception as exc:
            if isinstance(exc, (ParserLimitError, UnreadableSpectrumError, UnsupportedFormatVariantError)):
                raise
            raise UnreadableSpectrumError(format_id=self.format_id, detail=source.exception_detail(exc)) from exc
        if int(dataset.X.size) != x_element_count:
            raise UnreadableSpectrumError(
                format_id=self.format_id,
                detail="portable JSON shape contradicts the decoded dataset",
            )
        dataset.meta["source_file"] = source.path.name
        return ingestion_result(
            source=source,
            format_id=self.format_id,
            variant="dataset-wire",
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            assets=(dataset_asset(dataset, asset_id="dataset"),),
        )


PLUGIN = SherpaJsonPlugin()
