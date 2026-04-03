"""Design of Experiments (DOE) service functions."""

from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from xml.dom import minidom

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.factor_definition import FactorDefinition
from spectra_sherpa.app.models.matched_acquisition import MatchedAcquisition
from spectra_sherpa.app.models.mixture import Mixture
from spectra_sherpa.app.models.mixture_component import MixtureComponent
from spectra_sherpa.app.models.plate_well import PlateWell
from spectra_sherpa.app.models.run_level import RunLevel
from spectra_sherpa.app.models.sample import Sample


class ExperimentNotFoundError(Exception):
    """Raised when an experiment does not exist or is not owned by the user."""


# ==================== Ownership ====================


async def verify_experiment_ownership(
    session: AsyncSession,
    experiment_id: int,
    user_id: int,
) -> Experiment:
    """Verify experiment exists and belongs to user. Raises ExperimentNotFoundError."""
    stmt = select(Experiment).where(Experiment.id == experiment_id)
    result = await session.execute(stmt)
    experiment = result.scalar_one_or_none()
    if not experiment or experiment.user_id != user_id:
        raise ExperimentNotFoundError("Experiment not found")
    return experiment


# ==================== Samples ====================


async def import_samples(
    session: AsyncSession,
    experiment_id: int,
    csv_data: str,
) -> list[Sample]:
    """Import samples from CSV string. Raises ValueError on parse error."""
    try:
        csv_reader = csv.DictReader(io.StringIO(csv_data))
        samples = []

        for row in csv_reader:
            sample = Sample(
                experiment_id=experiment_id,
                sample_id=row.get("sample_id", ""),
                name=row.get("name", ""),
                type=row.get("type"),
                brand=row.get("brand"),
                cas_number=row.get("cas_number"),
                active=row.get("active", "true").lower() in ("true", "1", "yes"),
                notes=row.get("notes"),
            )
            session.add(sample)
            samples.append(sample)

        await session.commit()
        for sample in samples:
            await session.refresh(sample)

        return samples

    except Exception as e:
        await session.rollback()
        raise ValueError(f"CSV parse error: {e}") from e


async def list_samples(
    session: AsyncSession,
    experiment_id: int,
) -> list[Sample]:
    """List all samples for an experiment."""
    stmt = select(Sample).where(Sample.experiment_id == experiment_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_sample(
    session: AsyncSession,
    experiment_id: int,
    data: dict,
) -> Sample:
    """Create a single sample from a dict of attributes."""
    sample = Sample(experiment_id=experiment_id, **data)
    session.add(sample)
    await session.commit()
    await session.refresh(sample)
    return sample


# ==================== Mixtures ====================


async def list_mixtures(
    session: AsyncSession,
    experiment_id: int,
) -> list[dict]:
    """List mixtures with their components for an experiment."""
    stmt = select(Mixture).where(Mixture.experiment_id == experiment_id)
    result = await session.execute(stmt)
    mixtures = result.scalars().all()

    output = []
    for mixture in mixtures:
        stmt_components = select(MixtureComponent).where(MixtureComponent.mixture_id == mixture.id)
        result_components = await session.execute(stmt_components)
        components = result_components.scalars().all()

        mixture_dict = mixture.__dict__.copy()
        mixture_dict["components"] = components
        output.append(mixture_dict)

    return output


async def create_mixture(
    session: AsyncSession,
    experiment_id: int,
    mixture_id: str,
    name: str | None,
    basis: str,
    notes: str | None,
    components: list[dict],
) -> dict:
    """Create a mixture with its components. Returns dict with 'components' key."""
    mixture = Mixture(
        experiment_id=experiment_id,
        mixture_id=mixture_id,
        name=name,
        basis=basis,
        notes=notes,
    )
    session.add(mixture)
    await session.flush()

    comp_objects = []
    for comp_data in components:
        component = MixtureComponent(mixture_id=mixture.id, **comp_data)
        session.add(component)
        comp_objects.append(component)

    await session.commit()
    await session.refresh(mixture)

    mixture_dict = mixture.__dict__.copy()
    mixture_dict["components"] = comp_objects
    return mixture_dict


# ==================== Factors ====================


async def list_factors(
    session: AsyncSession,
    experiment_id: int,
) -> list[FactorDefinition]:
    """List factor definitions for an experiment."""
    stmt = select(FactorDefinition).where(FactorDefinition.experiment_id == experiment_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_factor(
    session: AsyncSession,
    experiment_id: int,
    data: dict,
) -> FactorDefinition:
    """Create a factor definition from a dict of attributes."""
    factor = FactorDefinition(experiment_id=experiment_id, **data)
    session.add(factor)
    await session.commit()
    await session.refresh(factor)
    return factor


# ==================== Plate Map ====================


async def get_plate_map(
    session: AsyncSession,
    experiment_id: int,
) -> list[PlateWell]:
    """Get 96-well plate map for an experiment."""
    stmt = select(PlateWell).where(PlateWell.experiment_id == experiment_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def set_plate_map(
    session: AsyncSession,
    experiment_id: int,
    wells_data: list[dict],
) -> list[PlateWell]:
    """Replace plate map with new wells (bulk operation)."""
    # Delete existing
    stmt_delete = select(PlateWell).where(PlateWell.experiment_id == experiment_id)
    result = await session.execute(stmt_delete)
    for well in result.scalars().all():
        await session.delete(well)

    # Create new
    wells = []
    for well_data in wells_data:
        well = PlateWell(experiment_id=experiment_id, **well_data)
        session.add(well)
        wells.append(well)

    await session.commit()
    for well in wells:
        await session.refresh(well)

    return wells


# ==================== Run Sequence ====================


async def get_run_sequence(
    session: AsyncSession,
    experiment_id: int,
) -> list[RunLevel]:
    """Get ordered run sequence for an experiment."""
    stmt = select(RunLevel).where(RunLevel.experiment_id == experiment_id).order_by(RunLevel.sequence_order)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def set_run_sequence(
    session: AsyncSession,
    experiment_id: int,
    levels_data: list[dict],
) -> list[RunLevel]:
    """Replace run sequence with new levels (bulk operation)."""
    # Delete existing
    stmt_delete = select(RunLevel).where(RunLevel.experiment_id == experiment_id)
    result = await session.execute(stmt_delete)
    for level in result.scalars().all():
        await session.delete(level)

    # Create new
    levels = []
    for level_data in levels_data:
        level = RunLevel(experiment_id=experiment_id, **level_data)
        session.add(level)
        levels.append(level)

    await session.commit()
    for level in levels:
        await session.refresh(level)

    return levels


# ==================== Acquisition Matching ====================


def generate_scan_path(first_cell: str, num_cells: int, orientation: str = "row") -> list[str]:
    """
    Generate plate scan path from first cell.

    Args:
        first_cell: Starting cell (e.g., "A1")
        num_cells: Number of cells to generate
        orientation: "row", "column", "serpentine", or "serpentine_column"

    Returns:
        List of cell positions
    """
    rows = "ABCDEFGH"
    cols = list(range(1, 13))

    # Parse first cell
    row_idx = rows.index(first_cell[0].upper())
    col_idx = int(first_cell[1:]) - 1

    cells = []

    if orientation == "row":
        for _ in range(num_cells):
            cells.append(f"{rows[row_idx]}{cols[col_idx]}")
            col_idx += 1
            if col_idx >= 12:
                col_idx = 0
                row_idx += 1
                if row_idx >= 8:
                    row_idx = 0

    elif orientation == "column":
        for _ in range(num_cells):
            cells.append(f"{rows[row_idx]}{cols[col_idx]}")
            row_idx += 1
            if row_idx >= 8:
                row_idx = 0
                col_idx += 1
                if col_idx >= 12:
                    col_idx = 0

    elif orientation == "serpentine":
        forward = True
        for _ in range(num_cells):
            cells.append(f"{rows[row_idx]}{cols[col_idx]}")
            if forward:
                col_idx += 1
                if col_idx >= 12:
                    col_idx = 11
                    row_idx += 1
                    forward = False
            else:
                col_idx -= 1
                if col_idx < 0:
                    col_idx = 0
                    row_idx += 1
                    forward = True
            if row_idx >= 8:
                row_idx = 0

    elif orientation == "serpentine_column":
        forward = True
        for _ in range(num_cells):
            cells.append(f"{rows[row_idx]}{cols[col_idx]}")
            if forward:
                row_idx += 1
                if row_idx >= 8:
                    row_idx = 7
                    col_idx += 1
                    forward = False
            else:
                row_idx -= 1
                if row_idx < 0:
                    row_idx = 0
                    col_idx += 1
                    forward = True
            if col_idx >= 12:
                col_idx = 0

    return cells


def extract_filename_number(filename: str) -> int | None:
    """
    Extract numeric portion from filename for seq number.
    Handles formats like: Spectrum_0002.csv, file_123.dat, 0045_data.txt
    """
    patterns = [
        r"_(\d+)\.",  # _0002.csv
        r"_(\d+)$",  # _0002
        r"^(\d+)_",  # 0002_
        r"(\d+)",  # Any digits
    ]

    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            return int(match.group(1))

    return None


async def auto_match_acquisitions(
    session: AsyncSession,
    experiment_id: int,
    file_list: list[str] | None,
    folders: list[dict] | None,
    first_cell: str | None,
    scan_orientation: str | None,
    seq_offset: int,
    use_plate_map: bool,
    use_run_sequence: bool,
) -> list[dict]:
    """
    Comprehensive auto-match with folder batching, scan path, and factor mapping.
    """
    matched = []

    # Prepare file list with folder/batch info
    files_with_meta = []

    if folders:
        for folder_idx, folder_data in enumerate(folders):
            folder_path = folder_data["folder_path"]
            batch_num = folder_data.get("batch_number", folder_idx + 1)

            for filename in folder_data["file_list"]:
                files_with_meta.append(
                    {
                        "filename": filename,
                        "folder": folder_path,
                        "batch": batch_num,
                    }
                )
    elif file_list:
        for filename in file_list:
            if "/" in filename or "\\" in filename:
                parts = filename.replace("\\", "/").split("/")
                folder = parts[-2] if len(parts) > 1 else None
                filename_only = parts[-1]
            else:
                folder = None
                filename_only = filename

            files_with_meta.append(
                {
                    "filename": filename_only,
                    "folder": folder,
                    "batch": None,
                }
            )
    else:
        return []

    # Load plate map if using scan path derivation
    plate_map = {}
    mixture_samples = {}

    if use_plate_map and first_cell and scan_orientation:
        stmt = (
            select(PlateWell).where(PlateWell.experiment_id == experiment_id).options(selectinload(PlateWell.mixture))
        )
        result = await session.execute(stmt)
        wells = result.scalars().all()

        for well in wells:
            if well.mixture_id:
                plate_map[well.well_position] = well.mixture_id

                if well.mixture:
                    mixture_samples[well.mixture_id] = well.mixture.name or well.mixture.mixture_id

    # Load run sequence for factor mapping
    run_factors = {}
    factor_names = {}

    if use_run_sequence:
        stmt = (
            select(RunLevel, FactorDefinition)
            .join(FactorDefinition, RunLevel.factor_definition_id == FactorDefinition.id)
            .where(RunLevel.experiment_id == experiment_id)
        )
        result = await session.execute(stmt)
        run_data = result.all()

        for run_level, factor_def in run_data:
            folder_key = run_level.path if run_level.path else f"batch_{run_level.batch}"

            if folder_key not in run_factors:
                run_factors[folder_key] = {}

            factor_label = f"{factor_def.name} [{factor_def.unit}]" if factor_def.unit else factor_def.name
            run_factors[folder_key][factor_label] = run_level.level_value
            factor_names[factor_def.id] = factor_label

    # Generate scan path if needed
    scan_cells = None
    if use_plate_map and first_cell and scan_orientation:
        scan_cells = generate_scan_path(first_cell, len(files_with_meta), scan_orientation)

    # Process each file
    for idx, file_meta in enumerate(files_with_meta):
        filename = file_meta["filename"]
        folder = file_meta["folder"]
        batch = file_meta["batch"]

        seq = idx + 1 + seq_offset

        # Extract timestamp
        timestamp_pattern = re.compile(r"(\d{8,14})")
        timestamp_match = timestamp_pattern.search(filename)
        timestamp = int(timestamp_match.group(1)) if timestamp_match else None

        # Determine cell and sample_id
        cell = None
        sample_id = None

        cell_pattern = re.compile(r"([A-H][0-9]{1,2})", re.IGNORECASE)
        cell_match = cell_pattern.search(filename)

        if cell_match:
            cell = cell_match.group(1).upper()
        elif scan_cells and idx < len(scan_cells):
            cell = scan_cells[idx]

        # Get sample_id from plate map
        if cell and cell in plate_map:
            mixture_id = plate_map[cell]
            sample_id = mixture_samples.get(mixture_id)

        # Get factor values
        factor_values = {}

        if use_run_sequence and folder:
            if folder in run_factors:
                factor_values = run_factors[folder].copy()
            elif batch and f"batch_{batch}" in run_factors:
                factor_values = run_factors[f"batch_{batch}"].copy()

        # Build date from timestamp
        date_str = None
        if timestamp:
            try:
                if len(str(timestamp)) == 14:  # YYYYMMDDhhmmss
                    dt = datetime.strptime(str(timestamp), "%Y%m%d%H%M%S")
                elif len(str(timestamp)) >= 10:  # Unix timestamp
                    dt = datetime.fromtimestamp(timestamp)
                else:
                    dt = None

                if dt:
                    date_str = dt.strftime("%Y-%m-%d")
            except (ValueError, OSError, OverflowError):
                pass

        matched.append(
            {
                "seq": seq,
                "filename": filename,
                "folder": folder,
                "timestamp": timestamp,
                "date": date_str,
                "batch": batch,
                "sample_id": sample_id,
                "cell": cell,
                "special": None,
                "factor_values": factor_values if factor_values else None,
            }
        )

    return matched


async def match_and_save_acquisitions(
    session: AsyncSession,
    experiment_id: int,
    file_list: list[str] | None,
    folders: list[dict] | None,
    first_cell: str | None,
    scan_orientation: str | None,
    seq_offset: int,
    use_plate_map: bool,
    use_run_sequence: bool,
) -> list[MatchedAcquisition]:
    """Auto-match acquisitions and persist them, replacing any existing ones."""
    # Delete existing
    stmt_delete = select(MatchedAcquisition).where(MatchedAcquisition.experiment_id == experiment_id)
    result = await session.execute(stmt_delete)
    for acq in result.scalars().all():
        await session.delete(acq)

    # Auto-match
    matched_data = await auto_match_acquisitions(
        session=session,
        experiment_id=experiment_id,
        file_list=file_list,
        folders=folders,
        first_cell=first_cell,
        scan_orientation=scan_orientation,
        seq_offset=seq_offset,
        use_plate_map=use_plate_map,
        use_run_sequence=use_run_sequence,
    )

    # Persist
    acquisitions = []
    for data in matched_data:
        acq = MatchedAcquisition(experiment_id=experiment_id, **data)
        session.add(acq)
        acquisitions.append(acq)

    await session.commit()
    for acq in acquisitions:
        await session.refresh(acq)

    return acquisitions


async def get_matched_acquisitions(
    session: AsyncSession,
    experiment_id: int,
) -> list[MatchedAcquisition]:
    """Get matched acquisitions ordered by sequence number."""
    stmt = (
        select(MatchedAcquisition)
        .where(MatchedAcquisition.experiment_id == experiment_id)
        .order_by(MatchedAcquisition.seq)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ==================== Export ====================


async def build_export_data(
    session: AsyncSession,
    experiment_id: int,
) -> dict:
    """Collect all DOE entities for an experiment into a single dict."""
    samples = await list_samples(session, experiment_id)
    mixtures = await list_mixtures(session, experiment_id)
    factors = await list_factors(session, experiment_id)
    plate_map_wells = await get_plate_map(session, experiment_id)
    run_seq = await get_run_sequence(session, experiment_id)
    matched = await get_matched_acquisitions(session, experiment_id)

    return {
        "experiment_id": experiment_id,
        "exported_at": datetime.utcnow().isoformat(),
        "samples": samples,
        "mixtures": mixtures,
        "factors": factors,
        "plate_map": plate_map_wells,
        "run_sequence": run_seq,
        "matched_acquisitions": matched,
    }


def export_csv(acquisitions: list[MatchedAcquisition]) -> str:
    """Generate CSV string from matched acquisitions with dynamic factor columns."""
    if not acquisitions:
        return ""

    # Collect all unique factor names
    all_factor_names: set[str] = set()
    for acq in acquisitions:
        if acq.factor_values:
            all_factor_names.update(acq.factor_values.keys())

    base_fields = ["seq", "filename", "folder", "timestamp", "cell", "sample_id"]
    factor_fields = sorted(list(all_factor_names))
    batch_field = ["batch"]
    all_fields = base_fields + factor_fields + batch_field

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=all_fields)
    writer.writeheader()

    for acq in acquisitions:
        row = {
            "seq": acq.seq,
            "filename": acq.filename,
            "folder": acq.folder,
            "timestamp": acq.timestamp,
            "cell": acq.cell,
            "sample_id": acq.sample_id,
            "batch": acq.batch,
        }

        if acq.factor_values:
            for factor_name in factor_fields:
                row[factor_name] = acq.factor_values.get(factor_name, "")

        writer.writerow(row)

    return output.getvalue()


def export_json(export_data: dict) -> str:
    """Generate JSON string from export data dict.

    Expects export_data values to have .model_dump() (Pydantic schemas)
    or be plain dicts.
    """
    serializable = {}
    for key, value in export_data.items():
        if isinstance(value, list):
            items = []
            for item in value:
                if hasattr(item, "model_dump"):
                    items.append(item.model_dump())
                elif isinstance(item, dict):
                    items.append(item)
                else:
                    items.append(str(item))
            serializable[key] = items
        else:
            serializable[key] = value

    return json.dumps(serializable, indent=2, default=str)


def export_xml(
    experiment_id: int,
    samples: list,
    mixtures: list,
    factors: list,
    matched: list,
) -> str:
    """Generate XML string from DOE data.

    Args accept either schema objects (with attribute access) or dicts.
    """
    root = ET.Element("experiment")
    root.set("id", str(experiment_id))

    # Samples
    samples_elem = ET.SubElement(root, "samples")
    for sample in samples:
        s_elem = ET.SubElement(samples_elem, "sample")
        sid = sample.sample_id if hasattr(sample, "sample_id") else sample["sample_id"]
        s_elem.set("id", sid)
        name = sample.name if hasattr(sample, "name") else sample["name"]
        ET.SubElement(s_elem, "name").text = name
        stype = sample.type if hasattr(sample, "type") else sample.get("type")
        if stype:
            ET.SubElement(s_elem, "type").text = stype
        brand = sample.brand if hasattr(sample, "brand") else sample.get("brand")
        if brand:
            ET.SubElement(s_elem, "brand").text = brand

    # Mixtures
    mixtures_elem = ET.SubElement(root, "mixtures")
    for mixture in mixtures:
        m_elem = ET.SubElement(mixtures_elem, "mixture")
        mid = mixture.mixture_id if hasattr(mixture, "mixture_id") else mixture["mixture_id"]
        m_elem.set("id", mid)
        basis = mixture.basis if hasattr(mixture, "basis") else mixture["basis"]
        ET.SubElement(m_elem, "basis").text = basis
        comps_elem = ET.SubElement(m_elem, "components")
        components = mixture.components if hasattr(mixture, "components") else mixture.get("components", [])
        for comp in components:
            c_elem = ET.SubElement(comps_elem, "component")
            amount = comp.amount if hasattr(comp, "amount") else comp["amount"]
            unit = comp.unit if hasattr(comp, "unit") else comp["unit"]
            ET.SubElement(c_elem, "amount").text = str(amount)
            ET.SubElement(c_elem, "unit").text = unit

    # Factors
    factors_elem = ET.SubElement(root, "factors")
    for factor in factors:
        f_elem = ET.SubElement(factors_elem, "factor")
        fname = factor.name if hasattr(factor, "name") else factor["name"]
        fscope = factor.scope if hasattr(factor, "scope") else factor["scope"]
        ftype = factor.type if hasattr(factor, "type") else factor["type"]
        ET.SubElement(f_elem, "name").text = fname
        ET.SubElement(f_elem, "scope").text = fscope
        ET.SubElement(f_elem, "type").text = ftype

    # Matched acquisitions
    matched_elem = ET.SubElement(root, "matched_acquisitions")
    for acq in matched:
        a_elem = ET.SubElement(matched_elem, "acquisition")
        seq = acq.seq if hasattr(acq, "seq") else acq.get("seq")
        if seq:
            ET.SubElement(a_elem, "seq").text = str(seq)
        fname = acq.filename if hasattr(acq, "filename") else acq.get("filename")
        if fname:
            ET.SubElement(a_elem, "filename").text = fname
        batch = acq.batch if hasattr(acq, "batch") else acq.get("batch")
        if batch:
            ET.SubElement(a_elem, "batch").text = str(batch)

    # nosec B318 — self-generated XML
    xml_str = minidom.parseString(ET.tostring(root)).toprettyxml(indent="  ")
    return xml_str


# ==================== Summary ====================


async def get_summary(
    session: AsyncSession,
    experiment_id: int,
) -> dict:
    """Get DOE summary counts for an experiment."""
    samples_count = await session.scalar(
        select(func.count()).select_from(Sample).where(Sample.experiment_id == experiment_id)
    )
    mixtures_count = await session.scalar(
        select(func.count()).select_from(Mixture).where(Mixture.experiment_id == experiment_id)
    )
    factors_count = await session.scalar(
        select(func.count()).select_from(FactorDefinition).where(FactorDefinition.experiment_id == experiment_id)
    )
    wells_count = await session.scalar(
        select(func.count()).select_from(PlateWell).where(PlateWell.experiment_id == experiment_id)
    )
    levels_count = await session.scalar(
        select(func.count()).select_from(RunLevel).where(RunLevel.experiment_id == experiment_id)
    )
    matched_count = await session.scalar(
        select(func.count()).select_from(MatchedAcquisition).where(MatchedAcquisition.experiment_id == experiment_id)
    )

    return {
        "sample_count": samples_count or 0,
        "mixture_count": mixtures_count or 0,
        "factor_count": factors_count or 0,
        "well_count": wells_count or 0,
        "run_level_count": levels_count or 0,
        "matched_count": matched_count or 0,
    }
