"""Closed workflow-purpose authority shared by persistence and execution.

Workflow purpose is semantic state, not presentation metadata.  In particular,
the managed-candidate authority persisted beside a scientist-facing starter is
inspectable evidence for the Harness; it is not an ordinary canvas workflow.
"""

from __future__ import annotations

from typing import Literal, cast

WorkflowPurpose = Literal["analysis", "managed_candidate_authority"]

ANALYSIS_WORKFLOW: WorkflowPurpose = "analysis"
MANAGED_CANDIDATE_AUTHORITY: WorkflowPurpose = "managed_candidate_authority"
WORKFLOW_PURPOSES: frozenset[str] = frozenset({ANALYSIS_WORKFLOW, MANAGED_CANDIDATE_AUTHORITY})


class WorkflowPurposeError(ValueError):
    """Raised when persisted or imported purpose is missing or unknown."""


def require_workflow_purpose(value: object) -> WorkflowPurpose:
    """Return a closed workflow purpose without guessing or translating."""

    if not isinstance(value, str) or value not in WORKFLOW_PURPOSES:
        raise WorkflowPurposeError("workflow purpose must be exactly 'analysis' or " "'managed_candidate_authority'")
    return cast(WorkflowPurpose, value)
