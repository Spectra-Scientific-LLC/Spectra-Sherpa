"""Design of Experiments (DOE) routes — thin HTTP adapter."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import demo_guard, get_current_user, get_session
from spectra_sherpa.app.core.security import check_export_allowed
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.doe import (
    DOESummary,
    FactorDefinitionCreate,
    MatchAcquisitionsRequest,
    MixtureCreate,
    PlateMapRequest,
    RunSequenceRequest,
    SampleCreate,
    SampleImportRequest,
)
from spectra_sherpa.app.schemas.doe import (
    FactorDefinition as FactorDefinitionSchema,
)
from spectra_sherpa.app.schemas.doe import (
    MatchedAcquisition as MatchedAcquisitionSchema,
)
from spectra_sherpa.app.schemas.doe import (
    Mixture as MixtureSchema,
)
from spectra_sherpa.app.schemas.doe import (
    PlateWell as PlateWellSchema,
)
from spectra_sherpa.app.schemas.doe import (
    RunLevel as RunLevelSchema,
)
from spectra_sherpa.app.schemas.doe import (
    Sample as SampleSchema,
)
from spectra_sherpa.app.services import doe as doe_service
from spectra_sherpa.app.services.doe import ExperimentNotFoundError

router = APIRouter(prefix="/experiments/{experiment_id}/doe")


async def _verify(experiment_id: int, session: AsyncSession, current_user: User):
    """Ownership check — maps domain exception to HTTP 404."""
    try:
        return await doe_service.verify_experiment_ownership(session, experiment_id, current_user.id)
    except ExperimentNotFoundError:
        raise HTTPException(status_code=404, detail="Experiment not found")


# ==================== Sample Database ====================


@router.post("/samples/import", response_model=list[SampleSchema], dependencies=[Depends(demo_guard("data_upload"))])
async def import_samples(
    experiment_id: int,
    payload: SampleImportRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[SampleSchema]:
    """Import samples from CSV (metadata only)"""
    await _verify(experiment_id, session, current_user)
    try:
        samples = await doe_service.import_samples(session, experiment_id, payload.csv_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [SampleSchema.model_validate(s) for s in samples]


@router.get("/samples", response_model=list[SampleSchema])
async def list_samples(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[SampleSchema]:
    """List samples for experiment"""
    await _verify(experiment_id, session, current_user)
    samples = await doe_service.list_samples(session, experiment_id)
    return [SampleSchema.model_validate(s) for s in samples]


@router.post("/samples", response_model=SampleSchema)
async def create_sample(
    experiment_id: int,
    payload: SampleCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> SampleSchema:
    """Create a single sample"""
    await _verify(experiment_id, session, current_user)
    sample = await doe_service.create_sample(session, experiment_id, payload.model_dump())
    return SampleSchema.model_validate(sample)


# ==================== Mixtures ====================


@router.get("/mixtures", response_model=list[MixtureSchema])
async def list_mixtures(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[MixtureSchema]:
    """List mixtures for experiment"""
    await _verify(experiment_id, session, current_user)
    mixtures = await doe_service.list_mixtures(session, experiment_id)
    return [MixtureSchema.model_validate(m) for m in mixtures]


@router.post("/mixtures", response_model=MixtureSchema)
async def create_mixture(
    experiment_id: int,
    payload: MixtureCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> MixtureSchema:
    """Create mixture with components"""
    await _verify(experiment_id, session, current_user)
    mixture_dict = await doe_service.create_mixture(
        session,
        experiment_id,
        mixture_id=payload.mixture_id,
        name=payload.name,
        basis=payload.basis,
        notes=payload.notes,
        components=[c.model_dump() for c in payload.components],
    )
    return MixtureSchema.model_validate(mixture_dict)


# ==================== Factor Definitions ====================


@router.get("/factors", response_model=list[FactorDefinitionSchema])
async def list_factors(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[FactorDefinitionSchema]:
    """List factor definitions for experiment"""
    await _verify(experiment_id, session, current_user)
    factors = await doe_service.list_factors(session, experiment_id)
    return [FactorDefinitionSchema.model_validate(f) for f in factors]


@router.post("/factors", response_model=FactorDefinitionSchema)
async def create_factor(
    experiment_id: int,
    payload: FactorDefinitionCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FactorDefinitionSchema:
    """Create factor definition"""
    await _verify(experiment_id, session, current_user)
    factor = await doe_service.create_factor(session, experiment_id, payload.model_dump())
    return FactorDefinitionSchema.model_validate(factor)


# ==================== Plate Map ====================


@router.get("/plate-map", response_model=list[PlateWellSchema])
async def get_plate_map(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[PlateWellSchema]:
    """Get 96-well plate map"""
    await _verify(experiment_id, session, current_user)
    wells = await doe_service.get_plate_map(session, experiment_id)
    return [PlateWellSchema.model_validate(w) for w in wells]


@router.post("/plate-map", response_model=list[PlateWellSchema])
async def set_plate_map(
    experiment_id: int,
    payload: PlateMapRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[PlateWellSchema]:
    """Set 96-well plate map (bulk operation)"""
    await _verify(experiment_id, session, current_user)
    wells = await doe_service.set_plate_map(session, experiment_id, [w.model_dump() for w in payload.wells])
    return [PlateWellSchema.model_validate(w) for w in wells]


# ==================== Run Sequence ====================


@router.get("/run-sequence", response_model=list[RunLevelSchema])
async def get_run_sequence(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[RunLevelSchema]:
    """Get run sequence"""
    await _verify(experiment_id, session, current_user)
    levels = await doe_service.get_run_sequence(session, experiment_id)
    return [RunLevelSchema.model_validate(l) for l in levels]


@router.post("/run-sequence", response_model=list[RunLevelSchema])
async def set_run_sequence(
    experiment_id: int,
    payload: RunSequenceRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[RunLevelSchema]:
    """Set run sequence (manual entry)"""
    await _verify(experiment_id, session, current_user)
    levels = await doe_service.set_run_sequence(session, experiment_id, [l.model_dump() for l in payload.levels])
    return [RunLevelSchema.model_validate(l) for l in levels]


# ==================== Acquisition Matching ====================


@router.post("/match-acquisitions", response_model=list[MatchedAcquisitionSchema])
async def match_acquisitions(
    experiment_id: int,
    payload: MatchAcquisitionsRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[MatchedAcquisitionSchema]:
    """Auto-match acquisitions with comprehensive folder/scan/factor support"""
    await _verify(experiment_id, session, current_user)
    acquisitions = await doe_service.match_and_save_acquisitions(
        session,
        experiment_id,
        file_list=payload.file_list,
        folders=[f.model_dump() for f in payload.folders] if payload.folders else None,
        first_cell=payload.first_cell,
        scan_orientation=payload.scan_orientation,
        seq_offset=payload.seq_offset,
        use_plate_map=payload.use_plate_map,
        use_run_sequence=payload.use_run_sequence,
    )
    return [MatchedAcquisitionSchema.model_validate(a) for a in acquisitions]


@router.get("/matched-acquisitions", response_model=list[MatchedAcquisitionSchema])
async def get_matched_acquisitions(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[MatchedAcquisitionSchema]:
    """Get matched acquisitions"""
    await _verify(experiment_id, session, current_user)
    acquisitions = await doe_service.get_matched_acquisitions(session, experiment_id)
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
    await _verify(experiment_id, session, current_user)

    acquisitions = await doe_service.get_matched_acquisitions(session, experiment_id)
    if not acquisitions:
        raise HTTPException(status_code=404, detail="No matched acquisitions found")

    csv_content = doe_service.export_csv(acquisitions)
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=doe_export.csv"},
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
    await _verify(experiment_id, session, current_user)

    export_data = await doe_service.build_export_data(session, experiment_id)
    json_content = doe_service.export_json(export_data)
    return Response(
        content=json_content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=doe_export.json"},
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
    await _verify(experiment_id, session, current_user)

    export_data = await doe_service.build_export_data(session, experiment_id)
    xml_content = doe_service.export_xml(
        experiment_id=experiment_id,
        samples=export_data["samples"],
        mixtures=export_data["mixtures"],
        factors=export_data["factors"],
        matched=export_data["matched_acquisitions"],
    )
    return Response(
        content=xml_content,
        media_type="application/xml",
        headers={"Content-Disposition": "attachment; filename=doe_export.xml"},
    )


# ==================== Summary ====================


@router.get("/summary", response_model=DOESummary)
async def get_doe_summary(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> DOESummary:
    """Get DOE summary statistics"""
    await _verify(experiment_id, session, current_user)
    summary = await doe_service.get_summary(session, experiment_id)
    return DOESummary(**summary)
