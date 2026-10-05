"""Execute reference-spectrum synthesis through the canonical typed DAG.

This module owns graph projection only.  The cited numerical authorities live
in registered nodes: source response scaling, ppm unit conversion, species
identity, pure-response merging, bilinear blending, and optional seeded noise.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from spectra_sherpa.core.execution_runtime import ExecutionRuntime

from .deployment import DEPLOYMENT_INPUT_SCHEMA
from .runtime import CanonicalSDKExecution, execute_workflow
from .workflow import WorkflowSpec, workflow_spec

_CONCENTRATION_STREAM = "reference-synthesis-concentrations"
_CONCENTRATION_INPUT = "reference.synthesis.concentrations"
_CONCENTRATION_FRACTION = "reference.synthesis.ppm-fraction"
_MERGE_NODE = "reference.synthesis.merge"
_BLEND_NODE = "reference.synthesis.blend"
_NOISE_NODE = "reference.synthesis.noise"


def reference_synthesis_workflow(
    *,
    component_names: Sequence[str],
    source: str,
    pathlength_cm: float,
    temperature_k: float,
    pressure_atm: float,
    noise_sigma_au: float,
    seed: int,
) -> WorkflowSpec:
    """Project one explicit NIST/HITRAN synthesis request into a typed DAG."""

    names = tuple(component_names)
    if not names or any(not isinstance(name, str) or not name.strip() for name in names):
        raise ValueError("reference synthesis requires non-empty component names")
    if len(set(names)) != len(names):
        raise ValueError("reference synthesis component names must be unique")
    if source == "nist_quant_ir":
        response_type = "synthesis.nist_quant_ir_response"
        response_parameters: dict[str, object] = {"pathlength_cm": pathlength_cm}
    elif source in {"hitran", "hitran_xsec"}:
        response_type = "synthesis.hitran_response"
        response_parameters = {
            "pathlength_cm": pathlength_cm,
            "pressure_atm": pressure_atm,
            "temperature_k": temperature_k,
        }
    else:
        raise ValueError(f"unsupported reference synthesis source: {source!r}")

    nodes: list[dict[str, object]] = [
        {
            "node_id": _CONCENTRATION_INPUT,
            "node_type": "deploy.input",
            "parameters": {
                "stream_name": _CONCENTRATION_STREAM,
                "schema_version": DEPLOYMENT_INPUT_SCHEMA,
            },
        },
        {
            "node_id": _CONCENTRATION_FRACTION,
            "node_type": "synthesis.ppm_fraction",
            "parameters": {},
        },
        {"node_id": _MERGE_NODE, "node_type": "synthesis.merge", "parameters": {}},
        {"node_id": _BLEND_NODE, "node_type": "synthesis.blend", "parameters": {}},
    ]
    edges: list[dict[str, str]] = [
        {
            "from_node_id": _CONCENTRATION_INPUT,
            "to_node_id": _CONCENTRATION_FRACTION,
            "from_output": "target",
            "to_input": "default",
        },
        {
            "from_node_id": _CONCENTRATION_FRACTION,
            "to_node_id": _BLEND_NODE,
            "from_output": "default",
            "to_input": "concentrations",
        },
        {
            "from_node_id": _MERGE_NODE,
            "to_node_id": _BLEND_NODE,
            "from_output": "default",
            "to_input": "pure_spectra",
        },
    ]
    for index, name in enumerate(names):
        input_id = f"reference.synthesis.source.{index}"
        response_id = f"reference.synthesis.response.{index}"
        species_id = f"reference.synthesis.species.{index}"
        stream_name = f"reference-synthesis-source-{index}"
        nodes.extend(
            [
                {
                    "node_id": input_id,
                    "node_type": "deploy.input",
                    "parameters": {"stream_name": stream_name, "schema_version": DEPLOYMENT_INPUT_SCHEMA},
                },
                {"node_id": response_id, "node_type": response_type, "parameters": dict(response_parameters)},
                {
                    "node_id": species_id,
                    "node_type": "synthesis.species",
                    "parameters": {"species_name": name, "molar_absorptivity": None},
                },
            ]
        )
        edges.extend(
            [
                {
                    "from_node_id": input_id,
                    "to_node_id": response_id,
                    "from_output": "default",
                    "to_input": "default",
                },
                {
                    "from_node_id": response_id,
                    "to_node_id": species_id,
                    "from_output": "default",
                    "to_input": "default",
                },
                {
                    "from_node_id": species_id,
                    "to_node_id": _MERGE_NODE,
                    "from_output": "default",
                    "to_input": "default",
                },
            ]
        )
    if noise_sigma_au > 0.0:
        nodes.append(
            {
                "node_id": _NOISE_NODE,
                "node_type": "custom.noise_injection",
                "parameters": {
                    "noise_level": noise_sigma_au,
                    "noise_type": "absolute",
                    "seed": seed,
                },
            }
        )
        edges.append(
            {
                "from_node_id": _BLEND_NODE,
                "to_node_id": _NOISE_NODE,
                "from_output": "default",
                "to_input": "default",
            }
        )
    return workflow_spec(nodes=nodes, edges=edges)


def execute_reference_synthesis(
    *,
    pure_responses: Sequence[Any],
    concentrations_ppm: Any,
    component_names: Sequence[str],
    source: str,
    pathlength_cm: float,
    temperature_k: float,
    pressure_atm: float,
    noise_sigma_au: float,
    seed: int,
    runtime: ExecutionRuntime | None = None,
) -> CanonicalSDKExecution:
    """Execute one reference synthesis and retain its exact workflow and diagnostics."""

    responses = tuple(pure_responses)
    if len(responses) != len(tuple(component_names)):
        raise ValueError("reference synthesis requires one pure response per component name")
    workflow = reference_synthesis_workflow(
        component_names=component_names,
        source=source,
        pathlength_cm=pathlength_cm,
        temperature_k=temperature_k,
        pressure_atm=pressure_atm,
        noise_sigma_au=noise_sigma_au,
        seed=seed,
    )
    deployment_inputs: dict[str, Any] = {_CONCENTRATION_STREAM: concentrations_ppm}
    deployment_inputs.update(
        {f"reference-synthesis-source-{index}": response for index, response in enumerate(responses)}
    )
    return execute_workflow(workflow, deployment_inputs=deployment_inputs, runtime=runtime)


def reference_synthesis_output(execution: CanonicalSDKExecution, *, noise_added: bool) -> Any:
    """Return the final dataset from one completed reference synthesis DAG."""

    return execution.output(_NOISE_NODE if noise_added else _BLEND_NODE)


__all__ = [
    "execute_reference_synthesis",
    "reference_synthesis_output",
    "reference_synthesis_workflow",
]
