"""Bounded read-only projection of source-owned workflow exclusion receipts.

The exclusions port is the authority, not a diagnostic label, current canvas,
or display-only projection. Full row maps remain in their checksummed outputs.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from threading import Lock
from typing import Any

from spectra_sherpa.app.lib.workflow_population import MAX_WORKFLOW_OBSERVATIONS, canonical_exclusions
from spectra_sherpa.app.schemas.run_evidence import OutputEvidence, RunEvidence
from spectra_sherpa.app.services.run_output_retention import read_output

SUMMARY_BYTES = 16 * 1024 * 1024
SUMMARY_SOURCES = 32
DEFINITION_BYTES = 2 * 1024 * 1024
COUNT_CACHE_ENTRIES = 128
_count_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
_count_cache_lock = Lock()
SCOPE = "Recorded at execution, per Load Data source, before any branch filter; later edits are not shown."


@dataclass(frozen=True)
class RetainedPopulationInput:
    """Plain admitted metadata for summary work outside an async ORM session."""

    id: int
    user_id: int
    evidence_completeness: Any
    params_snapshot: Any


class RetainedDefinitionRead:
    """One request's checked definition snapshot, never shared across requests.

    Keep one entry (at most 2 MiB serialized), bound to its owner and complete
    receipt. Report and summary consume the same verified bytes, including the
    same unavailable outcome. A new request must check storage again.
    """

    def __init__(self) -> None:
        self._key: tuple[int, str] | None = None
        self._value: Any = None
        self._failed = False

    def read(self, user_id: int, item: OutputEvidence | None) -> Any:
        if (
            item is None
            or item.state != "exact"
            or item.storage != "file"
            or item.byte_count is None
            or item.byte_count > DEFINITION_BYTES
        ):
            raise ValueError("Exact saved definition exceeds the supported budget or is unavailable")
        key = (user_id, item.model_dump_json())
        if key != self._key:
            self._key, self._value, self._failed = key, None, True
            self._value = read_output(user_id, item)
            self._failed = False
        if self._failed:
            raise ValueError("Saved definition was unavailable in this request")
        return deepcopy(self._value)


def _verified_counts(value: Any, user_id: int, item: OutputEvidence, node: str, parameters: Any) -> dict[str, Any]:
    """Cache scalar validation only, AFTER the caller checks current file bytes.

    Never cache a read, a failed validation, or mutable source rows. Even a hit
    requires read_output's owner-scoped existence/size/checksum/format checks.
    """
    try:
        binding = json.dumps(
            [user_id, item.model_dump(mode="json"), node, parameters],
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    except (ValueError, TypeError):
        return _counts(value, node, parameters)
    key = hashlib.sha256(binding).hexdigest()
    with _count_cache_lock:
        if key in _count_cache:
            _count_cache.move_to_end(key)
            return dict(_count_cache[key])
    result = _counts(value, node, parameters)
    with _count_cache_lock:
        _count_cache[key] = dict(result)
        _count_cache.move_to_end(key)
        while len(_count_cache) > COUNT_CACHE_ENTRIES:
            _count_cache.popitem(last=False)
    return result


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


def retained_population_summary(run: Any, *, definition_read: RetainedDefinitionRead | None = None) -> dict[str, Any]:
    """One bounded summary shared by Runs and all retained Report formats."""
    result: dict[str, Any] = {
        "schema_version": "spectrasherpa-retained-population-summary/1",
        "run_id": run.id,
        "sources": [],
        "rows": [{"label": "Observation exclusions", "value": SCOPE}],
    }
    remaining = SUMMARY_BYTES
    definition_read = definition_read if definition_read is not None else RetainedDefinitionRead()

    def read(item, *, definition: bool = False):
        nonlocal remaining
        if item is None or item.state != "exact" or item.storage != "file" or item.byte_count is None:
            raise ValueError("Exact source exclusion evidence was not retained")
        if item.byte_count > remaining:
            raise ValueError("Source exclusion summary read budget exceeded; inspect the individual retained output")
        if definition and item.byte_count > DEFINITION_BYTES:
            raise ValueError("Saved definition exceeds the supported byte limit")
        remaining -= item.byte_count
        if definition:
            return definition_read.read(run.user_id, item)
        return read_output(run.user_id, item)

    try:
        evidence = RunEvidence.model_validate(getattr(run, "evidence_completeness", None) or {})
    except ValueError:
        result["rows"].append({"label": "Exclusion map", "value": "Unavailable: invalid retention inventory."})
        return result
    sources = {node for node, ports in evidence.outputs.items() if "exclusions" in ports}
    params = getattr(run, "params_snapshot", None) or {}
    params = params if isinstance(params, dict) else {}
    sources.update(
        node for node, values in params.items() if isinstance(values, dict) and "workflow_exclusions" in values
    )
    labels: dict[str, str] = {}
    try:
        definition = read(evidence.outputs.get("__workflow__", {}).get("definition"), definition=True)
        if not isinstance(definition, dict) or definition.get("schema_version") != 1:
            raise ValueError("Unsupported saved source inventory")
        from spectra_sherpa.app.services.dag import node_registry

        for node in definition.get("nodes", []):
            if isinstance(node, dict) and isinstance(node.get("label"), str) and node["label"].strip():
                labels[str(node.get("node_id"))] = node["label"].strip()
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
                "value": "Saved definition unavailable; source coverage unknown.",
            }
        )
    if not sources:
        result["rows"].append(
            {
                "label": "Exclusion map",
                "value": "Not recorded; zero exclusions cannot be assumed.",
            }
        )
    if len(sources) > SUMMARY_SOURCES:
        result["rows"].append(
            {
                "label": "Source inventory",
                "value": "First 32 sources shown; inspect the others in Runs.",
            }
        )
    # Readers know a source by its canvas label; the node id disambiguates repeats.
    repeated = {label for label in labels.values() if list(labels.values()).count(label) > 1}

    def name(node: str) -> str:
        label = labels.get(node)
        return node if label is None else f"{label}, {node}" if label in repeated else label

    for node in sorted(sources)[:SUMMARY_SOURCES]:
        item = evidence.outputs.get(node, {}).get("exclusions")
        source: dict[str, Any] = {"node_id": node, "port": "exclusions", "availability": "unavailable"}
        try:
            source.update(_verified_counts(read(item), run.user_id, item, node, params.get(node)))
            source.update(availability="available", output_sha256=item.sha256)
            overlap = source["source_excluded_count"] + source["workflow_excluded_count"] > source["excluded_count"]
            value = (
                f"{source['source_count']} observations: {source['active_count']} used, "
                f"{source['excluded_count']} excluded ({source['source_excluded_count']} in My Dataset, "
                f"{source['workflow_excluded_count']} in workflow{'; some in both' if overlap else ''})."
            )
            result["rows"].append(
                {
                    "label": f"Exclusion map ({name(node)})",
                    "value": f"Source SHA-256 {source['source_digest']}; map SHA-256 {item.sha256}.",
                }
            )
        except (ValueError, OSError, TypeError, KeyError):
            # Do not leak storage paths or pretend that a missing/corrupt map is empty.
            value = "Unavailable: map missing, inconsistent or too large to summarize. Inspect it in Runs."
            source["reason"] = value
        source["summary"] = value
        result["sources"].append(source)
        result["rows"].append({"label": f"Exclusions ({name(node)})", "value": value})
    return result
