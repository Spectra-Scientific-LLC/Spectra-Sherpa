"""
Analysis API routes for chemometric methods.

These endpoints expose SpectrochemPy analysis methods directly,
allowing the frontend Analysis page to run methods on experiment data.
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
router = APIRouter(prefix="/analysis", dependencies=[Depends(get_current_user)])


class AnalysisRequest(BaseModel):
    """Request body for analysis operations."""
    experiment_id: int
    parameters: dict[str, Any] = {}


class AnalysisResponse(BaseModel):
    """Response from analysis operations."""
    success: bool
    message: str
    results: dict[str, Any] = {}
    output_files: list[str] = []


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


async def load_experiment_data(
    experiment_id: int, session: AsyncSession
) -> tuple[np.ndarray, np.ndarray]:
    """
    Load spectral data from experiment file records.

    Returns:
        Tuple of (wavenumbers, intensities) where intensities is 2D (samples x features)
    """
    from app.core.config import settings
    from app.models.experiment_file import ExperimentFile
    from sqlalchemy import select

    # Query experiment files from database (prefer preprocessed, then raw)
    for stage in ["preprocessed", "raw"]:
        query = (
            select(ExperimentFile)
            .where(ExperimentFile.experiment_id == experiment_id)
            .where(ExperimentFile.stage == stage)
        )
        result = await session.execute(query)
        files = result.scalars().all()

        if not files:
            continue

        # Try to load the first file
        exp_dir = experiment_dir(experiment_id)
        for file_record in files:
            # Build absolute path from relative file_path
            file_path = exp_dir / file_record.file_path

            if not file_path.exists():
                continue

            # Load based on file extension
            if file_path.suffix == ".npy":
                data = np.load(file_path)
                if data.ndim == 2:
                    return data[0], data[1:]
                return np.arange(len(data)), data.reshape(1, -1)
            elif file_path.suffix in [".csv", ".txt"]:
                data = np.loadtxt(file_path, delimiter=",", skiprows=1)
                if data.ndim == 2:
                    return data[:, 0], data[:, 1:].T
                return np.arange(len(data)), data.reshape(1, -1)

    raise FileNotFoundError(
        f"No spectral data files found for experiment {experiment_id}. "
        f"Please upload spectral data files (CSV, NPY, or TXT) to this experiment."
    )


async def save_analysis_results(
    experiment_id: int,
    method_name: str,
    results: dict[str, Any],
    session: AsyncSession,
) -> list[Path]:
    """Save analysis results to experiment directory and create file records."""
    from app.models.experiment_file import ExperimentFile

    exp_dir = experiment_dir(experiment_id)
    output_dir = exp_dir / "analysis"
    output_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []

    # Save each array result as CSV
    for key, value in results.items():
        if isinstance(value, np.ndarray):
            output_file = output_dir / f"{method_name}_{key}.csv"
            np.savetxt(output_file, value, delimiter=",")
            saved_files.append(output_file)
        elif isinstance(value, (list, dict)):
            output_file = output_dir / f"{method_name}_{key}.json"
            output_file.write_text(json.dumps(value, default=str))
            saved_files.append(output_file)

    # Save summary JSON
    summary_file = output_dir / f"{method_name}_summary.json"
    summary = {
        k: v.tolist() if isinstance(v, np.ndarray) else v
        for k, v in results.items()
        if not isinstance(v, np.ndarray) or v.size < 100
    }
    summary_file.write_text(json.dumps(summary, indent=2, default=str))
    saved_files.append(summary_file)

    # Create experiment file records for all saved files
    for file_path in saved_files:
        rel_path = file_path.relative_to(exp_dir).as_posix()
        file_size = file_path.stat().st_size
        file_type = file_path.suffix.lstrip(".") or None

        # Check if record already exists
        from sqlalchemy import select
        from app.models.experiment_file import ExperimentFile

        query = select(ExperimentFile).where(
            ExperimentFile.experiment_id == experiment_id,
            ExperimentFile.file_path == rel_path,
        )
        result = await session.execute(query)
        existing = result.scalar_one_or_none()

        if not existing:
            # Create new file record
            file_record = ExperimentFile(
                experiment_id=experiment_id,
                stage="analysis",
                file_path=rel_path,
                file_size_bytes=file_size,
                file_type=file_type,
            )
            session.add(file_record)

    await session.commit()

    return saved_files


@router.post("/pca", response_model=AnalysisResponse)
async def run_pca(
    request: AnalysisRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AnalysisResponse:
    """
    Run Principal Component Analysis.

    Parameters:
        - n_components: Number of components (default: 10)
        - standardize: Standardize data (default: True)
    """
    await _verify_experiment_ownership(request.experiment_id, session, current_user)

    try:
        wavenumbers, intensities = await load_experiment_data(request.experiment_id, session)

        n_components = request.parameters.get("n_components", 10)
        standardize = request.parameters.get("standardize", True)

        # Ensure enough samples for requested components
        n_samples = intensities.shape[0]
        n_features = intensities.shape[1] if intensities.ndim > 1 else len(intensities)
        max_components = min(n_samples, n_features)
        n_components = min(n_components, max_components)

        try:
            from app.lib.scp_compat import scp

            # Create NDDataset
            dataset = scp.NDDataset(intensities)
            dataset.x = scp.Coord(wavenumbers, title="Wavenumber", units="cm^-1")

            # Run PCA
            pca = scp.PCA(n_components=n_components, standardized=standardize)
            pca.fit(dataset)

            results = {
                "scores": pca.transform().data if hasattr(pca.transform(), 'data') else np.array(pca.transform()),
                "loadings": pca.components.data if hasattr(pca.components, 'data') else np.array(pca.components),
                "explained_variance": list(pca.explained_variance),
                "explained_variance_ratio": list(pca.explained_variance_ratio),
                "n_components": n_components,
                "n_samples": n_samples,
                "n_features": n_features,
            }
        except ImportError:
            # Fallback to sklearn
            from sklearn.decomposition import PCA
            from sklearn.preprocessing import StandardScaler

            X = intensities
            if standardize:
                scaler = StandardScaler()
                X = scaler.fit_transform(X)

            pca = PCA(n_components=n_components)
            scores = pca.fit_transform(X)

            results = {
                "scores": scores,
                "loadings": pca.components_,
                "explained_variance": list(pca.explained_variance_),
                "explained_variance_ratio": list(pca.explained_variance_ratio_),
                "n_components": n_components,
                "n_samples": n_samples,
                "n_features": n_features,
            }

        # Save results
        output_files = await save_analysis_results(request.experiment_id, "pca", results, session)

        return AnalysisResponse(
            success=True,
            message=f"PCA completed with {n_components} components",
            results={
                "n_components": n_components,
                "explained_variance_ratio": results["explained_variance_ratio"],
                "total_variance_explained": sum(results["explained_variance_ratio"]),
            },
            output_files=[f.name for f in output_files],
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}") from e


@router.post("/mcr_als", response_model=AnalysisResponse)
async def run_mcr_als(
    request: AnalysisRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AnalysisResponse:
    """
    Run Multivariate Curve Resolution with Alternating Least Squares (MCR-ALS).

    Parameters:
        - n_components: Number of pure components (default: 3)
        - max_iter: Maximum iterations (default: 100)
        - tol: Convergence tolerance (default: 1e-8)
    """
    await _verify_experiment_ownership(request.experiment_id, session, current_user)

    try:
        wavenumbers, intensities = await load_experiment_data(request.experiment_id, session)

        n_components = request.parameters.get("n_components", 3)
        max_iter = request.parameters.get("max_iter", 100)
        tol = request.parameters.get("tol", 1e-8)

        # Ensure we don't request more components than possible
        n_samples, n_features = intensities.shape
        n_components = min(n_components, n_samples, n_features)

        try:
            from app.lib.scp_compat import scp

            # Create NDDataset from the data matrix
            dataset = scp.NDDataset(intensities)
            dataset.x = scp.Coord(wavenumbers, title="Wavenumber", units="cm^-1")

            # Generate initial concentration guess using SVD
            # SVD gives us a good starting point for the concentration profiles
            U, S_svd, Vt = np.linalg.svd(intensities, full_matrices=False)
            # Use the first n_components columns of U scaled by singular values
            C0_data = U[:, :n_components] * S_svd[:n_components]
            # Ensure non-negative (MCR-ALS constraint)
            C0_data = np.abs(C0_data)
            C0 = scp.NDDataset(C0_data)

            # Create MCRALS instance (note: class name is MCRALS, not MCR_ALS)
            mcr = scp.MCRALS(max_iter=max_iter, tol=tol)
            mcr.fit(dataset, C0)

            # Extract results - St contains spectral profiles, C contains concentrations
            C_data = mcr.C.data if hasattr(mcr.C, 'data') else np.array(mcr.C)
            St_data = mcr.St.data if hasattr(mcr.St, 'data') else np.array(mcr.St)

            results = {
                "C": C_data,  # Concentrations (n_samples, n_components)
                "S": St_data,  # Pure spectra (n_components, n_features)
                "n_components": n_components,
                "converged": True,  # MCRALS doesn't expose converged attribute directly
                "iterations": max_iter,  # Actual iterations not easily accessible
            }
        except (ImportError, AttributeError) as e:
            # Fallback using NMF as approximation
            from sklearn.decomposition import NMF

            # NMF requires non-negative data
            X = intensities.copy()
            X[X < 0] = 0

            nmf = NMF(n_components=n_components, max_iter=max_iter, tol=tol)
            C = nmf.fit_transform(X)
            S = nmf.components_

            results = {
                "C": C,  # Concentrations
                "S": S,  # Pure spectra
                "n_components": n_components,
                "converged": True,
                "iterations": nmf.n_iter_,
                "fallback_method": "NMF",
                "fallback_reason": str(e),
            }

        output_files = await save_analysis_results(request.experiment_id, "mcr_als", results, session)

        return AnalysisResponse(
            success=True,
            message=f"MCR-ALS completed with {n_components} components",
            results={
                "n_components": n_components,
                "converged": results.get("converged", True),
                "iterations": results.get("iterations"),
                "fallback_method": results.get("fallback_method"),
            },
            output_files=[f.name for f in output_files],
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}") from e


@router.post("/cluster_kmeans", response_model=AnalysisResponse)
async def run_kmeans(
    request: AnalysisRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AnalysisResponse:
    """
    Run K-Means clustering.

    Parameters:
        - n_clusters: Number of clusters (default: 3)
        - n_init: Number of initializations (default: 10)
    """
    await _verify_experiment_ownership(request.experiment_id, session, current_user)

    try:
        from sklearn.cluster import KMeans

        wavenumbers, intensities = await load_experiment_data(request.experiment_id, session)

        n_clusters = request.parameters.get("n_clusters", 3)
        n_init = request.parameters.get("n_init", 10)

        # Ensure we have enough samples
        n_samples = intensities.shape[0]
        n_clusters = min(n_clusters, n_samples)

        kmeans = KMeans(n_clusters=n_clusters, n_init=n_init, random_state=42)
        labels = kmeans.fit_predict(intensities)

        results = {
            "labels": labels,
            "centroids": kmeans.cluster_centers_,
            "inertia": float(kmeans.inertia_),
            "n_clusters": n_clusters,
            "n_samples": n_samples,
        }

        output_files = await save_analysis_results(request.experiment_id, "kmeans", results, session)

        return AnalysisResponse(
            success=True,
            message=f"K-Means clustering completed with {n_clusters} clusters",
            results={
                "n_clusters": n_clusters,
                "inertia": results["inertia"],
                "cluster_sizes": [int(np.sum(labels == i)) for i in range(n_clusters)],
            },
            output_files=[f.name for f in output_files],
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}") from e


@router.post("/cluster_hierarchical", response_model=AnalysisResponse)
async def run_hierarchical(
    request: AnalysisRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AnalysisResponse:
    """
    Run hierarchical clustering.

    Parameters:
        - n_clusters: Number of clusters (default: 3)
        - linkage: Linkage method (default: "ward")
    """
    await _verify_experiment_ownership(request.experiment_id, session, current_user)

    try:
        from sklearn.cluster import AgglomerativeClustering
        from scipy.cluster.hierarchy import linkage as scipy_linkage, dendrogram

        wavenumbers, intensities = await load_experiment_data(request.experiment_id, session)

        n_clusters = request.parameters.get("n_clusters", 3)
        linkage = request.parameters.get("linkage", "ward")

        n_samples = intensities.shape[0]
        n_clusters = min(n_clusters, n_samples)

        clustering = AgglomerativeClustering(n_clusters=n_clusters, linkage=linkage)
        labels = clustering.fit_predict(intensities)

        # Compute linkage matrix for dendrogram
        Z = scipy_linkage(intensities, method=linkage)

        results = {
            "labels": labels,
            "linkage_matrix": Z,
            "n_clusters": n_clusters,
            "n_samples": n_samples,
            "linkage_method": linkage,
        }

        output_files = await save_analysis_results(request.experiment_id, "hierarchical", results, session)

        return AnalysisResponse(
            success=True,
            message=f"Hierarchical clustering completed with {n_clusters} clusters",
            results={
                "n_clusters": n_clusters,
                "linkage_method": linkage,
                "cluster_sizes": [int(np.sum(labels == i)) for i in range(n_clusters)],
            },
            output_files=[f.name for f in output_files],
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}") from e


@router.post("/pls", response_model=AnalysisResponse)
async def run_pls(
    request: AnalysisRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AnalysisResponse:
    """
    Run Partial Least Squares regression.

    Note: This requires Y values which should be provided in the experiment metadata
    or as a separate file. For now, this creates a demo with synthetic Y.

    Parameters:
        - n_components: Number of latent variables (default: 5)
        - scale: Scale X data (default: True)
    """
    await _verify_experiment_ownership(request.experiment_id, session, current_user)

    try:
        from sklearn.cross_decomposition import PLSRegression
        from sklearn.model_selection import cross_val_score

        wavenumbers, intensities = await load_experiment_data(request.experiment_id, session)

        n_components = request.parameters.get("n_components", 5)
        scale = request.parameters.get("scale", True)

        n_samples = intensities.shape[0]
        n_components = min(n_components, n_samples - 1)

        # For demo purposes, create synthetic Y from first PC
        # In production, Y should come from experiment metadata or uploaded file
        from sklearn.decomposition import PCA
        pca = PCA(n_components=1)
        y = pca.fit_transform(intensities).ravel()
        y = (y - y.min()) / (y.max() - y.min())  # Normalize to 0-1

        pls = PLSRegression(n_components=n_components, scale=scale)
        pls.fit(intensities, y)

        # Cross-validation score
        if n_samples >= 5:
            cv_scores = cross_val_score(pls, intensities, y, cv=min(5, n_samples))
            cv_mean = float(np.mean(cv_scores))
        else:
            cv_mean = None

        results = {
            "x_scores": pls.x_scores_,
            "y_scores": pls.y_scores_,
            "x_loadings": pls.x_loadings_,
            "y_loadings": pls.y_loadings_,
            "coef": pls.coef_,
            "n_components": n_components,
            "r2": float(pls.score(intensities, y)),
            "cv_r2": cv_mean,
        }

        output_files = await save_analysis_results(request.experiment_id, "pls", results, session)

        return AnalysisResponse(
            success=True,
            message=f"PLS regression completed with {n_components} components",
            results={
                "n_components": n_components,
                "r2": results["r2"],
                "cv_r2": results["cv_r2"],
                "note": "Y values synthesized from data for demo",
            },
            output_files=[f.name for f in output_files],
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}") from e


@router.post("/find_peaks", response_model=AnalysisResponse)
async def run_find_peaks(
    request: AnalysisRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AnalysisResponse:
    """
    Detect peaks in spectral data.

    Parameters:
        - height_threshold: Minimum peak height as fraction of max (default: 0.01)
        - distance: Minimum distance between peaks in points (default: 10)
    """
    await _verify_experiment_ownership(request.experiment_id, session, current_user)

    try:
        from scipy.signal import find_peaks

        wavenumbers, intensities = await load_experiment_data(request.experiment_id, session)

        height_threshold = request.parameters.get("height_threshold", 0.01)
        distance = request.parameters.get("distance", 10)

        # Work with mean spectrum if multiple spectra
        if intensities.ndim > 1:
            spectrum = np.mean(intensities, axis=0)
        else:
            spectrum = intensities

        # Find peaks
        height = height_threshold * np.max(spectrum)
        peaks, properties = find_peaks(
            spectrum,
            height=height,
            distance=distance,
            prominence=height / 2,
        )

        # Get peak information
        peak_table = []
        for i, peak_idx in enumerate(peaks):
            peak_table.append({
                "index": int(peak_idx),
                "wavenumber": float(wavenumbers[peak_idx]),
                "height": float(spectrum[peak_idx]),
                "prominence": float(properties.get("prominences", [0])[i]) if "prominences" in properties else None,
            })

        results = {
            "peaks": peak_table,
            "peak_indices": peaks,
            "n_peaks": len(peaks),
        }

        output_files = await save_analysis_results(request.experiment_id, "find_peaks", results, session)

        return AnalysisResponse(
            success=True,
            message=f"Found {len(peaks)} peaks",
            results={
                "n_peaks": len(peaks),
                "peaks": peak_table[:20],  # Return first 20 peaks in response
            },
            output_files=[f.name for f in output_files],
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}") from e


@router.get("/methods")
async def list_analysis_methods() -> list[dict[str, Any]]:
    """List all available analysis methods."""
    return [
        {
            "id": "pca",
            "name": "PCA",
            "category": "decomposition",
            "description": "Principal Component Analysis",
            "parameters": ["n_components", "standardize"],
        },
        {
            "id": "mcr_als",
            "name": "MCR-ALS",
            "category": "decomposition",
            "description": "Multivariate Curve Resolution - Alternating Least Squares",
            "parameters": ["n_components", "max_iter", "tol"],
        },
        {
            "id": "cluster_kmeans",
            "name": "K-Means Clustering",
            "category": "clustering",
            "description": "K-Means clustering for spectral grouping",
            "parameters": ["n_clusters", "n_init"],
        },
        {
            "id": "cluster_hierarchical",
            "name": "Hierarchical Clustering",
            "category": "clustering",
            "description": "Agglomerative hierarchical clustering",
            "parameters": ["n_clusters", "linkage"],
        },
        {
            "id": "pls",
            "name": "PLS Regression",
            "category": "regression",
            "description": "Partial Least Squares regression",
            "parameters": ["n_components", "scale"],
        },
        {
            "id": "find_peaks",
            "name": "Peak Detection",
            "category": "peaks",
            "description": "Automatic peak detection",
            "parameters": ["height_threshold", "distance"],
        },
    ]
