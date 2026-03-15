from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from spectra_sherpa.app.services.dag.executor import DAGExecutor, WorkflowEdge, WorkflowNode

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "data" / "templates"
OUTPUT_NODE_TYPES = {"output.plot", "output.export"}


def _load_template(slug: str) -> dict:
    raw = yaml.safe_load((TEMPLATES_DIR / f"{slug}.yaml").read_text(encoding="utf-8"))
    return raw.get("template_data", raw)


def _build_executor(td: dict, overrides: dict[str, dict]) -> tuple[DAGExecutor, dict[str, str]]:
    executor = DAGExecutor()
    node_types: dict[str, str] = {}

    for node in td.get("nodes", []):
        params = dict(node.get("parameters") or {})
        if node["node_id"] in overrides:
            for keep in list(params.keys()):
                if keep.endswith("_dataset") or keep in {"source", "example_dataset", "example_file"}:
                    del params[keep]
            params.update(overrides[node["node_id"]])
        executor.add_node(
            WorkflowNode(
                node_id=node["node_id"],
                node_type=node["node_type"],
                parameters=params,
            )
        )
        node_types[node["node_id"]] = node["node_type"]

    for edge in td.get("edges", []):
        executor.add_edge(
            WorkflowEdge(
                from_node=edge["from_node_id"],
                to_node=edge["to_node_id"],
                from_output=edge.get("from_output", "default"),
                to_input=edge.get("to_input", "default"),
            )
        )

    return executor, node_types


@pytest.mark.parametrize(
    "slug,overrides",
    [
        ("nested_cv_validation", {"data_1": {"source": "eigenvector", "eigenvector_dataset": "corn_m5"}}),
        ("peak_guided_pls", {"data_1": {"source": "eigenvector", "eigenvector_dataset": "corn_m5"}}),
        ("representative_calibration", {"data_1": {"source": "eigenvector", "eigenvector_dataset": "corn_m5"}}),
        ("variable_selection_pls", {"data_1": {"source": "eigenvector", "eigenvector_dataset": "corn_m5"}}),
        ("vip_assisted_pls", {"data_1": {"source": "eigenvector", "eigenvector_dataset": "corn_m5"}}),
    ],
)
@pytest.mark.asyncio
async def test_regression_templates_execute_end_to_end(slug: str, overrides: dict[str, dict]) -> None:
    td = _load_template(slug)
    executor, node_types = _build_executor(td, overrides)

    await executor.execute()

    missing = [
        node_id
        for node_id, node_type in node_types.items()
        if node_type not in OUTPUT_NODE_TYPES and node_id not in executor.results
    ]
    assert not missing, f"{slug}: missing core node results for {missing}"
