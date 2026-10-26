"""Decode BOSCH acquisitions and run the canonical OSS smoothing/peak workflow.

Run from this directory, or add this directory to PYTHONPATH. All input/output
paths are explicit. No download, source registration or phase inference occurs.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from pathlib import Path

import spectra_sherpa.sdk as ss
from spectra_sherpa.io.bosch_netcdf import read_bosch_netcdf
from spectra_sherpa.io.types import ParserLimits
from spectra_sherpa.sdk.deployment import DEPLOYMENT_INPUT_SCHEMA

try:
    from .bosch_parser_node import BoschOESParser as BoschOESParser
    from .transition_analyzer import TransitionAnalyzer
except ImportError:
    from bosch_parser_node import BoschOESParser as BoschOESParser
    from transition_analyzer import TransitionAnalyzer


def build_oes_dag():
    return ss.workflow.workflow_spec(
        nodes=[
            {
                "node_id": "oes_input",
                "node_type": "deploy.input",
                "parameters": {"stream_name": "bosch-oes-stream", "schema_version": DEPLOYMENT_INPUT_SCHEMA},
            },
            {
                "node_id": "smooth",
                "node_type": "preprocess.smooth",
                "parameters": {"method": "savitzky_golay", "size": 9, "order": 2},
            },
            {
                "node_id": "peak_finding",
                "node_type": "analysis.peak_finding",
                "parameters": {"distance": 6, "prominence": 10.0, "consensus_tolerance": 0.6},
            },
            {"node_id": "plot", "node_type": "output.plot", "parameters": {"plot_type": "spectra"}},
        ],
        edges=[
            {"from_node_id": "oes_input", "to_node_id": "smooth"},
            {"from_node_id": "smooth", "to_node_id": "peak_finding"},
            {"from_node_id": "smooth", "to_node_id": "plot"},
        ],
    )


def write_peak_csv(path: Path, rows: list[dict], analyzer: TransitionAnalyzer | None = None) -> None:
    """Write actual retained consensus measurements with valid CSV quoting."""
    fields = [
        "observed_wavelength_nm",
        "height",
        "half_prominence_width_nm",
        "candidate_species",
        "reference_wavelength_nm",
        "delta_nm",
        "lower_conf",
        "upper_conf",
        "term_transition",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            match = analyzer.identify_peak(float(row["median_pos"]), tolerance=0.7) if analyzer else {}
            transition = match.get("nist_transition") or {}
            writer.writerow(
                {
                    "observed_wavelength_nm": row["median_pos"],
                    "height": row["median_height"],
                    "half_prominence_width_nm": row["median_half_prominence_width"],
                    "candidate_species": match.get("species", "Unassigned"),
                    "reference_wavelength_nm": match.get("reference_wavelength_nm"),
                    "delta_nm": match.get("delta_nm"),
                    "lower_conf": transition.get("lower_conf", ""),
                    "upper_conf": transition.get("upper_conf", ""),
                    "term_transition": (
                        f"{transition['lower_term']} -> {transition['upper_term']}" if transition else ""
                    ),
                }
            )


def run_pipeline(
    oes_path: Path,
    dictionary_path: Path,
    *,
    group: str,
    row_count: int,
    output: Path,
    reference_csv: Path | None = None,
) -> dict:
    if type(row_count) is not int or row_count < 1:
        raise ValueError("row_count must be a positive integer")
    dataset = read_bosch_netcdf(
        oes_path,
        dictionary_path=dictionary_path,
        group=group,
        rows=slice(0, row_count),
        limits=ParserLimits(max_source_bytes=1024**3),
    )
    workflow = build_oes_dag()
    # Native acquisition annotations are not a managed spectral capability.
    # Use the canonical local executor's named deployment admission, retaining
    # the complete typed sample table instead of stripping it for SDK transport.
    from spectra_sherpa.app.services.dag.executor import DAGExecutor, WorkflowEdge, WorkflowNode

    executor = DAGExecutor()
    for node in workflow.payload["nodes"]:
        executor.add_node(WorkflowNode(node["node_id"], node["node_type"], node["parameters"]))
    for edge in workflow.payload["edges"]:
        executor.add_edge(
            WorkflowEdge(
                edge["from_node_id"], edge["to_node_id"], from_output=edge["from_output"], to_input=edge["to_input"]
            )
        )
    executor.inject_deployment_input("oes_input", dataset, stream_name="bosch-oes-stream")
    execution = asyncio.run(executor.execute())
    rows = execution["peak_finding"]["peaks"]["data"]
    analyzer = TransitionAnalyzer(reference_csv) if reference_csv else None
    write_peak_csv(output, rows, analyzer)
    return {
        "shape": list(dataset.shape),
        "workflow_digest": workflow.workflow_digest,
        "consensus_peaks": len(rows),
        "output": str(output),
        "ingestion_authority": dataset.get_extra("ingestion.authority"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--dictionary", type=Path, required=True)
    parser.add_argument("--group", default="Wafer_01")
    parser.add_argument("--rows", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-csv", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            run_pipeline(
                args.source,
                args.dictionary,
                group=args.group,
                row_count=args.rows,
                output=args.output,
                reference_csv=args.reference_csv,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
