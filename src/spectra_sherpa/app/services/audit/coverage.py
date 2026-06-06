"""Coverage registry + opt-out decorator for audited state changes.

Per the Phase 0 design (§6 — Coverage policy), every model in the
audited set must have at least one path that emits an audit event on
each state-changing action, OR an explicit ``@audit_excluded`` marker
declaring the exclusion intentional. The CI coverage guard (a pytest
test in ``tests/services/audit/test_coverage_guard.py``) verifies the
registry and the codebase agree.

This module ships two pieces:

  * ``AUDITED_MODELS`` — the registry of model class → declared
    actions. Adding a new entry triggers the CI guard until at least
    one emit (or an excluded path) covers it.
  * ``@audit_excluded(reason)`` — decorator for explicitly excluding a
    function from coverage. The decorator records the reason in a
    module-level registry so the CI guard can introspect.

Phase 3 keeps the registry conservative — only the models with hooks
that already exist in the OSS codebase. Phase 3b will extend to
File / DataSource / Report / etc. when those models exist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable)


@dataclass(frozen=True)
class AuditedModel:
    """One entry in the audited-model registry.

    ``target_type`` is the string used as ``AuditEvent.target_type``;
    keeping it explicit (rather than derived from the class name)
    lets future renames not break historical chains.

    ``actions`` is the set of action verbs the model MUST cover. The
    CI guard fails if any are unimplemented.
    """

    model_dotted_path: str
    target_type: str
    actions: frozenset[str]


# Registry — single source of truth for "which models are audited."
# Phase 3 adds: Project, Experiment, APIKey alongside the Phase 1
# entries (Workflow, WorkflowVersion, ExecutionRun, ModelArtifact).
AUDITED_MODELS: tuple[AuditedModel, ...] = (
    AuditedModel(
        model_dotted_path="spectra_sherpa.app.models.workflow.Workflow",
        target_type="Workflow",
        # workflow.run.started fires against target_type=Workflow
        # (correlation via request_id) — it is the informational start
        # signal; the binding fail-closed record at run termination
        # targets ExecutionRun.
        # project_linked / project_unlinked cover the project-membership
        # mutation paths POST/DELETE /projects/{pid}/workflows/{wid}.
        actions=frozenset(
            {
                "created",
                "updated",
                "deleted",
                "project_linked",
                "project_unlinked",
                "workflow.run.started",
            }
        ),
    ),
    AuditedModel(
        model_dotted_path="spectra_sherpa.app.models.workflow_version.WorkflowVersion",
        target_type="WorkflowVersion",
        actions=frozenset({"created"}),
    ),
    AuditedModel(
        model_dotted_path="spectra_sherpa.app.models.execution_run.ExecutionRun",
        target_type="ExecutionRun",
        # Terminal-status events for a workflow run — target_type is
        # the ExecutionRun row (id known after flush). Action verbs use
        # the dotted "workflow.run.<status>" form.
        actions=frozenset(
            {
                "workflow.run.completed",
                "workflow.run.partial",
                "workflow.run.failed",
                # batch_failed records a 207 batch-apply where no artifact
                # produced a successful run — no ExecutionRun row is
                # persisted, so target_id is the literal "unpersisted".
                "workflow.run.batch_failed",
            }
        ),
    ),
    AuditedModel(
        model_dotted_path="spectra_sherpa.app.models.model_artifact.ModelArtifact",
        target_type="ModelArtifact",
        # project_linked / project_unlinked cover the project-membership
        # mutation paths POST/DELETE /projects/{pid}/models/{uid}.
        actions=frozenset({"created", "updated", "deleted", "project_linked", "project_unlinked"}),
    ),
    AuditedModel(
        model_dotted_path="spectra_sherpa.app.models.project.Project",
        target_type="Project",
        actions=frozenset({"created", "updated", "deleted"}),
    ),
    AuditedModel(
        model_dotted_path="spectra_sherpa.app.models.experiment.Experiment",
        target_type="Experiment",
        # project_linked / project_unlinked cover the project-membership
        # mutation paths POST/DELETE /projects/{pid}/experiments/{eid}.
        actions=frozenset({"created", "updated", "deleted", "project_linked", "project_unlinked"}),
    ),
    AuditedModel(
        model_dotted_path="spectra_sherpa.app.models.experiment_file.ExperimentFile",
        target_type="ExperimentFile",
        actions=frozenset({"created", "deleted"}),
    ),
    AuditedModel(
        model_dotted_path="spectra_sherpa.app.models.project_data_source.ProjectDataSource",
        target_type="ProjectDataSource",
        # No DELETE route — ProjectDataSource rows are removed only by
        # cascade when the parent project is deleted. The parent
        # project.deleted event covers the user's action.
        actions=frozenset({"created", "updated"}),
    ),
    AuditedModel(
        model_dotted_path="spectra_sherpa.app.models.api_key.APIKey",
        target_type="APIKey",
        actions=frozenset({"created", "updated", "deleted"}),
    ),
)


# ---------------------------------------------------------------------------
# @audit_excluded decorator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ExcludedSite:
    """One site that has explicitly declined audit coverage."""

    qualified_name: str  # module.func or module.Cls.method
    reason: str


_EXCLUDED_SITES: list[_ExcludedSite] = []


def audit_excluded(reason: str) -> Callable[[F], F]:
    """Mark a state-changing function as intentionally not audited.

    The reason is recorded so the CI coverage guard can list every
    exclusion at a glance. Anything that mutates an audited model
    and is NOT covered by an explicit emit and NOT decorated with
    ``@audit_excluded`` is a coverage gap.

    Usage::

        @audit_excluded("scheduled cleanup; no individual-run audit")
        async def purge_stale_jobs(...):
            ...

    The decorator is purely declarative — it does not change the
    function's behaviour. Test coverage tooling reads the registry
    via ``get_excluded_sites()``.
    """
    if not reason or not isinstance(reason, str):
        raise ValueError("@audit_excluded requires a non-empty string reason")

    def _decorator(func: F) -> F:
        qual = f"{func.__module__}.{getattr(func, '__qualname__', func.__name__)}"
        _EXCLUDED_SITES.append(_ExcludedSite(qualified_name=qual, reason=reason))
        # Return the original function unchanged. A wrapping closure
        # would carry this module's __globals__, breaking FastAPI's
        # forward-ref resolution under `from __future__ import
        # annotations` (route signatures like `payload: BranchRequest`
        # become strings the wrapper's globals cannot see).
        return func

    return _decorator


def get_excluded_sites() -> list[_ExcludedSite]:
    """Return all currently-registered exclusions (test introspection)."""
    return list(_EXCLUDED_SITES)


def _reset_excluded_sites_for_tests() -> None:
    _EXCLUDED_SITES.clear()
