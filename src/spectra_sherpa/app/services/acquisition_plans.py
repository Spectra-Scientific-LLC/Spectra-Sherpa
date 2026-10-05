"""Persistence and validation for complete multi-well acquisition plans."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.db.session import begin_serialized_sqlite_write
from spectra_sherpa.app.models.acquisition_plan import AcquisitionPlan
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_specimen import ExperimentSpecimen
from spectra_sherpa.app.schemas.acquisition_plans import AcquisitionPlanDocument
from spectra_sherpa.core.plate_formats import DEFAULT_PLATE_FORMAT_ID, get_plate_format

ACQUISITION_PLAN_SCHEMA = "spectrasherpa-acquisition-plan/3"


class AcquisitionPlanRevisionConflict(ValueError):
    """The intended plan changed after the client loaded it."""


def empty_acquisition_plan(*, format_id: str = DEFAULT_PLATE_FORMAT_ID) -> dict[str, object]:
    return AcquisitionPlanDocument(plate_format_id=format_id).model_dump(mode="json")


def _plan_revision(document: Mapping[str, object]) -> str:
    payload = json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_plan_wells(wells: list[str], *, format_id: str = DEFAULT_PLATE_FORMAT_ID) -> list[str]:
    plate_format = get_plate_format(format_id)
    normalized: list[str] = []
    seen: set[str] = set()
    for value in wells:
        match = re.fullmatch(r"([A-Za-z]+)([0-9]+)", str(value).strip())
        candidate = f"{match.group(1).upper()}{int(match.group(2)):02d}" if match is not None else str(value)
        row, column = plate_format.parse_well(candidate)
        well = plate_format.format_well(row, column)
        if well in seen:
            raise ValueError(f"Acquisition plan assigns {well} more than once")
        seen.add(well)
        normalized.append(well)
    return sorted(normalized, key=plate_format.parse_well)


def _unique(values: list[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"Acquisition plan defines duplicate {label} '{value}'")
        seen.add(value)


def canonicalize_acquisition_plan(document: Mapping[str, object]) -> dict[str, object]:
    validated = AcquisitionPlanDocument.model_validate(document)
    data = validated.model_dump(mode="json")
    format_id = str(data["plate_format_id"])
    plate_format = get_plate_format(format_id)

    samples = list(data["samples"])
    mixtures = list(data["mixtures"])
    factors = list(data["factors"])
    wells = list(data["wells"])
    order = list(data["acquisition_order"])
    matching = dict(data["matching"])

    _unique([str(item["sample_id"]) for item in samples], "sample ID")
    _unique(
        [str(item["source_specimen_uid"]) for item in samples if item.get("source_specimen_uid")],
        "source specimen UID",
    )
    _unique([str(item["mixture_id"]) for item in mixtures], "mixture ID")
    _unique([str(item["factor_id"]) for item in factors], "factor ID")

    sample_ids = {str(item["sample_id"]) for item in samples}
    mixture_ids = {str(item["mixture_id"]) for item in mixtures}
    factor_ids = {str(item["factor_id"]) for item in factors}
    for mixture in mixtures:
        for component in mixture["components"]:
            if component["sample_id"] not in sample_ids:
                raise ValueError(
                    f"Mixture '{mixture['mixture_id']}' references unknown sample '{component['sample_id']}'"
                )

    by_position = {}
    for item in wells:
        normalized = normalize_plan_wells([str(item["well_position"])], format_id=format_id)[0]
        if normalized in by_position:
            raise ValueError(f"Acquisition plan assigns {normalized} more than once")
        candidate = dict(item)
        candidate["well_position"] = normalized
        if candidate.get("sample_id") and candidate["sample_id"] not in sample_ids:
            raise ValueError(f"Well {normalized} references unknown sample '{candidate['sample_id']}'")
        if candidate.get("mixture_id") and candidate["mixture_id"] not in mixture_ids:
            raise ValueError(f"Well {normalized} references unknown mixture '{candidate['mixture_id']}'")
        by_position[normalized] = candidate

    for step in order:
        if step["factor_id"] not in factor_ids:
            raise ValueError(f"Acquisition-order step references unknown factor '{step['factor_id']}'")
    order.sort(key=lambda item: (int(item["sequence_order"]), str(item["factor_id"])))

    matches = list(matching["matches"])
    for match in matches:
        if match.get("well_position"):
            match["well_position"] = normalize_plan_wells([str(match["well_position"])], format_id=format_id)[0]
    matches.sort(key=lambda item: int(item["sequence_order"]))

    data["samples"] = sorted(samples, key=lambda item: str(item["sample_id"]))
    data["mixtures"] = sorted(mixtures, key=lambda item: str(item["mixture_id"]))
    data["factors"] = sorted(factors, key=lambda item: str(item["factor_id"]))
    data["wells"] = sorted(by_position.values(), key=lambda item: plate_format.parse_well(item["well_position"]))
    data["acquisition_order"] = order
    matching["matches"] = matches
    data["matching"] = matching
    return data


async def _stored_plan(session: AsyncSession, experiment_id: int) -> AcquisitionPlan | None:
    result = await session.execute(select(AcquisitionPlan).where(AcquisitionPlan.experiment_id == experiment_id))
    return result.scalar_one_or_none()


async def _validate_source_specimens(session: AsyncSession, experiment_id: int, document: Mapping[str, object]) -> None:
    samples = document.get("samples")
    if not isinstance(samples, list):
        return
    requested = {
        str(item["source_specimen_uid"])
        for item in samples
        if isinstance(item, Mapping) and item.get("source_specimen_uid")
    }
    if not requested:
        return
    result = await session.execute(
        select(ExperimentSpecimen.specimen_uid).where(
            ExperimentSpecimen.experiment_id == experiment_id,
            ExperimentSpecimen.specimen_uid.in_(requested),
        )
    )
    missing = sorted(requested - set(result.scalars()))
    if missing:
        raise ValueError(
            "Acquisition plan references specimens that do not belong to this experiment: " + ", ".join(missing)
        )


async def read_acquisition_plan(session: AsyncSession, experiment_id: int) -> dict[str, object]:
    plate_format = get_plate_format(DEFAULT_PLATE_FORMAT_ID)
    stored = await _stored_plan(session, experiment_id)
    document = canonicalize_acquisition_plan(
        stored.document if stored is not None else empty_acquisition_plan(format_id=plate_format.id)
    )
    return {
        **document,
        "experiment_id": experiment_id,
        "plate_format_label": plate_format.label,
        "capacity": plate_format.capacity,
        "revision": _plan_revision(document),
    }


async def replace_acquisition_plan(
    session: AsyncSession,
    experiment_id: int,
    updates: Mapping[str, object] | list[str],
    *,
    format_id: str = DEFAULT_PLATE_FORMAT_ID,
    expected_revision: str,
) -> dict[str, object]:
    """CAS-replace supplied plan sections while retaining omitted scientific intent."""

    await begin_serialized_sqlite_write(session)
    await session.execute(select(Experiment.id).where(Experiment.id == experiment_id).with_for_update())
    current = await read_acquisition_plan(session, experiment_id)
    if current["revision"] != expected_revision:
        raise AcquisitionPlanRevisionConflict(
            "The acquisition plan changed after you opened it. Reload the plan before saving."
        )
    document = {
        key: value
        for key, value in current.items()
        if key not in {"experiment_id", "plate_format_label", "capacity", "revision"}
    }
    if isinstance(updates, list):
        updates = {"wells": [{"well_position": value} for value in updates]}
    document.update({key: value for key, value in updates.items() if value is not None})
    document["plate_format_id"] = str(document.get("plate_format_id") or format_id)
    canonical = canonicalize_acquisition_plan(document)
    await _validate_source_specimens(session, experiment_id, canonical)

    stored = await _stored_plan(session, experiment_id)
    if stored is None:
        stored = AcquisitionPlan(experiment_id=experiment_id, document=canonical)
        session.add(stored)
    else:
        stored.document = canonical
    await session.commit()
    return await read_acquisition_plan(session, experiment_id)


__all__ = [
    "ACQUISITION_PLAN_SCHEMA",
    "AcquisitionPlanRevisionConflict",
    "canonicalize_acquisition_plan",
    "empty_acquisition_plan",
    "normalize_plan_wells",
    "read_acquisition_plan",
    "replace_acquisition_plan",
]
