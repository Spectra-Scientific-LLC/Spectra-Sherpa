from __future__ import annotations

import asyncio
import csv
from pathlib import Path
from typing import Literal

import httpx
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session, require_project
from spectra_sherpa.app.core.config import app_config, settings
from spectra_sherpa.app.core.security import check_egress_permission, check_export_allowed
from spectra_sherpa.app.db.session import async_session
from spectra_sherpa.app.models.api_key import APIKey
from spectra_sherpa.app.models.background_job import BackgroundJob
from spectra_sherpa.app.models.data_egress import EgressDestination
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.nist_library import NistLibrary
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.synthesis import SynthesisSpectrumResponse
from spectra_sherpa.app.services import synthesis as synthesis_service
from spectra_sherpa.app.services.audit import audit_excluded
from spectra_sherpa.app.services.dataset_registry import dataset_registry
from spectra_sherpa.app.services.encryption import decrypt_value
from spectra_sherpa.app.services.experiments import add_experiment_file, experiment_dir
from spectra_sherpa.app.services.file_storage import FileValidationError, sanitize_filename
from spectra_sherpa.app.services.job_manager import job_manager
from spectra_sherpa.app.services.prepared_data import PreparedDataOverrides, save_prepared_data_overrides
from spectra_sherpa.app.services.synthesis import SynthesisError


def _resolve_handle_or_raise(dataset_id: str, current_user: User):
    """Resolve a dataset handle with ownership checks."""
    user_id = current_user.id if current_user is not None else None
    try:
        return dataset_registry.get(dataset_id, user_id=user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Dataset is not accessible for this user") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Dataset handle not found: {dataset_id}") from exc


class ExperimentDataset(BaseModel):
    id: int
    name: str
    description: str | None
    project_id: int | None = None
    stages: dict[str, list[dict]]


class LibraryDataset(BaseModel):
    id: int
    compound_name: str
    cas_number: str
    resolution: str | None
    file_path: str


class AvailableDatasetsResponse(BaseModel):
    experiments: list[ExperimentDataset]
    library: list[LibraryDataset]
    builder: list[dict]


class LibraryComponentSpec(BaseModel):
    component_id: str
    resolution_cm1: float | None = None
    wavenumber_min: float | None = None
    wavenumber_max: float | None = None
    temperature_k: float | None = None
    pressure_atm: float | None = None


class LoadedLibrarySpectrum(BaseModel):
    component_id: str
    name: str
    source: str
    wavenumber: list[float] = Field(min_length=2, max_length=50_000)
    intensity: list[float] = Field(min_length=2, max_length=50_000)
    y_quantity: str = "Intensity"
    y_units: str | None = None
    resolution_cm1: float | None = None
    apodization: str | None = None


class LibraryImportRequest(BaseModel):
    experiment_id: int
    source: Literal["nist", "nist_quant_ir", "hitran", "hitran_xsec"] = "nist"
    library_ids: list[int] = []
    component_ids: list[str] = []
    component_specs: list[LibraryComponentSpec] = Field(default_factory=list)
    spectra: list[LoadedLibrarySpectrum] = Field(default_factory=list)
    range_mode: Literal["common", "widest"] = "widest"
    resolution_cm1: float | None = None
    apodization: str | None = None
    wavenumber_min: float | None = None
    wavenumber_max: float | None = None
    temperature_k: float = 293.0
    pressure_atm: float = 1.0


class LibraryImportResponse(BaseModel):
    imported: int
    files: list[int]
    job_id: int | None = None
    queued: bool = False
    message: str | None = None
    failures: list[str] = Field(default_factory=list)


router = APIRouter(prefix="/datasets")
_HITRAN_LIBRARY_SOURCES = {"hitran", "hitran_xsec"}
MAX_NIST_LIBRARY_IMPORT_COUNT = 500


def _unique_destination_path(destination_dir: Path, filename: str) -> Path:
    destination = (destination_dir / filename).resolve()
    if not destination.is_relative_to(destination_dir.resolve()):
        raise FileValidationError("Invalid destination path")
    if not destination.exists():
        return destination

    stem = destination.stem
    suffix = destination.suffix
    for index in range(1, 1000):
        candidate = (destination_dir / f"{stem}_{index}{suffix}").resolve()
        if not candidate.is_relative_to(destination_dir.resolve()):
            raise FileValidationError("Invalid destination path")
        if not candidate.exists():
            return candidate
    raise FileValidationError(f"Could not create a unique filename for {filename}")


def _library_source_path(relative_path: str) -> Path:
    source = (settings.data_dir / relative_path).resolve()
    library_root = (settings.data_dir / "nist_library").resolve()
    if not source.is_relative_to(library_root):
        raise HTTPException(status_code=400, detail="Library path is outside the NIST library")
    if not source.exists() or not source.is_file():
        raise HTTPException(status_code=404, detail="Library file is missing from storage")
    return source


async def _stored_api_key(session: AsyncSession, current_user: User, service_name: str) -> str | None:
    return await _stored_api_key_for_user(session, current_user.id, service_name)


async def _stored_api_key_for_user(session: AsyncSession, user_id: int, service_name: str) -> str | None:
    record = (
        await session.execute(
            select(APIKey).where(APIKey.user_id == user_id, APIKey.service_name == service_name).limit(1)
        )
    ).scalar_one_or_none()
    if record is None:
        return None
    return decrypt_value(record.key_encrypted)


async def _check_library_egress(
    current_user: User,
    permission: str,
    destination: str,
    session: AsyncSession,
) -> bool:
    return await check_egress_permission(
        current_user,
        permission,
        destination=destination,
        session=session,
        skip_global_check=app_config.mode == "local",
    )


class _LibrarySpectrum(BaseModel):
    component_id: str
    name: str
    source: str
    x: list[float]
    y: list[float]
    x_title: str = "Wavenumber"
    x_units: str | None = "cm-1"
    y_title: str = "Intensity"
    y_units: str | None = None
    metadata: dict[str, str | int | float | None] = Field(default_factory=dict)


def _axis_title_from_units(units: str | None, *, fallback: str = "Wavenumber") -> str:
    text = (units or "").lower()
    if "nm" in text or "micrometer" in text or "um" in text or "µm" in text:
        return "Wavelength"
    return fallback


def _load_nist_library_spectrum(entry: NistLibrary) -> _LibrarySpectrum:
    from spectra_sherpa.app.lib.jcamp_reader import read_jcamp

    source = _library_source_path(entry.file_path)
    jcamp = read_jcamp(str(source))
    yunits = jcamp.yunits or "Intensity"
    yunits_lower = yunits.lower()
    if "transmit" in yunits_lower:
        y_title = "Transmittance"
    elif "absorb" in yunits_lower:
        y_title = "Absorbance"
    else:
        y_title = yunits
    axis_title = _axis_title_from_units(jcamp.xunits, fallback="Wavenumber")
    return _LibrarySpectrum(
        component_id=f"nist:{entry.id}",
        name=entry.compound_name,
        source="nist",
        x=np.asarray(jcamp.x, dtype=float).tolist(),
        y=np.asarray(jcamp.y, dtype=float).tolist(),
        x_title=axis_title,
        x_units=jcamp.xunits or None,
        y_title=y_title,
        y_units=yunits,
        metadata={
            "library_id": entry.id,
            "cas_number": entry.cas_number,
            "resolution": entry.resolution,
            "source_file": entry.file_path,
        },
    )


def _nist_import_failure(entry: NistLibrary, exc: Exception) -> str:
    detail = getattr(exc, "detail", None) or str(exc)
    return f"{entry.compound_name} ({entry.cas_number}): {type(exc).__name__}: {detail}"


def _load_nist_library_spectra(entries: list[NistLibrary]) -> tuple[list[_LibrarySpectrum], list[str]]:
    spectra: list[_LibrarySpectrum] = []
    failures: list[str] = []
    for entry in entries:
        try:
            spectra.append(_load_nist_library_spectrum(entry))
        except Exception as exc:
            failures.append(_nist_import_failure(entry, exc))
    return spectra, failures


@router.get("/library/{library_id}/spectrum")
async def get_nist_library_spectrum(
    library_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> _LibrarySpectrum:
    """Return a stored NIST library spectrum for source-side preview."""
    result = await session.execute(select(NistLibrary).where(NistLibrary.id == library_id))
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="NIST library entry not found")
    return _load_nist_library_spectrum(entry)


def _monotonic_xy(spectrum: _LibrarySpectrum) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(spectrum.x, dtype=float)
    y = np.asarray(spectrum.y, dtype=float)
    if x.shape != y.shape or x.size < 2:
        raise HTTPException(status_code=400, detail=f"Library spectrum '{spectrum.name}' is not a 1D spectrum")
    finite = np.isfinite(x) & np.isfinite(y)
    x = x[finite]
    y = y[finite]
    if x.size < 2:
        raise HTTPException(status_code=400, detail=f"Library spectrum '{spectrum.name}' has no finite points")
    if x[0] > x[-1]:
        x = x[::-1]
        y = y[::-1]
    order = np.argsort(x)
    x = x[order]
    y = y[order]
    unique_x, unique_indices = np.unique(x, return_index=True)
    return unique_x, y[unique_indices]


def _library_common_grid(
    spectra: list[_LibrarySpectrum],
    *,
    range_mode: str,
) -> tuple[np.ndarray, list[np.ndarray]]:
    arrays = [_monotonic_xy(spectrum) for spectrum in spectra]
    spacings = [
        float(np.nanmedian(np.abs(np.diff(x))))
        for x, _ in arrays
        if x.size > 1 and np.nanmedian(np.abs(np.diff(x))) > 0
    ]
    if not spacings:
        raise HTTPException(status_code=400, detail="Selected library spectra do not define an x-axis spacing")
    step = min(spacings)
    if range_mode == "common":
        x_min = max(float(x[0]) for x, _ in arrays)
        x_max = min(float(x[-1]) for x, _ in arrays)
        if not x_min < x_max:
            raise HTTPException(status_code=400, detail="Selected library spectra have no common x-axis overlap")
    else:
        x_min = min(float(x[0]) for x, _ in arrays)
        x_max = max(float(x[-1]) for x, _ in arrays)

    n_points = int(np.floor((x_max - x_min) / step)) + 1
    if n_points < 2:
        raise HTTPException(status_code=400, detail="Library x-axis grid has fewer than two points")
    if n_points > 50_000:
        raise HTTPException(
            status_code=400,
            detail="Library x-axis grid would exceed 50,000 points. Use a wider resolution or narrower range.",
        )
    grid = x_min + np.arange(n_points, dtype=float) * step

    aligned = [np.interp(grid, x, y, left=np.nan, right=np.nan) for x, y in arrays]
    return grid, aligned


def _library_spectrum_spacing(spectrum: _LibrarySpectrum) -> float:
    try:
        x, _ = _monotonic_xy(spectrum)
    except HTTPException:
        return float("inf")
    if x.size < 2:
        return float("inf")
    spacing = float(np.nanmedian(np.abs(np.diff(x))))
    return spacing if np.isfinite(spacing) and spacing > 0 else float("inf")


def _write_library_csv(
    destination: Path,
    *,
    x: np.ndarray,
    y: np.ndarray,
    spectrum: _LibrarySpectrum,
) -> None:
    axis_header = spectrum.x_title
    if spectrum.x_units:
        axis_header = f"{axis_header} ({spectrum.x_units})"
    label = spectrum.name
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([axis_header, label])
        for x_value, y_value in zip(x, y, strict=True):
            writer.writerow([f"{float(x_value):.12g}", "" if not np.isfinite(y_value) else f"{float(y_value):.12g}"])


def _library_spectrum_for_saved_file(
    spectrum: _LibrarySpectrum,
    y_values: np.ndarray,
) -> tuple[_LibrarySpectrum, np.ndarray]:
    if spectrum.source not in _HITRAN_LIBRARY_SOURCES:
        return spectrum, y_values

    if spectrum.y_units and not synthesis_service.is_hitran_cross_section_units(spectrum.y_units):
        return spectrum, y_values

    converted = synthesis_service.hitran_cross_section_to_molar_absorptivity(y_values)
    metadata = dict(spectrum.metadata)
    metadata["saved_y_quantity"] = "Molar absorption coefficient"
    metadata["saved_y_units"] = synthesis_service.MOLAR_ABSORPTION_COEFFICIENT_UNITS
    if spectrum.y_units:
        metadata["source_y_units"] = spectrum.y_units
    return (
        spectrum.model_copy(
            update={
                "y_title": "Molar absorption coefficient",
                "y_units": synthesis_service.MOLAR_ABSORPTION_COEFFICIENT_UNITS,
                "metadata": metadata,
            }
        ),
        converted,
    )


async def _write_library_spectra_to_experiment(
    *,
    session: AsyncSession,
    experiment_id: int,
    spectra: list[_LibrarySpectrum],
    range_mode: str,
) -> list[ExperimentFile]:
    if not spectra:
        raise HTTPException(status_code=400, detail="No library spectra selected")
    x_grid, aligned = _library_common_grid(spectra, range_mode=range_mode)

    raw_dir = experiment_dir(experiment_id) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    created: list[ExperimentFile] = []

    try:
        for spectrum, y_values in zip(spectra, aligned, strict=True):
            spectrum, y_values = _library_spectrum_for_saved_file(spectrum, y_values)
            base_name = sanitize_filename(f"library_{spectrum.source}_{spectrum.name}.csv")
            destination = _unique_destination_path(raw_dir, base_name)
            _write_library_csv(destination, x=x_grid, y=y_values, spectrum=spectrum)
            copied.append(destination)
            save_prepared_data_overrides(
                PreparedDataOverrides(
                    title=spectrum.name,
                    x_title=spectrum.x_title,
                    x_units=spectrum.x_units,
                    y_title=spectrum.y_title,
                    y_units=spectrum.y_units,
                    data_role="X_spectra",
                ),
                file_path=str(destination.resolve()),
            )

            rel_path = destination.relative_to(experiment_dir(experiment_id)).as_posix()
            created.append(
                await add_experiment_file(
                    session=session,
                    experiment_id=experiment_id,
                    stage="raw",
                    file_path=rel_path,
                    file_size_bytes=destination.stat().st_size,
                    file_type="csv",
                    flush_only=True,
                )
            )

        await session.commit()
    except FileValidationError as exc:
        await session.rollback()
        for path in copied:
            if path.exists():
                path.unlink()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BaseException:
        await session.rollback()
        for path in copied:
            if path.exists():
                path.unlink()
        raise

    for file_record in created:
        await session.refresh(file_record)

    return created


async def _write_nist_library_spectra_to_experiment(
    *,
    session: AsyncSession,
    experiment_id: int,
    spectra: list[_LibrarySpectrum],
    range_mode: str,
) -> tuple[list[ExperimentFile], list[str]]:
    remaining = list(spectra)
    skipped: list[str] = []

    while remaining:
        try:
            return (
                await _write_library_spectra_to_experiment(
                    session=session,
                    experiment_id=experiment_id,
                    spectra=remaining,
                    range_mode=range_mode,
                ),
                skipped,
            )
        except HTTPException as exc:
            detail = str(exc.detail)
            if exc.status_code != 400 or "50,000" not in detail or len(remaining) <= 1:
                raise
            spacings = [_library_spectrum_spacing(spectrum) for spectrum in remaining]
            drop_index = int(np.nanargmin(spacings))
            dropped = remaining.pop(drop_index)
            skipped.append(f"{dropped.name}: skipped because the combined library grid would exceed 50,000 points")

    detail = "; ".join(skipped[:3]) if skipped else "No NIST spectra were loaded"
    raise HTTPException(status_code=400, detail=f"NIST library import failed: {detail}")


def _hitran_spectrum_from_response(
    response: SynthesisSpectrumResponse,
    *,
    temperature_k: float,
    pressure_atm: float,
) -> _LibrarySpectrum:
    return _LibrarySpectrum(
        component_id=response.component_id,
        name=response.name,
        source=response.source,
        x=response.wavenumber,
        y=response.intensity,
        x_title="Wavenumber",
        x_units="cm-1",
        y_title=response.y_quantity,
        y_units=response.y_units,
        metadata={
            "component_id": response.component_id,
            "resolution_cm1": response.resolution_cm1,
            "temperature_k": temperature_k,
            "pressure_atm": pressure_atm,
            **response.metadata,
        },
    )


def _library_spectrum_from_loaded_payload(payload: LoadedLibrarySpectrum) -> _LibrarySpectrum:
    x = np.asarray(payload.wavenumber, dtype=float)
    y = np.asarray(payload.intensity, dtype=float)
    if x.size != y.size:
        raise HTTPException(
            status_code=400,
            detail=f"Loaded spectrum {payload.name!r} has mismatched wavenumber/intensity lengths",
        )
    if x.size < 2:
        raise HTTPException(status_code=400, detail=f"Loaded spectrum {payload.name!r} has fewer than two points")
    if not np.all(np.isfinite(x)):
        raise HTTPException(status_code=400, detail=f"Loaded spectrum {payload.name!r} has invalid wavenumbers")
    if not np.any(np.isfinite(y)):
        raise HTTPException(status_code=400, detail=f"Loaded spectrum {payload.name!r} has no finite intensity values")
    return _LibrarySpectrum(
        component_id=payload.component_id,
        name=payload.name,
        source=payload.source,
        x=x.tolist(),
        y=y.tolist(),
        x_title="Wavenumber",
        x_units="cm-1",
        y_title=payload.y_quantity or "Intensity",
        y_units=payload.y_units,
        metadata={
            "component_id": payload.component_id,
            "source": payload.source,
            "resolution_cm1": payload.resolution_cm1,
            "apodization": payload.apodization,
            "payload": "loaded_spectrum",
        },
    )


def _library_component_specs_from_payload(payload: LibraryImportRequest) -> list[LibraryComponentSpec]:
    raw_specs = payload.component_specs or [
        LibraryComponentSpec(component_id=component_id) for component_id in payload.component_ids
    ]
    specs: list[LibraryComponentSpec] = []
    seen: set[tuple[object, ...]] = set()
    for raw in raw_specs:
        component_id = raw.component_id.strip()
        if not component_id:
            continue
        spec = LibraryComponentSpec(
            component_id=component_id,
            resolution_cm1=raw.resolution_cm1 if raw.resolution_cm1 is not None else payload.resolution_cm1,
            wavenumber_min=raw.wavenumber_min if raw.wavenumber_min is not None else payload.wavenumber_min,
            wavenumber_max=raw.wavenumber_max if raw.wavenumber_max is not None else payload.wavenumber_max,
            temperature_k=raw.temperature_k if raw.temperature_k is not None else payload.temperature_k,
            pressure_atm=raw.pressure_atm if raw.pressure_atm is not None else payload.pressure_atm,
        )
        key = (
            spec.component_id,
            spec.resolution_cm1,
            spec.wavenumber_min,
            spec.wavenumber_max,
            spec.temperature_k,
            spec.pressure_atm,
        )
        if key in seen:
            continue
        seen.add(key)
        specs.append(spec)
    return specs


async def _run_hitran_library_import_job(
    *,
    job_id: int,
    user_id: int,
    experiment_id: int,
    source: str,
    component_specs: list[LibraryComponentSpec],
    loaded_spectra: list[_LibrarySpectrum] | None = None,
    range_mode: str,
) -> None:
    async with async_session() as session:
        experiment = (
            await session.execute(
                select(Experiment).where(Experiment.id == experiment_id, Experiment.user_id == user_id)
            )
        ).scalar_one_or_none()
        if experiment is None:
            raise SynthesisError("Experiment was deleted before HITRAN import could run")

        api_key = await _stored_api_key_for_user(session, user_id, "hitran")
        if not api_key:
            raise SynthesisError("HITRAN library import requires a HITRAN API key. Add it in Settings > API Keys.")

    spectra: list[_LibrarySpectrum] = list(loaded_spectra or [])
    failures: list[str] = []
    total = len(component_specs)

    for index, spec in enumerate(component_specs, start=1):
        try:
            summary = synthesis_service.get_component_summary(source, spec.component_id)
            label = summary.name
        except SynthesisError:
            label = spec.component_id
        async with async_session() as progress_session:
            await job_manager.update_progress(
                progress_session,
                job_id,
                max(1, int(((index - 1) / max(total, 1)) * 85)),
                f"Loading {index}/{total}: {label}",
            )
        try:
            response = await synthesis_service.get_component_spectrum(
                source,
                spec.component_id,
                resolution_cm1=spec.resolution_cm1,
                wavenumber_min=spec.wavenumber_min,
                wavenumber_max=spec.wavenumber_max,
                temperature_k=spec.temperature_k or 293.0,
                pressure_atm=spec.pressure_atm or 1.0,
                hitran_api_key=api_key,
            )
            spectra.append(
                _hitran_spectrum_from_response(
                    response,
                    temperature_k=spec.temperature_k or 293.0,
                    pressure_atm=spec.pressure_atm or 1.0,
                )
            )
        except (httpx.HTTPStatusError, SynthesisError) as exc:
            failures.append(f"{label}: {exc}")

    if not spectra:
        detail = "; ".join(failures[:3]) if failures else "No HITRAN spectra were generated"
        raise SynthesisError(f"HITRAN library import failed: {detail}")

    async with async_session() as write_session:
        await job_manager.update_progress(write_session, job_id, 90, "Writing imported HITRAN spectra")
        created = await _write_library_spectra_to_experiment(
            session=write_session,
            experiment_id=experiment_id,
            spectra=spectra,
            range_mode=range_mode,
        )

    if failures:
        message = f"Imported {len(created)} of {total} HITRAN spectra; failed {len(failures)}."
    else:
        message = f"Imported {len(created)} HITRAN spectra."
    async with async_session() as done_session:
        await job_manager.update_progress(done_session, job_id, 99, message)


def _experiment_file_payload(file_record: ExperimentFile) -> dict:
    payload = {
        "id": file_record.id,
        "file_path": file_record.file_path,
        "file_type": file_record.file_type,
        "file_size_bytes": file_record.file_size_bytes,
    }

    file_type = (file_record.file_type or "").lower()
    if file_type != "csv" and not file_record.file_path.lower().endswith(".csv"):
        return payload

    try:
        from spectra_sherpa.app.lib.io import load_csv_as_sherpa

        dataset = load_csv_as_sherpa(experiment_dir(file_record.experiment_id) / file_record.file_path)
        feature_axis = getattr(dataset, "feature_axis", None)
        payload.update(
            {
                "shape": list(dataset.shape),
                "n_samples": dataset.n_samples,
                "n_features": dataset.n_features,
                "data_role": dataset.data_role,
                "x_title": getattr(feature_axis, "title", None),
                "x_units": getattr(feature_axis, "units", None),
                "is_spectra": dataset.data_role == "X_spectra",
            }
        )
    except Exception:
        pass

    return payload


@router.get("/available", response_model=AvailableDatasetsResponse)
async def list_available_datasets(
    project_id: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AvailableDatasetsResponse:
    """
    Return all available datasets grouped by source for the workflow builder.

    Structure:
    - experiments: List of experiments with files grouped by stage (raw/preprocessed/synthetic)
    - library: List of NIST library entries (user-owned only)
    - builder: Placeholder for saved builder outputs (future feature)
    """
    if project_id is not None:
        await require_project(project_id, current_user.id, session)

    # Get experiments owned by current user
    experiments_query = select(Experiment).where(Experiment.user_id == current_user.id)
    if project_id is not None:
        experiments_query = experiments_query.where(Experiment.project_id == project_id)
    experiments_result = await session.execute(experiments_query.order_by(Experiment.created_at.desc()))
    experiments = list(experiments_result.scalars())

    experiment_datasets: list[ExperimentDataset] = []
    for exp in experiments:
        # Get files grouped by stage for this experiment
        files_result = await session.execute(
            select(ExperimentFile)
            .where(ExperimentFile.experiment_id == exp.id)
            .order_by(ExperimentFile.stage, ExperimentFile.file_path)
        )
        files = list(files_result.scalars())

        # Group files by stage
        stages: dict[str, list[dict]] = {"raw": [], "preprocessed": [], "synthetic": []}
        for file in files:
            if file.stage in stages:
                stages[file.stage].append(_experiment_file_payload(file))

        experiment_datasets.append(
            ExperimentDataset(
                id=exp.id,
                name=exp.name,
                description=exp.description,
                project_id=exp.project_id,
                stages=stages,
            )
        )

    # Get all library entries (NIST library is shared, not per-user)
    library_result = await session.execute(select(NistLibrary).order_by(NistLibrary.compound_name))
    library_entries = list(library_result.scalars())

    library_datasets = [
        LibraryDataset(
            id=entry.id,
            compound_name=entry.compound_name,
            cas_number=entry.cas_number,
            resolution=entry.resolution,
            file_path=entry.file_path,
        )
        for entry in library_entries
    ]

    return AvailableDatasetsResponse(
        experiments=experiment_datasets,
        library=library_datasets,
        builder=[],  # Placeholder for future builder outputs
    )


@router.post("/library/import", response_model=LibraryImportResponse)
async def import_library_datasets(
    payload: LibraryImportRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> LibraryImportResponse:
    """Copy shared library spectra into a user's My Dataset experiment."""
    experiment_result = await session.execute(
        select(Experiment).where(Experiment.id == payload.experiment_id, Experiment.user_id == current_user.id)
    )
    experiment = experiment_result.scalar_one_or_none()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    source = "nist" if payload.source == "nist_quant_ir" else payload.source
    spectra: list[_LibrarySpectrum] = []
    failures: list[str] = []

    if source == "nist":
        if not payload.library_ids:
            raise HTTPException(status_code=400, detail="At least one NIST library entry is required")
        unique_ids = list(dict.fromkeys(payload.library_ids))
        if len(unique_ids) > MAX_NIST_LIBRARY_IMPORT_COUNT:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"NIST library import supports at most {MAX_NIST_LIBRARY_IMPORT_COUNT} spectra per request. "
                    "Import a smaller basket or split the selection."
                ),
            )
        library_result = await session.execute(select(NistLibrary).where(NistLibrary.id.in_(unique_ids)))
        entries = list(library_result.scalars())
        if len(entries) != len(unique_ids):
            found = {entry.id for entry in entries}
            missing = [entry_id for entry_id in unique_ids if entry_id not in found]
            raise HTTPException(status_code=404, detail=f"Library entries not found: {missing}")
        entry_by_id = {entry.id: entry for entry in entries}
        ordered_entries = [entry_by_id[entry_id] for entry_id in unique_ids]
        spectra, failures = await asyncio.to_thread(_load_nist_library_spectra, ordered_entries)
        if not spectra:
            detail = "; ".join(failures[:3]) if failures else "No NIST spectra were loaded"
            raise HTTPException(status_code=400, detail=f"NIST library import failed: {detail}")
    elif source in _HITRAN_LIBRARY_SOURCES:
        component_specs = _library_component_specs_from_payload(payload)
        spectra.extend(_library_spectrum_from_loaded_payload(item) for item in payload.spectra)
        supplied_component_ids = {item.component_id for item in payload.spectra}
        component_specs = [spec for spec in component_specs if spec.component_id not in supplied_component_ids]
        if not component_specs and not spectra:
            raise HTTPException(status_code=400, detail="At least one HITRAN species is required")
        cached_checks: list[bool] = []
        for spec in component_specs:
            try:
                cached_checks.append(
                    synthesis_service.is_component_spectrum_cached(
                        source,
                        spec.component_id,
                        resolution_cm1=spec.resolution_cm1,
                        wavenumber_min=spec.wavenumber_min,
                        wavenumber_max=spec.wavenumber_max,
                        temperature_k=spec.temperature_k or payload.temperature_k,
                        pressure_atm=spec.pressure_atm or payload.pressure_atm,
                    )
                )
            except SynthesisError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        hitran_api_key: str | None = None
        if component_specs and not all(cached_checks):
            allowed = await _check_library_egress(
                current_user,
                "allow_hitran_queries",
                destination=EgressDestination.HITRAN,
                session=session,
            )
            if not allowed:
                raise HTTPException(status_code=403, detail="HITRAN library import requires HITRAN egress permission")
            hitran_api_key = await _stored_api_key(session, current_user, "hitran")
            if not hitran_api_key:
                raise HTTPException(
                    status_code=400,
                    detail="HITRAN library import requires a HITRAN API key. Add it in Settings > API Keys.",
                )
            job = BackgroundJob(
                user_id=current_user.id,
                job_type="library_import_hitran",
                status="pending",
                progress_message=f"{len(component_specs)} HITRAN spectra queued",
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id
            user_id = current_user.id

            async def _work() -> None:
                await _run_hitran_library_import_job(
                    job_id=job_id,
                    user_id=user_id,
                    experiment_id=payload.experiment_id,
                    source=source,
                    component_specs=component_specs,
                    loaded_spectra=spectra,
                    range_mode=payload.range_mode,
                )

            asyncio.create_task(job_manager.run_job(job_id, _work))
            return LibraryImportResponse(
                imported=0,
                files=[],
                job_id=job_id,
                queued=True,
                message=f"{len(component_specs)} HITRAN spectra queued for import",
            )

        for spec in component_specs:
            try:
                response = await synthesis_service.get_component_spectrum(
                    source,
                    spec.component_id,
                    resolution_cm1=spec.resolution_cm1,
                    wavenumber_min=spec.wavenumber_min,
                    wavenumber_max=spec.wavenumber_max,
                    temperature_k=spec.temperature_k or payload.temperature_k,
                    pressure_atm=spec.pressure_atm or payload.pressure_atm,
                    hitran_api_key=hitran_api_key,
                )
            except httpx.HTTPStatusError as exc:
                raise HTTPException(status_code=502, detail="HITRAN spectrum download failed") from exc
            except SynthesisError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            spectra.append(
                _hitran_spectrum_from_response(
                    response,
                    temperature_k=spec.temperature_k or payload.temperature_k,
                    pressure_atm=spec.pressure_atm or payload.pressure_atm,
                )
            )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported library source: {payload.source}")

    if source == "nist":
        created, skipped = await _write_nist_library_spectra_to_experiment(
            session=session,
            experiment_id=payload.experiment_id,
            spectra=spectra,
            range_mode=payload.range_mode,
        )
        failures.extend(skipped)
    else:
        created = await _write_library_spectra_to_experiment(
            session=session,
            experiment_id=payload.experiment_id,
            spectra=spectra,
            range_mode=payload.range_mode,
        )

    message = None
    if source == "nist" and failures:
        message = f"Imported {len(created)} of {len(unique_ids)} NIST spectra; failed {len(failures)}."
    return LibraryImportResponse(
        imported=len(created),
        files=[file_record.id for file_record in created],
        message=message,
        failures=failures if source == "nist" else [],
    )


@router.get("/download/{file_id}")
async def download_dataset(
    file_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Download a specific dataset file by its ID.
    Looks up the file path from the database and streams it to the client.
    Only allows downloading files from experiments owned by the current user.
    """
    if not await check_export_allowed(current_user):
        raise HTTPException(status_code=403, detail="Export not permitted for this user")

    # 1. Query Metadata with ownership check via experiment
    result = await session.execute(
        select(ExperimentFile)
        .join(Experiment, ExperimentFile.experiment_id == Experiment.id)
        .where(ExperimentFile.id == file_id)
        .where(Experiment.user_id == current_user.id)
    )
    file_record = result.scalar_one_or_none()

    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    # 2. Resolve path: file_path is relative to experiment directory
    exp_dir = experiment_dir(file_record.experiment_id)
    file_path = (exp_dir / file_record.file_path).resolve()

    # 3. Validate resolved path is within experiment directory (prevent traversal)
    if not file_path.is_relative_to(exp_dir):
        raise HTTPException(status_code=400, detail="Invalid file path")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File missing from storage")

    # 4. Stream File
    return FileResponse(path=file_path, filename=file_path.name, media_type="application/octet-stream")


@router.get("/{dataset_id}/manifest")
async def dataset_manifest(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
):
    ds = _resolve_handle_or_raise(dataset_id, current_user)
    return ds.manifest.model_dump(mode="json")


@router.get("/{dataset_id}/preview")
async def dataset_preview(
    dataset_id: str,
    n_rows: int = Query(5, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    from spectra_sherpa.app.lib.dataset_summarizer import DatasetSummarizer

    ds = _resolve_handle_or_raise(dataset_id, current_user)
    resource = DatasetSummarizer().to_mcp_resource(ds)
    preview = resource.get("preview", {})
    preview["n_rows"] = min(n_rows, ds.shape[0])
    preview["data"] = ds.X[: preview["n_rows"]].tolist()
    return preview


@router.get("/{dataset_id}/provenance")
async def dataset_provenance(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
):
    ds = _resolve_handle_or_raise(dataset_id, current_user)
    return ds.provenance.to_list()


@router.get("/{dataset_id}/quality")
async def dataset_quality(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
):
    ds = _resolve_handle_or_raise(dataset_id, current_user)
    return ds.quality.model_dump(exclude_none=True)


@router.get("/{dataset_id}/summary")
async def dataset_summary(
    dataset_id: str,
    tier: int = Query(1, ge=0, le=3),
    current_user: User = Depends(get_current_user),
):
    from spectra_sherpa.app.lib.dataset_summarizer import DatasetSummarizer

    ds = _resolve_handle_or_raise(dataset_id, current_user)
    summarizer = DatasetSummarizer()
    return {
        "dataset_id": ds.dataset_id,
        "summary": summarizer.summarize(ds, tier=tier),
        "structured": summarizer.to_structured(ds, tier=tier),
    }


class BranchRequest(BaseModel):
    label: str


@router.post("/{dataset_id}/branch")
@audit_excluded("process-local dataset handle; persistent DatasetVersion ledger required before audit coverage")
async def dataset_branch(
    dataset_id: str,
    payload: BranchRequest,
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.id if current_user is not None else None
    try:
        branched = dataset_registry.branch(dataset_id, label=payload.label, user_id=user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Dataset is not accessible for this user") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Dataset handle not found: {dataset_id}") from exc
    return branched.manifest.model_dump(mode="json")
