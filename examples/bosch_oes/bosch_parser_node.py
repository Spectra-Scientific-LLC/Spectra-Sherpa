"""Compatibility facade for the former prototype; no runtime node registration."""

from pathlib import Path

from spectra_sherpa.io.bosch_netcdf import read_bosch_netcdf
from spectra_sherpa.io.types import ParserLimits


class BoschOESParser:
    """Read actual acquisitions, without inventing process-phase boundaries."""

    @classmethod
    def parse_dataset(
        cls,
        oes_path: Path,
        dict_path: Path,
        wafer_group: str = "Wafer_01",
        step_filter: str = "all",
        sample_count: int = 50,
    ):
        if step_filter not in {"all", "time_series_sample"}:
            raise ValueError(
                "Phase-specific averaging requires independently established phase boundaries; "
                "use 'all' or 'time_series_sample' to ingest unaggregated acquisitions"
            )
        if type(sample_count) is not int or sample_count <= 0:
            raise ValueError("sample_count must be a positive integer")
        rows = slice(0, sample_count) if step_filter == "time_series_sample" else None
        return read_bosch_netcdf(
            oes_path,
            dictionary_path=dict_path,
            group=wafer_group,
            rows=rows,
            limits=ParserLimits(max_source_bytes=1024**3),
        )


# Retain the old import name as a facade, not as a registered/abstract Node.
BoschOESNetCDFParserNode = BoschOESParser
