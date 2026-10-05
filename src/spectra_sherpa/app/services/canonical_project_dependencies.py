"""Exact live-runtime readiness for an imported canonical application.

Sealed canonical packages are intentionally readable without their optional
numerical dependencies.  That offline property is not an execution grant:
this small service reuses the frozen first-party profile to decide whether the
same durable application plan may be bound as active or given an artifact
reader at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass

from spectra_sherpa.app.services.dag.managed_optimization_profile import (
    ManagedOptimizationProfileError,
    managed_optimization_profile,
)
from spectra_sherpa.sdk.canonical_application import CanonicalApplicationPlan


class CanonicalProjectDependencyError(ValueError):
    """A durable plan cannot be evaluated against the closed local profile."""


@dataclass(frozen=True)
class CanonicalProjectDependencyReadiness:
    """Bounded execution readiness derived only from sealed provenance."""

    ready: bool
    source_operation_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    remediation: tuple[str, ...]


def canonical_project_dependency_readiness(
    application_plan: CanonicalApplicationPlan,
) -> CanonicalProjectDependencyReadiness:
    """Return exact live readiness for the plan's sealed source operations.

    The application graph contains apply operations, while the durable plan
    retains their source operation IDs and the capsule has already bound those
    IDs to the frozen profile.  This resolver does not inspect mutable
    workflow-node parameters or grant artifact access.
    """

    source_operation_ids = tuple(sorted({node["source_operation_id"] for node in application_plan.payload["nodes"]}))
    if not source_operation_ids:
        raise CanonicalProjectDependencyError("canonical application plan has no source operations")
    profile = managed_optimization_profile()
    try:
        profile.runtime_attestation(source_operation_ids)
    except ManagedOptimizationProfileError:
        requirements = {
            (str(requirement["distribution"]), str(requirement["version"]))
            for operation_id in source_operation_ids
            for requirement in profile.operation(operation_id).payload["runtime_requirements"]
        }
        exact_requirements = ", ".join(f"{distribution}=={version}" for distribution, version in sorted(requirements))
        return CanonicalProjectDependencyReadiness(
            ready=False,
            source_operation_ids=source_operation_ids,
            blockers=("canonical_runtime_unavailable_or_unpinned",),
            remediation=(
                "Install the exact certified runtime required by this imported canonical project: "
                f"{exact_requirements}. Then restart the workbench and validate the unchanged project again.",
            ),
        )
    return CanonicalProjectDependencyReadiness(
        ready=True,
        source_operation_ids=source_operation_ids,
        blockers=(),
        remediation=(),
    )


__all__ = [
    "CanonicalProjectDependencyError",
    "CanonicalProjectDependencyReadiness",
    "canonical_project_dependency_readiness",
]
