"""
Deploy nodes for headless prediction server pipelines.

These nodes act as entry and exit points when a workflow is run
via the headless API or batch runner, allowing external data to be injected
and structured results to be returned.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa
from spectra_sherpa.app.services.dag.node_base import Node, NodeMetadata, NodeParameter, PortMetadata, register_node

logger = logging.getLogger(__name__)


@register_node
class DeployInputNode(Node):
    """
    Entry point for prediction pipelines.

    During 'Bench' interactive mode, this node acts as a dummy pass-through or returns
    an empty dataset to allow pipeline validation.

    During 'Deploy' (Headless) mode, the execution engine intercepts this node
    and injects the payload data matching the stream_name.
    """

    metadata = NodeMetadata(
        node_type="deploy.input",
        category="deploy",
        label="Deploy Input",
        description="Injects external data streams into headless prediction pipelines",
        parameters=[
            NodeParameter(
                name="stream_name",
                label="Stream Name",
                param_type="text",
                default="sample",
                description="Unique identifier for the incoming data stream (e.g. 'sample', 'reference')",
                required=True,
                category="basic",
            ),
        ],
        input_types=[],  # Source node
        output_type="spectrasherpa://types/SpectralDataset/1.0",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Dataset",
                description="Injected dataset",
            ),
        ],
    )

    async def execute(self, *args) -> Any:
        # In actual deployment, the runner (headless API or batch_predict.py)
        # intercepts execution and injects data before this is called.
        # If this execute() is called, we are likely running interactively in the Bench.
        logger.warning(
            f"DeployInputNode ({self.node_id}) executed normally. This usually indicates "
            "it's running in interactive/bench mode without injected payload data. Returning empty dataset."
        )
        empty_data = np.zeros((1, 1))
        dataset = coerce_to_sherpa(empty_data)
        dataset.title = f"Dummy Data for Stream: {self.parameters.get('stream_name')}"
        return dataset

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, input_map: dict[str, str], indent: str = "    ", use_scp: bool = False) -> list[str]:
        stream_name = self.parameters.get("stream_name", "sample")
        lines = [
            f"{indent}# --- {self.node_id} (Deploy Input) ---",
            f"{indent}# The prediction server injects the '{stream_name}' payload here.",
            f"{indent}# For local testing, supply dummy data:",
        ]
        if use_scp:
            lines.append(
                f"{indent}results['{self.node_id}'] = scp.NDDataset(np.zeros((1, 1)))  # Replace with actual data"
            )
        else:
            lines.append(f"{indent}results['{self.node_id}'] = _Result(np.zeros((1, 1)))  # Replace with actual data")
        return lines


@register_node
class DeployOutputNode(Node):
    """
    Exit point for prediction pipelines.

    Collects final pipeline outputs and formats them. The headless API
    will read the result of this node to return the HTTP response.
    """

    metadata = NodeMetadata(
        node_type="deploy.output",
        category="deploy",
        label="Deploy Output",
        description="Formats results for the headless prediction server API",
        parameters=[
            NodeParameter(
                name="output_format",
                label="Output Format",
                param_type="select",
                default="json",
                options=["json", "csv", "plain_text"],
                description="Format for the HTTP response or file output",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="key_value_separator",
                label="Key-Value Separator",
                param_type="text",
                default="=",
                description="Separator for plain_text mode (e.g. '=')",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="end_of_message_tag",
                label="End of Message Tag",
                param_type="text",
                default="\\n",
                description="Termination string for plain_text mode (e.g. '\\n')",
                required=False,
                category="advanced",
            ),
        ],
        input_types=["any"],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="any",
                required=True,
                label="Formatted Result",
                description="The formatted response data",
            ),
        ],
    )

    async def execute(self, payload: Any) -> dict:
        """
        Takes the upstream payload and formats it according to settings.
        Returns a dict containing the formatted raw response and metadata.
        """
        fmt = self.parameters.get("output_format", "json")
        separator = self.parameters.get("key_value_separator", "=")
        eom = self.parameters.get("end_of_message_tag", "\\n").encode().decode("unicode_escape")

        # If the payload is a dataset, try to extract its .data array
        raw_data = payload
        if isinstance(payload, SherpaDataset):
            raw_data = payload.data.tolist() if isinstance(payload.data, np.ndarray) else payload.data
        elif hasattr(payload, "data") and isinstance(payload.data, np.ndarray):
            raw_data = payload.data.tolist()
        elif isinstance(payload, np.ndarray):
            raw_data = payload.tolist()

        formatted_result = None

        if fmt == "json":
            # Just pass the raw serializable structure, FastAPI will jsonify it
            formatted_result = raw_data
        elif fmt == "csv":
            import csv
            import io

            output = io.StringIO()
            writer = csv.writer(output)
            if isinstance(raw_data, list) and len(raw_data) > 0:
                if isinstance(raw_data[0], list):
                    writer.writerows(raw_data)
                else:
                    writer.writerow(raw_data)
            else:
                writer.writerow([str(raw_data)])
            formatted_result = output.getvalue()
        elif fmt == "plain_text":
            if isinstance(raw_data, dict):
                lines = [f"{k}{separator}{v}" for k, v in raw_data.items()]
                formatted_result = "; ".join(lines) + eom
            else:
                formatted_result = f"Result{separator}{str(raw_data)}{eom}"

        return {"format": fmt, "content": formatted_result, "raw_payload": raw_data}

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, input_map: dict[str, str], indent: str = "    ", use_scp: bool = False) -> list[str]:
        in_var = input_map.get("default", "None")
        lines = [
            f"{indent}# --- {self.node_id} (Deploy Output) ---",
            f"{indent}# Pass through the result for export",
            f"{indent}results['{self.node_id}'] = {in_var}",
        ]
        return lines
