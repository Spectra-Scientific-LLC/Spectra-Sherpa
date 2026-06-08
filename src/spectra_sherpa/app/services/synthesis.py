from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import shutil
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

import httpx
import numpy as np
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.core.path_security import resolve_existing_file_path
from spectra_sherpa.app.lib.curves import evaluate_catmull_rom_samples
from spectra_sherpa.app.lib.jcamp_reader import parse_jcamp
from spectra_sherpa.app.lib.wavenumber_grid import (
    SAME_GRID_EPS_CM1,
    align_to_median_grid,
    median_spacing,
)
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.synthesis import (
    SynthesisComponentInput,
    SynthesisComponentResult,
    SynthesisComponentSummary,
    SynthesisRequest,
    SynthesisResult,
    SynthesisSaveRequest,
    SynthesisSaveResponse,
    SynthesisSpectrum,
    SynthesisSpectrumResponse,
    SynthesisVariant,
)
from spectra_sherpa.app.services.experiments import (
    add_experiment_file,
    create_experiment,
    experiment_dir,
)

logger = logging.getLogger(__name__)

NIST_SOURCE = "nist_quant_ir"
HITRAN_SOURCE = "hitran"
HITRAN_XSEC_SOURCE = "hitran_xsec"
DEFAULT_NIST_APODIZATION = "Blackman-Harris"
DEFAULT_HITRAN_RESOLUTION_CM1 = 1.0
DEFAULT_HITRAN_WAVENUMBER_MIN_CM1 = 2250.0
DEFAULT_HITRAN_WAVENUMBER_MAX_CM1 = 2400.0
DEFAULT_HITRAN_TEMPERATURE_K = 293.0
DEFAULT_HITRAN_PRESSURE_ATM = 1.0
SYNTHETIC_STAGE = "synthetic"
SYNTHETIC_FILE_TYPE = "application/x.spectra-sherpa.synthetic+npz"
SYNTHETIC_NPZ_SIGNATURE = "spectra_sherpa_synthetic_v1"
MAX_SYNTHESIS_OUTPUT_VALUES = 2_000_000
MAX_RESPONSE_SAMPLES = 50
MAX_RESPONSE_FEATURES = 2_000
_BOLTZMANN_J_PER_K = 1.380649e-23
_ATM_PA = 101325.0
_AVOGADRO_MOL = 6.02214076e23
HITRAN_CROSS_SECTION_UNITS = "cm^2 molecule^-1"
MOLAR_ABSORPTION_COEFFICIENT_UNITS = "L mol^-1 cm^-1"
HITRAN_CROSS_SECTION_TO_MOLAR_ABSORPTIVITY = _AVOGADRO_MOL / (1000.0 * math.log(10.0))
_NIST_WEBBOOK_URL = "https://webbook.nist.gov/cgi/cbook.cgi"
_SECRET_QUERY_RE = re.compile(r"(?i)(api[_-]?key|apikey|key|token|access[_-]?token)=([^&\s]+)")
_AUTHORIZATION_RE = re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s]+")
_HAPI2_LOCK = threading.Lock()
_NIST_APODIZATION_INDEX = {
    "boxcar": 0,
    "triangular": 5,
    "happ genzel": 10,
    "happ-genzel": 10,
    "3-term blackmann-harris": 15,
    "3-term blackman-harris": 15,
    "blackman-harris": 15,
    "blackmann-harris": 15,
    "norton beer strong": 20,
    "norton-beer-strong": 20,
}
_NIST_RESOLUTION_INDEX = {2.0: 0, 1.0: 1, 0.5: 2, 0.25: 3, 0.125: 4}
_HITRAN_HAPI_LOCK = asyncio.Lock()
_MISSING = object()
_HITRAN_LBL_MOLECULES: tuple[tuple[int, str, str], ...] = (
    (1, "H2O", "Water"),
    (2, "CO2", "Carbon dioxide"),
    (3, "O3", "Ozone"),
    (4, "N2O", "Nitrous oxide"),
    (5, "CO", "Carbon monoxide"),
    (6, "CH4", "Methane"),
    (7, "O2", "Oxygen"),
    (8, "NO", "Nitric oxide"),
    (9, "SO2", "Sulfur dioxide"),
    (10, "NO2", "Nitrogen dioxide"),
    (11, "NH3", "Ammonia"),
    (12, "HNO3", "Nitric acid"),
    (13, "OH", "Hydroxyl"),
    (14, "HF", "Hydrogen fluoride"),
    (15, "HCl", "Hydrogen chloride"),
    (16, "HBr", "Hydrogen bromide"),
    (17, "HI", "Hydrogen iodide"),
    (18, "ClO", "Chlorine monoxide"),
    (19, "OCS", "Carbonyl sulfide"),
    (20, "H2CO", "Formaldehyde"),
    (21, "HOCl", "Hypochlorous acid"),
    (22, "N2", "Nitrogen"),
    (23, "HCN", "Hydrogen cyanide"),
    (24, "CH3Cl", "Methyl chloride"),
    (25, "H2O2", "Hydrogen peroxide"),
    (26, "C2H2", "Acetylene"),
    (27, "C2H6", "Ethane"),
    (28, "PH3", "Phosphine"),
    (29, "COF2", "Carbonyl fluoride"),
    (30, "SF6", "Sulfur hexafluoride"),
    (31, "H2S", "Hydrogen sulfide"),
    (32, "HCOOH", "Formic acid"),
    (33, "HO2", "Hydroperoxyl"),
    (34, "O", "Oxygen atom"),
    (35, "ClONO2", "Chlorine nitrate"),
    (36, "NO+", "Nitric oxide cation"),
    (37, "HOBr", "Hypobromous acid"),
    (38, "C2H4", "Ethylene"),
    (39, "CH3OH", "Methanol"),
    (40, "CH3Br", "Methyl bromide"),
    (41, "CH3CN", "Acetonitrile"),
    (42, "CF4", "PFC-14"),
    (43, "C4H2", "Diacetylene"),
    (44, "HC3N", "Cyanoacetylene"),
    (45, "H2", "Hydrogen"),
    (46, "CS", "Carbon monosulfide"),
    (47, "SO3", "Sulfur trioxide"),
    (48, "C2N2", "Cyanogen"),
    (49, "COCl2", "Phosgene"),
    (50, "SO", "Sulfur monoxide"),
    (51, "CH3F", "Methyl fluoride"),
    (52, "GeH4", "Germane"),
    (53, "CS2", "Carbon disulfide"),
    (54, "CH3I", "Methyl iodide"),
    (55, "NF3", "Nitrogen trifluoride"),
    (56, "H3+", "Trihydrogen cation"),
    (57, "CH3", "Methyl radical"),
    (58, "S2", "Sulfur dimer"),
    (59, "COFCl", "Carbonyl chlorofluoride"),
    (60, "HONO", "Nitrous acid"),
    (61, "ClNO2", "Nitryl chloride"),
)
_HITRAN_SPECIAL_NOTATION_EXCLUSIONS = {30, 35, 42, 55}


class SynthesisError(ValueError):
    """Raised when a synthesis recipe is physically or structurally invalid."""


@dataclass(frozen=True)
class _AlignedComponent:
    component: SynthesisComponentInput
    wavenumber: np.ndarray
    intensity: np.ndarray


def list_sources(*, hitran_available: bool | None = None) -> list[dict[str, object]]:
    if hitran_available is None:
        hitran_available = _hitran_import_available()
    return [
        {
            "id": NIST_SOURCE,
            "label": "NIST Quantitative IR",
            "kind": "offline_manifest_live_fetch",
            "requires_key": False,
            "default_resolution_cm1": 1.0,
            "default_apodization": DEFAULT_NIST_APODIZATION,
        },
        {
            "id": HITRAN_SOURCE,
            "label": "HITRAN Line-by-Line",
            "kind": "optional_hapi_line_by_line",
            "requires_key": True,
            "available": hitran_available,
            "default_resolution_cm1": DEFAULT_HITRAN_RESOLUTION_CM1,
            "default_profile": "Voigt",
            "default_temperature_k": DEFAULT_HITRAN_TEMPERATURE_K,
            "default_pressure_atm": DEFAULT_HITRAN_PRESSURE_ATM,
        },
        {
            "id": HITRAN_XSEC_SOURCE,
            "label": "HITRAN Absorption X-section",
            "kind": "optional_hapi_cross_section",
            "requires_key": True,
            "available": hitran_available,
        },
    ]


def search_components(source: str, query: str = "", *, limit: int = 25) -> list[SynthesisComponentSummary]:
    source = _normalize_source(source)
    query_lower = query.strip().lower()
    if source == NIST_SOURCE:
        records = _load_nist_manifest().get("components", [])
    elif source == HITRAN_SOURCE:
        records = _static_hitran_catalog()
    elif source == HITRAN_XSEC_SOURCE:
        records = _hitran_xsec_records()
    else:
        raise SynthesisError(f"Unsupported synthesis source: {source}")

    matches: list[SynthesisComponentSummary] = []
    for record in records:
        haystack = " ".join(
            str(record.get(key) or "") for key in ("id", "name", "cas", "formula", "molecule_number")
        ).lower()
        if query_lower and query_lower not in haystack:
            continue
        matches.append(_summary_from_record(source, record))
        if len(matches) >= limit:
            break
    return matches


def get_component_summary(source: str, component_id: str) -> SynthesisComponentSummary:
    source = _normalize_source(source)
    if source == NIST_SOURCE:
        records = _load_nist_manifest().get("components", [])
    elif source == HITRAN_SOURCE:
        records = _static_hitran_catalog()
    elif source == HITRAN_XSEC_SOURCE:
        records = _hitran_xsec_records()
        component_id = _hitran_xsec_base_id(component_id)
    else:
        records = []
    for record in records:
        if str(record.get("id")) == component_id:
            return _summary_from_record(source, record)
    raise SynthesisError(f"Unknown synthesis component: {component_id}")


async def get_component_spectrum(
    source: str,
    component_id: str,
    *,
    resolution_cm1: float | None = None,
    apodization: str | None = None,
    wavenumber_min: float | None = None,
    wavenumber_max: float | None = None,
    temperature_k: float = DEFAULT_HITRAN_TEMPERATURE_K,
    pressure_atm: float = DEFAULT_HITRAN_PRESSURE_ATM,
    hitran_api_key: str | None = None,
) -> SynthesisSpectrumResponse:
    source = _normalize_source(source)
    if source == NIST_SOURCE:
        return await _get_nist_component_spectrum(
            component_id,
            resolution_cm1=resolution_cm1,
            apodization=apodization,
            wavenumber_min=wavenumber_min,
            wavenumber_max=wavenumber_max,
        )
    if source == HITRAN_SOURCE:
        return await _get_hitran_component_spectrum(
            component_id,
            resolution_cm1=resolution_cm1 or DEFAULT_HITRAN_RESOLUTION_CM1,
            wavenumber_min=wavenumber_min or DEFAULT_HITRAN_WAVENUMBER_MIN_CM1,
            wavenumber_max=wavenumber_max or DEFAULT_HITRAN_WAVENUMBER_MAX_CM1,
            temperature_k=temperature_k,
            pressure_atm=pressure_atm,
            api_key=hitran_api_key,
        )
    if source == HITRAN_XSEC_SOURCE:
        return await _get_hitran_xsec_component_spectrum(
            component_id,
            wavenumber_min=wavenumber_min,
            wavenumber_max=wavenumber_max,
            temperature_k=temperature_k,
            pressure_atm=pressure_atm,
            api_key=hitran_api_key,
        )
    raise SynthesisError(f"Unsupported synthesis source: {source}")


def is_component_spectrum_cached(
    source: str,
    component_id: str,
    *,
    resolution_cm1: float | None = None,
    apodization: str | None = None,
    wavenumber_min: float | None = None,
    wavenumber_max: float | None = None,
    temperature_k: float = DEFAULT_HITRAN_TEMPERATURE_K,
    pressure_atm: float = DEFAULT_HITRAN_PRESSURE_ATM,
) -> bool:
    source = _normalize_source(source)
    if source == NIST_SOURCE:
        summary = get_component_summary(NIST_SOURCE, component_id)
        variant = _select_nist_variant(summary, resolution_cm1=resolution_cm1, apodization=apodization)
        return _nist_cache_path(component_id, variant.resolution_cm1, variant.apodization).exists()
    if source == HITRAN_SOURCE:
        wmin = float(wavenumber_min or DEFAULT_HITRAN_WAVENUMBER_MIN_CM1)
        wmax = float(wavenumber_max or DEFAULT_HITRAN_WAVENUMBER_MAX_CM1)
        return _hitran_spectrum_cache_path(
            component_id,
            resolution_cm1=float(resolution_cm1 or DEFAULT_HITRAN_RESOLUTION_CM1),
            wavenumber_min=wmin,
            wavenumber_max=wmax,
            temperature_k=float(temperature_k),
            pressure_atm=float(pressure_atm),
        ).exists()
    if source == HITRAN_XSEC_SOURCE:
        record, option = _hitran_xsec_record_and_option(component_id)
        wmin, wmax = _hitran_xsec_effective_range(record, option, wavenumber_min, wavenumber_max)
        target_temperature = _hitran_xsec_effective_temperature(option, temperature_k)
        target_pressure = _hitran_xsec_effective_pressure_atm(option, pressure_atm)
        return _hitran_xsec_spectrum_cache_path(
            component_id,
            wavenumber_min=wmin,
            wavenumber_max=wmax,
            temperature_k=target_temperature,
            pressure_atm=target_pressure,
        ).exists()
    return False


def default_hitran_component_ids() -> list[str]:
    return [str(record["id"]) for record in _static_hitran_catalog()]


def normalize_hitran_component_id(component_id: str) -> str:
    value = str(component_id).strip()
    if not value:
        raise SynthesisError("HITRAN component id cannot be empty")
    if value.startswith("hitran:"):
        return value
    if value.isdigit():
        return f"hitran:{value}"
    value_lower = value.lower()
    for record in _static_hitran_catalog():
        if value_lower in {
            str(record["name"]).lower(),
            str(record.get("formula") or "").lower(),
            str(record.get("id") or "").lower(),
        }:
            return str(record["id"])
    raise SynthesisError(f"Unknown HITRAN component: {component_id}")


async def prewarm_hitran_default_library(
    api_key: str,
    *,
    component_ids: list[str] | None = None,
    temperature_k: float = DEFAULT_HITRAN_TEMPERATURE_K,
    pressure_atm: float = DEFAULT_HITRAN_PRESSURE_ATM,
    resolution_cm1: float = DEFAULT_HITRAN_RESOLUTION_CM1,
    wavenumber_min: float = DEFAULT_HITRAN_WAVENUMBER_MIN_CM1,
    wavenumber_max: float = DEFAULT_HITRAN_WAVENUMBER_MAX_CM1,
    force: bool = False,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Populate the user-local default HITRAN computed-spectrum cache."""

    if not api_key or not api_key.strip():
        raise SynthesisError("HITRAN API key is required to prewarm the default synthesis library")
    ids = [normalize_hitran_component_id(item) for item in (component_ids or default_hitran_component_ids())]
    results: list[dict[str, Any]] = []
    total = len(ids)
    for index, component_id in enumerate(ids, start=1):
        summary = get_component_summary(HITRAN_SOURCE, component_id)
        entry: dict[str, Any] = {
            "component_id": component_id,
            "name": summary.name,
            "index": index,
            "total": total,
        }
        if not force and is_component_spectrum_cached(
            HITRAN_SOURCE,
            component_id,
            resolution_cm1=resolution_cm1,
            wavenumber_min=wavenumber_min,
            wavenumber_max=wavenumber_max,
            temperature_k=temperature_k,
            pressure_atm=pressure_atm,
        ):
            entry["status"] = "cached"
            results.append(entry)
            if progress is not None:
                progress(entry)
            continue
        try:
            spectrum = await get_component_spectrum(
                HITRAN_SOURCE,
                component_id,
                resolution_cm1=resolution_cm1,
                wavenumber_min=wavenumber_min,
                wavenumber_max=wavenumber_max,
                temperature_k=temperature_k,
                pressure_atm=pressure_atm,
                hitran_api_key=api_key.strip(),
            )
            entry.update(
                {
                    "status": "generated",
                    "n_points": len(spectrum.wavenumber),
                    "cached": spectrum.cached,
                }
            )
        except Exception as exc:  # pragma: no cover - network/package dependent
            entry.update({"status": "failed", "error": str(exc)})
        results.append(entry)
        if progress is not None:
            progress(entry)
    return results


async def validate_hitran_api_key(api_key: str) -> None:
    """Validate HITRAN credentials with a lightweight provider catalog request."""
    key = api_key.strip()
    if not key:
        raise SynthesisError("HITRAN API key is required.")
    try:
        await asyncio.to_thread(_validate_hitran_api_key_blocking, key)
    except SynthesisError:
        raise
    except Exception as exc:  # pragma: no cover - provider/package dependent
        detail = _sanitize_provider_error(exc, api_key=key)
        logger.warning("HITRAN API key validation failed: %s", detail, exc_info=True)
        raise SynthesisError(f"HITRAN key validation failed: {detail}") from exc


def _validate_hitran_api_key_blocking(api_key: str) -> None:
    cache_dir = _synthesis_cache_dir("hitran") / "hapi2"
    cache_dir.mkdir(parents=True, exist_ok=True)
    hapi2 = _import_hapi2_module(cache_dir)
    original_cwd = Path.cwd()
    with _HAPI2_LOCK:
        with _temporary_hapi_api_key(hapi2, api_key):
            settings_obj = getattr(hapi2, "SETTINGS", None)
            previous_display = _MISSING
            if isinstance(settings_obj, dict):
                previous_display = settings_obj.get("display_fetch_url", _MISSING)
                settings_obj["display_fetch_url"] = False
            try:
                os.chdir(cache_dir)
                hapi2.fetch_info()
                molecules = hapi2.fetch_molecules()
                if hasattr(molecules, "__len__") and len(molecules) == 0:
                    raise SynthesisError("HITRAN validation returned an empty molecule catalog.")
            finally:
                os.chdir(original_cwd)
                if isinstance(settings_obj, dict):
                    if previous_display is _MISSING:
                        settings_obj.pop("display_fetch_url", None)
                    else:
                        settings_obj["display_fetch_url"] = previous_display


def compute_common_nist_variant(component_ids: list[str]) -> dict[str, object]:
    """Resolve the common NIST grid variant for a component basket.

    Preference order is the chemist-facing canonical variant:
    Blackman-Harris if all selected components have it, then the coarsest
    available common resolution. The caller still needs actual spectra to crop
    to the overlapping wavenumber span.
    """

    records = {str(c["id"]): c for c in _load_nist_manifest().get("components", [])}
    if not component_ids:
        raise SynthesisError("At least one component is required")
    common: set[tuple[float, str]] | None = None
    for component_id in component_ids:
        record = records.get(component_id)
        if record is None:
            raise SynthesisError(f"Unknown NIST Quant IR component: {component_id}")
        variants = {
            (float(v["resolution_cm1"]), str(v["apodization"]))
            for v in record.get("variants", [])
            if "resolution_cm1" in v and "apodization" in v
        }
        common = variants if common is None else common & variants
    if not common:
        raise SynthesisError("Selected NIST components do not share a common resolution/apodization")
    blackman = [v for v in common if v[1].lower() == DEFAULT_NIST_APODIZATION.lower()]
    candidates = blackman or list(common)
    resolution_cm1, apodization = max(candidates, key=lambda item: item[0])
    return {"resolution_cm1": resolution_cm1, "apodization": apodization}


def synthesize(request: SynthesisRequest) -> SynthesisResult:
    source = _normalize_source(request.settings.source)
    if any(_normalize_source(component.spectrum.source) != source for component in request.components):
        raise SynthesisError("All synthesis components must use the selected source")

    aligned, grid_info = _align_components(
        request.components,
        snap_tolerance=request.settings.snap_tolerance_cm1,
        range_mode=request.settings.range_mode,
        resolution_cm1=request.settings.resolution_cm1,
        preview_wavenumber_min=request.settings.preview_wavenumber_min,
        preview_wavenumber_max=request.settings.preview_wavenumber_max,
        preview_wavenumber_interval_cm1=request.settings.preview_wavenumber_interval_cm1,
    )
    wavenumber = aligned[0].wavenumber
    n_samples = int(request.settings.n_samples)
    output_values = n_samples * int(wavenumber.size)
    if output_values > MAX_SYNTHESIS_OUTPUT_VALUES:
        raise SynthesisError(
            "Synthetic output is too large for interactive generation "
            f"({n_samples} samples x {wavenumber.size} features). "
            "Reduce samples or wavenumber range."
        )
    concentration = np.vstack(
        [
            evaluate_catmull_rom_ppm(
                item.component.effective_ppm_points(),
                n_samples=n_samples,
            )
            for item in aligned
        ]
    ).T

    spectra = np.vstack([item.intensity for item in aligned])
    if source == NIST_SOURCE:
        # NIST Quant IR coefficients are decadic: A10(nu)=a(nu)*ppm*L_m.
        pathlength_m = float(request.settings.pathlength_cm) / 100.0
        absorbance = concentration @ spectra * pathlength_m
    elif source in {HITRAN_SOURCE, HITRAN_XSEC_SOURCE}:
        # HITRAN/HAPI cross sections are treated as napierian cm^2/molecule.
        # ppm -> molecules/cm^3 via ideal gas law; A10=tau/ln(10).
        number_density_cm3 = _ppm_to_number_density_cm3(
            concentration,
            temperature_k=request.settings.temperature_k,
            pressure_atm=request.settings.pressure_atm,
        )
        optical_depth = number_density_cm3 @ spectra * float(request.settings.pathlength_cm)
        absorbance = optical_depth / math.log(10.0)
    else:  # pragma: no cover - guarded by _normalize_source
        raise SynthesisError(f"Unsupported synthesis source: {source}")

    seed = request.settings.seed
    if request.settings.noise_sigma_au > 0:
        if seed is None:
            seed = int(np.random.default_rng().integers(0, np.iinfo(np.int32).max))
        rng = np.random.default_rng(seed)
        absorbance = absorbance + rng.normal(0.0, request.settings.noise_sigma_au, size=absorbance.shape)

    recipe = _build_recipe(request, wavenumber=wavenumber, seed=seed, grid_info=grid_info)
    ground_truth = {
        "C": concentration.tolist(),
        "C_units": "ppm",
        "S": spectra.tolist(),
        "S_units": [_component_units(item.component.spectrum) for item in aligned],
        "component_ids": [item.component.component_id for item in aligned],
        "component_names": [_component_name(item.component) for item in aligned],
        "grid": grid_info,
    }
    components = [
        SynthesisComponentResult(
            id=item.component.component_id,
            name=_component_name(item.component),
            concentration_ppm=concentration[:, index].tolist(),
        )
        for index, item in enumerate(aligned)
    ]
    return SynthesisResult(
        source=source,  # type: ignore[arg-type]
        wavenumber=wavenumber.tolist(),
        absorbance=absorbance.tolist(),
        components=components,
        recipe=recipe,
        ground_truth=ground_truth,
    )


def truncate_result_for_response(
    result: SynthesisResult,
    *,
    max_samples: int = MAX_RESPONSE_SAMPLES,
    max_features: int = MAX_RESPONSE_FEATURES,
) -> SynthesisResult:
    """Return a bounded response copy while preserving full saved artifacts."""

    sample_count = len(result.absorbance)
    feature_count = len(result.wavenumber)
    if sample_count <= max_samples and feature_count <= max_features:
        return result
    sample_indices = _even_indices(sample_count, max_samples)
    feature_indices = _even_indices(feature_count, max_features)
    absorbance = np.asarray(result.absorbance, dtype=float)
    ground_truth = dict(result.ground_truth)
    if "C" in ground_truth:
        ground_truth["C"] = np.asarray(ground_truth["C"], dtype=float)[sample_indices, :].tolist()
    if "S" in ground_truth:
        ground_truth["S"] = np.asarray(ground_truth["S"], dtype=float)[:, feature_indices].tolist()
    ground_truth["truncated"] = True
    return result.model_copy(
        update={
            "wavenumber": [result.wavenumber[i] for i in feature_indices],
            "absorbance": absorbance[np.ix_(sample_indices, feature_indices)].tolist(),
            "components": [
                component.model_copy(
                    update={
                        "concentration_ppm": [component.concentration_ppm[i] for i in sample_indices],
                    }
                )
                for component in result.components
            ],
            "ground_truth": ground_truth,
            "truncated": True,
        }
    )


async def save_synthesis_result(
    session: AsyncSession,
    current_user: User,
    request: SynthesisSaveRequest,
) -> SynthesisSaveResponse:
    result = synthesize(request)
    if request.project_id is not None:
        project = (
            await session.execute(
                select(Project).where(
                    Project.id == request.project_id,
                    Project.user_id == current_user.id,
                )
            )
        ).scalar_one_or_none()
        if project is None:
            raise SynthesisError("Project is not accessible for this user")
    experiment_id = request.experiment_id
    if experiment_id is None:
        experiment = await create_experiment(
            session,
            user_id=current_user.id,
            name=request.name or _default_dataset_name(result),
            description="Synthetic FTIR dataset generated from component spectra",
            metadata={
                "source": "synthesis",
                "synthesis_source": result.source,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "builder_state": {
                    "kind": "synthesis_recipe",
                    "version": 1,
                    "title": request.name or _default_dataset_name(result),
                    "recipe": result.recipe,
                },
            },
            project_id=request.project_id,
        )
        experiment_id = experiment.id
    else:
        existing = (
            await session.execute(
                select(Experiment).where(
                    Experiment.id == experiment_id,
                    Experiment.user_id == current_user.id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise SynthesisError("Experiment is not accessible for this user")
        if request.project_id is not None and existing.project_id != request.project_id:
            raise SynthesisError("Experiment does not belong to the requested project")

    base = experiment_dir(experiment_id) / SYNTHETIC_STAGE
    base.mkdir(parents=True, exist_ok=True)
    stem = _safe_stem(request.name or _default_dataset_name(result))
    npz_path, recipe_path = _unique_synthesis_artifact_paths(base, stem)
    _write_synthesis_npz(npz_path, result, title=request.name or _default_dataset_name(result))
    recipe_path.write_text(json.dumps({"recipe": result.recipe, "ground_truth": result.ground_truth}, indent=2))

    relative_file_path = f"{SYNTHETIC_STAGE}/{npz_path.name}"
    file_record = await add_experiment_file(
        session,
        experiment_id=experiment_id,
        stage=SYNTHETIC_STAGE,
        file_path=relative_file_path,
        file_size_bytes=npz_path.stat().st_size,
        file_type=SYNTHETIC_FILE_TYPE,
    )
    return SynthesisSaveResponse(
        experiment_id=experiment_id,
        file_id=file_record.id,
        file_path=relative_file_path,
        recipe_path=recipe_path.relative_to(settings.data_dir).as_posix(),
        result=result,
    )


def evaluate_catmull_rom_ppm(points: list[tuple[float, float]], *, n_samples: int) -> np.ndarray:
    """Synthesis-facing wrapper over :func:`lib.curves.evaluate_catmull_rom_samples`.

    Keeps the public ``SynthesisError`` contract (a ``ValueError`` subclass that
    the API layer maps to a 4xx) while the curve math itself lives in a single
    place. Numerically identical to the previous in-module implementation.
    """
    try:
        return evaluate_catmull_rom_samples(points, n_samples=n_samples)
    except ValueError as exc:
        raise SynthesisError(str(exc)) from exc


def load_synthetic_npz(path: str | Path) -> dict[str, Any]:
    with np.load(path, allow_pickle=False) as data:
        if not _npz_has_synthesis_signature(data):
            raise ValueError("NPZ file is not a SpectraSherpa synthetic dataset")
        payload = {
            "X": np.asarray(data["X"], dtype=float),
            "wavenumber": np.asarray(data["wavenumber"], dtype=float),
            "C": np.asarray(data["C"], dtype=float),
            "S": np.asarray(data["S"], dtype=float),
            "sample_labels": [str(x) for x in data["sample_labels"].tolist()],
            "feature_units": str(data["feature_units"].item()),
            "units": str(data["units"].item()),
            "recipe_json": str(data["recipe_json"].item()),
            "ground_truth_json": str(data["ground_truth_json"].item()),
            "metadata": _read_synthesis_npz_metadata(data),
        }
    return _normalize_synthetic_npz_payload(payload)


def is_synthetic_npz(path: str | Path) -> bool:
    try:
        with np.load(path, allow_pickle=False) as data:
            return _npz_has_synthesis_signature(data)
    except Exception:
        return False


def _ground_truth_metadata_for_npz(ground_truth: dict[str, Any]) -> dict[str, Any]:
    """Ground-truth JSON stores labels/units/grid metadata; arrays live in C/S."""

    return {key: value for key, value in ground_truth.items() if key not in {"C", "S"}}


def _write_synthesis_npz(path: Path, result: SynthesisResult, *, title: str | None = None) -> None:
    X = np.asarray(result.absorbance, dtype=np.float64)
    C = np.asarray(result.ground_truth["C"], dtype=np.float64)
    S = np.asarray(result.ground_truth["S"], dtype=np.float64)
    sample_labels = np.asarray([f"sample_{i + 1:03d}" for i in range(X.shape[0])])
    metadata = _default_synthesis_npz_metadata(result, title=title)
    ground_truth_metadata = _ground_truth_metadata_for_npz(result.ground_truth)
    np.savez_compressed(
        path,
        spectra_sherpa_synthetic=np.asarray(SYNTHETIC_NPZ_SIGNATURE),
        X=X,
        wavenumber=np.asarray(result.wavenumber, dtype=np.float64),
        C=C,
        S=S,
        sample_labels=sample_labels,
        feature_units=np.asarray("cm^-1"),
        units=np.asarray("absorbance"),
        recipe_json=np.asarray(json.dumps(result.recipe)),
        ground_truth_json=np.asarray(json.dumps(ground_truth_metadata)),
        metadata_json=np.asarray(json.dumps(metadata)),
    )


def _resolve_synthetic_npz_path(path: str | Path) -> Path:
    return resolve_existing_file_path(
        path,
        label="Synthetic NPZ",
        suffixes={".npz"},
        restrict_to_data_dir_in_multi_user=True,
    )


def update_synthetic_npz_metadata(path: str | Path, updates: dict[str, Any]) -> None:
    """Merge user-facing metadata edits into a synthetic npz artifact.

    Prepared-data sidecars are still written for every file type.  Synthetic
    npz files are SpectraSherpa-authored artifacts, so we also embed the edited
    metadata directly in the archive to make the file self-describing when it
    is loaded later by the workflow My Dataset node or moved with a project
    export.
    """
    path = _resolve_synthetic_npz_path(path)
    with np.load(path, allow_pickle=False) as data:
        if not _npz_has_synthesis_signature(data):
            raise ValueError("NPZ file is not a SpectraSherpa synthetic dataset")
        arrays = {key: np.asarray(data[key]) for key in data.files if key != "metadata_json"}
        metadata = _read_synthesis_npz_metadata(data)

    for key in ("title", "x_title", "x_units", "y_title", "is_time_series", "data_role"):
        value = updates.get(key)
        if value is not None:
            metadata[key] = value
    if updates.get("y_title") is not None:
        metadata["data_quantity"] = updates["y_title"]

    tmp_path = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    np.savez_compressed(tmp_path, **arrays, metadata_json=np.asarray(json.dumps(metadata)))
    tmp_npz = tmp_path.with_suffix(tmp_path.suffix + ".npz")
    # codeql[py/path-injection]
    if tmp_npz.exists():
        tmp_path = tmp_npz
    if tmp_path.parent != path.parent:
        raise ValueError("Synthetic NPZ temporary file resolved outside the artifact directory")
    # codeql[py/path-injection]
    os.replace(tmp_path, path)


def _default_synthesis_npz_metadata(result: SynthesisResult, *, title: str | None = None) -> dict[str, Any]:
    return {
        "title": title,
        "source": "synthesis",
        "synthesis_source": result.source,
        "x_title": "Wavenumber",
        "x_units": "cm^-1",
        "y_title": "Sample",
        "data_quantity": "Absorbance",
        "value_units": result.units or "absorbance",
        "data_role": "X_spectra",
        "is_time_series": False,
    }


def _read_synthesis_npz_metadata(data: np.lib.npyio.NpzFile) -> dict[str, Any]:
    if "metadata_json" not in data.files:
        return {}
    try:
        raw = str(data["metadata_json"].item())
        parsed = json.loads(raw)
    except Exception:
        logger.warning("Failed to parse synthetic npz metadata_json", exc_info=True)
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_hitran_cross_section_units(value: Any) -> bool:
    normalized = str(value or "").strip().lower().replace("²", "^2").replace("⁻¹", "^-1")
    normalized = normalized.replace("⋅", " ").replace("/", " ")
    return "cm^2" in normalized and ("molecule" in normalized or "particle" in normalized)


def _molar_absorptivity_from_cross_section(values: Any) -> np.ndarray:
    return np.asarray(values, dtype=float) * HITRAN_CROSS_SECTION_TO_MOLAR_ABSORPTIVITY


def hitran_cross_section_to_molar_absorptivity(values: Any) -> np.ndarray:
    """Convert HITRAN cross-section values to decadic molar absorptivity."""

    return _molar_absorptivity_from_cross_section(values)


def is_hitran_cross_section_units(value: Any) -> bool:
    return _is_hitran_cross_section_units(value)


def _normalize_synthetic_npz_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Patch legacy synthetic-library metadata on read.

    The atmospheric benchmark stores mixture absorbance in X. Its paired
    component-library file stores HITRAN pure-component absorption cross
    sections in X/S. Normalize legacy cross-section payloads to decadic molar
    absorption coefficient, while leaving synthetic mixture X as absorbance.
    """

    try:
        ground_truth = json.loads(str(payload.get("ground_truth_json") or "{}"))
    except (TypeError, ValueError):
        ground_truth = {}
    if not isinstance(ground_truth, dict):
        return payload

    metadata = dict(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {})
    s_units = ground_truth.get("S_units")
    legacy_s_units = (
        isinstance(s_units, list)
        and any(_is_hitran_cross_section_units(unit) for unit in s_units)
        or _is_hitran_cross_section_units(payload.get("units"))
        or _is_hitran_cross_section_units(metadata.get("value_units"))
    )
    if not legacy_s_units:
        return payload

    is_component_library = ground_truth.get("role") == "pure_component_library"
    spectra = np.asarray(payload.get("S"), dtype=float)
    if spectra.ndim == 2 and spectra.size:
        payload["S"] = _molar_absorptivity_from_cross_section(spectra)
        if isinstance(ground_truth.get("S"), list):
            ground_truth["S"] = payload["S"].tolist()

    n_spectra = int(payload["S"].shape[0]) if isinstance(payload.get("S"), np.ndarray) and payload["S"].ndim == 2 else 0
    ground_truth["S_units"] = [MOLAR_ABSORPTION_COEFFICIENT_UNITS] * n_spectra
    payload["ground_truth_json"] = json.dumps(ground_truth)

    if not is_component_library:
        return payload

    payload["X"] = _molar_absorptivity_from_cross_section(payload.get("X"))
    payload["units"] = MOLAR_ABSORPTION_COEFFICIENT_UNITS
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    metadata = dict(metadata)
    metadata["data_quantity"] = "Molar absorption coefficient"
    metadata["value_units"] = MOLAR_ABSORPTION_COEFFICIENT_UNITS
    payload["metadata"] = metadata
    return payload


def _align_components(
    components: list[SynthesisComponentInput],
    *,
    snap_tolerance: float,
    range_mode: str,
    resolution_cm1: float | None = None,
    preview_wavenumber_min: float | None = None,
    preview_wavenumber_max: float | None = None,
    preview_wavenumber_interval_cm1: float | None = None,
) -> tuple[list[_AlignedComponent], dict[str, Any]]:
    """Align component spectra onto a synthesis grid.

    NIST spectra keep the historical snap-to-median behavior because they are
    already sampled at a common nominal resolution. HITRAN line-by-line spectra
    often have the same spacing but different absolute phase, so they are
    binned into the requested resolution intervals before Beer-Lambert
    addition. HITRAN xsec spectra preserve explicit zero gaps between measured
    bands.
    """
    arrays = []
    mins = []
    maxs = []
    diagnostics: list[dict[str, Any]] = []
    for component in components:
        x = np.asarray(component.spectrum.wavenumber, dtype=float)
        y = np.asarray(component.spectrum.intensity, dtype=float)
        if x.ndim != 1 or y.ndim != 1 or len(x) != len(y):
            raise SynthesisError(f"Invalid spectrum shape for {component.component_id}")
        order = np.argsort(x)
        x_sorted = x[order]
        y_sorted = y[order]
        if np.any(np.diff(x_sorted) <= 0):
            raise SynthesisError(f"Spectrum wavenumber grid must be strictly monotonic for {component.component_id}")
        arrays.append((component, x_sorted, y_sorted))
        mins.append(float(x_sorted[0]))
        maxs.append(float(x_sorted[-1]))
        diagnostics.append(
            {
                "id": component.component_id,
                "name": _component_name(component),
                "native_n_points": int(x_sorted.size),
                "native_spacing_cm1": median_spacing(x_sorted),
                "native_min_cm1": float(x_sorted[0]),
                "native_max_cm1": float(x_sorted[-1]),
                "shifted": False,
                "max_shift_cm1": 0.0,
            }
        )

    if _all_hitran_line_by_line(arrays):
        base_min = min(mins) if range_mode == "widest" else max(mins)
        base_max = max(maxs) if range_mode == "widest" else min(maxs)
        if base_min >= base_max:
            latest_start = max(diagnostics, key=lambda item: float(item["native_min_cm1"]))
            earliest_end = min(diagnostics, key=lambda item: float(item["native_max_cm1"]))
            raise SynthesisError(
                "Selected components do not have an overlapping wavenumber range. "
                f"Latest start: {latest_start['name']} at {float(latest_start['native_min_cm1']):.4g} cm^-1; "
                f"earliest end: {earliest_end['name']} at {float(earliest_end['native_max_cm1']):.4g} cm^-1. "
                "Use widest range or remove one of those spectra."
            )
        return _align_hitran_line_by_line_to_resolution_bins(
            arrays,
            diagnostics,
            range_mode=range_mode,
            reference_min=base_min,
            reference_max=base_max,
            resolution_cm1=resolution_cm1,
            preview_wavenumber_min=preview_wavenumber_min,
            preview_wavenumber_max=preview_wavenumber_max,
        )

    if range_mode == "widest":
        base_min = min(mins)
        base_max = max(maxs)
        if preview_wavenumber_interval_cm1 is not None:
            return _align_components_to_requested_interval_grid(
                arrays,
                diagnostics,
                snap_tolerance=snap_tolerance,
                range_mode=range_mode,
                base_min=base_min,
                base_max=base_max,
                preview_wavenumber_min=preview_wavenumber_min,
                preview_wavenumber_max=preview_wavenumber_max,
                interval_cm1=preview_wavenumber_interval_cm1,
            )
        aligned, grid_info = _align_components_to_widest_range(
            arrays,
            diagnostics,
            snap_tolerance=snap_tolerance,
            union_min=base_min,
            union_max=base_max,
        )
        return _apply_preview_wavenumber_window(
            aligned,
            grid_info,
            preview_wavenumber_min=preview_wavenumber_min,
            preview_wavenumber_max=preview_wavenumber_max,
        )

    common_min = max(mins)
    common_max = min(maxs)

    if preview_wavenumber_interval_cm1 is not None:
        # Requested interval grids are defined by the preview min/max controls.
        # Allow those requested bin centers to sit just outside the strict
        # native overlap when every species has a nearest point inside snap.
        interval_common_min = common_min
        if preview_wavenumber_min is not None:
            interval_common_min = max(float(minimum) - snap_tolerance for minimum in mins)
        interval_common_max = common_max
        if preview_wavenumber_max is not None:
            interval_common_max = min(float(maximum) + snap_tolerance for maximum in maxs)
        if interval_common_min >= interval_common_max:
            latest_start = max(diagnostics, key=lambda item: float(item["native_min_cm1"]))
            earliest_end = min(diagnostics, key=lambda item: float(item["native_max_cm1"]))
            raise SynthesisError(
                "Selected components do not have an overlapping wavenumber range inside the snap tolerance. "
                f"Latest start: {latest_start['name']} at {float(latest_start['native_min_cm1']):.4g} cm^-1; "
                f"earliest end: {earliest_end['name']} at {float(earliest_end['native_max_cm1']):.4g} cm^-1. "
                "Use widest range or remove one of those spectra."
            )
        return _align_components_to_requested_interval_grid(
            arrays,
            diagnostics,
            snap_tolerance=snap_tolerance,
            range_mode=range_mode,
            base_min=interval_common_min,
            base_max=interval_common_max,
            preview_wavenumber_min=preview_wavenumber_min,
            preview_wavenumber_max=preview_wavenumber_max,
            interval_cm1=preview_wavenumber_interval_cm1,
        )

    if common_min >= common_max:
        latest_start = max(diagnostics, key=lambda item: float(item["native_min_cm1"]))
        earliest_end = min(diagnostics, key=lambda item: float(item["native_max_cm1"]))
        raise SynthesisError(
            "Selected components do not have an overlapping wavenumber range. "
            f"Latest start: {latest_start['name']} at {float(latest_start['native_min_cm1']):.4g} cm^-1; "
            f"earliest end: {earliest_end['name']} at {float(earliest_end['native_max_cm1']):.4g} cm^-1. "
            "Use widest range or remove one of those spectra."
        )

    xsec_gap_interval = _inferred_xsec_gap_interval(arrays)
    if xsec_gap_interval is not None:
        return _align_components_to_requested_interval_grid(
            arrays,
            diagnostics,
            snap_tolerance=snap_tolerance,
            range_mode=range_mode,
            base_min=common_min,
            base_max=common_max,
            preview_wavenumber_min=preview_wavenumber_min,
            preview_wavenumber_max=preview_wavenumber_max,
            interval_cm1=xsec_gap_interval,
        )

    try:
        reference, intensities, max_shifts = align_to_median_grid(
            [(x, y) for _, x, y in arrays],
            common_min=common_min,
            common_max=common_max,
            tolerance=snap_tolerance,
        )
    except ValueError as exc:
        spacings_seen = ", ".join(f"{d['name']} {d['native_spacing_cm1']:.4g}" for d in diagnostics)
        raise SynthesisError(
            f"Cannot align selected compounds onto a common (median) grid: {exc}. "
            f"Native spacings (cm^-1): {spacings_seen}. Increase the snap tolerance or "
            "choose compounds with matching spacing."
        ) from exc

    aligned: list[_AlignedComponent] = []
    for i, (component, _, _) in enumerate(arrays):
        diagnostics[i]["shifted"] = bool(max_shifts[i] > SAME_GRID_EPS_CM1)
        diagnostics[i]["max_shift_cm1"] = float(max_shifts[i])
        aligned.append(_AlignedComponent(component=component, wavenumber=reference, intensity=intensities[i]))

    spacings = [d["native_spacing_cm1"] for d in diagnostics if d["native_spacing_cm1"] > 0]
    spacing_consistent = bool(
        spacings and (max(spacings) - min(spacings)) <= max(snap_tolerance, 1e-9 + 0.01 * min(spacings))
    )
    grid_info: dict[str, Any] = {
        "range_mode": "common",
        "snap_tolerance_cm1": float(snap_tolerance),
        "reference_kind": "element-wise median of species wavenumbers",
        "reference_n_points": int(reference.size),
        "reference_spacing_cm1": median_spacing(reference),
        "range_cm1": [float(reference[0]), float(reference[-1])],
        "n_shifted": int(sum(1 for d in diagnostics if d["shifted"])),
        "any_shifted": bool(any(d["shifted"] for d in diagnostics)),
        "spacing_consistent": spacing_consistent,
        "components": diagnostics,
    }
    return _apply_preview_wavenumber_window(
        aligned,
        grid_info,
        preview_wavenumber_min=preview_wavenumber_min,
        preview_wavenumber_max=preview_wavenumber_max,
    )


def _align_components_to_requested_interval_grid(
    arrays: list[tuple[SynthesisComponentInput, np.ndarray, np.ndarray]],
    diagnostics: list[dict[str, Any]],
    *,
    snap_tolerance: float,
    range_mode: str,
    base_min: float,
    base_max: float,
    preview_wavenumber_min: float | None,
    preview_wavenumber_max: float | None,
    interval_cm1: float,
) -> tuple[list[_AlignedComponent], dict[str, Any]]:
    low = base_min if preview_wavenumber_min is None else max(base_min, float(preview_wavenumber_min))
    high = base_max if preview_wavenumber_max is None else min(base_max, float(preview_wavenumber_max))
    if low >= high:
        raise SynthesisError(
            "Preview wavenumber range does not overlap the aligned synthesis grid. "
            f"Aligned range is {base_min:.4g}-{base_max:.4g} cm^-1."
        )
    k_max = int(math.floor((high - low) / float(interval_cm1) + 1e-9))
    if k_max < 1:
        raise SynthesisError(
            "Preview interval leaves fewer than two grid points. " "Widen the range or use a smaller interval."
        )
    reference = low + np.arange(k_max + 1, dtype=float) * float(interval_cm1)

    aligned: list[_AlignedComponent] = []
    for i, (component, x, y) in enumerate(arrays):
        idx = _nearest_indices_for_reference(x, reference)
        dist = np.abs(x[idx] - reference)
        covered = dist <= snap_tolerance
        intensity = np.zeros_like(reference, dtype=float)
        intensity[covered] = y[idx[covered]]
        gap_zero_fill = range_mode == "common" and _allows_gap_zero_fill(component)
        if range_mode == "common" and not bool(np.all(covered)) and not gap_zero_fill:
            worst = float(np.max(dist[~covered])) if np.any(~covered) else 0.0
            raise SynthesisError(
                "Cannot align selected compounds onto the requested interval grid: "
                f"{_component_name(component)} has no native point within snap tolerance "
                f"for at least one bin (nearest miss {worst:.5g} cm^-1, tolerance {snap_tolerance:g}). "
                "Increase snap tolerance, use a larger interval, or use widest range."
            )
        max_shift = float(np.max(dist[covered])) if np.any(covered) else 0.0
        diagnostics[i]["shifted"] = bool(max_shift > SAME_GRID_EPS_CM1)
        diagnostics[i]["max_shift_cm1"] = max_shift
        diagnostics[i]["matched_points"] = int(np.count_nonzero(covered))
        diagnostics[i]["zero_padded_points"] = int(reference.size - int(np.count_nonzero(covered)))
        if gap_zero_fill:
            diagnostics[i]["gap_zero_filled_points"] = int(reference.size - int(np.count_nonzero(covered)))
            diagnostics[i]["gap_policy"] = "zero_fill_unmeasured_xsec_bins"
        aligned.append(_AlignedComponent(component=component, wavenumber=reference, intensity=intensity))

    spacings = [d["native_spacing_cm1"] for d in diagnostics if d["native_spacing_cm1"] > 0]
    spacing_consistent = bool(
        spacings and (max(spacings) - min(spacings)) <= max(snap_tolerance, 1e-9 + 0.01 * min(spacings))
    )
    grid_info: dict[str, Any] = {
        "range_mode": range_mode,
        "snap_tolerance_cm1": float(snap_tolerance),
        "preview_interval_cm1": float(interval_cm1),
        "preview_crop_applied": preview_wavenumber_min is not None or preview_wavenumber_max is not None,
        "requested_preview_range_cm1": [preview_wavenumber_min, preview_wavenumber_max],
        "reference_kind": "requested interval grid with nearest native points inside snap tolerance",
        "reference_n_points": int(reference.size),
        "reference_spacing_cm1": median_spacing(reference),
        "range_cm1": [float(reference[0]), float(reference[-1])],
        "n_shifted": int(sum(1 for d in diagnostics if d["shifted"])),
        "any_shifted": bool(any(d["shifted"] for d in diagnostics)),
        "spacing_consistent": spacing_consistent,
        "components": diagnostics,
    }
    return aligned, grid_info


def _allows_gap_zero_fill(component: SynthesisComponentInput) -> bool:
    """HITRAN xsec bundles can contain measured bands separated by gaps.

    In common-mode interval previews, those gap bins should remain explicit
    zeroes instead of being interpolated or rejected. Other sources still use
    strict common-mode coverage because missing bins usually indicate a grid
    mismatch rather than a declared unmeasured xsec window.
    """

    spectrum = component.spectrum
    metadata = spectrum.metadata or {}
    try:
        merged_gap_count = int(metadata.get("merged_gap_count") or 0)
    except (TypeError, ValueError):
        merged_gap_count = 0
    return spectrum.source == HITRAN_XSEC_SOURCE and (
        metadata.get("gap_policy") == "measured_points_only" or merged_gap_count > 0
    )


def _inferred_xsec_gap_interval(
    arrays: list[tuple[SynthesisComponentInput, np.ndarray, np.ndarray]],
) -> float | None:
    if not any(_allows_gap_zero_fill(component) for component, _x, _y in arrays):
        return None
    spacings = [median_spacing(x) for _component, x, _y in arrays]
    positive = [float(spacing) for spacing in spacings if math.isfinite(float(spacing)) and float(spacing) > 0]
    if not positive:
        return None
    return float(np.median(np.asarray(positive, dtype=float)))


def _apply_preview_wavenumber_window(
    aligned: list[_AlignedComponent],
    grid_info: dict[str, Any],
    *,
    preview_wavenumber_min: float | None,
    preview_wavenumber_max: float | None,
) -> tuple[list[_AlignedComponent], dict[str, Any]]:
    if preview_wavenumber_min is None and preview_wavenumber_max is None:
        return aligned, grid_info
    if not aligned:
        return aligned, grid_info

    reference = aligned[0].wavenumber
    low = (
        float(reference[0])
        if preview_wavenumber_min is None
        else max(float(reference[0]), float(preview_wavenumber_min))
    )
    high = (
        float(reference[-1])
        if preview_wavenumber_max is None
        else min(float(reference[-1]), float(preview_wavenumber_max))
    )
    if low >= high:
        raise SynthesisError(
            "Preview wavenumber range does not overlap the aligned synthesis grid. "
            f"Aligned range is {float(reference[0]):.4g}-{float(reference[-1]):.4g} cm^-1."
        )

    mask = (reference >= low) & (reference <= high)
    if int(np.count_nonzero(mask)) < 2:
        raise SynthesisError(
            "Preview wavenumber range leaves fewer than two grid points. "
            "Widen the range or choose a coarser spectrum."
        )

    cropped = [
        _AlignedComponent(component=item.component, wavenumber=item.wavenumber[mask], intensity=item.intensity[mask])
        for item in aligned
    ]
    cropped_reference = cropped[0].wavenumber
    updated_grid_info = {
        **grid_info,
        "preview_crop_applied": True,
        "range_before_preview_cm1": grid_info.get("range_cm1"),
        "requested_preview_range_cm1": [preview_wavenumber_min, preview_wavenumber_max],
        "range_cm1": [float(cropped_reference[0]), float(cropped_reference[-1])],
        "reference_n_points": int(cropped_reference.size),
        "reference_spacing_cm1": median_spacing(cropped_reference),
    }
    return cropped, updated_grid_info


def _nearest_indices_for_reference(x: np.ndarray, reference: np.ndarray) -> np.ndarray:
    pos = np.searchsorted(x, reference)
    left = np.clip(pos - 1, 0, x.size - 1)
    right = np.clip(pos, 0, x.size - 1)
    choose_left = np.abs(reference - x[left]) <= np.abs(x[right] - reference)
    return np.where(choose_left, left, right)


def _all_hitran_line_by_line(arrays: list[tuple[SynthesisComponentInput, np.ndarray, np.ndarray]]) -> bool:
    return bool(arrays) and all(
        _normalize_source(component.spectrum.source) == HITRAN_SOURCE for component, _, _ in arrays
    )


def _median_positive_spacing(diagnostics: list[dict[str, Any]]) -> float:
    spacings = [
        float(item["native_spacing_cm1"])
        for item in diagnostics
        if math.isfinite(float(item["native_spacing_cm1"])) and float(item["native_spacing_cm1"]) > 0
    ]
    if not spacings:
        raise SynthesisError("Selected components do not contain enough spectrum points")
    return float(np.median(np.asarray(spacings, dtype=float)))


def _align_hitran_line_by_line_to_resolution_bins(
    arrays: list[tuple[SynthesisComponentInput, np.ndarray, np.ndarray]],
    diagnostics: list[dict[str, Any]],
    *,
    range_mode: str,
    reference_min: float,
    reference_max: float,
    resolution_cm1: float | None,
    preview_wavenumber_min: float | None,
    preview_wavenumber_max: float | None,
) -> tuple[list[_AlignedComponent], dict[str, Any]]:
    low = reference_min if preview_wavenumber_min is None else max(reference_min, float(preview_wavenumber_min))
    high = reference_max if preview_wavenumber_max is None else min(reference_max, float(preview_wavenumber_max))
    if low >= high:
        raise SynthesisError(
            "Preview wavenumber range does not overlap the aligned synthesis grid. "
            f"Aligned range is {reference_min:.4g}-{reference_max:.4g} cm^-1."
        )
    reference_spacing = float(resolution_cm1 or _median_positive_spacing(diagnostics))
    if not math.isfinite(reference_spacing) or reference_spacing <= 0:
        raise SynthesisError("HITRAN synthesis resolution must be greater than zero")
    _validate_hitran_line_by_line_resolution(diagnostics, reference_spacing)
    n_bins = int(math.floor((high - low) / reference_spacing + 1e-9)) + 1
    if n_bins < 2:
        raise SynthesisError("Selected wavenumber range is too small to align grids")
    reference = low + np.arange(n_bins, dtype=float) * reference_spacing

    aligned: list[_AlignedComponent] = []
    for i, (component, x, y) in enumerate(arrays):
        intensity, covered, native_points_binned = _bin_component_to_resolution_intervals(
            x,
            y,
            origin=low,
            n_bins=n_bins,
            resolution_cm1=reference_spacing,
        )
        if range_mode == "common" and not bool(np.all(covered)):
            missing = int(reference.size - int(np.count_nonzero(covered)))
            raise SynthesisError(
                "Cannot bin selected HITRAN line-by-line spectra onto the requested common resolution grid: "
                f"{_component_name(component)} has no native points in {missing} bin(s). "
                "Use widest range, reduce the selected range, or reload spectra at the chosen resolution."
            )
        diagnostics[i]["shifted"] = False
        diagnostics[i]["max_shift_cm1"] = 0.0
        diagnostics[i]["matched_points"] = int(np.count_nonzero(covered))
        diagnostics[i]["native_points_binned"] = int(native_points_binned)
        diagnostics[i]["zero_padded_points"] = int(reference.size - int(np.count_nonzero(covered)))
        diagnostics[i]["binning_method"] = "resolution_interval_mean"
        aligned.append(_AlignedComponent(component=component, wavenumber=reference, intensity=intensity))

    spacings = [d["native_spacing_cm1"] for d in diagnostics if d["native_spacing_cm1"] > 0]
    spacing_consistent = bool(spacings and (max(spacings) - min(spacings)) <= max(1e-9, 0.01 * min(spacings)))
    grid_info: dict[str, Any] = {
        "range_mode": range_mode,
        "reference_kind": "HITRAN line-by-line resolution bins",
        "binning_method": "resolution_interval_mean",
        "reference_n_points": int(reference.size),
        "reference_spacing_cm1": median_spacing(reference),
        "resolution_cm1": reference_spacing,
        "range_cm1": [float(reference[0]), float(reference[-1])],
        "n_shifted": 0,
        "any_shifted": False,
        "spacing_consistent": spacing_consistent,
        "components": diagnostics,
    }
    return aligned, grid_info


def _validate_hitran_line_by_line_resolution(
    diagnostics: list[dict[str, Any]],
    resolution_cm1: float,
) -> None:
    tolerance = max(1e-8, abs(float(resolution_cm1)) * 1e-6)
    mismatches = [
        f"{item['name']} {float(item['native_spacing_cm1']):.6g}"
        for item in diagnostics
        if math.isfinite(float(item["native_spacing_cm1"]))
        and float(item["native_spacing_cm1"]) > 0
        and abs(float(item["native_spacing_cm1"]) - float(resolution_cm1)) > tolerance
    ]
    if mismatches:
        raise SynthesisError(
            "Selected HITRAN line-by-line spectra must be loaded at the same resolution before synthesis. "
            f"Requested resolution is {float(resolution_cm1):.6g} cm^-1; "
            f"mismatched native spacing(s): {', '.join(mismatches)}. "
            "Reload those spectra at the selected resolution."
        )


def _bin_component_to_resolution_intervals(
    x: np.ndarray,
    y: np.ndarray,
    *,
    origin: float,
    n_bins: int,
    resolution_cm1: float,
) -> tuple[np.ndarray, np.ndarray, int]:
    bin_index = np.floor((x - float(origin)) / float(resolution_cm1) + 1e-12).astype(int)
    valid = (bin_index >= 0) & (bin_index < int(n_bins))
    if not np.any(valid):
        return np.zeros(int(n_bins), dtype=float), np.zeros(int(n_bins), dtype=bool), 0
    indices = bin_index[valid]
    values = y[valid]
    sums = np.bincount(indices, weights=values, minlength=int(n_bins)).astype(float)
    counts = np.bincount(indices, minlength=int(n_bins)).astype(float)
    covered = counts > 0
    intensity = np.zeros(int(n_bins), dtype=float)
    intensity[covered] = sums[covered] / counts[covered]
    return intensity, covered, int(values.size)


def _align_components_to_widest_range(
    arrays: list[tuple[SynthesisComponentInput, np.ndarray, np.ndarray]],
    diagnostics: list[dict[str, Any]],
    *,
    snap_tolerance: float,
    union_min: float,
    union_max: float,
) -> tuple[list[_AlignedComponent], dict[str, Any]]:
    spacings = [d["native_spacing_cm1"] for d in diagnostics if d["native_spacing_cm1"] > 0]
    if not spacings:
        raise SynthesisError("Selected components do not contain enough spectrum points")
    reference_spacing = float(np.median(spacings))
    spacing_window = max(snap_tolerance, 1e-9 + 0.01 * min(spacings))
    spacing_consistent = bool((max(spacings) - min(spacings)) <= spacing_window)

    k_max = int(math.floor((union_max - union_min) / reference_spacing + 1e-9))
    if k_max < 1:
        raise SynthesisError("Selected wavenumber range is too small to align grids")
    reference = union_min + np.arange(k_max + 1, dtype=float) * reference_spacing

    aligned: list[_AlignedComponent] = []
    for i, (component, x, y) in enumerate(arrays):
        idx = _nearest_indices_for_reference(x, reference)
        dist = np.abs(x[idx] - reference)
        covered = dist <= snap_tolerance
        intensity = np.zeros_like(reference, dtype=float)
        intensity[covered] = y[idx[covered]]
        max_shift = float(np.max(dist[covered])) if np.any(covered) else 0.0
        diagnostics[i]["shifted"] = bool(max_shift > SAME_GRID_EPS_CM1)
        diagnostics[i]["max_shift_cm1"] = max_shift
        diagnostics[i]["zero_padded_points"] = int(reference.size - int(np.count_nonzero(covered)))
        diagnostics[i]["matched_points"] = int(np.count_nonzero(covered))
        aligned.append(_AlignedComponent(component=component, wavenumber=reference, intensity=intensity))

    grid_info: dict[str, Any] = {
        "range_mode": "widest",
        "snap_tolerance_cm1": float(snap_tolerance),
        "reference_kind": "widest source range with nearest native points inside snap tolerance",
        "reference_n_points": int(reference.size),
        "reference_spacing_cm1": median_spacing(reference),
        "range_cm1": [float(reference[0]), float(reference[-1])],
        "n_shifted": int(sum(1 for d in diagnostics if d["shifted"])),
        "any_shifted": bool(any(d["shifted"] for d in diagnostics)),
        "spacing_consistent": spacing_consistent,
        "components": diagnostics,
    }
    return aligned, grid_info


def _even_indices(length: int, limit: int) -> list[int]:
    if length <= limit:
        return list(range(length))
    return sorted(set(int(round(i)) for i in np.linspace(0, length - 1, limit)))


def _npz_has_synthesis_signature(data: np.lib.npyio.NpzFile) -> bool:
    if "spectra_sherpa_synthetic" not in data.files:
        return False
    try:
        return str(data["spectra_sherpa_synthetic"].item()) == SYNTHETIC_NPZ_SIGNATURE
    except Exception:
        return False


def _normalize_source(source: str) -> str:
    normalized = source.strip().lower().replace("-", "_")
    if normalized in {"nist", "nist_quant_ir", "nist_quantitative_ir"}:
        return NIST_SOURCE
    if normalized in {"hitran", "hapi"}:
        return HITRAN_SOURCE
    if normalized in {"hitran_xsec", "hitran_xsection", "hitran_cross_section", "hitran_absorption_x_section"}:
        return HITRAN_XSEC_SOURCE
    raise SynthesisError(f"Unsupported synthesis source: {source}")


def _load_nist_manifest() -> dict[str, Any]:
    text = resources.files("spectra_sherpa").joinpath("data/synthesis/nist_quant_ir_manifest.json").read_text()
    return dict(json.loads(text))


@lru_cache(maxsize=1)
def _load_hitran_xsec_manifest() -> dict[str, Any]:
    text = resources.files("spectra_sherpa").joinpath("data/synthesis/hitran_xsec_manifest.json").read_text()
    return dict(json.loads(text))


def _hitran_xsec_records() -> list[dict[str, Any]]:
    return [
        record
        for record in _load_hitran_xsec_manifest().get("components", [])
        if record.get("xsec_options") or record.get("variants")
    ]


def _summary_from_record(source: str, record: dict[str, Any]) -> SynthesisComponentSummary:
    return SynthesisComponentSummary(
        id=str(record["id"]),
        name=str(record["name"]),
        source=source,  # type: ignore[arg-type]
        cas=record.get("cas"),
        formula=record.get("formula"),
        variants=(
            []
            if source == HITRAN_XSEC_SOURCE
            else [SynthesisVariant(**variant) for variant in record.get("variants", [])]
        ),
        xsec_options=(
            _group_hitran_xsec_options(record.get("xsec_options") or record.get("variants", []))
            if source == HITRAN_XSEC_SOURCE
            else []
        ),
    )


def _static_hitran_catalog() -> list[dict[str, Any]]:
    return [
        {"id": f"hitran:{number}", "name": name, "formula": formula, "molecule_number": number}
        for number, formula, name in _HITRAN_LBL_MOLECULES
        if number not in _HITRAN_SPECIAL_NOTATION_EXCLUSIONS
    ]


async def _get_nist_component_spectrum(
    component_id: str,
    *,
    resolution_cm1: float | None,
    apodization: str | None,
    wavenumber_min: float | None,
    wavenumber_max: float | None,
) -> SynthesisSpectrumResponse:
    summary = get_component_summary(NIST_SOURCE, component_id)
    if not summary.cas:
        raise SynthesisError("NIST Quant IR component is missing a CAS number")
    variant = _select_nist_variant(summary, resolution_cm1=resolution_cm1, apodization=apodization)
    index = _nist_quant_ir_index(variant.resolution_cm1, variant.apodization)
    cache_path = _nist_cache_path(component_id, variant.resolution_cm1, variant.apodization)
    cached = cache_path.exists()
    if cached:
        text = cache_path.read_text(encoding="utf-8", errors="replace")
    else:
        text = await _download_nist_quant_ir_jcamp(summary.cas, index=index)
        if not _looks_like_jcamp_spectrum(text):
            raise SynthesisError("NIST did not return a JCAMP-DX spectrum for the selected variant")
        cache_path.write_text(text, encoding="utf-8")
    try:
        parsed = parse_jcamp(text)
    except Exception as exc:
        detail = _sanitize_provider_error(exc)
        raise SynthesisError(f"NIST JCAMP-DX parsing failed: {detail}") from exc
    x = np.asarray(parsed.x, dtype=float)
    y = np.asarray(parsed.y, dtype=float)
    x, y = _crop_spectrum(x, y, wavenumber_min=wavenumber_min, wavenumber_max=wavenumber_max)
    return SynthesisSpectrumResponse(
        component_id=summary.id,
        name=summary.name,
        source=NIST_SOURCE,  # type: ignore[arg-type]
        wavenumber=x.tolist(),
        intensity=y.tolist(),
        y_quantity="decadic_absorption_coefficient",
        y_units="ppm^-1 m^-1",
        resolution_cm1=variant.resolution_cm1,
        apodization=variant.apodization,
        cached=cached,
    )


async def _get_hitran_component_spectrum(
    component_id: str,
    *,
    resolution_cm1: float,
    wavenumber_min: float,
    wavenumber_max: float,
    temperature_k: float,
    pressure_atm: float,
    api_key: str | None,
) -> SynthesisSpectrumResponse:
    summary = get_component_summary(HITRAN_SOURCE, component_id)
    record = next((item for item in _static_hitran_catalog() if str(item["id"]) == component_id), None)
    if record is None:
        raise SynthesisError(f"Unknown HITRAN component: {component_id}")

    if wavenumber_min >= wavenumber_max:
        raise SynthesisError("HITRAN wavenumber range must have min < max")
    spectrum_cache_path = _hitran_spectrum_cache_path(
        component_id,
        resolution_cm1=resolution_cm1,
        wavenumber_min=wavenumber_min,
        wavenumber_max=wavenumber_max,
        temperature_k=temperature_k,
        pressure_atm=pressure_atm,
    )
    cached = spectrum_cache_path.exists()
    if cached:
        x, y = _read_hitran_spectrum_cache(spectrum_cache_path)
    else:
        if not api_key or not api_key.strip():
            raise SynthesisError("HITRAN API key is required. Add a HITRAN key in Settings before downloading spectra.")
        async with _HITRAN_HAPI_LOCK:
            if spectrum_cache_path.exists():
                x, y = _read_hitran_spectrum_cache(spectrum_cache_path)
                cached = True
            else:
                hapi = _import_hapi1_module()
                table_name = _safe_stem(f"{component_id}-{wavenumber_min:g}-{wavenumber_max:g}")
                table_cache_dir = _hitran_table_cache_dir(table_name)
                hitran_line_dir = _hitran_line_table_dir(table_name)
                cached = False
                try:
                    # HAPI is synchronous and not concurrency-safe: the HAPI2
                    # line-table download and the HAPI1 Voigt coefficient pass
                    # both block.  Hold the async lock to serialize HAPI's
                    # global state (and bound the process-wide ``os.chdir``
                    # inside the fetch helper), but run the blocking work in a
                    # worker thread so the single event loop stays responsive
                    # to other users' requests instead of stalling for the
                    # full download + numpy pass.
                    nu, coef = await asyncio.to_thread(
                        _compute_hitran_spectrum_blocking,
                        hapi,
                        table_cache_dir,
                        hitran_line_dir,
                        table_name,
                        int(record["molecule_number"]),
                        float(wavenumber_min),
                        float(wavenumber_max),
                        float(temperature_k),
                        float(pressure_atm),
                        float(resolution_cm1),
                        api_key.strip(),
                    )
                except Exception as exc:  # pragma: no cover - network/package dependent
                    detail = _sanitize_provider_error(exc, api_key=api_key.strip())
                    logger.warning(
                        "HITRAN spectrum generation failed for component=%s range=%s-%s cm-1: %s",
                        component_id,
                        wavenumber_min,
                        wavenumber_max,
                        detail,
                        exc_info=True,
                    )
                    raise SynthesisError(
                        "HITRAN spectrum generation failed"
                        + (f": {detail}" if detail else "")
                        + ". Verify the API key, molecule, and wavenumber range."
                    ) from exc
                x = np.asarray(nu, dtype=float)
                y = np.asarray(coef, dtype=float)
                x, y = _crop_spectrum(x, y, wavenumber_min=wavenumber_min, wavenumber_max=wavenumber_max)
                _write_hitran_spectrum_cache(spectrum_cache_path, x, y)
    return SynthesisSpectrumResponse(
        component_id=summary.id,
        name=summary.name,
        source=HITRAN_SOURCE,  # type: ignore[arg-type]
        wavenumber=x.tolist(),
        intensity=y.tolist(),
        y_quantity="absorption_cross_section",
        y_units="cm^2 molecule^-1",
        resolution_cm1=resolution_cm1,
        apodization="Voigt",
        cached=cached,
    )


async def _get_hitran_xsec_component_spectrum(
    component_id: str,
    *,
    wavenumber_min: float | None,
    wavenumber_max: float | None,
    temperature_k: float,
    pressure_atm: float,
    api_key: str | None,
) -> SynthesisSpectrumResponse:
    record, option = _hitran_xsec_record_and_option(component_id)
    wmin, wmax = _hitran_xsec_effective_range(record, option, wavenumber_min, wavenumber_max)
    if wmin >= wmax:
        raise SynthesisError("HITRAN absorption cross-section wavenumber range must have min < max")
    target_temperature = _hitran_xsec_effective_temperature(option, temperature_k)
    target_pressure = _hitran_xsec_effective_pressure_atm(option, pressure_atm)
    spectrum_cache_path = _hitran_xsec_spectrum_cache_path(
        component_id,
        wavenumber_min=wmin,
        wavenumber_max=wmax,
        temperature_k=target_temperature,
        pressure_atm=target_pressure,
    )
    cached = spectrum_cache_path.exists()
    metadata: dict[str, Any] = {}
    if cached:
        x, y = _read_hitran_spectrum_cache(spectrum_cache_path)
        metadata = _read_hitran_spectrum_cache_metadata(spectrum_cache_path)
    else:
        if not api_key or not api_key.strip():
            raise SynthesisError("HITRAN API key is required. Add a HITRAN key in Settings before downloading spectra.")
        async with _HITRAN_HAPI_LOCK:
            if spectrum_cache_path.exists():
                x, y = _read_hitran_spectrum_cache(spectrum_cache_path)
                cached = True
            else:
                cache_dir = _synthesis_cache_dir("hitran") / "xsec"
                try:
                    x, y, metadata = await asyncio.to_thread(
                        _fetch_hitran_xsec_blocking,
                        cache_dir,
                        record,
                        option,
                        wmin,
                        wmax,
                        target_temperature,
                        target_pressure,
                        api_key.strip(),
                    )
                except Exception as exc:  # pragma: no cover - network/package dependent
                    detail = _sanitize_provider_error(exc, api_key=api_key.strip())
                    logger.warning(
                        "HITRAN absorption cross-section load failed for component=%s range=%s-%s cm-1: %s",
                        component_id,
                        wmin,
                        wmax,
                        detail,
                        exc_info=True,
                    )
                    raise SynthesisError(
                        "HITRAN absorption cross-section load failed"
                        + (f": {detail}" if detail else "")
                        + ". Verify the API key, molecule, and selected measurement conditions."
                    ) from exc
                _write_hitran_spectrum_cache(spectrum_cache_path, x, y, metadata=metadata)
    return SynthesisSpectrumResponse(
        component_id=component_id,
        name=str(record["name"]),
        source=HITRAN_XSEC_SOURCE,  # type: ignore[arg-type]
        wavenumber=x.tolist(),
        intensity=y.tolist(),
        y_quantity="absorption_cross_section",
        y_units="cm^2 molecule^-1",
        resolution_cm1=_coerce_optional_float(metadata.get("resolution_cm1")),
        apodization=str(metadata.get("broadener") or "measured x-section"),
        cached=cached,
        metadata={
            "formula": record.get("formula"),
            "source_kind": "hitran_absorption_x_section",
            "selected_option": option,
            **metadata,
        },
    )


def _hitran_xsec_base_id(component_id: str) -> str:
    return str(component_id).split("#", 1)[0]


def _hitran_xsec_option_index(component_id: str) -> int:
    if "#" not in str(component_id):
        return 0
    suffix = str(component_id).split("#", 1)[1].strip()
    if suffix.startswith("option="):
        suffix = suffix.split("=", 1)[1]
    try:
        index = int(suffix)
    except ValueError as exc:
        raise SynthesisError(f"Invalid HITRAN absorption cross-section option: {component_id}") from exc
    if index < 0:
        raise SynthesisError(f"Invalid HITRAN absorption cross-section option: {component_id}")
    return index


def _hitran_xsec_record_and_option(component_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    base_id = _hitran_xsec_base_id(component_id)
    index = _hitran_xsec_option_index(component_id)
    for record in _hitran_xsec_records():
        if str(record.get("id")) != base_id:
            continue
        options = _group_hitran_xsec_options(record.get("xsec_options") or record.get("variants", []))
        if not options:
            raise SynthesisError(f"HITRAN absorption cross-section component has no available measurements: {base_id}")
        if index >= len(options):
            raise SynthesisError(
                f"HITRAN absorption cross-section option {index} is not available for {record['name']}"
            )
        return dict(record), dict(options[index])
    raise SynthesisError(f"Unknown HITRAN absorption cross-section component: {component_id}")


def _range_midpoint(value: Any) -> float | None:
    if not isinstance(value, list | tuple) or len(value) != 2:
        return None
    try:
        low = float(value[0])
        high = float(value[1])
    except (TypeError, ValueError):
        return None
    return (low + high) / 2.0


def _xsec_group_key_from_option(option: dict[str, Any]) -> tuple[Any, Any, Any, str]:
    return (
        _xsec_group_numeric(option.get("temperature_k")),
        _xsec_group_numeric(option.get("pressure_torr")),
        _xsec_group_numeric(option.get("resolution_cm1")),
        _xsec_group_text(option.get("broadener")),
    )


def _xsec_group_numeric(value: Any) -> Any:
    if isinstance(value, list | tuple) and len(value) == 2:
        return (_round_for_xsec_group(value[0]), _round_for_xsec_group(value[1]))
    return _round_for_xsec_group(value)


def _round_for_xsec_group(value: Any) -> float | None:
    number = _coerce_optional_float(value)
    if number is None:
        return None
    return round(number, 6)


def _xsec_group_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _group_hitran_xsec_options(options: Any) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, Any, Any, str], dict[str, Any]] = {}
    for raw_option in options or []:
        option = dict(raw_option)
        x_range = option.get("wavenumber_cm1")
        if not isinstance(x_range, list | tuple) or len(x_range) != 2:
            continue
        x_min = _coerce_optional_float(x_range[0])
        x_max = _coerce_optional_float(x_range[1])
        if x_min is None or x_max is None:
            continue
        if x_min > x_max:
            x_min, x_max = x_max, x_min
        key = _xsec_group_key_from_option(option)
        group = groups.get(key)
        if group is None:
            group = {
                "temperature_k": option.get("temperature_k"),
                "pressure_torr": option.get("pressure_torr"),
                "resolution_cm1": option.get("resolution_cm1"),
                "broadener": option.get("broadener"),
                "sets": 0,
                "wavenumber_cm1": [x_min, x_max],
                "regions": [],
            }
            groups[key] = group
        group["wavenumber_cm1"] = [
            min(float(group["wavenumber_cm1"][0]), x_min),
            max(float(group["wavenumber_cm1"][1]), x_max),
        ]
        group["sets"] = max(int(group.get("sets") or 0), int(option.get("sets") or 0))
        group["regions"].append(
            {
                "xsec_id": option.get("xsec_id"),
                "modality": option.get("modality"),
                "wavenumber_cm1": [x_min, x_max],
                "sets": option.get("sets"),
                "npts": option.get("npts"),
                "source": option.get("source"),
            }
        )
    grouped = list(groups.values())
    for group in grouped:
        group["regions"] = sorted(group["regions"], key=lambda item: float(item["wavenumber_cm1"][0]))
    return sorted(grouped, key=lambda item: (float(item["wavenumber_cm1"][0]), float(item["wavenumber_cm1"][1])))


def _hitran_xsec_effective_range(
    record: dict[str, Any],
    option: dict[str, Any],
    wavenumber_min: float | None,
    wavenumber_max: float | None,
) -> tuple[float, float]:
    option_range = option.get("wavenumber_cm1")
    if isinstance(option_range, list | tuple) and len(option_range) == 2:
        default_min = float(option_range[0])
        default_max = float(option_range[1])
    else:
        all_ranges = [
            item.get("wavenumber_cm1")
            for item in record.get("variants", [])
            if isinstance(item.get("wavenumber_cm1"), list | tuple) and len(item.get("wavenumber_cm1")) == 2
        ]
        if not all_ranges:
            raise SynthesisError(
                f"HITRAN absorption cross-section component lacks a wavenumber range: {record['name']}"
            )
        default_min = min(float(item[0]) for item in all_ranges)
        default_max = max(float(item[1]) for item in all_ranges)
    return float(wavenumber_min if wavenumber_min is not None else default_min), float(
        wavenumber_max if wavenumber_max is not None else default_max
    )


def _hitran_xsec_effective_temperature(option: dict[str, Any], temperature_k: float) -> float:
    return float(_range_midpoint(option.get("temperature_k")) or temperature_k)


def _hitran_xsec_effective_pressure_atm(option: dict[str, Any], pressure_atm: float) -> float:
    pressure_torr = _range_midpoint(option.get("pressure_torr"))
    if pressure_torr is None or pressure_torr <= 0:
        return float(pressure_atm)
    return float(pressure_torr / 760.0)


def _hitran_xsec_spectrum_cache_path(
    component_id: str,
    *,
    wavenumber_min: float,
    wavenumber_max: float,
    temperature_k: float,
    pressure_atm: float,
) -> Path:
    payload = {
        "component_id": component_id,
        "source": HITRAN_XSEC_SOURCE,
        "wavenumber_min": float(wavenumber_min),
        "wavenumber_max": float(wavenumber_max),
        "temperature_k": float(temperature_k),
        "pressure_atm": float(pressure_atm),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
    return _synthesis_cache_dir("hitran") / "xsec_spectra" / f"{_safe_stem(component_id)}-{digest}.npz"


def _fetch_hitran_xsec_blocking(
    cache_dir: Path,
    record: dict[str, Any],
    option: dict[str, Any],
    wavenumber_min: float,
    wavenumber_max: float,
    temperature_k: float,
    pressure_atm: float,
    api_key: str,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "~tmp").mkdir(parents=True, exist_ok=True)
    hapi2 = _import_hapi2_module(cache_dir)
    original_cwd = Path.cwd()
    with _HAPI2_LOCK:
        with _temporary_hapi_api_key(hapi2, api_key):
            settings_obj = getattr(hapi2, "SETTINGS", None)
            previous_display = _MISSING
            if isinstance(settings_obj, dict):
                previous_display = settings_obj.get("display_fetch_url", _MISSING)
                settings_obj["display_fetch_url"] = False
            try:
                os.chdir(cache_dir)
                hapi2.fetch_info()
                molecule = _find_hapi2_xsec_molecule(hapi2.fetch_molecules(), record)
                headers = hapi2.fetch_cross_section_headers(molecule)
                selected_headers = _select_hapi2_xsec_header_group(
                    headers,
                    option=option,
                    wavenumber_min=wavenumber_min,
                    wavenumber_max=wavenumber_max,
                    temperature_k=temperature_k,
                    pressure_atm=pressure_atm,
                )
                fetched = hapi2.fetch_cross_section_spectra(selected_headers)
                if fetched:
                    selected_headers = fetched
                x, y, metadata = _merge_hapi2_xsec_headers(
                    selected_headers,
                    wavenumber_min=wavenumber_min,
                    wavenumber_max=wavenumber_max,
                )
            finally:
                os.chdir(original_cwd)
                if isinstance(settings_obj, dict):
                    if previous_display is _MISSING:
                        settings_obj.pop("display_fetch_url", None)
                    else:
                        settings_obj["display_fetch_url"] = previous_display
    x, y = _crop_spectrum(
        np.asarray(x, dtype=float),
        np.asarray(y, dtype=float),
        wavenumber_min=wavenumber_min,
        wavenumber_max=wavenumber_max,
    )
    if x.size < 2:
        raise SynthesisError("Selected HITRAN absorption cross-section has no data in the requested range")
    return x, y, metadata


def _find_hapi2_xsec_molecule(molecules: Any, record: dict[str, Any]) -> Any:
    hitran_molecule_id = _coerce_optional_int(record.get("hitran_molecule_id"))
    formula = _normalized_formula(record.get("formula"))
    name = _normalized_lookup_text(record.get("name"))
    for molecule in molecules or []:
        if hitran_molecule_id is not None and getattr(molecule, "id", None) == hitran_molecule_id:
            return molecule
        candidates = [
            getattr(molecule, attr, None)
            for attr in (
                "formula",
                "chemical_formula",
                "formula_html",
                "name",
                "common_name",
                "global_name",
                "molecule_name",
                "alias",
            )
        ]
        if formula and any(_normalized_formula(candidate) == formula for candidate in candidates):
            return molecule
        if name and any(_normalized_lookup_text(candidate) == name for candidate in candidates):
            return molecule
    raise SynthesisError(f"HAPI2 did not return a molecule record for {record['name']} ({record.get('formula')})")


def _select_hapi2_xsec_header_group(
    headers: Any,
    *,
    option: dict[str, Any],
    wavenumber_min: float,
    wavenumber_max: float,
    temperature_k: float,
    pressure_atm: float,
) -> list[Any]:
    candidates = [item for item in (headers or []) if _hapi2_xsec_overlaps(item, wavenumber_min, wavenumber_max)]
    if not candidates:
        raise SynthesisError("HAPI2 returned no absorption cross-sections overlapping the requested range")
    option_regions = option.get("regions") if isinstance(option.get("regions"), list) else []
    option_xsec_ids = {
        parsed
        for xsec_id in (
            [option.get("xsec_id")] + [region.get("xsec_id") for region in option_regions if isinstance(region, dict)]
        )
        if (parsed := _coerce_optional_int(xsec_id)) is not None
    }
    if option_xsec_ids:
        matching_candidates = [
            item
            for item in candidates
            if _coerce_optional_int(_xsec_attr(item, "id", "xsec_id", "cross_section_id")) in option_xsec_ids
        ]
        if matching_candidates:
            candidates = matching_candidates
    groups: dict[tuple[Any, Any, Any, str], list[Any]] = {}
    for item in candidates:
        groups.setdefault(_hapi2_xsec_group_key(item), []).append(item)
    option_range = option.get("wavenumber_cm1")
    target_pressure_torr = float(pressure_atm) * 760.0

    def score(group_items: list[Any]) -> tuple[float, float, float, float, float]:
        first = group_items[0]
        item_temp = _coerce_optional_float(_xsec_attr(first, "temperature", "Temperature")) or temperature_k
        item_pressure = _coerce_optional_float(_xsec_attr(first, "pressure", "Pressure")) or target_pressure_torr
        coverage = _hapi2_xsec_coverage(group_items, wavenumber_min, wavenumber_max)
        group_min = min(
            _coerce_optional_float(_xsec_attr(item, "numin", "nu_min", "wavenumber_min")) or wavenumber_min
            for item in group_items
        )
        group_max = max(
            _coerce_optional_float(_xsec_attr(item, "numax", "nu_max", "wavenumber_max")) or wavenumber_max
            for item in group_items
        )
        if isinstance(option_range, list | tuple) and len(option_range) == 2:
            range_distance = abs(group_min - float(option_range[0])) + abs(group_max - float(option_range[1]))
        else:
            range_distance = abs(group_min - wavenumber_min) + abs(group_max - wavenumber_max)
        return (
            _xsec_distance_to_option_range(item_temp, option.get("temperature_k"), temperature_k),
            _xsec_distance_to_option_range(item_pressure, option.get("pressure_torr"), target_pressure_torr),
            -coverage,
            abs(item_temp - temperature_k),
            range_distance,
        )

    selected = min(groups.values(), key=score)
    return sorted(
        selected,
        key=lambda item: _coerce_optional_float(_xsec_attr(item, "numin", "nu_min", "wavenumber_min"))
        or wavenumber_min,
    )


def _hapi2_xsec_group_key(item: Any) -> tuple[Any, Any, Any, str]:
    return (
        _round_for_xsec_group(_xsec_attr(item, "temperature", "Temperature")),
        _round_for_xsec_group(_xsec_attr(item, "pressure", "Pressure")),
        _round_for_xsec_group(_xsec_attr(item, "resolution")),
        _xsec_group_text(_xsec_attr(item, "broadener")),
    )


def _xsec_distance_to_option_range(value: float, option_value: Any, fallback: float) -> float:
    if isinstance(option_value, list | tuple) and len(option_value) == 2:
        low = _coerce_optional_float(option_value[0])
        high = _coerce_optional_float(option_value[1])
        if low is not None and high is not None:
            if low > high:
                low, high = high, low
            tolerance = max(abs(high - low) * 0.005, 1e-6)
            if low - tolerance <= value <= high + tolerance:
                return 0.0
            return min(abs(value - low), abs(value - high))
    target = _coerce_optional_float(option_value)
    return abs(value - (target if target is not None else fallback))


def _hapi2_xsec_coverage(items: list[Any], wavenumber_min: float, wavenumber_max: float) -> float:
    coverage = 0.0
    for item in items:
        item_min = _coerce_optional_float(_xsec_attr(item, "numin", "nu_min", "wavenumber_min"))
        item_max = _coerce_optional_float(_xsec_attr(item, "numax", "nu_max", "wavenumber_max"))
        if item_min is None or item_max is None:
            continue
        if item_min > item_max:
            item_min, item_max = item_max, item_min
        overlap_min = max(float(wavenumber_min), item_min)
        overlap_max = min(float(wavenumber_max), item_max)
        coverage += max(0.0, overlap_max - overlap_min)
    return coverage


def _merge_hapi2_xsec_headers(
    headers: list[Any],
    *,
    wavenumber_min: float,
    wavenumber_max: float,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    segments: list[tuple[np.ndarray, np.ndarray, Any]] = []
    for header in headers:
        x_raw, y_raw = _hapi2_xsec_xy(header)
        x_arr = np.asarray(x_raw, dtype=float)
        y_arr = np.asarray(y_raw, dtype=float)
        finite = np.isfinite(x_arr) & np.isfinite(y_arr)
        x_arr = x_arr[finite]
        y_arr = y_arr[finite]
        if x_arr.size < 2:
            continue
        order = np.argsort(x_arr)
        x_sorted = x_arr[order]
        y_sorted = y_arr[order]
        mask = (x_sorted >= float(wavenumber_min)) & (x_sorted <= float(wavenumber_max))
        if int(np.count_nonzero(mask)) >= 2:
            segments.append((x_sorted[mask], y_sorted[mask], header))
    if not segments:
        raise SynthesisError("Selected HITRAN absorption cross-section has no data in the requested range")

    spacing = _estimate_xsec_spacing(segments)
    ordered_segments = sorted(segments, key=lambda item: float(item[0][0]))
    start = min(float(x[0]) for x, _y, _header in ordered_segments)
    stop = max(float(x[-1]) for x, _y, _header in ordered_segments)
    if stop <= start:
        raise SynthesisError("Selected HITRAN absorption cross-section has an invalid wavenumber range")
    tolerance = max(abs(spacing) * 0.35, 1e-6)
    x_parts: list[np.ndarray] = []
    y_parts: list[np.ndarray] = []
    gap_count = 0
    last_x: float | None = None
    for x_arr, y_arr, _header in ordered_segments:
        if last_x is not None and float(x_arr[0]) > last_x + tolerance:
            gap_count += 1
        keep = np.ones_like(x_arr, dtype=bool) if last_x is None else x_arr > last_x + tolerance
        if not np.any(keep):
            continue
        x_kept = x_arr[keep]
        y_kept = y_arr[keep]
        x_parts.append(x_kept)
        y_parts.append(y_kept)
        last_x = float(x_kept[-1])
    if not x_parts:
        raise SynthesisError("Selected HITRAN absorption cross-section has no usable data after merging")

    merged_x = np.concatenate(x_parts)
    merged_y = np.concatenate(y_parts)
    metadata = _hapi2_xsec_group_metadata([header for _x, _y, header in ordered_segments], merged_x, spacing)
    metadata["merged_gap_count"] = gap_count
    metadata["gap_policy"] = "measured_points_only"
    return merged_x, merged_y, metadata


def _estimate_xsec_spacing(segments: list[tuple[np.ndarray, np.ndarray, Any]]) -> float:
    candidates: list[float] = []
    fallback_candidates: list[float] = []
    for x_arr, _y_arr, header in segments:
        diffs = np.diff(x_arr)
        positive = diffs[np.isfinite(diffs) & (diffs > 0)]
        if positive.size:
            candidates.append(float(np.median(positive)))
        resolution = _coerce_optional_float(_xsec_attr(header, "resolution"))
        if resolution is not None and resolution > 0:
            fallback_candidates.append(float(resolution))
    usable = candidates or fallback_candidates
    if not usable:
        raise SynthesisError("Selected HITRAN absorption cross-section has no usable wavenumber spacing")
    spacing = float(np.median(np.asarray(usable, dtype=float)))
    if not math.isfinite(spacing) or spacing <= 0:
        raise SynthesisError("Selected HITRAN absorption cross-section has invalid wavenumber spacing")
    return spacing


def _hapi2_xsec_overlaps(item: Any, wavenumber_min: float, wavenumber_max: float) -> bool:
    item_min = _coerce_optional_float(_xsec_attr(item, "numin", "nu_min", "wavenumber_min"))
    item_max = _coerce_optional_float(_xsec_attr(item, "numax", "nu_max", "wavenumber_max"))
    if item_min is None or item_max is None:
        return True
    return max(item_min, wavenumber_min) < min(item_max, wavenumber_max)


def _hapi2_xsec_xy(item: Any) -> tuple[np.ndarray, np.ndarray]:
    data = item.get_data() if hasattr(item, "get_data") else None
    x: Any = None
    y: Any = None
    if isinstance(data, tuple) and len(data) >= 2:
        x, y = data[0], data[1]
    elif isinstance(data, dict):
        x = data.get("nu") or data.get("wavenumber")
        y = data.get("xsc") or data.get("sigma") or data.get("cross_section")
    if y is None:
        y = _xsec_attr(item, "xsc", "sigma", "cross_section", "data")
    y_arr = np.asarray(y, dtype=float)
    if x is None:
        start = _coerce_optional_float(_xsec_attr(item, "numin", "nu_min", "wavenumber_min"))
        stop = _coerce_optional_float(_xsec_attr(item, "numax", "nu_max", "wavenumber_max"))
        npts = _coerce_optional_float(_xsec_attr(item, "npnts", "npts", "num_points"))
        if start is None or stop is None:
            raise SynthesisError("HAPI2 cross-section data did not include a wavenumber axis")
        count = int(npts or y_arr.size)
        x_arr = np.linspace(start, stop, count)
    else:
        x_arr = np.asarray(x, dtype=float)
    if x_arr.shape != y_arr.shape:
        raise SynthesisError("HAPI2 cross-section data axis and intensity lengths do not match")
    return x_arr, y_arr


def _hapi2_xsec_metadata(item: Any) -> dict[str, Any]:
    pressure_torr = _coerce_optional_float(_xsec_attr(item, "pressure", "Pressure"))
    return {
        "provider_id": _xsec_attr(item, "id"),
        "filename": _xsec_attr(item, "filename"),
        "temperature_k": _coerce_optional_float(_xsec_attr(item, "temperature", "Temperature")),
        "pressure_torr": pressure_torr,
        "pressure_atm": pressure_torr / 760.0 if pressure_torr is not None else None,
        "resolution_cm1": _coerce_optional_float(_xsec_attr(item, "resolution")),
        "npts": _coerce_optional_int(_xsec_attr(item, "npnts", "npts", "num_points")),
        "broadener": _xsec_attr(item, "broadener"),
        "apodization": _xsec_attr(item, "apodization"),
        "wavenumber_min": _coerce_optional_float(_xsec_attr(item, "numin", "nu_min", "wavenumber_min")),
        "wavenumber_max": _coerce_optional_float(_xsec_attr(item, "numax", "nu_max", "wavenumber_max")),
    }


def _hapi2_xsec_group_metadata(headers: list[Any], x: np.ndarray, spacing: float) -> dict[str, Any]:
    metas = [_hapi2_xsec_metadata(item) for item in headers]
    first = metas[0] if metas else {}
    regions = [
        {
            "provider_id": meta.get("provider_id"),
            "filename": meta.get("filename"),
            "wavenumber_min": meta.get("wavenumber_min"),
            "wavenumber_max": meta.get("wavenumber_max"),
            "npts": meta.get("npts"),
        }
        for meta in metas
    ]
    provider_ids = [meta.get("provider_id") for meta in metas if meta.get("provider_id") is not None]
    filenames = [meta.get("filename") for meta in metas if meta.get("filename")]
    return {
        **first,
        "provider_id": provider_ids[0] if len(provider_ids) == 1 else None,
        "provider_ids": provider_ids,
        "filename": filenames[0] if len(filenames) == 1 else None,
        "filenames": filenames,
        "regions": sorted(
            regions,
            key=lambda item: float(item.get("wavenumber_min") or 0.0),
        ),
        "resolution_cm1": first.get("resolution_cm1") or spacing,
        "npts": int(x.size),
        "wavenumber_min": float(x[0]),
        "wavenumber_max": float(x[-1]),
        "merged_region_count": len(regions),
    }


def _xsec_attr(item: Any, *names: str) -> Any:
    for name in names:
        if isinstance(item, dict) and name in item:
            return item[name]
        value = getattr(item, name, _MISSING)
        if value is not _MISSING:
            return value
    return None


def _coerce_optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _coerce_optional_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _normalized_formula(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _normalized_lookup_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _sanitize_provider_error(exc: BaseException, *, api_key: str | None = None, max_length: int = 320) -> str:
    text = f"{type(exc).__name__}: {exc}".strip()
    if api_key:
        text = text.replace(api_key, "[redacted]")
    text = _SECRET_QUERY_RE.sub("credential=[redacted]", text)
    text = _AUTHORIZATION_RE.sub(r"\1[redacted]", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_length:
        return text[: max_length - 1].rstrip() + "..."
    return text


def _compute_hitran_spectrum_blocking(
    hapi: Any,
    cache_dir: Path,
    hitran_line_dir: Path,
    table_name: str,
    molecule_number: int,
    wavenumber_min: float,
    wavenumber_max: float,
    temperature_k: float,
    pressure_atm: float,
    resolution_cm1: float,
    api_key: str,
) -> tuple[Any, Any]:
    """Blocking HITRAN fetch + Voigt coefficient computation.

    Extracted so the caller can run it via ``asyncio.to_thread`` while
    holding ``_HITRAN_HAPI_LOCK``.  Cached HAPI line tables are reused;
    HAPI2 only downloads on a cache miss.
    """
    _migrate_legacy_hitran_table_cache(table_name, hitran_line_dir)
    if not (hitran_line_dir / f"{table_name}.data").exists():
        _hapi2_fetch_transitions_with_api_key(
            cache_dir,
            table_name,
            molecule_number,
            wavenumber_min,
            wavenumber_max,
            api_key=api_key,
        )
    hapi.db_begin(str(hitran_line_dir))
    components = _hitran_components_from_loaded_table(hapi, table_name, molecule_number)
    return hapi.absorptionCoefficient_Voigt(
        Components=components,
        SourceTables=table_name,
        Environment={"T": float(temperature_k), "p": float(pressure_atm)},
        WavenumberStep=float(resolution_cm1),
        HITRAN_units=True,
        OmegaWing=25.0,
        Diluent={"air": 1.0},
    )


def _hitran_components_from_loaded_table(hapi: Any, table_name: str, molecule_number: int) -> list[tuple[int, int]]:
    """Derive HAPI1 ``Components`` tuples from a downloaded HAPI2 line table.

    HAPI1 expects local HITRAN isotopologue ids (1-based), while HAPI2 line
    tables can expose isotope identifiers in forms that HAPI1 does not accept
    directly, including zero-based local ids.  Normalize against HAPI1's isotope
    registry before calling ``absorptionCoefficient_*``.
    """
    table_cache = getattr(hapi, "LOCAL_TABLE_CACHE", {}).get(table_name, {})
    table_data = table_cache.get("data", {}) if isinstance(table_cache, dict) else {}
    molecule_values = table_data.get("molec_id")
    isotope_values = table_data.get("local_iso_id")
    if molecule_values is None or isotope_values is None:
        return [(molecule_number, 1)]

    components: set[tuple[int, int]] = set()
    for raw_molecule, raw_isotope in zip(np.asarray(molecule_values).ravel(), np.asarray(isotope_values).ravel()):
        try:
            molecule_id = int(raw_molecule)
            isotope_id = int(raw_isotope)
        except (TypeError, ValueError):
            continue
        if molecule_id != molecule_number:
            continue
        local_id = _resolve_hapi_local_isotope_id(hapi, molecule_id, isotope_id)
        if local_id is not None:
            components.add((molecule_id, local_id))

    if not components:
        raise SynthesisError(f"HITRAN line table {table_name!r} did not contain usable isotopologues")
    return sorted(components)


def _resolve_hapi_local_isotope_id(hapi: Any, molecule_id: int, isotope_id: int) -> int | None:
    iso_registry = getattr(hapi, "ISO", {})
    if (molecule_id, isotope_id) in iso_registry:
        return isotope_id

    # Some APIs expose the global HITRAN isotopologue id.  HAPI1 stores that as
    # ISO[(molecule, local_id)][ISO_INDEX["id"]].
    iso_index = getattr(hapi, "ISO_INDEX", {})
    global_id_index = iso_index.get("id") if isinstance(iso_index, dict) else None
    if global_id_index is not None:
        for (candidate_molecule, local_id), info in iso_registry.items():
            if candidate_molecule != molecule_id:
                continue
            try:
                if int(info[global_id_index]) == isotope_id:
                    return int(local_id)
            except (IndexError, TypeError, ValueError):
                continue

    # HAPI2 can store local isotopologues as zero-based ids.
    if (molecule_id, isotope_id + 1) in iso_registry:
        return isotope_id + 1
    return None


def _hitran_table_cache_dir(table_name: str) -> Path:
    return _synthesis_cache_dir("hitran") / "tables" / table_name


def _hitran_line_table_dir(table_name: str) -> Path:
    return _hitran_table_cache_dir(table_name) / "~tmp"


def _hitran_spectrum_cache_path(
    component_id: str,
    *,
    resolution_cm1: float,
    wavenumber_min: float,
    wavenumber_max: float,
    temperature_k: float,
    pressure_atm: float,
) -> Path:
    payload = {
        "component_id": component_id,
        "profile": "Voigt",
        "resolution_cm1": float(resolution_cm1),
        "wavenumber_min": float(wavenumber_min),
        "wavenumber_max": float(wavenumber_max),
        "temperature_k": float(temperature_k),
        "pressure_atm": float(pressure_atm),
        "hitran_units": True,
        "diluent": {"air": 1.0},
        "omega_wing": 25.0,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
    return _synthesis_cache_dir("hitran") / "spectra" / f"{_safe_stem(component_id)}-{digest}.npz"


def _read_hitran_spectrum_cache(path: Path) -> tuple[np.ndarray, np.ndarray]:
    try:
        with np.load(path, allow_pickle=False) as cached:
            x = np.asarray(cached["wavenumber"], dtype=float)
            y = np.asarray(cached["intensity"], dtype=float)
    except Exception as exc:
        raise SynthesisError("Cached HITRAN spectrum is unreadable; remove it and retry the download") from exc
    if x.ndim != 1 or y.ndim != 1 or x.size != y.size or x.size < 2:
        raise SynthesisError("Cached HITRAN spectrum has an invalid shape; remove it and retry the download")
    return x, y


def _read_hitran_spectrum_cache_metadata(path: Path) -> dict[str, Any]:
    try:
        with np.load(path, allow_pickle=False) as cached:
            if "metadata_json" not in cached.files:
                return {}
            raw = str(cached["metadata_json"].item())
    except Exception:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _write_hitran_spectrum_cache(
    path: Path,
    x: np.ndarray,
    y: np.ndarray,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    with tmp_path.open("wb") as fh:
        np.savez_compressed(
            fh,
            spectra_sherpa_hitran_spectrum=np.asarray(1, dtype=np.int8),
            wavenumber=np.asarray(x, dtype=np.float64),
            intensity=np.asarray(y, dtype=np.float64),
            metadata_json=np.asarray(json.dumps(metadata or {}, sort_keys=True)),
        )
    tmp_path.replace(path)


def _migrate_legacy_hitran_table_cache(table_name: str, hitran_line_dir: Path) -> None:
    legacy_dir = _synthesis_cache_dir("hitran") / "~tmp"
    legacy_data = legacy_dir / f"{table_name}.data"
    if not legacy_data.exists() or (hitran_line_dir / f"{table_name}.data").exists():
        return
    hitran_line_dir.mkdir(parents=True, exist_ok=True)
    for suffix in (".data", ".header"):
        source = legacy_dir / f"{table_name}{suffix}"
        if source.exists():
            shutil.copy2(source, hitran_line_dir / source.name)


def _hapi2_fetch_transitions_with_api_key(
    cache_dir: Path,
    table_name: str,
    molecule_number: int,
    wavenumber_min: float,
    wavenumber_max: float,
    *,
    api_key: str,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "~tmp").mkdir(parents=True, exist_ok=True)
    hapi2 = _import_hapi2_module(cache_dir)
    original_cwd = Path.cwd()
    with _HAPI2_LOCK:
        with _temporary_hapi_api_key(hapi2, api_key):
            settings_obj = getattr(hapi2, "SETTINGS", None)
            previous_display = _MISSING
            if isinstance(settings_obj, dict):
                previous_display = settings_obj.get("display_fetch_url", _MISSING)
                settings_obj["display_fetch_url"] = False
            try:
                os.chdir(cache_dir)
                hapi2.fetch_info()
                molecules = hapi2.fetch_molecules()
                molecule = next((item for item in molecules if getattr(item, "id", None) == molecule_number), None)
                if molecule is None:
                    raise SynthesisError(f"HITRAN molecule {molecule_number} was not found in HAPI2 molecule catalog")
                isotopologues = hapi2.fetch_isotopologues(molecule)
                if not isotopologues:
                    raise SynthesisError(f"HITRAN molecule {molecule_number} has no available isotopologues")
                hapi2.fetch_transitions(
                    list(isotopologues),
                    float(wavenumber_min),
                    float(wavenumber_max),
                    table_name,
                )
            finally:
                os.chdir(original_cwd)
                if isinstance(settings_obj, dict):
                    if previous_display is _MISSING:
                        settings_obj.pop("display_fetch_url", None)
                    else:
                        settings_obj["display_fetch_url"] = previous_display


async def _download_nist_quant_ir_jcamp(cas: str, *, index: int) -> str:
    params = {"ID": cas, "Index": f"QUANT-IR,{index}", "Type": "IR-SPEC"}
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        page_response = await client.get(_NIST_WEBBOOK_URL, params=params)
        page_response.raise_for_status()
        download_url = _extract_nist_jcamp_download_url(page_response.text)
        jcamp_response = await client.get(download_url)
        jcamp_response.raise_for_status()
    return jcamp_response.text


def _extract_nist_jcamp_download_url(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        href_upper = href.upper()
        if "JCAMP=" in href_upper and "TYPE=IR" in href_upper:
            return urljoin(_NIST_WEBBOOK_URL, href)
    raise SynthesisError("NIST Quant IR page did not include a JCAMP-DX download link")


def _looks_like_jcamp_spectrum(text: str) -> bool:
    upper = text.upper()
    return upper.lstrip().startswith("##") and (
        "##XYDATA=" in upper or "##XYPOINTS=" in upper or "##PEAK TABLE=" in upper
    )


def _select_nist_variant(
    summary: SynthesisComponentSummary,
    *,
    resolution_cm1: float | None,
    apodization: str | None,
) -> SynthesisVariant:
    variants = summary.variants
    if not variants:
        raise SynthesisError(f"NIST component {summary.name} has no downloadable variants")
    if resolution_cm1 is None and apodization is None:
        requested = compute_common_nist_variant([summary.id])
        resolution_cm1 = float(requested["resolution_cm1"])
        apodization = str(requested["apodization"])
    for variant in variants:
        resolution_match = resolution_cm1 is None or abs(variant.resolution_cm1 - resolution_cm1) < 1e-9
        apod_match = apodization is None or variant.apodization.lower() == apodization.lower()
        if resolution_match and apod_match:
            return variant
    raise SynthesisError("Selected NIST resolution/apodization is not available for this component")


def _nist_quant_ir_index(resolution_cm1: float, apodization: str) -> int:
    apod_key = apodization.strip().lower()
    base = _NIST_APODIZATION_INDEX.get(apod_key)
    if base is None:
        raise SynthesisError(f"Unsupported NIST apodization: {apodization}")
    rounded_resolution = min(_NIST_RESOLUTION_INDEX, key=lambda value: abs(value - resolution_cm1))
    if abs(rounded_resolution - resolution_cm1) > 1e-9:
        raise SynthesisError(f"Unsupported NIST resolution: {resolution_cm1}")
    return base + _NIST_RESOLUTION_INDEX[rounded_resolution]


def _nist_cache_path(component_id: str, resolution_cm1: float, apodization: str) -> Path:
    return _synthesis_cache_dir("nist_quant_ir") / (
        f"{_safe_stem(component_id)}-{resolution_cm1:g}-{_safe_stem(apodization)}.jdx"
    )


def _import_hapi1_module() -> Any:
    try:
        import hapi  # type: ignore

        return hapi
    except Exception as exc:  # pragma: no cover - depends on optional extra
        raise SynthesisError("HITRAN synthesis requires the optional 'hitran' extra to be installed") from exc


def _import_hapi2_module(work_dir: Path | None = None) -> Any:
    original_cwd = Path.cwd()
    if work_dir is None:
        work_dir = _synthesis_cache_dir("hitran") / "hapi2"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        with _HAPI2_LOCK:
            os.chdir(work_dir)
            try:
                import hapi2 as hapi  # type: ignore
            finally:
                os.chdir(original_cwd)
        return hapi
    except Exception as exc:  # pragma: no cover - depends on optional extra
        detail = _sanitize_provider_error(exc)
        raise SynthesisError(
            "HITRAN downloads require HAPI2 from the optional 'hitran' extra "
            f"and a writable cache directory ({detail})"
        ) from exc


@contextmanager
def _temporary_hapi_api_key(hapi: Any, api_key: str):
    settings_obj = getattr(hapi, "SETTINGS", None)
    previous_settings_key = _MISSING
    if isinstance(settings_obj, dict):
        previous_settings_key = settings_obj.get("api_key", _MISSING)
        settings_obj["api_key"] = api_key
    variables = getattr(hapi, "VARIABLES", None)
    previous_variables_api_key = _MISSING
    previous_variables_key = _MISSING
    if isinstance(variables, dict):
        previous_variables_api_key = variables.get("API_KEY", _MISSING)
        previous_variables_key = variables.get("api_key", _MISSING)
        variables["API_KEY"] = api_key
        variables["api_key"] = api_key
    try:
        yield
    finally:
        if isinstance(settings_obj, dict):
            if previous_settings_key is _MISSING:
                settings_obj.pop("api_key", None)
            else:
                settings_obj["api_key"] = previous_settings_key
        if isinstance(variables, dict):
            if previous_variables_api_key is _MISSING:
                variables.pop("API_KEY", None)
            else:
                variables["API_KEY"] = previous_variables_api_key
            if previous_variables_key is _MISSING:
                variables.pop("api_key", None)
            else:
                variables["api_key"] = previous_variables_key


def _crop_spectrum(
    x: np.ndarray,
    y: np.ndarray,
    *,
    wavenumber_min: float | None,
    wavenumber_max: float | None,
) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(x)
    x_sorted = x[order]
    y_sorted = y[order]
    mask = np.ones_like(x_sorted, dtype=bool)
    if wavenumber_min is not None:
        mask &= x_sorted >= float(wavenumber_min)
    if wavenumber_max is not None:
        mask &= x_sorted <= float(wavenumber_max)
    if int(np.count_nonzero(mask)) < 2:
        raise SynthesisError("Selected wavenumber range does not contain enough spectrum points")
    return x_sorted[mask], y_sorted[mask]


def _synthesis_cache_dir(source: str) -> Path:
    cache_dir = settings.data_dir / "synthesis_cache" / _safe_stem(source)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _hitran_import_available() -> bool:
    try:
        import hapi  # noqa: F401
    except Exception:
        return False
    return True


def _ppm_to_number_density_cm3(
    concentration_ppm: np.ndarray,
    *,
    temperature_k: float,
    pressure_atm: float,
) -> np.ndarray:
    pressure_pa = pressure_atm * _ATM_PA
    molecules_per_m3 = pressure_pa / (_BOLTZMANN_J_PER_K * temperature_k)
    return concentration_ppm * 1e-6 * molecules_per_m3 / 1e6


def _component_name(component: SynthesisComponentInput) -> str:
    return component.name or component.spectrum.name or component.component_id


def _component_units(spectrum: SynthesisSpectrum) -> str:
    return spectrum.y_units or spectrum.units or spectrum.y_quantity


def _build_recipe(
    request: SynthesisRequest,
    *,
    wavenumber: np.ndarray,
    seed: int | None,
    grid_info: dict[str, Any],
) -> dict[str, Any]:
    settings_dict = request.settings.model_dump()
    settings_dict["seed"] = seed
    return {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "settings": settings_dict,
        "components": [
            {
                "component_id": component.component_id,
                "name": _component_name(component),
                "source": component.spectrum.source,
                "concentration_max_ppm": component.concentration_max_ppm,
                "control_points": [point.model_dump() for point in component.control_points],
                "spectrum_units": _component_units(component.spectrum),
            }
            for component in request.components
        ],
        "wavenumber": {
            "min": float(np.min(wavenumber)),
            "max": float(np.max(wavenumber)),
            "n_points": int(len(wavenumber)),
            "units": "cm^-1",
        },
        "grid": grid_info,
        "fingerprint": _fingerprint_recipe(request),
    }


def _fingerprint_recipe(request: SynthesisRequest) -> str:
    payload = {
        "settings": request.settings.model_dump(mode="json"),
        "components": [
            {
                "component_id": component.component_id,
                "name": component.name,
                "source": component.spectrum.source,
                "y_quantity": component.spectrum.y_quantity,
                "y_units": component.spectrum.y_units,
                "units": component.spectrum.units,
                "spectrum": _spectrum_fingerprint(component.spectrum),
                "concentration_max_ppm": component.concentration_max_ppm,
                "control_points": [point.model_dump(mode="json") for point in component.control_points],
            }
            for component in request.components
        ],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _spectrum_fingerprint(spectrum: SynthesisSpectrum) -> dict[str, Any]:
    x = np.asarray(spectrum.wavenumber, dtype=np.float64)
    y = np.asarray(spectrum.intensity, dtype=np.float64)
    return {
        "component_id": spectrum.component_id,
        "name": spectrum.name,
        "n_points": int(x.size),
        "wavenumber_min": float(np.min(x)),
        "wavenumber_max": float(np.max(x)),
        "wavenumber_sha256": _array_sha256(x),
        "intensity_sha256": _array_sha256(y),
    }


def _array_sha256(values: np.ndarray) -> str:
    arr = np.ascontiguousarray(values, dtype=np.float64)
    digest = hashlib.sha256()
    digest.update(str(arr.shape).encode("utf-8"))
    digest.update(arr.tobytes(order="C"))
    return digest.hexdigest()


def _default_dataset_name(result: SynthesisResult) -> str:
    component_bits = "-".join(_safe_stem(c.name) for c in result.components[:3])
    suffix = result.recipe.get("fingerprint", "synthetic")
    return f"Synthetic {result.source} {component_bits} {suffix}".strip()


def _safe_stem(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-._")
    return safe[:80] or "synthetic-spectrum"


def _unique_synthesis_artifact_paths(base: Path, stem: str) -> tuple[Path, Path]:
    for index in range(1, 10_000):
        candidate_stem = stem if index == 1 else f"{stem}-{index}"
        npz_path = base / f"{candidate_stem}.npz"
        recipe_path = base / f"{candidate_stem}.recipe.json"
        if not npz_path.exists() and not recipe_path.exists():
            return npz_path, recipe_path
    raise SynthesisError("Could not allocate a unique synthetic dataset filename")
