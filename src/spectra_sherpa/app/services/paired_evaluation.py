"""Retained paired development evaluations using the canonical fold executor."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.sheet_fold_validation import _ensure_type_registry, _supervised_inputs
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.services.run_output_retention import read_output
from spectra_sherpa.core.node_identity import canonical_node_type
from spectra_sherpa.sdk.validate import make_split_plan

SCHEMA = "spectrasherpa-paired-evaluation/1"


class RecipeSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: int = Field(gt=0)
    model_node_id: str = Field(min_length=1, max_length=200)


class PairedEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipes: list[RecipeSelection] = Field(min_length=2, max_length=2)
    population_run_id: int = Field(gt=0)
    folds: int = Field(default=5, ge=2, le=20)
    repetitions: int = Field(default=1, ge=1, le=10)
    seed: int = Field(default=42, ge=0, le=2**31 - 11)
    meaningful_rmsecv_difference: float = Field(default=0, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def selected_population(self):
        if self.population_run_id not in {recipe.run_id for recipe in self.recipes}:
            raise ValueError("Choose the development population of one of the selected saved runs.")
        if len({(r.run_id, r.model_node_id) for r in self.recipes}) != 2:
            raise ValueError("Choose two distinct saved model outputs.")
        return self


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def retained_reader(run):
    evidence = RunEvidence.model_validate(run.evidence_completeness)
    if run.status != "completed" or evidence.qualification != "qualified":
        raise ValueError(
            "A completed run with exact retained evidence is required; execute and save the workflow first."
        )
    remaining = 64 * 1024 * 1024

    def exact(node, port):
        nonlocal remaining
        item = evidence.outputs.get(node, {}).get(port)
        if item is None or item.state != "exact" or item.storage != "file" or not item.sha256:
            raise ValueError(f"Exact saved output {node}/{port} is unavailable; execute and save the workflow first.")
        remaining -= item.byte_count or 0
        if remaining < 0 or not item.byte_count:
            raise ValueError("Retained recipe exceeds the 64 MiB evaluation read budget.")
        return read_output(run.user_id, item)

    return exact


def restore_dataset(payload: dict) -> SherpaDataset:
    """Restore checksummed API retention, verifying the scientific identity."""
    wire = dict(payload)
    if wire.get("type") != "SherpaDataset":
        raise ValueError("The saved source is not an exact scientific dataset.")
    manifest = wire.pop("manifest", {})
    science = wire.pop("scientific_projection", {})
    if science.get("schema_version") != "spectrasherpa-dataset-scientific-projection/1":
        raise ValueError("The saved source has no supported scientific receipt.")
    wire["title"] = science["title"]
    wire["data"] = np.asarray(wire["data"], dtype=science["normalized_dtype"])
    if wire.get("target") is not None and science.get("target") is not None:
        wire["target"] = np.asarray(wire["target"], dtype=science["target"]["dtype"])
    for old, new in (("x_axis", "feature_axis"), ("y_axis", "sample_axis")):
        if old in wire:
            wire[new] = wire.pop(old)
    wire["metadata"] = {
        **wire.get("metadata", {}),
        "data_type": (wire.get("domain") or {}).get("technique") or "generic",
    }
    dataset = SherpaDataset.from_dict(wire)
    if dataset.scientific_digest != manifest.get("scientific_digest"):
        raise ValueError("The saved source no longer reproduces its scientific identity.")
    return dataset


@dataclass(frozen=True)
class RetainedRecipe:
    selection: RecipeSelection
    graph: Any
    dataset: SherpaDataset
    source_digest: str
    development_indices: tuple[int, ...]
    held_out_indices: tuple[int, ...]
    definition_digest: str
    groups: np.ndarray | None = None
    supervision_digest: str | None = None
    held_out_dataset: SherpaDataset | None = None


def load_recipe(run, selection: RecipeSelection) -> RetainedRecipe:
    import spectra_sherpa.app.services.dag.nodes.data  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node  # noqa: F401
    from spectra_sherpa.app.services.dag.retained_holdout import retained_holdout_partition, source_replay_digest

    _ensure_type_registry()
    exact = retained_reader(run)
    definition = exact("__workflow__", "definition")
    if definition.get("schema_version") != 1:
        raise ValueError("Unsupported retained workflow definition.")
    nodes = {n["node_id"]: n for n in definition["nodes"]}
    model = nodes.get(selection.model_node_id)
    if not model or canonical_node_type(model["node_type"]) != "model.fitted_pls":
        raise ValueError("Paired evaluation currently supports fitted PLS regression outputs.")
    chain, seen, split_id = [], set(), None
    current = selection.model_node_id
    while True:
        if current in seen:
            raise ValueError("The saved recipe contains a cycle.")
        seen.add(current)
        node = nodes[current]
        kind = canonical_node_type(node["node_type"])
        if kind in {"data.file_load", "data.load_group", "data.collection_load", "data.attach_target"}:
            source = current
            break
        if kind == "data.train_test_split":
            if split_id is not None:
                raise ValueError("Select a recipe with a single retained train/test partition.")
            split_id = current
        else:
            chain.append(WorkflowNode(current, kind, node.get("parameters", {})))
        incoming = [edge for edge in definition["edges"] if edge["to_node_id"] == current]
        if len(incoming) != 1:
            raise ValueError(
                "Paired evaluation requires a single spectral chain with its target attached at the source."
            )
        edge = incoming[0]
        if (
            canonical_node_type(nodes[edge["from_node_id"]]["node_type"]) == "data.train_test_split"
            and edge.get("from_output") != "X_train"
        ):
            raise ValueError("Paired development evaluation must use the training output, never held-out samples.")
        current = edge["from_node_id"]
    # Target attachment may not hide fitted preprocessing outside the folds.
    pending = [e["from_node_id"] for e in definition["edges"] if e["to_node_id"] == source]
    from spectra_sherpa.app.services.dag.node_base import node_registry

    visited = set()
    while pending:
        ancestor = pending.pop()
        if ancestor in visited:
            continue
        visited.add(ancestor)
        metadata = node_registry.get_metadata(canonical_node_type(nodes[ancestor]["node_type"]))
        if metadata.resolved_execution_contract().payload["lifecycle_kind"] in {"fitted_transform", "fitted_model"}:
            raise ValueError("Move fitted preprocessing after target attachment so every fold refits it.")
        pending.extend(e["from_node_id"] for e in definition["edges"] if e["to_node_id"] == ancestor)
    dataset = restore_dataset(exact(source, "default"))
    # Event timestamps distinguish executions, not scientific populations.
    source_digest = source_replay_digest(dataset)
    for axis in (dataset.sample_axis, dataset.get_feature_axis()):
        if axis is not None and axis.include_mask is not None and not np.all(axis.include_mask):
            raise ValueError("Materialize declared sample/feature exclusions before the paired evaluation.")
    target, groups, supervision_digest = _supervised_inputs(dataset)
    train, test = tuple(range(dataset.shape[0])), ()
    held_out_dataset = None
    if split_id:
        partition = retained_holdout_partition(
            dataset,
            split_node_id=split_id,
            source_node_id=source,
            source_run_id=run.id,
            train_indices=exact(split_id, "train_indices"),
            test_indices=exact(split_id, "test_indices"),
        )
        train, test = tuple(partition["train_indices"]), tuple(partition["test_indices"])
        held_out_dataset = SherpaDataset(
            X=np.asarray(dataset.X)[np.asarray(test)],
            target=target[np.asarray(test)],
            feature_axis=dataset.get_feature_axis(),
            target_context=dataset.target_context,
        )
        indices = np.asarray(train)
        # Verify full-source supervision before slicing; inherited full-row
        # bindings must never be mistaken for a subset receipt. Carry exact
        # sliced target/groups separately into the canonical capability.
        dataset = SherpaDataset(
            X=np.asarray(dataset.X)[indices],
            target=target[indices],
            feature_axis=dataset.get_feature_axis(),
            target_context=dataset.target_context,
        )
        groups = None if groups is None else groups[indices]
    ordered = list(reversed(chain))
    evaluator_id = "paired_evaluation_score"
    if evaluator_id in nodes:
        raise ValueError("Reserved evaluation node identity is already in use.")
    ordered.append(WorkflowNode(evaluator_id, "diagnostics.regression_evaluator", {}))
    graph = admit_validation_graph(ordered, [WorkflowEdge(a.node_id, b.node_id) for a, b in zip(ordered, ordered[1:])])
    return RetainedRecipe(
        selection,
        graph,
        dataset,
        source_digest,
        train,
        test,
        digest(definition),
        groups,
        supervision_digest,
        held_out_dataset,
    )


def prepare_protocol(recipes: list[RetainedRecipe], request: PairedEvaluationRequest):
    population = next(r for r in recipes if r.selection.run_id == request.population_run_id)
    dataset = population.dataset
    target, groups, binding = _supervised_inputs(dataset)
    if population.groups is not None:
        groups = population.groups
    binding = population.supervision_digest or binding
    if target.ndim != 1 or not np.isfinite(target).all():
        raise ValueError("Paired PLS evaluation requires one finite quantitative response.")
    if groups is not None and request.repetitions > 1:
        raise ValueError(
            "Repeated randomized grouped partitions are not supported. "
            "Choose one grouped assessment; groups remain intact."
        )
    for axis in (dataset.sample_axis, dataset.get_feature_axis()):
        if axis is not None and axis.include_mask is not None and not np.all(axis.include_mask):
            raise ValueError("Materialize declared sample/feature exclusions before the paired evaluation.")
    for recipe in recipes:
        if (
            recipe.source_digest != population.source_digest
            or recipe.development_indices != population.development_indices
        ):
            raise ValueError(
                "Saved development populations differ. Create runs with the same declared training membership first; "
                "held-out rows are never pooled."
            )
    splits = [
        make_split_plan(
            dataset.shape[0],
            n_splits=request.folds,
            groups=groups,
            shuffle=groups is None,
            random_state=request.seed + i if groups is None else None,
        )
        for i in range(request.repetitions)
    ]
    memberships = [digest(sorted(sorted(fold.test.tolist()) for fold in split.folds)) for split in splits]
    if len(set(memberships)) != len(memberships):
        raise ValueError("Repeated seeds produced identical partitions; reduce repetitions or change the seed.")
    for recipe in recipes:
        components = next(
            int(n.parameters.get("n_components", 2)) for n in recipe.graph.nodes if n.operation_id == "model.fitted_pls"
        )
        if any(components > min(len(f.train) - 1, dataset.shape[1]) for split in splits for f in split.folds):
            raise ValueError(
                "PLS component count is infeasible in a training fold. "
                "Reduce components or choose fewer folds explicitly."
            )
    return population, target, groups, binding, splits


async def evaluate_pair(
    recipes: list[RetainedRecipe],
    request: PairedEvaluationRequest,
    checkpoint: Callable[[int, int], Awaitable[None]] | None = None,
) -> dict:
    from spectra_sherpa.app.services.dag.fold_graph_executor import (
        apply_local_full_refit_regression,
        execute_candidate_validation_with_local_regression_rows,
        execute_selected_candidate_full_refit,
    )

    population, target, groups, binding, splits = prepare_protocol(recipes, request)
    dataset = population.dataset
    minimal = SherpaDataset(
        X=np.asarray(dataset.X),
        target=target,
        feature_axis=dataset.get_feature_axis(),
        target_context=dataset.target_context,
    )
    results = []
    applications = {}

    total = len(splits) * len(recipes)
    for repetition, split in enumerate(splits):
        capability = SpectralDatasetCapability.from_dataset(
            minimal,
            custody_id="local-paired-evaluation",
            dataset_ref_digest=binding,
            split_plan_digest=split.digest,
            groups=groups,
        )
        for index, recipe in enumerate(recipes):
            if checkpoint:
                await checkpoint(len(results), total)

            # Cancellation occurs between bounded recipe evaluations. No resume.
            async def execute():
                execution, rows = await execute_candidate_validation_with_local_regression_rows(
                    recipe.graph, capability, split
                )
                if index not in applications:
                    refit = await execute_selected_candidate_full_refit(recipe.graph, capability, execution)
                    calibration = await apply_local_full_refit_regression(recipe.graph, refit, minimal)
                    held = population.held_out_dataset
                    held_predictions = (
                        await apply_local_full_refit_regression(recipe.graph, refit, held) if held is not None else None
                    )
                    applications[index] = {
                        "fit": refit.as_dict(),
                        "fit_digest": refit.digest,
                        "calibration": {"observations": target.tolist(), "predictions": calibration},
                        "held_out": (
                            {
                                "observations": np.asarray(held.target).tolist(),
                                "predictions": held_predictions,
                            }
                            if held is not None
                            else None
                        ),
                    }
                return execution, rows

            execution, rows = await asyncio.to_thread(lambda: asyncio.run(execute()))
            local_oof = {
                **rows,
                "sample_ids": [f"{population.source_digest}:{i}" for i in population.development_indices],
                "feature_receipt": population.source_digest,
                "response_identity": digest({"source": population.source_digest, "target": target.tolist()}),
                "response": dataset.target_context.target_name,
                "units": dataset.target_context.target_units,
            }
            results.append(
                {
                    "recipe_index": index,
                    "repetition": repetition,
                    "seed": request.seed + repetition,
                    "source_run_id": recipe.selection.run_id,
                    "model_node_id": recipe.selection.model_node_id,
                    "definition_digest": recipe.definition_digest,
                    "execution": execution.as_dict(),
                    "execution_digest": execution.digest,
                    "local_oof": local_oof,
                    "local_application": applications[index],
                }
            )
    if checkpoint:
        await checkpoint(total, total)
    differences = [
        float(results[i * 2 + 1]["execution"]["metrics"]["rmse"])
        - float(results[i * 2]["execution"]["metrics"]["rmse"])
        for i in range(len(splits))
    ]
    margin = request.meaningful_rmsecv_difference
    return {
        "schema_version": SCHEMA,
        "protocol": request.model_dump(),
        "protocol_digest": digest(request.model_dump()),
        "population": {
            "source_digest": population.source_digest,
            "development_count": len(population.development_indices),
            "held_out_count": len(population.held_out_indices),
            "development_indices": list(population.development_indices),
            "held_out_indices": list(population.held_out_indices),
            "n_groups": None if groups is None else len(set(groups.tolist())),
        },
        "splits": [
            {
                "digest": s.digest,
                "method": s.method,
                "n_samples": s.n_samples,
                "grouped": s.grouped,
                "folds": [{"train": f.train.tolist(), "test": f.test.tolist()} for f in s.folds],
            }
            for s in splits
        ],
        "results": results,
        "paired_rmsecv_differences": differences,
        "summary": {
            "mean_difference": float(np.mean(differences)),
            "min_difference": min(differences),
            "max_difference": max(differences),
            "right_meaningfully_better": sum(d < -margin for d in differences),
            "left_meaningfully_better": sum(d > margin for d in differences),
            "within_margin": sum(abs(d) <= margin for d in differences),
        },
        "interpretation": (
            "Difference is right minus left RMSECV. Repetitions overlap and are development evidence, "
            "not independent validation or a significance test."
        ),
        "resume_supported": False,
    }


def resolve_paired_evidence(run, reference, selection):
    """Read one immutable recipe/repetition through the shared evidence seam."""
    from spectra_sherpa.app.contracts.comparison_evidence import EvaluationEvidence, ResolvedComparisonEvidence
    from spectra_sherpa.app.schemas.scientific_comparison import PopulationSummary
    from spectra_sherpa.app.services.dag.out_of_fold_evidence import _normalized_split_plan
    from spectra_sherpa.sdk import validate as sdk_validate

    label = getattr(run, "name", None) or f"Evaluation {run.id}"
    if selection is None:
        return ResolvedComparisonEvidence(
            reference, label, unavailable_reason="Choose a recipe and repetition from this saved paired evaluation."
        )
    import re

    recipe_match = re.fullmatch(r"recipe:([01])", selection.node_id)
    repetition_match = re.fullmatch(r"repetition:([0-9]+)", selection.presentation_id)
    if recipe_match is None or repetition_match is None:
        raise ValueError("Choose a recipe and repetition from this saved paired evaluation.")
    recipe_index, repetition = int(recipe_match[1]), int(repetition_match[1])
    evidence = RunEvidence.model_validate(run.evidence_completeness)
    if run.status != "completed" or evidence.qualification != "qualified":
        raise ValueError("A completed exact paired evaluation is required.")
    saved = evidence.outputs.get("__evaluation__", {}).get("record")
    if saved is None or saved.state != "exact" or not saved.byte_count or saved.byte_count > 64 * 1024 * 1024:
        raise ValueError("Exact bounded paired evaluation evidence is unavailable.")
    record = read_output(run.user_id, saved)
    if record.get("schema_version") != SCHEMA:
        raise ValueError("Unsupported saved paired evaluation schema.")
    candidates = [r for r in record["results"] if r["recipe_index"] == recipe_index and r["repetition"] == repetition]
    if len(candidates) != 1:
        raise ValueError("The selected recipe/repetition is unavailable.")
    selected = candidates[0]
    execution, rows = selected["execution"], selected.get("local_oof")
    if rows is None:
        return ResolvedComparisonEvidence(
            reference,
            label,
            unavailable_reason=(
                "Historical aggregate-only evaluation has no retained OOF rows; " "run a new common evaluation."
            ),
        )
    if (
        digest(execution) != selected["execution_digest"]
        or rows["validation_execution_digest"] != selected["execution_digest"]
    ):
        raise ValueError("Retained OOF rows are not bound to this validation execution.")
    normalized, plan = _normalized_split_plan(rows["split_plan"], n_samples=len(rows["observations"]))
    if plan.digest != execution["split_plan_digest"] or plan.digest != record["splits"][repetition]["digest"]:
        raise ValueError("Retained OOF rows do not match the scored split plan.")
    computed = sdk_validate.metrics(rows["observations"], rows["predictions"]).as_dict()
    if not np.isclose(computed["rmse"], execution["metrics"]["rmse"], rtol=1e-10, atol=1e-12):
        raise ValueError("Retained OOF rows do not reproduce the scored evaluation.")
    source = record["population"]
    expected_ids = [f"{source['source_digest']}:{i}" for i in source["development_indices"]]
    if rows["feature_receipt"] != source["source_digest"] or rows["sample_ids"] != expected_ids:
        raise ValueError("Retained OOF sample identities do not match the development population.")
    population = PopulationSummary(
        development_count=len(source["development_indices"]),
        held_out_count=len(source["held_out_indices"]),
        evaluation_count=plan.n_samples,
        grouped=plan.grouped,
        group_count=source.get("n_groups"),
        fold_count=len(plan.folds),
        partition_digest=plan.digest,
        source_receipt=source["source_digest"],
        response=rows.get("response"),
        units=rows.get("units"),
        verification="partial",
        limitations=["Repeated CV is development evidence; it does not establish independent validation."],
    )
    evidence = EvaluationEvidence(
        role="training_cv",
        sample_ids=tuple(rows["sample_ids"]),
        observations=tuple(rows["observations"]),
        predictions=tuple(rows["predictions"]),
        feature_receipt=rows["feature_receipt"],
        response_identity=rows["response_identity"],
        units=rows.get("units"),
        response=rows.get("response"),
        split_plan=normalized,
        population=population,
    )
    evaluations = [evidence]
    application = selected.get("local_application")
    if application is not None:
        fit = application["fit"]
        if digest(fit) != application["fit_digest"] or fit["graph_digest"] != execution["graph_digest"]:
            raise ValueError("Retained application is not bound to the evaluated recipe")
        first = next(r for r in record["results"] if r["recipe_index"] == recipe_index and r["repetition"] == 0)
        if fit["validation_execution_digest"] != first["execution_digest"]:
            raise ValueError("Retained full-development fit has no scored execution authority")
        for role, membership in (("calibration", "development_indices"), ("held_out", "held_out_indices")):
            applied = application.get(role)
            if applied is None:
                continue
            indices = source[membership]
            if len(applied["observations"]) != len(indices) or len(applied["predictions"]) != len(indices):
                raise ValueError("Retained application rows differ from the declared population")
            if role == "calibration" and applied["observations"] != rows["observations"]:
                raise ValueError("Calibration observations differ from the scored development population")
            evaluations.append(
                EvaluationEvidence(
                    role=role,
                    sample_ids=tuple(f"{source['source_digest']}:{i}" for i in indices),
                    observations=tuple(applied["observations"]),
                    predictions=tuple(applied["predictions"]),
                    fitted_sample_ids=tuple(expected_ids),
                    feature_receipt=rows["feature_receipt"],
                    response_identity=rows["response_identity"],
                    units=rows.get("units"),
                    response=rows.get("response"),
                    population=population.model_copy(update={"evaluation_count": len(indices)}),
                    limitation=(
                        "Applied the frozen full-development fit; "
                        "held-out rows never entered fitting or training CV."
                    ),
                )
            )
    return ResolvedComparisonEvidence(
        reference,
        f"Run {selected['source_run_id']} · {selected['model_node_id']} · repetition {repetition + 1}",
        tuple(evaluations),
        population,
    )


def paired_comparison(run, repetition=0):
    from spectra_sherpa.app.schemas.execution_runs import EvaluationSelection
    from spectra_sherpa.app.services.scientific_comparison import compare_evidence, run_evidence_reference

    items = []
    for index in range(2):
        selection = EvaluationSelection(node_id=f"recipe:{index}", presentation_id=f"repetition:{repetition}")
        reference = run_evidence_reference(run, selection).model_copy(update={"kind": "evaluation"})
        items.append(resolve_paired_evidence(run, reference, selection))
    return compare_evidence(items)
