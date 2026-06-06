"""LLM-assisted spectral peak identification node."""

from __future__ import annotations

import json
import math
import re
from typing import Any

from spectra_sherpa.app.contracts.ai_provider_registry import get_sherpa_advisor

from ...node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)

_POSITION_KEYS = ("median_pos", "peak_position", "position", "mean_pos", "x")
_HEIGHT_KEYS = ("median_height", "height", "peak_height", "intensity", "amplitude", "y")
_DEFAULT_MAX_PEAKS = 30
_DEFAULT_MIN_RELATIVE_HEIGHT = 0.03


def _as_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _collapse_paragraph(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _extract_peak_payload(value: Any) -> tuple[list[Any], dict[str, Any]]:
    """Accept a peak port payload or a full Peak Finding output map."""
    payload = value
    if isinstance(payload, NodeResult):
        payload = payload.outputs
    if isinstance(payload, dict) and isinstance(payload.get("peaks"), dict):
        payload = payload["peaks"]

    if isinstance(payload, dict):
        data = payload.get("data")
        metadata = _as_record(payload.get("metadata"))
        return data if isinstance(data, list) else [], metadata

    if isinstance(payload, list):
        return payload, {}

    return [], {}


def _extract_peak_positions(rows: list[Any]) -> list[Any]:
    positions: list[Any] = []
    for row in rows:
        if isinstance(row, dict):
            value = None
            for key in _POSITION_KEYS:
                if key in row and row[key] is not None:
                    value = row[key]
                    break
            if value is not None:
                positions.append(value)
        elif isinstance(row, (int, float, str)):
            positions.append(row)
    return positions


def _finite_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _peak_position(row: Any) -> Any:
    if isinstance(row, dict):
        for key in _POSITION_KEYS:
            value = row.get(key)
            if value is not None:
                return value
        return None
    if isinstance(row, (int, float, str)):
        return row
    return None


def _peak_height(row: Any) -> float | None:
    if not isinstance(row, dict):
        return None
    for key in _HEIGHT_KEYS:
        numeric = _finite_float_or_none(row.get(key))
        if numeric is not None:
            return abs(numeric)
    return None


def _peak_count(row: Any) -> int:
    if not isinstance(row, dict):
        return 1
    value = row.get("count")
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        detected = str(row.get("detected") or "")
        match = re.match(r"\s*(\d+)\s*/", detected)
        return max(1, int(match.group(1))) if match else 1


def _positive_int(value: Any, *, default: int, name: str) -> int:
    if value in (None, ""):
        return default
    try:
        numeric = int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Peak ID {name} must be a number.") from exc
    if numeric < 0:
        raise ValueError(f"Peak ID {name} must be non-negative.")
    return numeric


def _nonnegative_float(value: Any, *, default: float, name: str) -> float:
    if value in (None, ""):
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Peak ID {name} must be a number.") from exc
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError(f"Peak ID {name} must be a finite non-negative number.")
    return numeric


def _select_peaks_for_prompt(
    rows: list[Any],
    *,
    max_peaks: int = _DEFAULT_MAX_PEAKS,
    min_relative_height: float = _DEFAULT_MIN_RELATIVE_HEIGHT,
) -> tuple[list[Any], dict[str, Any]]:
    """Select major peaks for the LLM prompt while preserving validation.

    Peak Finding may return a long consensus list with many weak peaks.  The
    LLM assignment task is more stable when it sees the strongest, most
    repeatably detected peaks first.
    """
    candidates: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        position = _peak_position(row)
        if position is None:
            continue
        candidates.append(
            {
                "index": index,
                "position": position,
                "numeric_position": _finite_float_or_none(position),
                "height": _peak_height(row),
                "count": _peak_count(row),
            }
        )

    heights = [item["height"] for item in candidates if item["height"] is not None]
    max_height = max(heights) if heights else None

    filtered = candidates
    if max_height and min_relative_height > 0:
        filtered = [
            item
            for item in candidates
            if item["height"] is None or (float(item["height"]) / max_height) >= min_relative_height
        ]
        if not filtered:
            filtered = candidates

    can_rank = any(item["height"] is not None for item in filtered) or any(item["count"] > 1 for item in filtered)
    if can_rank:
        ranked = sorted(
            filtered,
            key=lambda item: (
                float(item["height"] or 0.0),
                int(item["count"]),
            ),
            reverse=True,
        )
    else:
        ranked = list(filtered)

    if max_peaks > 0:
        ranked = ranked[:max_peaks]

    selected = sorted(ranked, key=lambda item: item["index"])
    positions = [item["position"] for item in selected]

    return positions, {
        "n_input_peaks": len(candidates),
        "n_prompt_peaks": len(positions),
        "n_omitted_peaks": max(0, len(candidates) - len(positions)),
        "max_peaks": max_peaks,
        "min_relative_height": min_relative_height,
        "used_height_filter": bool(max_height and min_relative_height > 0),
    }


def _format_peak_list(positions: list[Any]) -> str:
    formatted: list[str] = []
    for position in positions:
        if isinstance(position, (int, float)):
            numeric = float(position)
            if not math.isfinite(numeric):
                raise ValueError("Peak ID requires finite numeric peak positions.")
            formatted.append(f"{numeric:.6g}")
        else:
            text = str(position).strip()
            if text:
                lower_text = text.lower()
                if re.search(r"(^|[^a-z])(nan|inf|infinity)([^a-z]|$)", lower_text):
                    raise ValueError("Peak ID requires finite numeric peak positions.")
                try:
                    numeric = float(text)
                except ValueError:
                    formatted.append(text)
                    continue
                if not math.isfinite(numeric):
                    raise ValueError("Peak ID requires finite numeric peak positions.")
                formatted.append(text)
    return ", ".join(formatted)


def _json_from_response(text: str) -> Any:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _normalize_assignment(row: Any) -> dict[str, str]:
    if isinstance(row, dict):
        peak = row.get("peak_position") or row.get("peak") or row.get("position") or row.get("x")
        mode = row.get("vibration_mode") or row.get("mode") or row.get("vibration")
        origin = row.get("structural_origin") or row.get("origin") or row.get("structure")
        return {
            "peak_position": _collapse_paragraph(peak),
            "vibration_mode": _collapse_paragraph(mode),
            "structural_origin": _collapse_paragraph(origin),
        }
    if isinstance(row, (list, tuple)) and len(row) >= 3:
        return {
            "peak_position": _collapse_paragraph(row[0]),
            "vibration_mode": _collapse_paragraph(row[1]),
            "structural_origin": _collapse_paragraph(row[2]),
        }
    return {"peak_position": "", "vibration_mode": "", "structural_origin": ""}


def _parse_markdown_table(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        if "|" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        lower = " ".join(c.lower() for c in cells)
        if "peak" in lower and ("mode" in lower or "vibration" in lower):
            continue
        if all(set(c) <= {"-", ":"} for c in cells):
            continue
        rows.append(
            {
                "peak_position": cells[0],
                "vibration_mode": cells[1],
                "structural_origin": cells[2],
            }
        )
    return rows


def _parse_peak_id_response(text: str) -> tuple[list[dict[str, str]], str]:
    assignments: list[dict[str, str]] = []
    summary = ""

    try:
        parsed = _json_from_response(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        parsed = None

    if isinstance(parsed, dict):
        raw_assignments = (
            parsed.get("assignments") or parsed.get("peaks") or parsed.get("table") or parsed.get("rows") or []
        )
        if isinstance(raw_assignments, list):
            assignments = [
                item for item in (_normalize_assignment(row) for row in raw_assignments) if any(item.values())
            ]
        summary = _collapse_paragraph(parsed.get("summary") or parsed.get("paragraph"))
    elif isinstance(parsed, list):
        assignments = [item for item in (_normalize_assignment(row) for row in parsed) if any(item.values())]

    if not assignments:
        assignments = _parse_markdown_table(text)

    if not summary:
        non_table_lines = [line.strip() for line in text.splitlines() if line.strip() and "|" not in line]
        summary = _collapse_paragraph(" ".join(non_table_lines[-3:]))

    return assignments, summary


async def _call_primary_llm(prompt: str) -> str:
    advisor = get_sherpa_advisor()
    chunks: list[str] = []

    if not getattr(advisor, "is_available", False):
        raise ValueError("Peak ID requires Sherpa Advisor. This node is unavailable in OSS-only mode.")

    async for event in advisor.stream_llm_chat(
        message=prompt,
        workflow_context={"source": "peak_id_node"},
    ):
        event_type = event.get("type") if isinstance(event, dict) else None
        if event_type == "chunk" and event.get("text"):
            chunks.append(str(event["text"]))
        elif event_type == "error":
            raise ValueError(str(event.get("detail") or "Sherpa advisor returned an error"))

    response = "".join(chunks).strip()
    if response:
        return response

    raise ValueError("Sherpa Advisor returned an empty Peak ID response.")


@register_node
class PeakIDNode(Node):
    """Assign likely molecular vibrations to peaks using the configured primary LLM."""

    metadata = NodeMetadata(
        node_type="analysis.peak_id",
        category="exploratory",
        label="Peak ID",
        description="Use the configured primary LLM to propose vibration assignments for identified spectral peaks",
        parameters=[
            NodeParameter(
                name="compound",
                label="Compound or CAS",
                param_type="text",
                default="",
                required=False,
                description="Optional single compound name or CAS number to guide peak assignment",
            ),
            NodeParameter(
                name="max_peaks",
                label="Max Peaks Sent",
                param_type="number",
                default=_DEFAULT_MAX_PEAKS,
                required=False,
                description="Maximum number of major peaks to include in the LLM prompt; 0 sends all peaks",
            ),
            NodeParameter(
                name="min_relative_height",
                label="Min Relative Height",
                param_type="number",
                default=_DEFAULT_MIN_RELATIVE_HEIGHT,
                required=False,
                description=(
                    "Drop peaks below this fraction of the strongest peak when peak heights are available; "
                    "0 disables filtering"
                ),
            ),
        ],
        input_types=["PeakData"],
        input_ports=[
            PortMetadata(
                name="peaks",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Peak List",
                description="Peak list output from Peak Finding",
            ),
        ],
        output_type="PeakID",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Peak Assignments",
                description="Peak position, vibration mode, and structural origin assignments",
            ),
        ],
        policy=NodePolicy(
            safe_for_auto_apply=False,
            requires_human_review=True,
            data_egress_risk="metadata",
            offload_to_pool=False,
        ),
    )

    async def execute(self, peaks: Any) -> NodeResult:
        rows, metadata = _extract_peak_payload(peaks)
        positions = _extract_peak_positions(rows)
        if not positions:
            raise ValueError("Peak ID requires a non-empty peak list from the Peak Finding node.")
        _format_peak_list(positions)

        max_peaks = _positive_int(
            self.parameters.get("max_peaks"),
            default=_DEFAULT_MAX_PEAKS,
            name="max_peaks",
        )
        min_relative_height = _nonnegative_float(
            self.parameters.get("min_relative_height"),
            default=_DEFAULT_MIN_RELATIVE_HEIGHT,
            name="min_relative_height",
        )
        selected_positions, selection_metadata = _select_peaks_for_prompt(
            rows,
            max_peaks=max_peaks,
            min_relative_height=min_relative_height,
        )
        if not selected_positions:
            raise ValueError("Peak ID could not select any valid peaks for assignment.")

        technique = _collapse_paragraph(metadata.get("technique")) or "spectroscopy"
        x_title = _collapse_paragraph(metadata.get("x_title")) or "x axis"
        x_units = _collapse_paragraph(metadata.get("x_units")) or "unknown units"
        compound = _collapse_paragraph(self.parameters.get("compound")) or "the sample"
        peak_list = _format_peak_list(selected_positions)
        selection_note = ""
        if selection_metadata["n_omitted_peaks"]:
            selection_note = (
                f" I selected {selection_metadata['n_prompt_peaks']} major peaks from "
                f"{selection_metadata['n_input_peaks']} candidates using relative height and detection count; "
                "do not infer assignments for omitted minor peaks."
            )

        prompt = (
            f"Given my {technique} spectra have peaks identified in {peak_list} "
            f"with x axis of {x_title} in {x_units}, what molecular vibrations of {compound} was excited. "
            f"{selection_note}"
            "Answer as JSON only with keys assignments and summary. "
            "assignments must be a list of objects with exactly peak_position, vibration_mode, and structural_origin. "
            "Use one assignment per supplied peak when possible, and make summary one paragraph only."
        )

        raw_response = await _call_primary_llm(prompt)
        assignments, summary = _parse_peak_id_response(raw_response)

        if not assignments:
            raise ValueError("Peak ID could not parse vibration assignments from the LLM response.")

        return NodeResult(
            outputs={
                "default": {
                    "data": assignments,
                    "metadata": {
                        "type": "PeakID",
                        "compound": compound,
                        "technique": technique,
                        "x_title": x_title,
                        "x_units": x_units,
                        "n_peaks": len(positions),
                        "n_prompt_peaks": selection_metadata["n_prompt_peaks"],
                        "n_omitted_peaks": selection_metadata["n_omitted_peaks"],
                        "peak_selection": selection_metadata,
                        "summary": summary,
                        "raw_response": raw_response,
                    },
                }
            },
            diagnostics={
                "n_assignments": len(assignments),
                "n_prompt_peaks": selection_metadata["n_prompt_peaks"],
                "n_omitted_peaks": selection_metadata["n_omitted_peaks"],
            },
        )
