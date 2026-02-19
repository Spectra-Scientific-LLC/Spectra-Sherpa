from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SpectrumPayload(BaseModel):
    label: str
    file_path: Optional[str] = None
    wavenumber: Optional[List[float]] = None
    absorbance: Optional[List[float]] = None
    source: str = "csv"
    model_type: Optional[str] = None
    model_at_wavenumber: Optional[List[Optional[str]]] = None
    slope: Optional[List[Optional[float]]] = None
    intercept: Optional[List[Optional[float]]] = None
    s: Optional[List[Optional[float]]] = None
    p: Optional[List[Optional[float]]] = None
    c: Optional[List[Optional[float]]] = None
    reference_concentration: Optional[float] = None
    concentration_mode: Optional[str] = None
    x_label: Optional[str] = None
    x_unit: Optional[str] = None
    pathlength_m: Optional[float] = None


class PreprocessRequest(BaseModel):
    spectra: List[SpectrumPayload]
    settings: Dict[str, Any] = Field(default_factory=dict)


class PreprocessResponse(BaseModel):
    status: str
    data: List[SpectrumPayload]
    metadata: Optional[Dict[str, Any]] = None


class CurvePointsRequest(BaseModel):
    count: int = Field(default=11, ge=4, le=60)


class CurvePointsResponse(BaseModel):
    points: List[Dict[str, float]]
    segments: List[Dict[str, Any]]


class CurveDefaultsResponse(BaseModel):
    curvePoints: List[Dict[str, float]]
    curveSegments: List[Dict[str, Any]]
    curveDefaultCount: int
    curveSamplesPerSegment: int
    curveSourceLabel: str


class CurveSpec(BaseModel):
    """Specification for generating a single concentration curve."""

    label: str
    curve_type: str = Field(
        default="constant", description="Type: sigmoid, gaussian, linear, exponential, step, constant, catmull_rom"
    )
    max_concentration: float = Field(default=1.0, ge=0.0)
    center: float = Field(default=0.5, ge=0.0, le=1.0, description="Center for sigmoid/gaussian (0-1)")
    width: float = Field(default=0.1, gt=0.0, description="Width for sigmoid/gaussian/exponential")
    control_points: Optional[List[Dict[str, float]]] = Field(
        default=None, description="Control points for catmull_rom curves"
    )


class ConcentrationGenerateRequest(BaseModel):
    """Request to generate concentration curves for multiple species."""

    curves: List[CurveSpec]
    n_points: int = Field(default=100, ge=2, le=10000, description="Number of time points")
    time_min: float = Field(default=0.0, description="Start time")
    time_max: float = Field(default=1.0, description="End time")
    time_unit: str = Field(default="s", description="Time unit (s, min, h)")


class ConcentrationGenerateResponse(BaseModel):
    """Response containing generated concentration curves."""

    status: str
    times: List[float]
    time_unit: str
    concentrations: Dict[str, List[float]]  # {species_label: [concentration_values]}
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SynthesizeRequest(BaseModel):
    """Request to synthesize blended spectra from species and concentrations."""

    species: List[SpectrumPayload]
    concentrations: Dict[str, List[float]]  # {species_label: [concentration_values]}
    pathlength_m: Optional[float] = None
    settings: Dict[str, Any] = Field(default_factory=dict)


class SynthesizeResponse(BaseModel):
    """Response containing synthesized spectral data."""

    status: str
    wavenumbers: List[float]
    times: List[float]
    absorbance_matrix: List[List[float]]  # (n_wavenumbers, n_times)
    statistics: Dict[str, float]
    ground_truth: Optional[Dict[str, Any]] = None


# Legacy aliases for backward compatibility
class BlendRequest(BaseModel):
    """DEPRECATED: Use SynthesizeRequest instead."""

    species: List[SpectrumPayload]
    concentration_timeseries: Dict[str, List[float]]
    pathlength_m: Optional[float] = None
    settings: Dict[str, Any] = Field(default_factory=dict)


class BlendResponse(BaseModel):
    """DEPRECATED: Use SynthesizeResponse instead."""

    status: str
    wavenumbers: List[float]
    times: List[float]
    absorbance_matrix: List[List[float]]
    statistics: Dict[str, float]
