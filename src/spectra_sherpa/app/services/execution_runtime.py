"""Application adapter that constructs explicit scientific execution authority."""

from __future__ import annotations

from typing import Any

import numpy as np

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.services.dag.nodes.classification.plsda_state import (
    canonical_model_validation_required,
)
from spectra_sherpa.app.services.dataset_source_resolver import ApplicationDatasetSourceResolver
from spectra_sherpa.app.services.model_store import get_model_store
from spectra_sherpa.core.canonical_artifact import ReadOnlyCanonicalArtifactReader
from spectra_sherpa.core.execution_runtime import ExecutionRuntime
from spectra_sherpa.core.model_artifact import ReadOnlyModelArtifactReader


class ApplicationModelArtifactReplay:
    """Import-lazy adapter for Workbench model preprocessing and diagnostics."""

    def prepare(
        self,
        X: Any,
        source_dataset: Any,
        manifest: dict[str, Any],
    ) -> tuple[np.ndarray, tuple[str, ...]]:
        dataset, warnings = self.prepare_dataset(X, source_dataset, manifest)
        return np.asarray(dataset.X), warnings

    def prepare_dataset(self, X: Any, source_dataset: Any, manifest: dict[str, Any]) -> tuple[Any, tuple[str, ...]]:
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
        from spectra_sherpa.app.services import model_application

        matrix = np.asarray(X, dtype=np.float64)
        source = source_dataset if isinstance(source_dataset, SherpaDataset) else SherpaDataset(X=matrix)
        if matrix.ndim > 2:
            # Native multiway models validate all fitted axes themselves. These
            # source records do not change values; 2D replay must not reinterpret
            # a time/spatial axis as the feature axis.
            from collections.abc import Mapping

            from spectra_sherpa.app.services.artifact_preprocessing_authority import (
                validate_experiment_source_provenance,
            )

            if manifest.get("feature_mask") is not None:
                raise ValueError("Multiway saved application cannot replay a two-dimensional feature mask")
            for step in manifest.get("preprocessing_chain") or []:
                if not isinstance(step, Mapping) or set(step) != {"op_id", "parameters"}:
                    raise ValueError("Multiway model preprocessing provenance is malformed")
                parameters = step["parameters"]
                if not isinstance(parameters, Mapping):
                    raise ValueError("Multiway model preprocessing parameters are malformed")
                if step["op_id"] in {"data.file_load", "data.attach_target", "data.train_test_split"}:
                    continue
                if step["op_id"] == "spectrasherpa.experiment_dataset_read/2":
                    validate_experiment_source_provenance(parameters)
                    continue
                raise ValueError(f"Processing step {step['op_id']!r} has no multiway artifact replay")
            return source.with_data(matrix), ()
        model_application.validate_feature_contract(matrix, source_dataset, manifest)
        prepared, _, _, replay_warnings, replay_source = model_application._prepare_artifact_input(
            matrix, None, manifest, scope="all", source_dataset=source
        )
        prepared, feature_warnings = model_application._apply_feature_mask(prepared, source_dataset, manifest)
        model_application.validate_prepared_feature_contract(prepared, manifest)
        mask = manifest.get("feature_mask")
        if mask is not None and replay_source.shape[1] != prepared.shape[1]:
            replay_source = replay_source[:, np.asarray(mask, dtype=bool)]
        return replay_source.with_data(prepared), tuple(replay_warnings + feature_warnings)

    def applicability(self, extract: Any, X: Any) -> dict[str, Any] | None:
        from spectra_sherpa.app.services.model_application import _applicability_diagnostics

        return _applicability_diagnostics(extract, np.asarray(X, dtype=np.float64))


class ApplicationModelArtifactSemanticValidator:
    """Delegate canonical lineage admission without coupling the DAG to storage."""

    def validate(self, manifest: dict[str, Any], arrays: dict[str, Any]) -> None:
        if not canonical_model_validation_required(manifest):
            return
        from spectra_sherpa.app.services.canonical_model_bridge import (
            validate_canonical_plsda_model_artifact,
        )

        validate_canonical_plsda_model_artifact(manifest, arrays)


def build_application_execution_runtime(
    *,
    canonical_artifact_read_grant: Any = None,
    model_artifact_reader: Any = None,
    preloaded_datasets: dict[str, Any] | None = None,
    allowed_model_artifact_uids: tuple[str, ...] | None = None,
) -> ExecutionRuntime:
    """Project app configuration and durable custody into one closed runtime."""

    store = get_model_store()
    reader = store if model_artifact_reader is None else model_artifact_reader
    worker_reader = ReadOnlyModelArtifactReader(settings.data_dir, allowed_artifact_uids=allowed_model_artifact_uids)
    if allowed_model_artifact_uids is not None:
        if model_artifact_reader is not None:
            raise ValueError("A scoped execution cannot override its admitted model reader")
        reader = worker_reader
    canonical_reader = None
    if canonical_artifact_read_grant is not None:
        canonical_reader = ReadOnlyCanonicalArtifactReader(
            settings.data_dir,
            allowed_artifact_digests=(canonical_artifact_read_grant.artifact_digest,),
            artifact_root=canonical_artifact_read_grant.artifact_dir.parent,
        )
    return ExecutionRuntime(
        node_timeout_seconds=float(settings.max_job_duration_sec),
        model_artifact_reader=reader,
        model_artifact_writer=store,
        worker_model_artifact_reader=worker_reader,
        model_artifact_replay=ApplicationModelArtifactReplay(),
        model_artifact_semantic_validator=ApplicationModelArtifactSemanticValidator(),
        canonical_artifact_reader=canonical_reader,
        dataset_source_resolver=ApplicationDatasetSourceResolver(preloaded_datasets=preloaded_datasets),
    )


__all__ = [
    "ApplicationModelArtifactReplay",
    "ApplicationModelArtifactSemanticValidator",
    "build_application_execution_runtime",
]
