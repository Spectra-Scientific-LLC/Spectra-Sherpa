"""Design of Experiments (DOE) routes"""

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from xml.dom import minidom

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import demo_guard, get_current_user, get_session
from spectra_sherpa.app.core.security import check_export_allowed
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.factor_definition import FactorDefinition
from spectra_sherpa.app.models.matched_acquisition import MatchedAcquisition
from spectra_sherpa.app.models.mixture import Mixture
from spectra_sherpa.app.models.mixture_component import MixtureComponent
from spectra_sherpa.app.models.plate_well import PlateWell
from spectra_sherpa.app.models.run_level import RunLevel
from spectra_sherpa.app.models.sample import Sample
from spectra_sherpa.app.schemas.doe import (
    DOESummary,
    FactorDefinition as FactorDefinitionSchema,
    FactorDefinitionCreate,
    MatchAcquisitionsRequest,
    MatchedAcquisition as MatchedAcquisitionSchema,
    Mixture as MixtureSchema,
    MixtureCreate,
    PlateMapRequest,
    PlateWell as PlateWellSchema,
    RunLevel as RunLevelSchema,
    RunSequenceRequest,
    Sample as SampleSchema,
    SampleCreate,
    SampleImportRequest,
)

router = APIRouter(prefix="/experiments/{experiment_id}/doe")


async def _verify_experiment_ownership(
    experiment_id: int,
    session: AsyncSession,
    current_user: User,
) -> Experiment:
    """Verify experiment exists and belongs to current user."""
    stmt = select(Experiment).where(Experiment.id == experiment_id)
    result = await session.execute(stmt)
    experiment = result.scalar_one_or_none()
    if not experiment or experiment.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return experiment


# ==================== Sample Database ====================


@router.post("/samples/import", response_model=list[SampleSchema], dependencies=[Depends(demo_guard("data_upload"))])
async def import_samples(
    experiment_id: int,
    payload: SampleImportRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[SampleSchema]:
    """Import samples from CSV (metadata only)"""
    await _verify_experiment_ownership(experiment_id, session, current_user)

    # Parse CSV
    try:
        csv_reader = csv.DictReader(io.StringIO(payload.csv_data))
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

        return [SampleSchema.model_validate(s) for s in samples]

    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=f"CSV parse error: {str(e)}")


@router.get("/samples", response_model=list[SampleSchema])
async def list_samples(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[SampleSchema]:
    """List samples for experiment"""
    await _verify_experiment_ownership(experiment_id, session, current_user)
    stmt = select(Sample).where(Sample.experiment_id == experiment_id)
    result = await session.execute(stmt)
    samples = result.scalars().all()
    return [SampleSchema.model_validate(s) for s in samples]


@router.post("/samples", response_model=SampleSchema)
async def create_sample(
    experiment_id: int,
    payload: SampleCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> SampleSchema:
    """Create a single sample"""
    await _verify_experiment_ownership(experiment_id, session, current_user)
    sample = Sample(experiment_id=experiment_id, **payload.model_dump())
    session.add(sample)
    await session.commit()
    await session.refresh(sample)
    return SampleSchema.model_validate(sample)


# ==================== Mixtures ====================


@router.get("/mixtures", response_model=list[MixtureSchema])
async def list_mixtures(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[MixtureSchema]:
    """List mixtures for experiment"""
    await _verify_experiment_ownership(experiment_id, session, current_user)
    stmt = (
        select(Mixture)
        .where(Mixture.experiment_id == experiment_id)
        .options()  # Add eager loading if needed
    )
    result = await session.execute(stmt)
    mixtures = result.scalars().all()

    # Load components for each mixture
    output = []
    for mixture in mixtures:
        stmt_components = select(MixtureComponent).where(
            MixtureComponent.mixture_id == mixture.id
        )
        result_components = await session.execute(stmt_components)
        components = result_components.scalars().all()

        mixture_dict = mixture.__dict__.copy()
        mixture_dict["components"] = components
        output.append(MixtureSchema.model_validate(mixture_dict))

    return output


@router.post("/mixtures", response_model=MixtureSchema)
async def create_mixture(
    experiment_id: int,
    payload: MixtureCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> MixtureSchema:
    """Create mixture with components"""
    await _verify_experiment_ownership(experiment_id, session, current_user)
    mixture = Mixture(
        experiment_id=experiment_id,
        mixture_id=payload.mixture_id,
        name=payload.name,
        basis=payload.basis,
        notes=payload.notes,
    )
    session.add(mixture)
    await session.flush()

    components = []
    for comp_data in payload.components:
        component = MixtureComponent(
            mixture_id=mixture.id, **comp_data.model_dump()
        )
        session.add(component)
        components.append(component)

    await session.commit()
    await session.refresh(mixture)

    mixture_dict = mixture.__dict__.copy()
    mixture_dict["components"] = components
    return MixtureSchema.model_validate(mixture_dict)


# ==================== Factor Definitions ====================


@router.get("/factors", response_model=list[FactorDefinitionSchema])
async def list_factors(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[FactorDefinitionSchema]:
    """List factor definitions for experiment"""
    await _verify_experiment_ownership(experiment_id, session, current_user)
    stmt = select(FactorDefinition).where(
        FactorDefinition.experiment_id == experiment_id
    )
    result = await session.execute(stmt)
    factors = result.scalars().all()
    return [FactorDefinitionSchema.model_validate(f) for f in factors]


@router.post("/factors", response_model=FactorDefinitionSchema)
async def create_factor(
    experiment_id: int,
    payload: FactorDefinitionCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FactorDefinitionSchema:
    """Create factor definition"""
    await _verify_experiment_ownership(experiment_id, session, current_user)
    factor = FactorDefinition(experiment_id=experiment_id, **payload.model_dump())
    session.add(factor)
    await session.commit()
    await session.refresh(factor)
    return FactorDefinitionSchema.model_validate(factor)


# ==================== Plate Map ====================


@router.get("/plate-map", response_model=list[PlateWellSchema])
async def get_plate_map(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[PlateWellSchema]:
    """Get 96-well plate map"""
    await _verify_experiment_ownership(experiment_id, session, current_user)
    stmt = select(PlateWell).where(PlateWell.experiment_id == experiment_id)
    result = await session.execute(stmt)
    wells = result.scalars().all()
    return [PlateWellSchema.model_validate(w) for w in wells]


@router.post("/plate-map", response_model=list[PlateWellSchema])
async def set_plate_map(
    experiment_id: int,
    payload: PlateMapRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[PlateWellSchema]:
    """Set 96-well plate map (bulk operation)"""
    await _verify_experiment_ownership(experiment_id, session, current_user)
    # Delete existing plate map
    stmt_delete = select(PlateWell).where(PlateWell.experiment_id == experiment_id)
    result = await session.execute(stmt_delete)
    existing = result.scalars().all()
    for well in existing:
        await session.delete(well)

    # Create new plate map
    wells = []
    for well_data in payload.wells:
        well = PlateWell(experiment_id=experiment_id, **well_data.model_dump())
        session.add(well)
        wells.append(well)

    await session.commit()
    for well in wells:
        await session.refresh(well)

    return [PlateWellSchema.model_validate(w) for w in wells]


# ==================== Run Sequence ====================


@router.get("/run-sequence", response_model=list[RunLevelSchema])
async def get_run_sequence(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[RunLevelSchema]:
    """Get run sequence"""
    await _verify_experiment_ownership(experiment_id, session, current_user)
    stmt = (
        select(RunLevel)
        .where(RunLevel.experiment_id == experiment_id)
        .order_by(RunLevel.sequence_order)
    )
    result = await session.execute(stmt)
    levels = result.scalars().all()
    return [RunLevelSchema.model_validate(l) for l in levels]


@router.post("/run-sequence", response_model=list[RunLevelSchema])
async def set_run_sequence(
    experiment_id: int,
    payload: RunSequenceRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[RunLevelSchema]:
    """Set run sequence (manual entry)"""
    await _verify_experiment_ownership(experiment_id, session, current_user)
    # Delete existing run sequence
    stmt_delete = select(RunLevel).where(RunLevel.experiment_id == experiment_id)
    result = await session.execute(stmt_delete)
    existing = result.scalars().all()
    for level in existing:
        await session.delete(level)

    # Create new run sequence
    levels = []
    for level_data in payload.levels:
        level = RunLevel(experiment_id=experiment_id, **level_data.model_dump())
        session.add(level)
        levels.append(level)

    await session.commit()
    for level in levels:
        await session.refresh(level)

    return [RunLevelSchema.model_validate(l) for l in levels]


# ==================== Acquisition Matching ====================


def generate_scan_path(
    first_cell: str, num_cells: int, orientation: str = "row"
) -> list[str]:
    """
    Generate plate scan path from first cell.

    Args:
        first_cell: Starting cell (e.g., "A1")
        num_cells: Number of cells to generate
        orientation: Scan pattern:
            - "row": A1→A2→...→A12→B1→B2→...→H12
            - "column": A1→B1→...→H1→A2→B2→...→H12
            - "serpentine": A1→A12, B12→B1, C1→C12, ... (row-based)
            - "serpentine_column": A1→H1, H2→A2, A3→H3, ... (column-based)

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
        # Row-wise: A1, A2, ..., A12, B1, B2, ..., H12
        for _ in range(num_cells):
            cells.append(f"{rows[row_idx]}{cols[col_idx]}")
            col_idx += 1
            if col_idx >= 12:
                col_idx = 0
                row_idx += 1
                if row_idx >= 8:
                    row_idx = 0

    elif orientation == "column":
        # Column-wise: A1, B1, ..., H1, A2, B2, ..., H12
        for _ in range(num_cells):
            cells.append(f"{rows[row_idx]}{cols[col_idx]}")
            row_idx += 1
            if row_idx >= 8:
                row_idx = 0
                col_idx += 1
                if col_idx >= 12:
                    col_idx = 0

    elif orientation == "serpentine":
        # Serpentine (row-based): A1→A12, B12→B1, C1→C12, D12→D1, ...
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
        # Serpentine (column-based): A1→H1, H2→A2, A3→H3, H4→A4, ...
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
    # Look for continuous digit sequences
    patterns = [
        r"_(\d+)\.",  # _0002.csv
        r"_(\d+)$",   # _0002
        r"^(\d+)_",   # 0002_
        r"(\d+)",     # Any digits
    ]

    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            return int(match.group(1))

    return None


async def auto_match_acquisitions(
    experiment_id: int,
    file_list: list[str] | None,
    folders: list[dict] | None,
    first_cell: str | None,
    scan_orientation: str | None,
    seq_offset: int,
    use_plate_map: bool,
    use_run_sequence: bool,
    session: AsyncSession,
) -> list[dict]:
    """
    Comprehensive auto-match with folder batching, scan path, and factor mapping.
    """
    matched = []

    # Prepare file list with folder/batch info
    files_with_meta = []

    if folders:
        # Folder-based ingestion (Gap 1)
        for folder_idx, folder_data in enumerate(folders):
            folder_path = folder_data["folder_path"]
            batch_num = folder_data.get("batch_number", folder_idx + 1)

            for filename in folder_data["file_list"]:
                files_with_meta.append({
                    "filename": filename,
                    "folder": folder_path,
                    "batch": batch_num,
                })
    elif file_list:
        # Simple file list (detect folder from path)
        for filename in file_list:
            # Try to extract folder from full path
            if "/" in filename or "\\" in filename:
                parts = filename.replace("\\", "/").split("/")
                folder = parts[-2] if len(parts) > 1 else None
                filename_only = parts[-1]
            else:
                folder = None
                filename_only = filename

            files_with_meta.append({
                "filename": filename_only,
                "folder": folder,
                "batch": None,
            })
    else:
        return []

    # Load plate map if using scan path derivation
    plate_map = {}
    mixture_samples = {}

    if use_plate_map and first_cell and scan_orientation:
        # Gap 2: Scan-path derived cells - using eager loading to prevent N+1 queries
        stmt = (
            select(PlateWell)
            .where(PlateWell.experiment_id == experiment_id)
            .options(selectinload(PlateWell.mixture))
        )
        result = await session.execute(stmt)
        wells = result.scalars().all()

        for well in wells:
            if well.mixture_id:
                plate_map[well.well_position] = well.mixture_id

                # Mixture is already loaded via eager loading
                if well.mixture:
                    # Use mixture name (or mixture_id if name is not set)
                    mixture_samples[well.mixture_id] = well.mixture.name or well.mixture.mixture_id

    # Load run sequence for factor mapping (Gap 3)
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

            # Store factor values with unit if present
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

        # Assign sequence number based on GLOBAL index (Gap 4)
        # Use global idx to ensure seq continues across folders (1-40, 41-80, 81-121)
        # seq_offset allows adjusting the starting number (e.g., -1 to start from 1 for file_0002.csv)
        seq = idx + 1 + seq_offset

        # Extract timestamp
        timestamp_pattern = re.compile(r"(\d{8,14})")
        timestamp_match = timestamp_pattern.search(filename)
        timestamp = int(timestamp_match.group(1)) if timestamp_match else None

        # Determine cell and sample_id
        cell = None
        sample_id = None

        # Try filename pattern first
        cell_pattern = re.compile(r"([A-H][0-9]{1,2})", re.IGNORECASE)
        cell_match = cell_pattern.search(filename)

        if cell_match:
            cell = cell_match.group(1).upper()
        elif scan_cells and idx < len(scan_cells):
            # Use scan path (Gap 2)
            cell = scan_cells[idx]

        # Get sample_id from plate map
        if cell and cell in plate_map:
            mixture_id = plate_map[cell]
            sample_id = mixture_samples.get(mixture_id)

        # Get factor values (Gap 3)
        factor_values = {}

        if use_run_sequence and folder:
            # Try exact folder match first
            if folder in run_factors:
                factor_values = run_factors[folder].copy()
            # Try batch-based match
            elif batch and f"batch_{batch}" in run_factors:
                factor_values = run_factors[f"batch_{batch}"].copy()

        # Build date from timestamp
        date_str = None
        if timestamp:
            try:
                # Handle different timestamp formats
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

        matched.append({
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
        })

    return matched


@router.post("/match-acquisitions", response_model=list[MatchedAcquisitionSchema])
async def match_acquisitions(
    experiment_id: int,
    payload: MatchAcquisitionsRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[MatchedAcquisitionSchema]:
    """Auto-match acquisitions with comprehensive folder/scan/factor support"""
    await _verify_experiment_ownership(experiment_id, session, current_user)
    # Delete existing matched acquisitions
    stmt_delete = select(MatchedAcquisition).where(
        MatchedAcquisition.experiment_id == experiment_id
    )
    result = await session.execute(stmt_delete)
    existing = result.scalars().all()
    for acq in existing:
        await session.delete(acq)

    # Auto-match with all enhancements
    matched_data = await auto_match_acquisitions(
        experiment_id=experiment_id,
        file_list=payload.file_list,
        folders=[f.model_dump() for f in payload.folders] if payload.folders else None,
        first_cell=payload.first_cell,
        scan_orientation=payload.scan_orientation,
        seq_offset=payload.seq_offset,
        use_plate_map=payload.use_plate_map,
        use_run_sequence=payload.use_run_sequence,
        session=session,
    )

    acquisitions = []
    for data in matched_data:
        acq = MatchedAcquisition(experiment_id=experiment_id, **data)
        session.add(acq)
        acquisitions.append(acq)

    await session.commit()
    for acq in acquisitions:
        await session.refresh(acq)

    return [MatchedAcquisitionSchema.model_validate(a) for a in acquisitions]


@router.get("/matched-acquisitions", response_model=list[MatchedAcquisitionSchema])
async def get_matched_acquisitions(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[MatchedAcquisitionSchema]:
    """Get matched acquisitions"""
    await _verify_experiment_ownership(experiment_id, session, current_user)
    stmt = (
        select(MatchedAcquisition)
        .where(MatchedAcquisition.experiment_id == experiment_id)
        .order_by(MatchedAcquisition.seq)
    )
    result = await session.execute(stmt)
    acquisitions = result.scalars().all()
    return [MatchedAcquisitionSchema.model_validate(a) for a in acquisitions]


# ==================== Export ====================


@router.get("/export/csv")
async def export_doe_csv(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Export DOE design as CSV with dynamic factor columns"""
    if not await check_export_allowed(current_user):
        raise HTTPException(status_code=403, detail="Export not permitted for this user")
    await _verify_experiment_ownership(experiment_id, session, current_user)
    # Get matched acquisitions
    stmt = (
        select(MatchedAcquisition)
        .where(MatchedAcquisition.experiment_id == experiment_id)
        .order_by(MatchedAcquisition.seq)
    )
    result = await session.execute(stmt)
    acquisitions = result.scalars().all()

    if not acquisitions:
        raise HTTPException(status_code=404, detail="No matched acquisitions found")

    # Collect all unique factor names across all acquisitions
    all_factor_names = set()
    for acq in acquisitions:
        if acq.factor_values:
            all_factor_names.update(acq.factor_values.keys())

    # Build dynamic fieldnames
    base_fields = ["seq", "filename", "folder", "timestamp", "cell", "sample_id"]
    factor_fields = sorted(list(all_factor_names))  # Sort for consistent column order
    batch_field = ["batch"]
    all_fields = base_fields + factor_fields + batch_field

    # Generate CSV
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

        # Add factor values
        if acq.factor_values:
            for factor_name in factor_fields:
                row[factor_name] = acq.factor_values.get(factor_name, "")

        writer.writerow(row)

    from fastapi.responses import StreamingResponse

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=doe_export.csv"},
    )


@router.get("/export/json")
async def export_doe_json(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Export DOE design as JSON"""
    if not await check_export_allowed(current_user):
        raise HTTPException(status_code=403, detail="Export not permitted for this user")
    await _verify_experiment_ownership(experiment_id, session, current_user)

    # Get all DOE data
    samples = await list_samples(experiment_id, session, current_user)
    mixtures = await list_mixtures(experiment_id, session, current_user)
    factors = await list_factors(experiment_id, session, current_user)
    plate_map = await get_plate_map(experiment_id, session, current_user)
    run_sequence = await get_run_sequence(experiment_id, session, current_user)
    matched = await get_matched_acquisitions(experiment_id, session, current_user)

    export_data = {
        "experiment_id": experiment_id,
        "exported_at": datetime.utcnow().isoformat(),
        "samples": [s.model_dump() for s in samples],
        "mixtures": [m.model_dump() for m in mixtures],
        "factors": [f.model_dump() for f in factors],
        "plate_map": [p.model_dump() for p in plate_map],
        "run_sequence": [r.model_dump() for r in run_sequence],
        "matched_acquisitions": [m.model_dump() for m in matched],
    }

    from fastapi.responses import Response

    return Response(
        content=json.dumps(export_data, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=doe_export.json"},
    )


@router.get("/export/xml")
async def export_doe_xml(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Export DOE design as XML"""
    if not await check_export_allowed(current_user):
        raise HTTPException(status_code=403, detail="Export not permitted for this user")
    await _verify_experiment_ownership(experiment_id, session, current_user)

    # Get all DOE data
    samples = await list_samples(experiment_id, session, current_user)
    mixtures = await list_mixtures(experiment_id, session, current_user)
    factors = await list_factors(experiment_id, session, current_user)
    matched = await get_matched_acquisitions(experiment_id, session, current_user)

    # Build XML
    root = ET.Element("experiment")
    root.set("id", str(experiment_id))

    # Samples
    samples_elem = ET.SubElement(root, "samples")
    for sample in samples:
        s_elem = ET.SubElement(samples_elem, "sample")
        s_elem.set("id", sample.sample_id)
        ET.SubElement(s_elem, "name").text = sample.name
        if sample.type:
            ET.SubElement(s_elem, "type").text = sample.type
        if sample.brand:
            ET.SubElement(s_elem, "brand").text = sample.brand

    # Mixtures
    mixtures_elem = ET.SubElement(root, "mixtures")
    for mixture in mixtures:
        m_elem = ET.SubElement(mixtures_elem, "mixture")
        m_elem.set("id", mixture.mixture_id)
        ET.SubElement(m_elem, "basis").text = mixture.basis
        comps_elem = ET.SubElement(m_elem, "components")
        for comp in mixture.components:
            c_elem = ET.SubElement(comps_elem, "component")
            ET.SubElement(c_elem, "amount").text = str(comp.amount)
            ET.SubElement(c_elem, "unit").text = comp.unit

    # Factors
    factors_elem = ET.SubElement(root, "factors")
    for factor in factors:
        f_elem = ET.SubElement(factors_elem, "factor")
        ET.SubElement(f_elem, "name").text = factor.name
        ET.SubElement(f_elem, "scope").text = factor.scope
        ET.SubElement(f_elem, "type").text = factor.type

    # Matched acquisitions
    matched_elem = ET.SubElement(root, "matched_acquisitions")
    for acq in matched:
        a_elem = ET.SubElement(matched_elem, "acquisition")
        if acq.seq:
            ET.SubElement(a_elem, "seq").text = str(acq.seq)
        if acq.filename:
            ET.SubElement(a_elem, "filename").text = acq.filename
        if acq.batch:
            ET.SubElement(a_elem, "batch").text = str(acq.batch)

    # Pretty print
    xml_str = minidom.parseString(ET.tostring(root)).toprettyxml(indent="  ")

    from fastapi.responses import Response

    return Response(
        content=xml_str,
        media_type="application/xml",
        headers={"Content-Disposition": f"attachment; filename=doe_export.xml"},
    )


# ==================== Summary ====================


@router.get("/summary", response_model=DOESummary)
async def get_doe_summary(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> DOESummary:
    """Get DOE summary statistics"""
    await _verify_experiment_ownership(experiment_id, session, current_user)
    samples_count = await session.scalar(
        select(Sample).where(Sample.experiment_id == experiment_id)
    )
    mixtures_count = await session.scalar(
        select(Mixture).where(Mixture.experiment_id == experiment_id)
    )
    factors_count = await session.scalar(
        select(FactorDefinition).where(
            FactorDefinition.experiment_id == experiment_id
        )
    )
    wells_count = await session.scalar(
        select(PlateWell).where(PlateWell.experiment_id == experiment_id)
    )
    levels_count = await session.scalar(
        select(RunLevel).where(RunLevel.experiment_id == experiment_id)
    )
    matched_count = await session.scalar(
        select(MatchedAcquisition).where(
            MatchedAcquisition.experiment_id == experiment_id
        )
    )

    return DOESummary(
        sample_count=samples_count or 0,
        mixture_count=mixtures_count or 0,
        factor_count=factors_count or 0,
        well_count=wells_count or 0,
        run_level_count=levels_count or 0,
        matched_count=matched_count or 0,
    )
