"""Display-only application of excluded observations to the executed fit.

Numerical edges always use active results. These companions cannot be wired,
fitted, evaluated or included in metrics. Nodes opt in with an explicit
``project_population`` operation; lifecycle names and array lengths alone are
not proof that a scientific application is defined.
"""

from __future__ import annotations

import logging
from typing import Any

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

DISPLAY_KEY = "__workflow_population"
logger = logging.getLogger(__name__)


def computational_outputs(value: Any) -> Any:
    """Legacy dictionary inputs retain public results, never display payloads."""
    private = {DISPLAY_KEY, "__source_population"}
    if not isinstance(value, dict) or not private.intersection(value):
        return value
    return {key: item for key, item in value.items() if key not in private}


def observation_refs(dataset: SherpaDataset) -> list[str]:
    axis = dataset.sample_axis
    refs = None if axis is None else axis.workflow_observation_refs
    if (
        not isinstance(refs, list)
        or len(refs) != dataset.n_samples
        or any(not isinstance(ref, str) or not ref for ref in refs)
        or len(set(refs)) != len(refs)
    ):
        raise ValueError("Display population requires exact aligned source observation references")
    return refs


def application_input(dataset: SherpaDataset) -> SherpaDataset:
    """Admit rows for application only; never pass this copy to fitting."""
    from spectra_sherpa.core.target_authority import admit_target_authority

    from .supervision_binding import admit_attached_sample_table_supervision, bind_sample_table_supervision

    supervision = admit_attached_sample_table_supervision(dataset)
    admitted = dataset.copy()
    axis = admitted.sample_axis
    axis.include_mask = [True] * admitted.n_samples
    admitted.sample_axis = axis
    if supervision is not None:
        authority = admit_target_authority(supervision.record["target_authority"], optional=False)
        rebound = bind_sample_table_supervision(
            admitted,
            target_column=authority.column,
            target_type=authority.target_type,
            group_column=supervision.record["group_column"],
            target_authority=authority,
        )
        admitted.meta["supervision_binding"] = {**rebound.record, "supervision_binding_sha256": rebound.digest}
    return admitted


def projection_within_budget(outputs: Any, inputs: Any, *, limit: int = 64 * 1024 * 1024) -> bool:
    """Bound the entire dispatch, including nested datasets and fitted state."""
    import sys

    import numpy as np

    remaining, visited = limit, {}

    def charge(value: Any) -> bool:
        nonlocal remaining
        if id(value) in visited:
            return True
        # Hold references: NumPy structured scalars are temporary wrappers and
        # Python may otherwise reuse their ids before the walk is finished.
        visited[id(value)] = value
        if isinstance(value, np.ndarray):
            remaining -= max(sys.getsizeof(value), value.nbytes)
            if value.dtype.hasobject:
                return remaining >= 0 and all(charge(item) for item in value.flat)
        elif isinstance(value, np.void) and value.dtype.hasobject and value.dtype.names:
            remaining -= sys.getsizeof(value)
            return remaining >= 0 and all(charge(value[name]) for name in value.dtype.names)
        elif isinstance(value, SherpaDataset):
            # The worker receives the dataset, not just its numerical matrix:
            # axes/sample tables, provenance and typed contexts travel too.
            return charge(vars(value))
        elif isinstance(value, dict):
            remaining -= sys.getsizeof(value)
            return remaining >= 0 and all(charge(item) for pair in value.items() for item in pair)
        elif isinstance(value, (list, tuple, set, frozenset)):
            remaining -= sys.getsizeof(value)
            return remaining >= 0 and all(charge(item) for item in value)
        elif isinstance(value, (str, bytes, bytearray)):
            remaining -= sys.getsizeof(value)
        elif isinstance(value, memoryview):
            remaining -= max(sys.getsizeof(value), value.nbytes)
        elif isinstance(value, (int, float, np.number)):
            remaining -= sys.getsizeof(value)
        elif hasattr(value, "__dict__"):
            return charge(vars(value))
        return remaining >= 0

    return charge((outputs, inputs))


def applied_dataset(values: Any, source: SherpaDataset, template: SherpaDataset) -> SherpaDataset:
    """Node-declared application output with exact observation/feature axes."""
    output = SherpaDataset(
        X=values,
        feature_axis=template.feature_axis,
        sample_axis=source.sample_axis,
        target=source.target,
        target_context=source.target_context,
        domain=template.domain,
        source_identity=source.source_identity,
        provenance=template.provenance.copy(),
        units=template.units,
        title=template.title,
        data_role=template.data_role,
    )
    if output.n_samples != source.n_samples:
        raise ValueError("Population application changed observation membership")
    # Only display labels may cross populations. In particular, never copy an
    # active-cohort supervision receipt or calibration metrics onto these rows.
    for key in (
        "pc_labels",
        "lv_labels",
        "explained_variance_ratio",
        "scientific_matrix_role",
        "x_title",
        "x_units",
        "y_title",
        "y_units",
    ):
        if key in template.meta:
            output.meta[key] = template.meta[key]
    output.provenance.append(
        op_id="spectrasherpa.population_display/1",
        parameters={"role": "display_only_not_fit_or_validation", "fitted_population_count": template.n_samples},
        input_shape=source.shape,
        output_shape=output.shape,
    )
    return output


class RowLocalPopulationProjection:
    """Explicit opt-in for transforms mathematically independent per spectrum.

    Never attach this to cohort-based selection, fitting, aggregation, or any
    writer. The same canonical execute function computes the display values.
    """

    async def project_population(self, outputs: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
        source = inputs.get("input_data", inputs.get("default"))
        if not isinstance(source, SherpaDataset):
            return {}
        result = await self.execute(input_data=application_input(source))
        result_outputs = result.outputs if hasattr(result, "outputs") else result
        return {
            name: applied_dataset(value.X, source, value)
            for name, value in result_outputs.items()
            if isinstance(value, SherpaDataset)
        }


class RetainedTransformPopulationProjection:
    """Apply, never refit, the exact transform state retained during execution."""

    async def project_population(self, outputs: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
        source = inputs.get("input_data", inputs.get("default"))
        output = outputs.get("default")
        if not isinstance(source, SherpaDataset) or not isinstance(output, SherpaDataset):
            return {}
        step = output.provenance.to_list()[-1]
        state = step["parameters"]["transform_state"]
        projected = self.apply_fitted_state(application_input(source), state)
        return {"default": applied_dataset(projected.X, source, output)}


async def retain_population_display(executor: Any, node_id: str) -> None:
    """Attach a non-connectable projection using only this execution's inputs."""
    node = executor.nodes[node_id]
    outputs = executor.results[node_id]
    if not isinstance(outputs, dict):
        return
    if isinstance(outputs.get("__source_population"), SherpaDataset) and isinstance(outputs.get("exclusions"), dict):
        state = outputs["exclusions"]
        summary = {key: value for key, value in state.items() if key not in {"rows", "data"}}
        outputs[DISPLAY_KEY] = {
            "sources": {node_id: summary},
            "availability": "available",
            "outputs": {"default": outputs.pop("__source_population")},
        }
        return
    sources: dict[str, Any] = {}
    inputs: dict[str, Any] = {}
    source_states: dict[str, dict[str, Any]] = {}
    for edge in executor.edges:
        if edge.to_node != node_id:
            continue
        upstream = executor.results.get(edge.from_node)
        companion = upstream.get(DISPLAY_KEY) if isinstance(upstream, dict) else None
        if not isinstance(companion, dict):
            continue
        workflow_sources = {
            key: state for key, state in companion["sources"].items() if state.get("workflow_excluded_count", 0) > 0
        }
        if not workflow_sources:
            continue
        sources.update(workflow_sources)
        if edge.from_output in companion.get("outputs", {}):
            value = companion["outputs"][edge.from_output]
            state = upstream.get("exclusions")
            if isinstance(value, SherpaDataset) and isinstance(state, dict) and state.get("rows"):
                source_states[edge.to_input] = state
            inputs[edge.to_input] = value
    if not sources:
        return
    record: dict[str, Any] = {
        "sources": sources,
        "outputs": {},
        "availability": "unavailable",
        "reason": "This operation has no declared out-of-fit observation projection.",
    }
    projector = getattr(node, "project_population", None)
    if callable(projector) and inputs:
        if not projection_within_budget(outputs, inputs):
            record["reason"] = "Excluded display projection exceeds the 64 MiB input budget."
            outputs[DISPLAY_KEY] = record
            return
        try:
            # Only eligible, bounded projections may allocate a source copy.
            # My Dataset defines the starting population; workflow exclusions
            # alone travel downstream as display-only overlays.
            import numpy as np

            from .sample_subset_supervision import rebind_sample_subset_supervision

            for name, state in source_states.items():
                value = inputs[name]
                source_refs = {row["observation_ref"] for row in state["rows"] if row["source_included"]}
                mask = np.asarray([ref in source_refs for ref in observation_refs(value)], dtype=bool)
                if not mask.all():
                    subset = value[mask]
                    rebind_sample_subset_supervision(value, subset)
                    inputs[name] = subset
            if not projection_within_budget(outputs, inputs):
                raise ValueError("Excluded display projection exceeds the 64 MiB input budget.")
            record["outputs"] = await executor._run_population_projection(node, outputs, inputs)
        except Exception as exc:
            # A projection refusal must not turn a successful fit into a failed
            # run or silently manufacture positions. Retain the refusal.
            logger.warning("Workflow population projection unavailable for %s: %s", node_id, exc)
            record["reason"] = str(exc)
        record["availability"] = "available" if record["outputs"] else "unavailable"
        if record["outputs"]:
            record.pop("reason", None)
    outputs[DISPLAY_KEY] = record
