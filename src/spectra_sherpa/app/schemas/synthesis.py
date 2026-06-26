from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

SynthesisSource = Literal["nist_quant_ir", "hitran", "hitran_xsec"]
SynthesisRangeMode = Literal["common", "widest"]


class SynthesisVariant(BaseModel):
    resolution_cm1: float = Field(..., gt=0)
    apodization: str
    wavenumber_min: float | None = None
    wavenumber_max: float | None = None


class SynthesisComponentSummary(BaseModel):
    id: str
    name: str
    source: SynthesisSource
    cas: str | None = None
    formula: str | None = None
    variants: list[SynthesisVariant] = Field(default_factory=list)
    xsec_options: list[dict[str, Any]] = Field(default_factory=list)


class SynthesisSourcesResponse(BaseModel):
    sources: list[dict[str, object]]


class SynthesisSearchResponse(BaseModel):
    components: list[SynthesisComponentSummary]


class SynthesisSpectrumResponse(BaseModel):
    component_id: str
    name: str
    source: SynthesisSource
    wavenumber: list[float] = Field(..., min_length=2, max_length=200_000)
    intensity: list[float] = Field(..., min_length=2, max_length=200_000)
    y_quantity: str | None = None
    y_units: str | None = None
    resolution_cm1: float | None = None
    apodization: str | None = None
    cached: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class SynthesisSpectrumLoadRequest(BaseModel):
    source: SynthesisSource
    component_id: str = Field(..., min_length=1, max_length=120)
    resolution_cm1: float | None = Field(default=None, gt=0)
    apodization: str | None = Field(default=None, max_length=80)
    wavenumber_min: float | None = None
    wavenumber_max: float | None = None
    temperature_k: float = Field(default=293.0, gt=0)
    pressure_atm: float = Field(default=1.0, gt=0)


class SynthesisSpectrumLoadResponse(BaseModel):
    queued: bool = False
    job_id: int | None = None
    message: str | None = None
    spectrum: SynthesisSpectrumResponse | None = None


class SynthesisSpectrum(BaseModel):
    component_id: str
    name: str
    source: SynthesisSource
    wavenumber: list[float] = Field(..., min_length=2, max_length=200_000)
    intensity: list[float] = Field(..., min_length=2, max_length=200_000)
    units: str | None = None
    y_quantity: str | None = None
    y_units: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _same_length(self) -> SynthesisSpectrum:
        if len(self.wavenumber) != len(self.intensity):
            raise ValueError("wavenumber and intensity must have the same length")
        quantity = (self.y_quantity or "").strip().lower()
        units = (self.y_units or "").strip().lower().replace("µ", "u")
        if self.source == "nist_quant_ir":
            if quantity not in {"absorption_coefficient", "decadic_absorption_coefficient"}:
                raise ValueError("NIST Quant IR spectra must declare a decadic absorption coefficient")
            if self.y_units and units not in {"ppm^-1 m^-1", "(umol/mol)^-1 m^-1", "umol/mol^-1 m^-1"}:
                raise ValueError("NIST Quant IR spectra must use ppm^-1 m^-1 units")
        elif self.source in {"hitran", "hitran_xsec"}:
            if quantity not in {"cross_section", "absorption_cross_section"}:
                raise ValueError("HITRAN spectra must declare an absorption cross section")
            if self.y_units and units not in {"cm^2 molecule^-1", "cm2 molecule^-1", "cm^2/molecule"}:
                raise ValueError("HITRAN spectra must use cm^2 molecule^-1 units")
        return self


class SynthesisControlPoint(BaseModel):
    """A concentration-trace control point.

    Two parametrizations are accepted (exactly one per point):

    - ``y``      normalized 0-1 curve *shape*; the absolute concentration is
                 ``y * SynthesisComponentInput.concentration_max_ppm``. This is
                 the canonical form used by the handle-tuned curve editor and
                 keeps every species on a magnitude-agnostic editing surface.
    - ``y_ppm``  absolute concentration in ppm (legacy form). Preserved so
                 older clients / saved recipes keep working unchanged.
    """

    x: float = Field(..., ge=0)
    y: float | None = Field(default=None, ge=0, le=1)
    y_ppm: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _exactly_one_parametrization(self) -> SynthesisControlPoint:
        if (self.y is None) == (self.y_ppm is None):
            raise ValueError("control point must set exactly one of 'y' (0-1 shape) or 'y_ppm' (absolute ppm)")
        return self


class SynthesisComponentInput(BaseModel):
    component_id: str
    name: str | None = None
    spectrum: SynthesisSpectrum
    # Per-species peak concentration in ppm. Different species span very
    # different orders of magnitude (trace contaminant vs. major component),
    # so the curve is edited as a normalized 0-1 shape and this multiplier
    # carries the magnitude. Required when control points use ``y``; ignored
    # in the legacy ``y_ppm`` form.
    concentration_max_ppm: float | None = Field(default=None, gt=0)
    control_points: list[SynthesisControlPoint] = Field(..., min_length=2, max_length=64)

    @model_validator(mode="after")
    def _consistent_parametrization(self) -> SynthesisComponentInput:
        normalized = [point.y is not None for point in self.control_points]
        if any(normalized) and not all(normalized):
            raise ValueError(
                f"component '{self.component_id}' mixes normalized 'y' and absolute 'y_ppm' control points"
            )
        if all(normalized) and self.concentration_max_ppm is None:
            raise ValueError(
                f"component '{self.component_id}' uses normalized control points but no concentration_max_ppm"
            )
        return self

    def effective_ppm_points(self) -> list[tuple[float, float]]:
        """Return ``(x, ppm)`` points, resolving shape x multiplier centrally.

        This is the single place the normalized/absolute distinction is
        collapsed, so the synthesis service only ever sees absolute ppm and
        Beer-Lambert stays untouched.
        """
        if self.control_points and self.control_points[0].y is not None:
            multiplier = float(self.concentration_max_ppm or 0.0)
            return [(float(p.x), float(p.y or 0.0) * multiplier) for p in self.control_points]
        return [(float(p.x), float(p.y_ppm or 0.0)) for p in self.control_points]


class SynthesisSettings(BaseModel):
    source: SynthesisSource
    range_mode: SynthesisRangeMode = "common"
    n_samples: int = Field(default=50, ge=2, le=1000)
    pathlength_cm: float = Field(default=1.0, gt=0)
    temperature_k: float = Field(default=293.0, gt=0)
    pressure_atm: float = Field(default=1.0, gt=0)
    noise_sigma_au: float = Field(default=0.001, ge=0)
    # Wavenumber grids for different compounds (esp. NIST Quant IR) are often
    # offset by a small fraction of a cm^-1 at the *same* spacing. Minority
    # grids are rigidly snapped onto the majority grid when every point is
    # within this tolerance of a majority point (absorbance unchanged).
    # 0 requires the grids to already coincide.
    snap_tolerance_cm1: float = Field(default=0.05, ge=0, le=5.0)
    seed: int | None = None
    resolution_cm1: float | None = Field(default=None, gt=0)
    apodization: str | None = None
    preview_wavenumber_min: float | None = None
    preview_wavenumber_max: float | None = None
    preview_wavenumber_interval_cm1: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _valid_preview_range(self) -> SynthesisSettings:
        if (
            self.preview_wavenumber_min is not None
            and self.preview_wavenumber_max is not None
            and self.preview_wavenumber_min >= self.preview_wavenumber_max
        ):
            raise ValueError("preview_wavenumber_min must be lower than preview_wavenumber_max")
        return self


class SynthesisRequest(BaseModel):
    settings: SynthesisSettings
    components: list[SynthesisComponentInput] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _validate_control_point_domain(self) -> SynthesisRequest:
        max_x = float(self.settings.n_samples - 1)
        for component in self.components:
            for point in component.control_points:
                if point.x > max_x:
                    raise ValueError(
                        "Synthesis control point x values must be sample indices "
                        f"between 0 and {self.settings.n_samples - 1}"
                    )
        return self


class SynthesisComponentResult(BaseModel):
    id: str
    name: str
    concentration_ppm: list[float]


class SynthesisResult(BaseModel):
    source: SynthesisSource
    wavenumber: list[float]
    absorbance: list[list[float]]
    units: str = "absorbance"
    components: list[SynthesisComponentResult]
    recipe: dict
    ground_truth: dict
    truncated: bool = False


class SynthesisSaveRequest(SynthesisRequest):
    name: str | None = Field(default=None, max_length=120)
    experiment_id: int | None = None
    project_id: int | None = None


class SynthesisSaveResponse(BaseModel):
    experiment_id: int
    file_id: int
    file_path: str
    recipe_path: str
    result: SynthesisResult
