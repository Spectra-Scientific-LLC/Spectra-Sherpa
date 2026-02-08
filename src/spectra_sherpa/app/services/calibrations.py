from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import curve_fit
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.cal_model import CalModel
from app.models.calibration import Calibration
from app.models.calibration_file import CalibrationFile
from app.services.experiments import relative_to_data_dir, resolve_data_path
from app.lib.preprocessing import build_golden_grid, interpolate_to_grid

# Alias for backward compatibility
interpolate_to_golden_grid = interpolate_to_grid


DEFAULT_NRMSE_THRESHOLD = 0.05
DEFAULT_OUTLIER_THRESHOLD = None
DEFAULT_MIN_POINTS = 4
DEFAULT_MERGE_TOLERANCE = 0.05
DEFAULT_INTERPOLATION = "pchip"


def calibration_dir(calibration_id: int) -> Path:
    return settings.data_dir / "calibrations" / f"cal_{calibration_id:03d}"


def metadata_path_for(calibration_id: int) -> Path:
    return calibration_dir(calibration_id) / "metadata.json"


def ensure_calibration_dirs(calibration_id: int) -> None:
    base = calibration_dir(calibration_id)
    (base / "raw_measurements").mkdir(parents=True, exist_ok=True)
    (base / "models" / "versions").mkdir(parents=True, exist_ok=True)


def write_metadata(metadata_path: Path, metadata: dict[str, Any]) -> None:
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, indent=2, default=str))


def read_metadata(metadata_path: Path) -> dict[str, Any]:
    if not metadata_path.exists():
        return {}
    return json.loads(metadata_path.read_text())


def _load_csv(file_path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = np.genfromtxt(file_path, delimiter=",", skip_header=1)
    if data.ndim != 2 or data.shape[1] < 2 or np.isnan(data[0, 0]):
        data = np.genfromtxt(file_path, delimiter=",", skip_header=0)
    if data.ndim != 2 or data.shape[1] < 2:
        raise ValueError(f"Unexpected CSV format in {file_path.name}")
    wavenumber = data[:, 0]
    absorbance = data[:, 1]
    return wavenumber, absorbance


def _linear_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    slope, intercept = np.polyfit(x, y, 1)
    return float(slope), float(intercept)


def _saturation_model(x: np.ndarray, s: float, p: float, c: float) -> np.ndarray:
    return s * np.tanh((c * x / s) ** p) ** (1.0 / p)


def _saturation_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    s_init = min(1.8, float(np.max(y) * 0.9)) if np.max(y) > 0 else 1.0
    c_init = max(1e-6, float(np.max(y) / max(np.max(x), 1e-6)))
    p_init = 1.0
    bounds = ([1e-6, 0.1, 1e-6], [10.0, 10.0, 10.0])
    params, _ = curve_fit(
        _saturation_model,
        x,
        y,
        p0=[s_init, p_init, c_init],
        bounds=bounds,
        maxfev=20000,
    )
    return float(params[0]), float(params[1]), float(params[2])


def _nrmse(y_true: np.ndarray, y_pred: np.ndarray) -> float | None:
    if y_true.size == 0:
        return None
    range_val = np.max(y_true) - np.min(y_true)
    if range_val <= 0:
        return None
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    return float(rmse / range_val)


def _r2(y_true: np.ndarray, y_pred: np.ndarray) -> float | None:
    if y_true.size == 0:
        return None
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    if ss_tot <= 0:
        return None
    return 1.0 - ss_res / ss_tot


def _collect_measurements(
    files: list[CalibrationFile],
) -> tuple[np.ndarray, list[np.ndarray], list[np.ndarray]]:
    concentrations: list[float] = []
    wavenumbers: list[np.ndarray] = []
    absorbances: list[np.ndarray] = []

    for entry in files:
        path = resolve_data_path(entry.file_path)
        wn, abs_values = _load_csv(path)
        wavenumbers.append(wn)
        absorbances.append(abs_values)
        concentrations.append(entry.concentration)

    return np.array(concentrations, dtype=float), wavenumbers, absorbances


def _align_measurements(
    wavenumbers: list[np.ndarray],
    absorbances: list[np.ndarray],
    interpolation_method: str,
    merge_tolerance: float,
) -> tuple[np.ndarray, list[np.ndarray]]:
    golden_grid = build_golden_grid(wavenumbers, merge_tolerance=merge_tolerance)
    aligned = []
    for wn, absorbance in zip(wavenumbers, absorbances):
        aligned_absorbance = interpolate_to_golden_grid(
            wn, absorbance, golden_grid, method=interpolation_method
        )
        aligned.append(aligned_absorbance)
    return golden_grid, aligned


def _extract_settings(settings_dict: dict[str, Any]) -> dict[str, Any]:
    return {
        "nrmse_max_threshold": settings_dict.get(
            "nrmse_max_threshold", DEFAULT_NRMSE_THRESHOLD
        ),
        "absorbance_outlier_threshold": settings_dict.get(
            "absorbance_outlier_threshold", DEFAULT_OUTLIER_THRESHOLD
        ),
        "min_points": settings_dict.get("min_points", DEFAULT_MIN_POINTS),
        "wavenumber_merge_tolerance": settings_dict.get(
            "wavenumber_merge_tolerance", DEFAULT_MERGE_TOLERANCE
        ),
        "interpolation_method": settings_dict.get(
            "interpolation_method", DEFAULT_INTERPOLATION
        ),
    }


def _fit_wavenumber(
    concentrations: np.ndarray,
    absorbance_values: np.ndarray,
    model_type: str,
    nrmse_threshold: float,
) -> tuple[dict | None, dict | None, str | None]:
    linear_model = None
    saturation_model = None
    winner = None

    if model_type in {"linear", "hybrid"}:
        slope, intercept = _linear_fit(concentrations, absorbance_values)
        predicted = slope * concentrations + intercept
        linear_model = {
            "slope": slope,
            "intercept": intercept,
            "r2": _r2(absorbance_values, predicted),
            "nrmse": _nrmse(absorbance_values, predicted),
        }
        linear_model["passes_threshold"] = bool(
            linear_model["nrmse"] is not None
            and linear_model["nrmse"] <= nrmse_threshold
        )

    if model_type in {"saturation", "hybrid"}:
        try:
            s, p, c = _saturation_fit(concentrations, absorbance_values)
            predicted = _saturation_model(concentrations, s, p, c)
            saturation_model = {
                "s": s,
                "p": p,
                "c": c,
                "r2": _r2(absorbance_values, predicted),
                "nrmse": _nrmse(absorbance_values, predicted),
            }
            saturation_model["passes_threshold"] = bool(
                saturation_model["nrmse"] is not None
                and saturation_model["nrmse"] <= nrmse_threshold
            )
        except Exception:
            saturation_model = None

    if model_type == "linear":
        if linear_model and linear_model.get("passes_threshold"):
            winner = "linear"
    elif model_type == "saturation":
        if saturation_model and saturation_model.get("passes_threshold"):
            winner = "saturation"
    else:
        linear_ok = bool(linear_model and linear_model.get("passes_threshold"))
        sat_ok = bool(saturation_model and saturation_model.get("passes_threshold"))
        if linear_ok and sat_ok:
            winner = (
                "linear"
                if linear_model["nrmse"] <= saturation_model["nrmse"]
                else "saturation"
            )
        elif linear_ok:
            winner = "linear"
        elif sat_ok:
            winner = "saturation"

    return linear_model, saturation_model, winner


def _compute_calibration_fit(
    measurement_files: list[CalibrationFile],
    model_type: str,
    nrmse_threshold: float,
    outlier_threshold: float | None,
    min_points: int,
    merge_tolerance: float,
    interpolation_method: str,
    max_wavenumbers: int,
    max_job_duration_sec: float,
) -> tuple[np.ndarray, list[dict[str, Any]], list[float], list[float]]:
    """CPU-bound calibration fitting.

    Extracted so it can be offloaded to a thread pool via
    ``loop.run_in_executor`` — keeps the async event loop responsive.
    """
    concentrations, wavenumbers, absorbances = _collect_measurements(measurement_files)
    max_wn = max((len(wn) for wn in wavenumbers), default=0)
    if max_wn > max_wavenumbers:
        raise ValueError("Measurement exceeds max wavenumbers limit")
    golden_grid, aligned_absorbances = _align_measurements(
        wavenumbers, absorbances, interpolation_method, merge_tolerance
    )
    if golden_grid.size > max_wavenumbers:
        raise ValueError("Aligned wavenumber grid exceeds max limit")

    data_matrix = np.stack(aligned_absorbances, axis=0)

    wavenumber_entries: list[dict[str, Any]] = []
    winner_r2: list[float] = []
    winner_rmse: list[float] = []

    deadline = time.monotonic() + max_job_duration_sec

    for idx, wn in enumerate(golden_grid):
        if time.monotonic() > deadline:
            raise TimeoutError("Calibration fit exceeded max duration")
        y_values = data_matrix[:, idx]
        valid_mask = np.isfinite(y_values)
        if outlier_threshold is not None:
            valid_mask &= y_values <= outlier_threshold
        x_values = concentrations[valid_mask]
        y_values = y_values[valid_mask]

        if len(x_values) < min_points:
            continue

        linear_model, saturation_model, winner = _fit_wavenumber(
            x_values, y_values, model_type, nrmse_threshold
        )

        if linear_model and linear_model.get("passes_threshold"):
            predicted = linear_model["slope"] * x_values + linear_model["intercept"]
            rmse_val = float(np.sqrt(np.mean((y_values - predicted) ** 2)))
            if winner == "linear":
                if linear_model.get("r2") is not None:
                    winner_r2.append(linear_model["r2"])
                winner_rmse.append(rmse_val)

        if saturation_model and saturation_model.get("passes_threshold"):
            predicted = _saturation_model(
                x_values, saturation_model["s"], saturation_model["p"], saturation_model["c"]
            )
            rmse_val = float(np.sqrt(np.mean((y_values - predicted) ** 2)))
            if winner == "saturation":
                if saturation_model.get("r2") is not None:
                    winner_r2.append(saturation_model["r2"])
                winner_rmse.append(rmse_val)

        wavenumber_entries.append(
            {
                "wavenumber": float(wn),
                "winner_model": winner,
                "points_used_in_fit": int(len(x_values)),
                "linear_model": linear_model,
                "saturation_model": saturation_model,
            }
        )

    return golden_grid, wavenumber_entries, winner_r2, winner_rmse


async def create_calibration(
    session: AsyncSession,
    user_id: int,
    compound_name: str,
    concentration_mode: str,
    x_unit: str,
    pathlength_m: float | None,
    metadata: dict[str, Any],
) -> Calibration:
    calibration = Calibration(
        user_id=user_id,
        compound_name=compound_name,
        concentration_mode=concentration_mode,
        x_unit=x_unit,
        pathlength_m=pathlength_m,
        metadata_path="",
    )
    session.add(calibration)
    await session.flush()

    try:
        ensure_calibration_dirs(calibration.id)
        metadata_file = metadata_path_for(calibration.id)
        write_metadata(metadata_file, metadata)
        calibration.metadata_path = relative_to_data_dir(metadata_file)
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    await session.refresh(calibration)
    return calibration


async def list_calibrations(
    session: AsyncSession, user_id: int | None = None, limit: int = 50, offset: int = 0
) -> list[Calibration]:
    query = select(Calibration).order_by(Calibration.created_at.desc())
    if user_id is not None:
        query = query.where(Calibration.user_id == user_id)
    query = query.limit(limit).offset(offset)
    result = await session.execute(query)
    return list(result.scalars())


async def get_calibration(session: AsyncSession, calibration_id: int) -> Calibration | None:
    result = await session.execute(
        select(Calibration).where(Calibration.id == calibration_id)
    )
    return result.scalar_one_or_none()


async def add_measurement(
    session: AsyncSession,
    calibration_id: int,
    file_path: str,
    concentration: float,
) -> CalibrationFile:
    measurement = CalibrationFile(
        calibration_id=calibration_id,
        file_path=file_path,
        concentration=concentration,
    )
    session.add(measurement)
    await session.commit()
    await session.refresh(measurement)
    return measurement


async def list_measurements(
    session: AsyncSession, calibration_id: int
) -> list[CalibrationFile]:
    result = await session.execute(
        select(CalibrationFile).where(CalibrationFile.calibration_id == calibration_id)
    )
    return list(result.scalars())


async def list_models(session: AsyncSession, calibration_id: int) -> list[CalModel]:
    result = await session.execute(
        select(CalModel)
        .where(CalModel.calibration_id == calibration_id)
        .order_by(CalModel.created_at.desc())
    )
    return list(result.scalars())


async def activate_model(
    session: AsyncSession, calibration_id: int, model_id: int
) -> CalModel:
    await session.execute(
        update(CalModel)
        .where(CalModel.calibration_id == calibration_id)
        .values(is_active=False)
    )
    result = await session.execute(
        select(CalModel)
        .where(CalModel.calibration_id == calibration_id)
        .where(CalModel.id == model_id)
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise ValueError("Model not found")
    model.is_active = True
    await session.commit()
    await session.refresh(model)
    return model


async def get_active_model(
    session: AsyncSession, calibration_id: int
) -> CalModel | None:
    result = await session.execute(
        select(CalModel)
        .where(CalModel.calibration_id == calibration_id)
        .where(CalModel.is_active.is_(True))
    )
    return result.scalar_one_or_none()


async def fit_model(
    session: AsyncSession,
    calibration: Calibration,
    model_type: str,
    settings_dict: dict[str, Any],
    version_name: str | None = None,
) -> CalModel:
    model_type = model_type.lower()
    if model_type not in {"linear", "saturation", "hybrid"}:
        raise ValueError("Invalid model_type")
    measurement_files = await list_measurements(session, calibration.id)
    if not measurement_files:
        raise ValueError("No calibration measurements uploaded")
    if len(measurement_files) > settings.max_spectra_per_job:
        raise ValueError("Too many calibration measurements for a single fit")

    settings_values = _extract_settings(settings_dict)
    nrmse_threshold = settings_values["nrmse_max_threshold"]
    outlier_threshold = settings_values["absorbance_outlier_threshold"]
    min_points = settings_values["min_points"]
    merge_tolerance = settings_values["wavenumber_merge_tolerance"]
    interpolation_method = settings_values["interpolation_method"]
    if interpolation_method not in {"sinc", "pchip", "linear"}:
        raise ValueError("Invalid interpolation_method")
    if min_points < 2:
        raise ValueError("min_points must be >= 2")

    # Offload CPU-bound fitting (curve_fit, interpolation, NumPy) to thread pool
    loop = asyncio.get_running_loop()
    golden_grid, wavenumber_entries, winner_r2, winner_rmse = await loop.run_in_executor(
        None,
        partial(
            _compute_calibration_fit,
            measurement_files=measurement_files,
            model_type=model_type,
            nrmse_threshold=nrmse_threshold,
            outlier_threshold=outlier_threshold,
            min_points=min_points,
            merge_tolerance=merge_tolerance,
            interpolation_method=interpolation_method,
            max_wavenumbers=settings.max_wavenumbers,
            max_job_duration_sec=settings.max_job_duration_sec,
        ),
    )

    metadata = read_metadata(resolve_data_path(calibration.metadata_path))
    output_payload = {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "species_name": calibration.compound_name,
            "concentration_mode": calibration.concentration_mode,
            "x_unit": calibration.x_unit,
            "pathlength_m": calibration.pathlength_m,
            "absorbance_outlier_threshold": outlier_threshold,
            "nrmse_max_threshold": nrmse_threshold,
            "wavenumber_range": {
                "min": float(np.min(golden_grid)),
                "max": float(np.max(golden_grid)),
            },
            "num_spectra": len(measurement_files),
            "total_wavenumbers": len(golden_grid),
            "metadata": metadata,
        },
        "wavenumbers": wavenumber_entries,
    }

    base_dir = calibration_dir(calibration.id)
    version_name = version_name or _next_version_name(session, calibration.id, model_type)
    model_dir = base_dir / "models" / "versions" / version_name
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "model.json"
    model_path.write_text(json.dumps(output_payload, indent=2))

    avg_r2 = float(np.mean(winner_r2)) if winner_r2 else None
    avg_rmse = float(np.mean(winner_rmse)) if winner_rmse else None

    model = CalModel(
        calibration_id=calibration.id,
        version_name=version_name,
        model_type=model_type,
        model_path=relative_to_data_dir(model_path),
        r_squared=avg_r2,
        rmse=avg_rmse,
    )
    session.add(model)
    await session.commit()
    await session.refresh(model)
    return model


def _next_version_name(
    session: AsyncSession, calibration_id: int, model_type: str
) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"v_{model_type}_{timestamp}"


class CalibrationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_calibration(
        self,
        user_id: int,
        compound_name: str,
        concentration_mode: str,
        x_unit: str,
        pathlength_m: float | None,
        metadata: dict[str, Any],
    ) -> Calibration:
        return await create_calibration(
            self.session,
            user_id=user_id,
            compound_name=compound_name,
            concentration_mode=concentration_mode,
            x_unit=x_unit,
            pathlength_m=pathlength_m,
            metadata=metadata,
        )

    async def list_calibrations(
        self, limit: int = 50, offset: int = 0
    ) -> list[Calibration]:
        return await list_calibrations(self.session, limit=limit, offset=offset)

    async def get_calibration(self, calibration_id: int) -> Calibration | None:
        return await get_calibration(self.session, calibration_id)

    async def add_measurement(
        self, calibration_id: int, file_path: str, concentration: float
    ) -> CalibrationFile:
        return await add_measurement(
            self.session,
            calibration_id=calibration_id,
            file_path=file_path,
            concentration=concentration,
        )

    async def list_measurements(
        self, calibration_id: int
    ) -> list[CalibrationFile]:
        return await list_measurements(self.session, calibration_id)

    async def fit_model(
        self,
        calibration: Calibration,
        model_type: str,
        settings_dict: dict[str, Any],
        version_name: str | None = None,
    ) -> CalModel:
        return await fit_model(
            self.session,
            calibration=calibration,
            model_type=model_type,
            settings_dict=settings_dict,
            version_name=version_name,
        )

    async def list_models(self, calibration_id: int) -> list[CalModel]:
        return await list_models(self.session, calibration_id)

    async def activate_model(self, calibration_id: int, model_id: int) -> CalModel:
        return await activate_model(self.session, calibration_id, model_id)

    async def get_active_model(self, calibration_id: int) -> CalModel | None:
        return await get_active_model(self.session, calibration_id)
