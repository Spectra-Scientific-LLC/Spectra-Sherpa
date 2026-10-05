"""Dataset readiness and explicit portable-CSV supervision bindings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.lib.dataset_compatibility import build_dataset_analysis_readiness
from spectra_sherpa.app.lib.sherpa_dataset import TargetContext
from spectra_sherpa.app.lib.template_runtime import template_runtime_readiness
from spectra_sherpa.app.models.dataset_analysis_binding import DatasetAnalysisBinding
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
from spectra_sherpa.app.services.dag.nodes.data.sample_table import (
    apply_sample_table_to_dataset,
    load_portable_sample_table,
)
from spectra_sherpa.app.services.experiments import experiment_dir
from spectra_sherpa.app.services.template_availability import template_admitted_in_profile
from spectra_sherpa.core.spectra_meta import DataProvenance, SourceType, SpectraMeta, set_spectra_meta


async def dataset_analysis_readiness(dataset: Any, session: AsyncSession) -> dict[str, Any]:
    """Evaluate one runtime dataset through the canonical compatibility engine."""

    rows = await session.scalars(
        select(WorkflowTemplate).where(WorkflowTemplate.is_active.is_(True)).order_by(WorkflowTemplate.slug)
    )
    templates = []
    for template in rows.all():
        if not template_admitted_in_profile(template):
            continue
        template_data = template.template_data if isinstance(template.template_data, dict) else {}
        status = template_data.get("status")
        templates.append(
            {
                "slug": template.slug,
                "name": template.name,
                "category": template.category,
                "status": status,
                "template_data": {**template_data, "status": status},
                "runtime_readiness": template_runtime_readiness(template_data),
            }
        )
    return build_dataset_analysis_readiness(dataset, templates)


async def apply_saved_analysis_binding(
    dataset: Any,
    *,
    source_file: ExperimentFile | None,
    session: AsyncSession,
) -> tuple[Any, DatasetAnalysisBinding | None]:
    """Apply the durable CSV binding for an exact source file, if one exists."""

    if source_file is None:
        return dataset, None
    binding = await session.scalar(
        select(DatasetAnalysisBinding).where(DatasetAnalysisBinding.source_file_id == source_file.id)
    )
    if binding is None:
        return dataset, None
    table_file = await session.scalar(select(ExperimentFile).where(ExperimentFile.id == binding.sample_table_file_id))
    if table_file is None or table_file.experiment_id != source_file.experiment_id:
        raise ValueError("Saved dataset analysis binding no longer resolves inside its source dataset")
    result = dataset.snapshot()
    _set_source_file_authority(result, source_file)
    table = load_portable_sample_table(
        experiment_dir(source_file.experiment_id) / table_file.file_path,
        selected_target=binding.selected_target,
        target_type=binding.target_type,
    )
    if table is None:
        raise ValueError("Saved dataset analysis binding does not point to a portable sample-table CSV")
    apply_sample_table_to_dataset(result, table)
    result.target = np.asarray(table["target_values"])
    class_names = None
    if binding.target_type == "categorical":
        class_names = sorted({str(value) for value in table["target_values"] if value is not None})
    result.target_context = TargetContext(
        target_type=binding.target_type,
        target_name=binding.selected_target,
        target_names=[binding.selected_target],
        selected_target=binding.selected_target,
        n_classes=len(class_names) if class_names is not None else None,
        class_names=class_names,
    )
    return result, binding


def validate_analysis_binding(
    *,
    source_file: ExperimentFile,
    sample_table_file: ExperimentFile,
    selected_target: str,
    target_type: str,
    load_source: Any,
    experiment_root: Path | None = None,
) -> None:
    """Prove the table matches the exact source before persisting the binding."""

    if source_file.id == sample_table_file.id:
        raise ValueError("Source data and sample-table CSV must be different files")
    if source_file.experiment_id != sample_table_file.experiment_id:
        raise ValueError("Source data and sample-table CSV must belong to the same dataset")
    if Path(sample_table_file.file_path).suffix.lower() != ".csv":
        raise ValueError("Dataset analysis metadata must be a portable CSV sample table")
    root = experiment_root or experiment_dir(source_file.experiment_id)
    source_path = root / source_file.file_path
    table_path = root / sample_table_file.file_path
    dataset = load_source(source_path)
    _set_source_file_authority(dataset, source_file)
    table = load_portable_sample_table(
        table_path,
        selected_target=selected_target,
        target_type=target_type,
    )
    if table is None:
        raise ValueError("Selected CSV is not a portable sample table")
    apply_sample_table_to_dataset(dataset, table)


def _set_source_file_authority(dataset: Any, source_file: ExperimentFile) -> None:
    created_at = source_file.created_at
    set_spectra_meta(
        dataset,
        SpectraMeta(
            provenance=DataProvenance(
                source_type=SourceType.EXPERIMENT,
                experiment_id=source_file.experiment_id,
                file_id=source_file.id,
                original_file_path=source_file.file_path,
                original_file_format=Path(source_file.file_path).suffix.lower().lstrip("."),
                created_datetime=created_at.isoformat() if created_at is not None else None,
            ),
            processing_steps=["load"],
        ),
    )


__all__ = [
    "apply_saved_analysis_binding",
    "dataset_analysis_readiness",
    "validate_analysis_binding",
]
