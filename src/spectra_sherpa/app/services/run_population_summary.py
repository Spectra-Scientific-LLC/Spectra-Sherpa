"""Bounded read-only projection of source-owned workflow exclusion receipts.

The exclusions port is the authority, not a diagnostic label, current canvas,
or display-only projection. Full row maps remain in their checksummed outputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from spectra_sherpa.app.lib.workflow_population import MAX_WORKFLOW_OBSERVATIONS, canonical_exclusions
from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.services.run_output_retention import read_output

SUMMARY_BYTES = 16 * 1024 * 1024
SUMMARY_SOURCES = 32
SCOPE = (
    "Retained run decisions only; current workflow edits are not substituted. "
    "Source membership is before branch filtering; it does not establish use by every downstream computation. "
    "Counts are per source, not unique specimens."
)


@dataclass(frozen=True)
class RetainedPopulationInput:
    """Plain admitted metadata for summary work outside an async ORM session."""

    id: int
    user_id: int
    evidence_completeness: Any
    params_snapshot: Any


def _counts(value: Any, node: str, parameters: Any) -> dict[str, Any]:
    """Check the canonical receipt's internal alignment; never rebuild it."""
    if not isinstance(value, dict) or value.get("schema_version") != "spectrasherpa-workflow-population/1":
        raise ValueError("Unsupported source exclusion receipt")
    if value.get("availability") == "unavailable":
        raise ValueError("Source observation map was unavailable at execution")
    digest = value.get("source_digest")
    rows = value.get("rows")
    if (
        value.get("source_node_id") != node
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or not isinstance(rows, list)
        or not 0 < len(rows) <= MAX_WORKFLOW_OBSERVATIONS
        or type(value.get("source_count")) is not int
        or value["source_count"] != len(rows)
    ):
        raise ValueError("Source observation map is incomplete or misbound")
    active = source_excluded = 0
    excluded = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or any(
            type(row.get(key)) is not bool for key in ("included", "source_included", "workflow_excluded")
        ):
            raise ValueError("Source inclusion decisions are not recorded")
        if (
            type(row.get("source_row")) is not int
            or row["source_row"] != index + 1
            or row.get("observation_ref") != f"{node}:{digest}:{index}"
            or row["included"] != (row["source_included"] and not row["workflow_excluded"])
        ):
            raise ValueError("Source observation map is inconsistent")
        active += row["included"]
        source_excluded += not row["source_included"]
        if row["workflow_excluded"]:
            excluded.add(row["observation_ref"])
        expected = active if row["included"] else None
        if row.get("result_row") != expected or (expected is not None and type(row.get("result_row")) is not int):
            raise ValueError("Source/result row mapping is inconsistent")
    if any(
        type(value.get(key)) is not int or value[key] != count
        for key, count in (("active_count", active), ("workflow_excluded_count", len(excluded)))
    ):
        raise ValueError("Source inclusion counts are inconsistent")
    # Missing historical settings are not interpreted as an empty decision.
    if isinstance(parameters, dict) and "workflow_exclusions" in parameters:
        decision = canonical_exclusions(parameters["workflow_exclusions"])
        if (decision is None and excluded) or (
            decision is not None and (decision["source_digest"] != digest or set(decision["excluded_refs"]) != excluded)
        ):
            raise ValueError("Source map disagrees with retained execution parameters")
    return {
        "source_digest": digest,
        "source_count": len(rows),
        "active_count": active,
        "source_excluded_count": source_excluded,
        "workflow_excluded_count": len(excluded),
        "excluded_count": len(rows) - active,
    }


def retained_population_summary(run: Any) -> dict[str, Any]:
    """One bounded summary shared by Runs and all retained Report formats."""
    result: dict[str, Any] = {
        "schema_version": "spectrasherpa-retained-population-summary/1",
        "run_id": run.id,
        "sources": [],
        "rows": [{"label": "Workflow observation exclusions", "value": SCOPE}],
    }
    remaining = SUMMARY_BYTES

    def read(item):
        nonlocal remaining
        if item is None or item.state != "exact" or item.storage != "file" or item.byte_count is None:
            raise ValueError("Exact source exclusion evidence was not retained")
        if item.byte_count > remaining:
            raise ValueError("Source exclusion summary read budget exceeded; inspect the individual retained output")
        remaining -= item.byte_count
        return read_output(run.user_id, item)

    try:
        evidence = RunEvidence.model_validate(getattr(run, "evidence_completeness", None) or {})
    except ValueError:
        result["rows"].append(
            {"label": "Retained observation map", "value": "Unavailable: invalid retention inventory."}
        )
        return result
    sources = {node for node, ports in evidence.outputs.items() if "exclusions" in ports}
    params = getattr(run, "params_snapshot", None) or {}
    params = params if isinstance(params, dict) else {}
    sources.update(
        node for node, values in params.items() if isinstance(values, dict) and "workflow_exclusions" in values
    )
    try:
        definition = read(evidence.outputs.get("__workflow__", {}).get("definition"))
        if not isinstance(definition, dict) or definition.get("schema_version") != 1:
            raise ValueError("Unsupported saved source inventory")
        from spectra_sherpa.app.services.dag import node_registry

        for node in definition.get("nodes", []):
            try:
                metadata = node_registry.get_metadata(node["node_type"])
                if any(
                    port.type_ref == "spectrasherpa://types/WorkflowPopulation/1.0"
                    for port in metadata.output_ports or []
                ):
                    sources.add(node["node_id"])
            except (KeyError, ValueError) as exc:
                raise ValueError("Saved source inventory cannot be completely classified") from exc
    except (ValueError, OSError, TypeError, AttributeError):
        result["rows"].append(
            {
                "label": "Source inventory",
                "value": "Saved definition unavailable; source coverage cannot be established.",
            }
        )
    if not sources:
        result["rows"].append(
            {
                "label": "Retained observation map",
                "value": (
                    "Unavailable: no canonical source exclusion map was retained; zero exclusions cannot be inferred."
                ),
            }
        )
    if len(sources) > SUMMARY_SOURCES:
        result["rows"].append(
            {
                "label": "Source inventory",
                "value": "Summary limited to 32 sources; inspect remaining retained source outputs individually.",
            }
        )
    for node in sorted(sources)[:SUMMARY_SOURCES]:
        item = evidence.outputs.get(node, {}).get("exclusions")
        source: dict[str, Any] = {"node_id": node, "port": "exclusions", "availability": "unavailable"}
        try:
            source.update(_counts(read(item), node, params.get(node)))
            source.update(availability="available", output_sha256=item.sha256)
            value = (
                f"{source['source_count']} source; {source['active_count']} used in the retained run's source result; "
                f"{source['excluded_count']} excluded from that source result. "
                f"{source['source_excluded_count']} excluded in the source; "
                f"{source['workflow_excluded_count']} workflow exclusions (may overlap source exclusions)."
            )
            result["rows"].append(
                {
                    "label": f"Retained row map ({node})",
                    "value": (
                        f"Run {run.id}, node {node}, port exclusions. Source SHA-256 {source['source_digest']}; "
                        f"output SHA-256 {item.sha256}. Complete individual decisions remain in this retained output."
                    ),
                }
            )
        except (ValueError, OSError, TypeError, KeyError):
            # Do not leak storage paths or pretend that a missing/corrupt map is empty.
            value = (
                "Unavailable: source map missing, unsupported, inconsistent, or outside the summary read budget. "
                "Inspect retained evidence."
            )
            source["reason"] = value
        source["summary"] = value
        result["sources"].append(source)
        result["rows"].append({"label": f"Retained exclusions ({node})", "value": value})
    return result
