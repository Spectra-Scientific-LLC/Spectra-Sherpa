"""
Processing API routes for spectral data preprocessing.

These endpoints expose SpectrochemPy preprocessing methods directly,
allowing the frontend Process page to apply operations to experiment data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session
from app.models.experiment import Experiment
from app.models.user import User
from app.services.experiments import experiment_dir

# Router with authentication required for all endpoints
router = APIRouter(prefix="/process", dependencies=[Depends(get_current_user)])


class ProcessRequest(BaseModel):
    """Request body for processing operations."""
    experiment_id: int
    parameters: dict[str, Any] = {}


class ProcessResponse(BaseModel):
    """Response from processing operations."""
    success: bool
    message: str
    output_file: str | None = None
    details: dict[str, Any] = {}


async def _verify_experiment_ownership(
    experiment_id: int,
    session: AsyncSession,
    current_user: User,
) -> Experiment:
    """Verify experiment exists and belongs to current user."""
    result = await session.execute(
        select(Experiment).where(Experiment.id == experiment_id)
    )
    experiment = result.scalar_one_or_none()
    if not experiment or experiment.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return experiment


def load_experiment_data(experiment_id: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Load spectral data from experiment directory.

    Returns:
        Tuple of (wavenumbers, intensities)
    """
    exp_dir = experiment_dir(experiment_id)

    # Look for preprocessed data first, then raw
    for stage in ["preprocessed", "raw"]:
        stage_dir = exp_dir / stage
        if not stage_dir.exists():
            continue

        # Find CSV or NPY files
        for ext in ["*.csv", "*.npy", "*.txt"]:
            files = list(stage_dir.glob(ext))
            if files:
                file_path = files[0]
                if file_path.suffix == ".npy":
                    data = np.load(file_path)
                    if data.ndim == 2:
                        return data[0], data[1:]  # First row is wavenumbers
                    return np.arange(len(data)), data
                else:
                    # CSV or TXT
                    data = np.loadtxt(file_path, delimiter=",", skiprows=1)
                    if data.ndim == 2:
                        return data[:, 0], data[:, 1:]
                    return np.arange(len(data)), data

    raise FileNotFoundError(f"No spectral data found for experiment {experiment_id}")


def save_processed_data(
    experiment_id: int,
    wavenumbers: np.ndarray,
    intensities: np.ndarray,
    method_name: str,
) -> Path:
    """Save processed data to experiment directory."""
    exp_dir = experiment_dir(experiment_id)
    output_dir = exp_dir / "preprocessed"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / f"{method_name}_result.csv"

    # Combine wavenumbers and intensities
    if intensities.ndim == 1:
        data = np.column_stack([wavenumbers, intensities])
    else:
        data = np.column_stack([wavenumbers, intensities.T])

    np.savetxt(output_file, data, delimiter=",", header="wavenumber,intensity")

    return output_file


@router.post("/baseline_als", response_model=ProcessResponse)
async def baseline_als(
    request: ProcessRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProcessResponse:
    """
    Apply Asymmetric Least Squares (ALS) baseline correction.

    Parameters:
        - lam: Smoothness parameter (default: 1e5)
        - p: Asymmetry parameter (default: 0.001)
        - niter: Number of iterations (default: 10)
    """
    await _verify_experiment_ownership(request.experiment_id, session, current_user)

    try:
        from app.lib.scp_compat import scp

        wavenumbers, intensities = load_experiment_data(request.experiment_id)

        # Create NDDataset
        dataset = scp.NDDataset(intensities)
        dataset.x = scp.Coord(wavenumbers, title="Wavenumber", units="cm^-1")

        # Apply ALS baseline correction
        lam = request.parameters.get("lam", 1e5)
        p = request.parameters.get("p", 0.001)

        corrected = dataset.copy()
        corrected.basc(lamb=lam, asymmetry=p)

        # Save result
        output_file = save_processed_data(
            request.experiment_id,
            wavenumbers,
            corrected.data,
            "baseline_als",
        )

        return ProcessResponse(
            success=True,
            message="ALS baseline correction applied successfully",
            output_file=str(output_file.name),
            details={"lam": lam, "p": p},
        )
    except ImportError:
        # Fallback without spectrochempy
        return _baseline_als_fallback(request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}") from e


def _baseline_als_fallback(request: ProcessRequest) -> ProcessResponse:
    """ALS baseline correction without spectrochempy using scipy."""
    from scipy import sparse
    from scipy.sparse.linalg import spsolve

    wavenumbers, intensities = load_experiment_data(request.experiment_id)

    lam = request.parameters.get("lam", 1e5)
    p = request.parameters.get("p", 0.001)
    niter = request.parameters.get("niter", 10)

    def als_baseline(y, lam, p, niter):
        L = len(y)
        D = sparse.diags([1, -2, 1], [0, -1, -2], shape=(L, L - 2))
        w = np.ones(L)
        for _ in range(niter):
            W = sparse.spdiags(w, 0, L, L)
            Z = W + lam * D.dot(D.transpose())
            z = spsolve(Z, w * y)
            w = p * (y > z) + (1 - p) * (y < z)
        return z

    if intensities.ndim == 1:
        baseline = als_baseline(intensities, lam, p, niter)
        corrected = intensities - baseline
    else:
        corrected = np.zeros_like(intensities)
        for i in range(intensities.shape[0]):
            baseline = als_baseline(intensities[i], lam, p, niter)
            corrected[i] = intensities[i] - baseline

    output_file = save_processed_data(
        request.experiment_id,
        wavenumbers,
        corrected,
        "baseline_als",
    )

    return ProcessResponse(
        success=True,
        message="ALS baseline correction applied (scipy fallback)",
        output_file=str(output_file.name),
        details={"lam": lam, "p": p, "niter": niter},
    )


@router.post("/baseline_polynomial", response_model=ProcessResponse)
async def baseline_polynomial(
    request: ProcessRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProcessResponse:
    """
    Apply polynomial baseline correction.

    Parameters:
        - order: Polynomial order (default: 2)
    """
    await _verify_experiment_ownership(request.experiment_id, session, current_user)

    try:
        wavenumbers, intensities = load_experiment_data(request.experiment_id)

        order = request.parameters.get("order", 2)

        if intensities.ndim == 1:
            coeffs = np.polyfit(wavenumbers, intensities, order)
            baseline = np.polyval(coeffs, wavenumbers)
            corrected = intensities - baseline
        else:
            corrected = np.zeros_like(intensities)
            for i in range(intensities.shape[0]):
                coeffs = np.polyfit(wavenumbers, intensities[i], order)
                baseline = np.polyval(coeffs, wavenumbers)
                corrected[i] = intensities[i] - baseline

        output_file = save_processed_data(
            request.experiment_id,
            wavenumbers,
            corrected,
            "baseline_polynomial",
        )

        return ProcessResponse(
            success=True,
            message="Polynomial baseline correction applied",
            output_file=str(output_file.name),
            details={"order": order},
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}") from e


@router.post("/smooth_savgol", response_model=ProcessResponse)
async def smooth_savgol(
    request: ProcessRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProcessResponse:
    """
    Apply Savitzky-Golay smoothing filter.

    Parameters:
        - window: Window size (default: 15, must be odd)
        - order: Polynomial order (default: 2)
        - deriv: Derivative order (default: 0)
    """
    await _verify_experiment_ownership(request.experiment_id, session, current_user)

    try:
        from scipy.signal import savgol_filter

        wavenumbers, intensities = load_experiment_data(request.experiment_id)

        window = request.parameters.get("window", 15)
        order = request.parameters.get("order", 2)
        deriv = request.parameters.get("deriv", 0)

        # Ensure window is odd
        if window % 2 == 0:
            window += 1

        if intensities.ndim == 1:
            smoothed = savgol_filter(intensities, window, order, deriv=deriv)
        else:
            smoothed = np.array([
                savgol_filter(row, window, order, deriv=deriv)
                for row in intensities
            ])

        output_file = save_processed_data(
            request.experiment_id,
            wavenumbers,
            smoothed,
            "smooth_savgol",
        )

        return ProcessResponse(
            success=True,
            message="Savitzky-Golay smoothing applied",
            output_file=str(output_file.name),
            details={"window": window, "order": order, "deriv": deriv},
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}") from e


@router.post("/smooth_ma", response_model=ProcessResponse)
async def smooth_moving_average(
    request: ProcessRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProcessResponse:
    """
    Apply moving average smoothing.

    Parameters:
        - window: Window size (default: 5)
    """
    await _verify_experiment_ownership(request.experiment_id, session, current_user)

    try:
        wavenumbers, intensities = load_experiment_data(request.experiment_id)

        window = request.parameters.get("window", 5)

        def moving_average(data, n):
            return np.convolve(data, np.ones(n) / n, mode="same")

        if intensities.ndim == 1:
            smoothed = moving_average(intensities, window)
        else:
            smoothed = np.array([
                moving_average(row, window)
                for row in intensities
            ])

        output_file = save_processed_data(
            request.experiment_id,
            wavenumbers,
            smoothed,
            "smooth_ma",
        )

        return ProcessResponse(
            success=True,
            message="Moving average smoothing applied",
            output_file=str(output_file.name),
            details={"window": window},
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}") from e


@router.post("/align_peak", response_model=ProcessResponse)
async def align_peak(
    request: ProcessRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProcessResponse:
    """
    Align spectra based on a reference peak position.

    Parameters:
        - target: Target wavenumber for alignment (default: 2350)
        - window: Search window around target (default: 50)
    """
    await _verify_experiment_ownership(request.experiment_id, session, current_user)

    try:
        from scipy.interpolate import interp1d

        wavenumbers, intensities = load_experiment_data(request.experiment_id)

        target = request.parameters.get("target", 2350)
        window = request.parameters.get("window", 50)

        # Find peaks within window
        mask = (wavenumbers >= target - window) & (wavenumbers <= target + window)

        if intensities.ndim == 1:
            intensities = intensities.reshape(1, -1)

        aligned = np.zeros_like(intensities)
        for i in range(intensities.shape[0]):
            # Find peak in window
            window_data = intensities[i, mask]
            peak_idx = np.argmax(window_data)
            actual_peak = wavenumbers[mask][peak_idx]

            # Shift spectrum
            shift = target - actual_peak
            shifted_wn = wavenumbers + shift

            # Interpolate to original wavenumber grid
            f = interp1d(shifted_wn, intensities[i], kind="linear", fill_value="extrapolate")
            aligned[i] = f(wavenumbers)

        if aligned.shape[0] == 1:
            aligned = aligned.squeeze()

        output_file = save_processed_data(
            request.experiment_id,
            wavenumbers,
            aligned,
            "align_peak",
        )

        return ProcessResponse(
            success=True,
            message="Peak alignment applied",
            output_file=str(output_file.name),
            details={"target": target, "window": window},
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}") from e


@router.post("/interpolate", response_model=ProcessResponse)
async def interpolate_linear(
    request: ProcessRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProcessResponse:
    """
    Resample spectra to uniform wavenumber grid using linear interpolation.

    Parameters:
        - start: Start wavenumber (default: 400)
        - end: End wavenumber (default: 4000)
        - points: Number of points (default: 1000)
    """
    await _verify_experiment_ownership(request.experiment_id, session, current_user)

    try:
        from scipy.interpolate import interp1d

        wavenumbers, intensities = load_experiment_data(request.experiment_id)

        start = request.parameters.get("start", 400)
        end = request.parameters.get("end", 4000)
        points = request.parameters.get("points", 1000)

        new_wn = np.linspace(start, end, points)

        if intensities.ndim == 1:
            f = interp1d(wavenumbers, intensities, kind="linear", fill_value="extrapolate")
            interpolated = f(new_wn)
        else:
            interpolated = np.zeros((intensities.shape[0], points))
            for i in range(intensities.shape[0]):
                f = interp1d(wavenumbers, intensities[i], kind="linear", fill_value="extrapolate")
                interpolated[i] = f(new_wn)

        output_file = save_processed_data(
            request.experiment_id,
            new_wn,
            interpolated,
            "interpolate",
        )

        return ProcessResponse(
            success=True,
            message="Linear interpolation applied",
            output_file=str(output_file.name),
            details={"start": start, "end": end, "points": points},
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}") from e


@router.post("/interpolate_pchip", response_model=ProcessResponse)
async def interpolate_pchip(
    request: ProcessRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProcessResponse:
    """
    Resample spectra using PCHIP interpolation (preserves monotonicity).

    Parameters:
        - start: Start wavenumber (default: 400)
        - end: End wavenumber (default: 4000)
        - points: Number of points (default: 1000)
    """
    await _verify_experiment_ownership(request.experiment_id, session, current_user)

    try:
        from scipy.interpolate import PchipInterpolator

        wavenumbers, intensities = load_experiment_data(request.experiment_id)

        start = request.parameters.get("start", 400)
        end = request.parameters.get("end", 4000)
        points = request.parameters.get("points", 1000)

        new_wn = np.linspace(start, end, points)

        # Sort by wavenumber for PCHIP
        sort_idx = np.argsort(wavenumbers)
        sorted_wn = wavenumbers[sort_idx]

        if intensities.ndim == 1:
            sorted_int = intensities[sort_idx]
            f = PchipInterpolator(sorted_wn, sorted_int)
            interpolated = f(new_wn)
        else:
            interpolated = np.zeros((intensities.shape[0], points))
            for i in range(intensities.shape[0]):
                sorted_int = intensities[i, sort_idx]
                f = PchipInterpolator(sorted_wn, sorted_int)
                interpolated[i] = f(new_wn)

        output_file = save_processed_data(
            request.experiment_id,
            new_wn,
            interpolated,
            "interpolate_pchip",
        )

        return ProcessResponse(
            success=True,
            message="PCHIP interpolation applied",
            output_file=str(output_file.name),
            details={"start": start, "end": end, "points": points},
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}") from e


@router.get("/methods")
async def list_processing_methods() -> list[dict[str, Any]]:
    """List all available processing methods."""
    return [
        {
            "id": "baseline_als",
            "name": "ALS Baseline",
            "category": "baseline",
            "description": "Asymmetric Least Squares baseline correction",
            "parameters": ["lam", "p", "niter"],
        },
        {
            "id": "baseline_polynomial",
            "name": "Polynomial Baseline",
            "category": "baseline",
            "description": "Polynomial fit baseline correction",
            "parameters": ["order"],
        },
        {
            "id": "smooth_savgol",
            "name": "Savitzky-Golay",
            "category": "smoothing",
            "description": "Polynomial smoothing filter",
            "parameters": ["window", "order", "deriv"],
        },
        {
            "id": "smooth_ma",
            "name": "Moving Average",
            "category": "smoothing",
            "description": "Simple moving average smoothing",
            "parameters": ["window"],
        },
        {
            "id": "align_peak",
            "name": "Peak Alignment",
            "category": "alignment",
            "description": "Align spectra to reference peak",
            "parameters": ["target", "window"],
        },
        {
            "id": "interpolate",
            "name": "Linear Interpolation",
            "category": "interpolation",
            "description": "Resample to uniform grid",
            "parameters": ["start", "end", "points"],
        },
        {
            "id": "interpolate_pchip",
            "name": "PCHIP Interpolation",
            "category": "interpolation",
            "description": "Monotonicity-preserving resampling",
            "parameters": ["start", "end", "points"],
        },
    ]
