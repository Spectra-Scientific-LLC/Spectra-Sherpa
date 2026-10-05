"""Create, execute, save, and reopen a small canonical spectroscopy DAG."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

import spectra_sherpa.sdk as ss
from spectra_sherpa.sdk.deployment import DEPLOYMENT_INPUT_SCHEMA


def example_dataset() -> ss.SherpaDataset:
    """Return a small deterministic absorbance dataset with physical axes."""

    axis = np.linspace(1000.0, 1800.0, 24)
    baseline = np.linspace(0.2, 0.8, axis.size)
    rows = np.vstack([baseline + 0.08 * index + 0.04 * np.sin(axis / 55.0 + index) for index in range(8)])
    return ss.data.from_array(
        rows,
        x=axis,
        samples=[f"sample-{index + 1}" for index in range(rows.shape[0])],
        units="cm-1",
        data_units="absorbance",
        technique="FTIR",
        title="Canonical SDK quickstart",
    )


def build_workflow() -> ss.workflow.WorkflowSpec:
    """Build the same typed DAG that the Workbench executor understands."""

    return ss.workflow.workflow_spec(
        nodes=[
            {
                "node_id": "spectra",
                "node_type": "deploy.input",
                "parameters": {
                    "stream_name": "quickstart-spectra",
                    "schema_version": DEPLOYMENT_INPUT_SCHEMA,
                },
            },
            {
                "node_id": "normalize",
                "node_type": "preprocess.normalize",
                "parameters": {"method": "snv"},
            },
            {
                "node_id": "plot",
                "node_type": "output.plot",
                "parameters": {"plot_type": "spectra", "colorscale": "Viridis"},
            },
        ],
        edges=[
            {
                "from_node_id": "spectra",
                "to_node_id": "normalize",
                "from_output": "default",
                "to_input": "default",
            },
            {
                "from_node_id": "normalize",
                "to_node_id": "plot",
                "from_output": "default",
                "to_input": "default",
            },
        ],
    )


def run(output_dir: str | Path) -> dict[str, Any]:
    """Execute the quickstart twice, proving durable DAG identity and output."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    workflow = build_workflow()
    workflow_path = destination / "canonical-workflow.json"
    workflow_path.write_text(json.dumps(workflow.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    reopened = ss.workflow.WorkflowSpec.from_dict(json.loads(workflow_path.read_text(encoding="utf-8")))
    dataset = example_dataset()
    execution = ss.runtime.execute_workflow(
        reopened,
        deployment_inputs={"quickstart-spectra": dataset},
    )
    visualization = dict(execution.output("plot", "visualization"))
    plot_path = destination / "canonical-plot.json"
    plot_path.write_text(json.dumps(visualization, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = {
        "workflow_digest": reopened.workflow_digest,
        "dataset_content_digests": dict(execution.dataset_content_digests),
        "completed_nodes": sorted(execution.results),
        "diagnostic_nodes": sorted(execution.diagnostics),
        "workflow_path": str(workflow_path),
        "plot_path": str(plot_path),
        "plot_traces": len(visualization["data"]),
    }
    (destination / "run-summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="spectra-sherpa-quickstart")
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
