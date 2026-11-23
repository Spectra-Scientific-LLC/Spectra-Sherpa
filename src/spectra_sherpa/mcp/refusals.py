"""Every MCP refusal says why it happened and where the action can be done.

Only these fixed codes and texts are ever shown to an AI client. Server details,
paths, identifiers and credentials are never echoed.
"""

from __future__ import annotations

READ_ONLY_WHERE = "Build, run and change analyses in the SpectraSherpa Workbench or SDK, then inspect the results here."

REFUSALS: dict[str, tuple[str, str]] = {
    "unsupported_operation": (
        "This MCP connection is read-only: it inspects data, workflows, runs, results and comparisons, and cannot "
        "save, run, export or apply anything.",
        READ_ONLY_WHERE,
    ),
    "invalid_arguments": (
        "The arguments do not match this tool's input schema.",
        "Check the tool's input schema and retry.",
    ),
    "object_unavailable": (
        "That dataset, workflow or run is not available in this connection's project.",
        "Use list_runs, get_run or inspect_workflow to find identifiers in this project.",
    ),
    "privacy_denied": (
        "This project's privacy settings do not allow sharing this data with an AI client.",
        "The user can review AI sharing for this project in the Workbench under Settings.",
    ),
    "disclosure_denied": (
        "This connection was not granted access to that kind of data.",
        "Create a connection with the needed access in the Workbench under Settings, Integrations.",
    ),
    "project_summary_consent_required": (
        "This connection was not granted access to project datasets and workflows.",
        "Create a connection with project summaries in the Workbench under Settings, Integrations.",
    ),
    "retained_result_consent_required": (
        "This connection was not granted access to retained results.",
        "Create a connection with retained results in the Workbench under Settings, Integrations.",
    ),
    "access_denied": (
        "This connection was revoked, expired or does not match the project.",
        "Create a new connection in the Workbench under Settings, Integrations.",
    ),
    "busy": ("The Workbench is busy with other inspection requests.", "Retry shortly."),
    "timeout": ("The Workbench did not finish the read in time.", "Retry, or request a smaller page."),
    "request_limit": ("The request exceeds the size limit.", "Send fewer or shorter arguments."),
    "response_limit": ("The result exceeds the response size limit.", "Request a smaller page or a narrower read."),
    "catalog_limit": ("The node catalog exceeds the response size limit.", "Request a smaller page."),
    "retained_evidence_changed": (
        "The run's retained evidence changed during the read.",
        "Reopen the run in the Workbench and retry.",
    ),
    "inspection_failed": (
        "The retained evidence for this read could not be loaded.",
        "Open the run in the Workbench to check it, then retry.",
    ),
    "invalid_response": (
        "The Workbench returned a response this connection cannot use.",
        "Retry; if it persists, update SpectraSherpa.",
    ),
    "unavailable": (
        "The SpectraSherpa Workbench could not be reached.",
        "Start the Workbench on this machine and check the connection settings.",
    ),
}


def refusal_text(code: str) -> str:
    why, where = REFUSALS.get(code, REFUSALS["inspection_failed"])
    return f"{why} {where}"
