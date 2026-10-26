"""Bounded projections of the canonical gas-phase labels for My Dataset."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

from spectra_sherpa.app.services.dag.nodes.bosch_phases import PHASE_LABELS, phase_projection
from spectra_sherpa.io.bosch_netcdf import bosch_phase_observations
from spectra_sherpa.io.registry import builtin_registry


def _identity(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return str(path), stat.st_size, stat.st_mtime_ns


@lru_cache(maxsize=6)
def _catalog(daily_identity, process_identity):
    daily_path, process_path = Path(daily_identity[0]), Path(process_identity[0])
    observations = bosch_phase_observations(daily_path)
    date_prefix = "Day_" + observations["date"].replace("-", "_") + "_"
    wafers, private, process_sha = [], {}, None
    for group in observations["groups"]:
        name = group["asset_id"]
        process_group = date_prefix + name
        result = builtin_registry.ingest(process_path, asset_id=process_group)
        if result.format_id != "bosch-netcdf" or result.assets[0].dataset.data_role != "X_features":
            raise ValueError("The required companion must contain BOSCH process gas-flow groups")
        current_sha = result.source_members[0].sha256
        if process_sha is not None and current_sha != process_sha:
            raise ValueError("Process companion changed while phase labels were being built")
        process_sha = current_sha
        times = group["times"]
        try:
            labels, alignment = phase_projection(times, group["signal"], result.assets[0].dataset)
        except ValueError as exc:
            wafers.append({"asset_id": name, "steps": [], "refusal": str(exc), "alignment": None})
            continue
        steps = []
        for key, label in PHASE_LABELS.items():
            mask = labels == key
            if not mask.any():
                continue
            # Split at missing optical samples; a range never hides an optical
            # recording gap larger than one second.
            intervals = []
            selected = np.flatnonzero(mask)
            cuts = np.flatnonzero((np.diff(selected) != 1) | (np.diff(times[selected]) > 1)) + 1
            for run in np.split(selected, cuts):
                intervals.append(
                    {
                        "first_acquisition": int(run[0]) + 1,
                        "last_acquisition": int(run[-1]) + 1,
                        "start_time": float(times[run[0]]),
                        "end_time": float(times[run[-1]]),
                        "acquisition_count": len(run),
                    }
                )
            steps.append({"step_id": key, "label": label, "acquisition_count": int(mask.sum()), "intervals": intervals})
        wafers.append({"asset_id": name, "steps": steps, "alignment": alignment, "refusal": None})
        private[name] = {"times": times, "labels": labels}
    return {
        "source_sha256": observations["source_sha256"],
        "process_sha256": process_sha,
        "date": observations["date"],
        "lot": observations["lot"],
        "wafers": wafers,
        "unrecorded_protocol_steps": [
            "Initial chamber preparation (2-minute plasmas, dummy BOSCH, EPD clean, 30-minute break)",
            "Conditioning repetitions (O₂, O₂/SF₆, 4-minute breaks)",
        ],
        "warnings": [
            "Phase clocks are estimated from gas/OES correlation, not a shared declared epoch.",
            "Transition edges within one process sampling interval are excluded from etch/passivation.",
            (
                "Gas1 identity is unconfirmed; do not treat the tentative O2 mapping as a verified assignment. "
                "EPD control is not established."
            ),
        ],
        "_private": private,
    }


def phase_catalog(daily_path: Path, process_path: Path) -> dict:
    return _catalog(_identity(daily_path), _identity(process_path))


def step_preview(
    daily_path: Path,
    process_path: Path,
    *,
    asset_id: str,
    step_id: str,
    source_sha256: str,
    process_sha256: str,
    max_rows: int = 4,
):
    if not 1 <= max_rows <= 16:
        raise ValueError("Preview supports 1..16 original acquisitions per wafer/step")
    catalog = phase_catalog(daily_path, process_path)
    if catalog["source_sha256"] != source_sha256 or catalog["process_sha256"] != process_sha256:
        raise ValueError("Sources changed; refresh the processing-step inventory")
    if builtin_registry.inspect(process_path).source_members[0].sha256 != process_sha256:
        raise ValueError("Process companion changed; refresh the processing-step inventory")
    group = catalog["_private"].get(asset_id)
    if group is None or step_id not in PHASE_LABELS:
        raise ValueError("Select an aligned wafer and recorded processing step")
    rows = np.flatnonzero(group["labels"] == step_id)
    if not len(rows):
        raise ValueError("The selected wafer has no acquisitions for this processing step")
    selected = rows[np.unique(np.linspace(0, len(rows) - 1, min(max_rows, len(rows))).astype(int))]
    result = builtin_registry.ingest(daily_path, asset_id=asset_id, rows=tuple(int(i) for i in selected))
    if result.source_members[0].sha256 != source_sha256:
        raise ValueError("Daily source changed during preview")
    dataset = result.assets[0].dataset
    axis = dataset.sample_axis.model_dump()
    table = dict(axis.get("sample_table") or {})
    table["processing_step"] = [PHASE_LABELS[step_id]] * len(selected)
    table["acquisition_number"] = [int(row) + 1 for row in selected]
    axis["sample_table"] = table
    from spectra_sherpa.app.lib.axes import SampleAxis

    dataset.sample_axis = SampleAxis(**axis)
    dataset.set_extra(
        "bosch.phase_selection",
        {
            "step_id": step_id,
            "process_sha256": process_sha256,
            "selected_acquisition_count": len(rows),
            "preview_acquisitions": len(selected),
            "method": "Evenly spaced original acquisitions; no averaging",
        },
    )
    return dataset, len(rows)
