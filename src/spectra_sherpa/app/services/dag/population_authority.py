"""Conservative graph population authority shared by admission and execution.

A split identity is meaningful only inside its exact execution graph. Distinct
source handles alone do not prove independent observations. Unclassified row
transformations and externally loaded fitted states cannot acquire a held-out
claim from matching array dimensions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .executor_types import ValidationIssue, WorkflowEdge
from .managed_port_topology import resolve_declared_port
from .node_base import Node

# Population is an exact source or split branch, never a sample count.
Population = tuple[str, str]


@dataclass(frozen=True)
class Lineage:
    population: Population | None = None
    fits: frozenset[Population] = frozenset()
    qualified: bool = False
    exposures: frozenset[Population] = frozenset()


def _variable_selection_lineage(
    node: Node,
    output: str,
    inputs: dict[str, Lineage],
    primary: Lineage,
    fits: frozenset[Population],
    qualified: bool,
    exposures: frozenset[Population],
) -> Lineage:
    """Carry a training-derived feature mask across its test application."""

    method = node.parameters.get("method", "vip")
    selected_data_output = output in {"default", "X_selected"}
    if method == "peak_window":
        # Peak locations are estimated from the connected cohort.  The mask
        # is therefore fitted preprocessing state even though the numerical
        # node remains a stateless transform.
        mask_fits = fits | primary.exposures
        if output == "mask":
            return Lineage(None, mask_fits, primary.qualified, primary.exposures)
        if selected_data_output:
            return Lineage(primary.population, mask_fits, primary.qualified, primary.exposures)
        return Lineage(None, mask_fits, False, primary.exposures)
    if method == "apply_mask":
        mask = inputs.get("mask", Lineage())
        mask_fits = fits | mask.fits
        mask_exposures = primary.exposures | mask.exposures
        mask_qualified = primary.qualified and mask.qualified
        if output == "mask":
            return Lineage(None, mask_fits, mask_qualified, mask_exposures)
        if selected_data_output:
            return Lineage(primary.population, mask_fits, mask_qualified, mask_exposures)
        return Lineage(None, mask_fits, False, mask_exposures)
    if output == "mask":
        return Lineage(None, fits, qualified, exposures)
    if selected_data_output:
        return Lineage(primary.population, fits, qualified, exposures)
    return Lineage(None, fits, False, exposures)


def analyze_populations(
    nodes: dict[str, Node], edges: list[WorkflowEdge]
) -> tuple[list[ValidationIssue], dict[str, dict[str, Any]]]:
    """Return refusals and evaluation receipts without reading matrices."""
    incoming: dict[str, list[tuple[str, str, str]]] = {key: [] for key in nodes}
    for edge in edges:
        try:
            source = nodes[edge.from_node].metadata
            target = nodes[edge.to_node].metadata
            if source is None or target is None:
                continue
            output = resolve_declared_port(source, edge.from_output, "output").name
            port = resolve_declared_port(target, edge.to_input, "input").name
            incoming[edge.to_node].append((port, edge.from_node, output))
        except (KeyError, ValueError):
            continue  # Structural admission reports the malformed edge.
    issues: list[ValidationIssue] = []
    receipts: dict[str, dict[str, Any]] = {}
    cache: dict[tuple[str, str], Lineage] = {}
    visiting: set[tuple[str, str]] = set()

    def refuse(node_id: str, port: str, message: str) -> None:
        issue = ValidationIssue("error", node_id, port, "Population authority: " + message, "population_authority")
        if issue not in issues:
            issues.append(issue)

    def trace(node_id: str, output: str = "default") -> Lineage:
        key = node_id, output
        if key in cache:
            return cache[key]
        if key in visiting:
            return Lineage()  # Cycle admission owns the error.
        visiting.add(key)
        node = nodes[node_id]
        metadata = node.metadata
        contract = metadata.resolved_execution_contract() if metadata else None
        if not metadata or contract is None:
            result = Lineage()
        elif not metadata.input_ports:
            result = Lineage((node_id, "source"), qualified=True, exposures=frozenset({(node_id, "source")}))
        else:
            resolved_inputs = [(port, trace(source, out)) for port, source, out in incoming[node_id]]
            inputs = dict(resolved_inputs)
            payload = contract.payload
            lifecycle = payload["lifecycle_kind"]
            # The first declared data input is the canonical primary input;
            # classifier applications explicitly select X_new when connected.
            primary_name = "X_new" if "X_new" in inputs else metadata.input_ports[0].name
            primary = inputs.get(primary_name, Lineage())
            fits = frozenset(pop for _, item in resolved_inputs for pop in item.fits)
            qualified = (
                bool(inputs) and len(inputs) == len(resolved_inputs) and all(item.qualified for item in inputs.values())
            )
            population = primary.population
            exposures = frozenset(pop for _, item in resolved_inputs for pop in item.exposures)
            if metadata.node_type == "data.train_test_split":
                if output in {"X_train", "y_train", "X_test", "y_test"}:
                    population = (node_id, "train" if output.endswith("train") else "test")
                else:
                    population = None
                result = Lineage(
                    population,
                    fits,
                    qualified and population is not None,
                    frozenset({population}) if population else frozenset(),
                )
            elif metadata.node_type == "selection.variable_select":
                result = _variable_selection_lineage(
                    node,
                    output,
                    inputs,
                    primary,
                    fits,
                    qualified,
                    exposures,
                )
            else:
                if lifecycle in {"fitted_model", "fitted_transform"}:
                    reference = inputs.get("reference", primary)
                    if reference.population:
                        fit_exposures = reference.exposures | frozenset(
                            pop
                            for port, item in inputs.items()
                            if port not in {primary_name, "reference"}
                            for pop in item.exposures
                        )
                        fits = fits | fit_exposures
                        if any(pop[1] == "test" for pop in fit_exposures):
                            refuse(
                                node_id,
                                "reference" if "reference" in inputs else primary_name,
                                "fitting on an explicit test branch is not admitted; fit on training data.",
                            )
                    else:
                        qualified = False
                    if "y" in inputs and inputs["y"].population != reference.population:
                        populations = (inputs["y"].population, reference.population)
                        if all(pop is not None for pop in populations) and any(
                            pop[1] in {"train", "test"} for pop in populations if pop is not None
                        ):
                            refuse(node_id, "y", "predictor and target fitting populations do not match.")
                        qualified = False
                if lifecycle == "artifact_application":
                    # These are the canonical state/reference input names. A
                    # data input may itself carry fitted preprocessing, which
                    # says nothing about the applied model's training rows.
                    states = [inputs[name] for name in ("fitted_state", "model", "model_ref") if name in inputs]
                    if not states or not all(state.qualified and state.fits for state in states):
                        qualified = False
                    # Parameter-loaded artifacts have no in-graph fit receipt.
                if lifecycle == "evaluator" and "y_true" in inputs:
                    truth = inputs["y_true"]
                    role = "unqualified_evaluation"
                    if population is not None and truth.population is not None and population != truth.population:
                        if any(pop[1] in {"train", "test"} for pop in (population, truth.population)):
                            refuse(
                                node_id, "y_true", "prediction and reference populations come from different branches."
                            )
                    aligned = qualified and population is not None and population == truth.population
                    if aligned and population[1] == "test":
                        expected = (population[0], "train")
                        if not fits or fits != frozenset({expected}):
                            refuse(
                                node_id,
                                primary_name,
                                "held-out evaluation requires every fitted state "
                                "to use the same split's training branch.",
                            )
                        else:
                            role = "held_out_test"
                    elif aligned and fits == frozenset({population}):
                        role = "calibration"
                    receipts[node_id] = {
                        "schema_version": "spectrasherpa-population-authority/1",
                        "role": role,
                        "population": list(population) if population else None,
                        "fitted_populations": [list(item) for item in sorted(fits)],
                        "qualification": "graph_verified" if role != "unqualified_evaluation" else "unverified_lineage",
                    }
                elif payload["sample_effect"] != "preserves_samples":
                    qualified = False
                    population = None
                # Auxiliary outputs such as loadings are not sample rows.
                # State edges still carry fitted-population evidence, but must
                # not impersonate row-preserving predictor data.
                if not metadata.output_ports or output not in {
                    metadata.output_ports[0].name,
                    "predictions",
                    "X_selected",
                    "scores",
                    "fitted_state",
                    "model",
                }:
                    population = None
                    qualified = False
                result = Lineage(population, fits, qualified, exposures)
        visiting.remove(key)
        cache[key] = result
        return result

    for node_id in nodes:
        trace(node_id)
    return issues, receipts


def qualify_evaluation_result(result: Any, receipt: dict[str, Any] | None) -> Any:
    """Project executor-owned evidence onto results after worker execution."""
    if receipt is None:
        return result
    from .node_base import NodeResult

    if not isinstance(result, NodeResult):
        return result
    role = receipt["role"]
    result.diagnostics["population_authority"] = receipt
    metrics = result.outputs.get("default")
    if isinstance(metrics, dict):
        metrics["population_authority"] = receipt
    comparison = result.outputs.get("comparison")
    if isinstance(comparison, dict):
        comparison.setdefault("metadata", {}).update(role=role, population_authority=receipt)
        for row in comparison.get("data", []):
            row["role"] = role
    visualization = result.outputs.get("visualization")
    if isinstance(visualization, dict):
        visualization.setdefault("metadata", {}).update(role=role, population_authority=receipt)
    return result
