from __future__ import annotations

import json
import math
import os
import uuid
from typing import ClassVar

import httpx
import numpy as np
import pytest

from spectra_sherpa.app.schemas.synthesis import (
    SynthesisComponentInput,
    SynthesisControlPoint,
    SynthesisRequest,
    SynthesisSaveRequest,
    SynthesisSettings,
    SynthesisSpectrum,
    SynthesisSpectrumResponse,
)
from spectra_sherpa.app.services.synthesis import (
    HITRAN_CROSS_SECTION_TO_MOLAR_ABSORPTIVITY,
    MOLAR_ABSORPTION_COEFFICIENT_UNITS,
    SynthesisError,
    is_synthetic_npz,
    load_synthetic_npz,
    save_synthesis_result,
    synthesize,
    update_synthetic_npz_metadata,
)


def test_preview_spectrum_payload_allows_large_loaded_spectra() -> None:
    n_points = 50_001
    spectrum = SynthesisSpectrum(
        component_id="hitran_xsec:test",
        name="large x-section",
        source="hitran_xsec",
        wavenumber=[float(index) for index in range(n_points)],
        intensity=[0.0] * n_points,
        y_quantity="cross_section",
        y_units="cm^2 molecule^-1",
    )

    assert len(spectrum.wavenumber) == n_points


def _component(
    component_id: str,
    *,
    source: str = "nist_quant_ir",
    y: list[float] | None = None,
    ppm: float = 100.0,
    x_end: float = 2.0,
) -> SynthesisComponentInput:
    return SynthesisComponentInput(
        component_id=component_id,
        name=component_id,
        spectrum=SynthesisSpectrum(
            component_id=component_id,
            name=component_id,
            source=source,  # type: ignore[arg-type]
            wavenumber=[1000.0, 1001.0, 1002.0],
            intensity=y or [1.0, 2.0, 3.0],
            y_quantity="absorption_coefficient" if source == "nist_quant_ir" else "cross_section",
            y_units="ppm^-1 m^-1" if source == "nist_quant_ir" else "cm^2 molecule^-1",
        ),
        control_points=[
            SynthesisControlPoint(x=0, y_ppm=ppm),
            SynthesisControlPoint(x=x_end, y_ppm=ppm),
        ],
    )


def _normalized_component(
    component_id: str,
    *,
    shape: list[tuple[float, float]],
    max_ppm: float,
) -> SynthesisComponentInput:
    return SynthesisComponentInput(
        component_id=component_id,
        name=component_id,
        spectrum=SynthesisSpectrum(
            component_id=component_id,
            name=component_id,
            source="nist_quant_ir",
            wavenumber=[1000.0, 1001.0, 1002.0],
            intensity=[1.0, 2.0, 3.0],
            y_quantity="absorption_coefficient",
            y_units="ppm^-1 m^-1",
        ),
        concentration_max_ppm=max_ppm,
        control_points=[SynthesisControlPoint(x=x, y=y) for x, y in shape],
    )


def test_synthesis_allows_more_than_twelve_components() -> None:
    request = SynthesisRequest(
        settings=SynthesisSettings(source="nist_quant_ir", n_samples=3, pathlength_cm=10.0, noise_sigma_au=0.0),
        components=[
            _normalized_component(
                f"component_{index}",
                shape=[(0, 0.2), (2, 0.8)],
                max_ppm=100.0,
            )
            for index in range(13)
        ],
    )

    result = synthesize(request)

    assert len(result.components) == 13
    assert np.asarray(result.absorbance).shape == (3, 3)


def test_hitran_xsec_preview_uses_cross_section_beer_lambert_path() -> None:
    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(
                source="hitran_xsec",
                n_samples=2,
                pathlength_cm=1.0,
                temperature_k=293.0,
                pressure_atm=1.0,
                noise_sigma_au=0.0,
            ),
            components=[
                SynthesisComponentInput(
                    component_id="hitran_xsec:test",
                    name="x-section",
                    spectrum=SynthesisSpectrum(
                        component_id="hitran_xsec:test",
                        name="x-section",
                        source="hitran_xsec",
                        wavenumber=[1000.0, 1001.0, 1002.0],
                        intensity=[1.0e-20, 2.0e-20, 3.0e-20],
                        y_quantity="cross_section",
                        y_units="cm^2 molecule^-1",
                    ),
                    control_points=[
                        SynthesisControlPoint(x=0, y_ppm=100.0),
                        SynthesisControlPoint(x=1, y_ppm=100.0),
                    ],
                )
            ],
        )
    )

    assert result.source == "hitran_xsec"
    assert result.units == "absorbance"
    assert np.asarray(result.absorbance).shape == (2, 3)
    assert float(np.max(result.absorbance)) > 0.0


def test_normalized_shape_times_multiplier_matches_absolute_ppm() -> None:
    """Reparametrization is unit-preserving: shape x multiplier == y_ppm."""
    settings = SynthesisSettings(source="nist_quant_ir", n_samples=5, pathlength_cm=100.0, noise_sigma_au=0.0)

    absolute = synthesize(
        SynthesisRequest(
            settings=settings,
            components=[
                SynthesisComponentInput(
                    component_id="water",
                    name="water",
                    spectrum=SynthesisSpectrum(
                        component_id="water",
                        name="water",
                        source="nist_quant_ir",
                        wavenumber=[1000.0, 1001.0, 1002.0],
                        intensity=[1.0, 2.0, 3.0],
                        y_quantity="absorption_coefficient",
                        y_units="ppm^-1 m^-1",
                    ),
                    control_points=[
                        SynthesisControlPoint(x=0, y_ppm=0.0),
                        SynthesisControlPoint(x=2, y_ppm=250.0),
                        SynthesisControlPoint(x=4, y_ppm=500.0),
                    ],
                )
            ],
        )
    )
    normalized = synthesize(
        SynthesisRequest(
            settings=settings,
            components=[
                _normalized_component(
                    "water",
                    shape=[(0, 0.0), (2, 0.5), (4, 1.0)],
                    max_ppm=500.0,
                )
            ],
        )
    )

    np.testing.assert_allclose(normalized.absorbance, absolute.absorbance)
    np.testing.assert_allclose(normalized.ground_truth["C"], absolute.ground_truth["C"])


def test_recipe_records_concentration_multiplier() -> None:
    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(source="nist_quant_ir", n_samples=3, noise_sigma_au=0.0),
            components=[_normalized_component("water", shape=[(0, 0.2), (2, 0.8)], max_ppm=12345.0)],
        )
    )
    assert result.recipe["components"][0]["concentration_max_ppm"] == 12345.0


def test_recipe_fingerprint_hashes_spectra_without_storing_raw_arrays() -> None:
    from spectra_sherpa.app.services import synthesis as synthesis_service

    request = SynthesisRequest(
        settings=SynthesisSettings(source="nist_quant_ir", n_samples=3, noise_sigma_au=0.0),
        components=[_component("water", y=[1.0, 2.0, 3.0])],
    )
    changed = SynthesisRequest(
        settings=request.settings,
        components=[_component("water", y=[1.0, 2.0, 4.0])],
    )

    fingerprint = synthesis_service._fingerprint_recipe(request)
    changed_fingerprint = synthesis_service._fingerprint_recipe(changed)
    spectrum_fingerprint = synthesis_service._spectrum_fingerprint(request.components[0].spectrum)

    assert fingerprint != changed_fingerprint
    assert "intensity" not in spectrum_fingerprint
    assert "wavenumber" not in spectrum_fingerprint
    assert spectrum_fingerprint["intensity_sha256"]
    assert spectrum_fingerprint["wavenumber_sha256"]


def test_normalized_control_points_require_multiplier() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="no concentration_max_ppm"):
        SynthesisComponentInput(
            component_id="water",
            spectrum=SynthesisSpectrum(
                component_id="water",
                name="water",
                source="nist_quant_ir",
                wavenumber=[1000.0, 1001.0],
                intensity=[1.0, 2.0],
                y_quantity="absorption_coefficient",
                y_units="ppm^-1 m^-1",
            ),
            control_points=[SynthesisControlPoint(x=0, y=0.1), SynthesisControlPoint(x=1, y=0.9)],
        )


def test_control_point_rejects_ambiguous_parametrization() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="exactly one"):
        SynthesisControlPoint(x=0, y=0.5, y_ppm=10.0)
    with pytest.raises(ValidationError, match="exactly one"):
        SynthesisControlPoint(x=0)


def test_component_rejects_mixed_parametrization() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="mixes normalized"):
        SynthesisComponentInput(
            component_id="water",
            concentration_max_ppm=100.0,
            spectrum=SynthesisSpectrum(
                component_id="water",
                name="water",
                source="nist_quant_ir",
                wavenumber=[1000.0, 1001.0],
                intensity=[1.0, 2.0],
                y_quantity="absorption_coefficient",
                y_units="ppm^-1 m^-1",
            ),
            control_points=[SynthesisControlPoint(x=0, y=0.1), SynthesisControlPoint(x=1, y_ppm=90.0)],
        )


def test_nist_synthesis_uses_decadic_beer_lambert_units() -> None:
    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(source="nist_quant_ir", n_samples=3, pathlength_cm=100.0, noise_sigma_au=0.0),
            components=[_component("water", y=[0.1, 0.2, 0.3], ppm=10.0)],
        )
    )

    assert result.units == "absorbance"
    assert result.wavenumber == [1000.0, 1001.0, 1002.0]
    assert np.allclose(result.absorbance, [[1.0, 2.0, 3.0]] * 3)
    assert result.ground_truth["C_units"] == "ppm"
    assert result.ground_truth["S_units"] == ["ppm^-1 m^-1"]


def test_hitran_synthesis_converts_napierian_optical_depth_to_decadic_absorbance() -> None:
    sigma = 1e-20
    ppm = 1000.0
    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(source="hitran", n_samples=2, pathlength_cm=10.0, noise_sigma_au=0.0),
            components=[_component("co2", source="hitran", y=[sigma, sigma, sigma], ppm=ppm, x_end=1.0)],
        )
    )

    number_density_cm3 = ppm * 1e-6 * 101325.0 / (1.380649e-23 * 293.0) / 1e6
    expected = sigma * number_density_cm3 * 10.0 / math.log(10.0)
    assert np.allclose(result.absorbance, [[expected, expected, expected]] * 2)


def test_synthesis_rejects_source_mixing() -> None:
    with pytest.raises(SynthesisError, match="selected source"):
        synthesize(
            SynthesisRequest(
                settings=SynthesisSettings(source="nist_quant_ir"),
                components=[
                    _component("water", source="nist_quant_ir"),
                    _component("co2", source="hitran"),
                ],
            )
        )


def _grid_component(
    cid: str,
    *,
    wavenumber: list[float],
    intensity: list[float] | None = None,
    ppm: float = 100.0,
    source: str = "nist_quant_ir",
    metadata: dict[str, object] | None = None,
) -> SynthesisComponentInput:
    n = len(wavenumber)
    return SynthesisComponentInput(
        component_id=cid,
        name=cid,
        spectrum=SynthesisSpectrum(
            component_id=cid,
            name=cid,
            source=source,  # type: ignore[arg-type]
            wavenumber=list(wavenumber),
            intensity=list(intensity) if intensity is not None else list(np.linspace(0.1, 1.0, n)),
            y_quantity="absorption_coefficient" if source == "nist_quant_ir" else "cross_section",
            y_units="ppm^-1 m^-1" if source == "nist_quant_ir" else "cm^2 molecule^-1",
            metadata=metadata or {},
        ),
        control_points=[
            SynthesisControlPoint(x=0, y_ppm=ppm),
            SynthesisControlPoint(x=1, y_ppm=ppm),
        ],
    )


def test_minority_grid_is_snapped_to_median_absorbance_preserved() -> None:
    """Two species define the median; the offset third is snapped, not interpolated."""
    base = np.arange(1000.0, 1100.0, 1.0)  # 1 cm^-1 spacing
    a_int = list(np.linspace(0.10, 1.00, len(base)))
    c_int = list(np.linspace(0.05, 0.50, len(base)))  # the offset (minority) species
    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(source="nist_quant_ir", n_samples=2, noise_sigma_au=0.0),
            components=[
                SynthesisComponentInput(
                    component_id="a",
                    name="a",
                    spectrum=SynthesisSpectrum(
                        component_id="a",
                        name="a",
                        source="nist_quant_ir",
                        wavenumber=list(base),
                        intensity=a_int,
                        y_quantity="absorption_coefficient",
                        y_units="ppm^-1 m^-1",
                    ),
                    control_points=[SynthesisControlPoint(x=0, y_ppm=100.0), SynthesisControlPoint(x=1, y_ppm=100.0)],
                ),
                SynthesisComponentInput(
                    component_id="b",
                    name="b",
                    spectrum=SynthesisSpectrum(
                        component_id="b",
                        name="b",
                        source="nist_quant_ir",
                        wavenumber=list(base),  # same as a → defines the median
                        intensity=a_int,
                        y_quantity="absorption_coefficient",
                        y_units="ppm^-1 m^-1",
                    ),
                    control_points=[SynthesisControlPoint(x=0, y_ppm=100.0), SynthesisControlPoint(x=1, y_ppm=100.0)],
                ),
                SynthesisComponentInput(
                    component_id="c",
                    name="c",
                    spectrum=SynthesisSpectrum(
                        component_id="c",
                        name="c",
                        source="nist_quant_ir",
                        wavenumber=list(base + 0.02),  # shifted +0.02 cm^-1, same spacing
                        intensity=c_int,
                        y_quantity="absorption_coefficient",
                        y_units="ppm^-1 m^-1",
                    ),
                    control_points=[SynthesisControlPoint(x=0, y_ppm=100.0), SynthesisControlPoint(x=1, y_ppm=100.0)],
                ),
            ],
        )
    )
    grid = result.recipe["grid"]
    comps = {c["id"]: c for c in grid["components"]}
    # Median of [base, base, base+0.02] == base → a,b unshifted; c shifted by 0.02.
    assert comps["a"]["shifted"] is False and comps["b"]["shifted"] is False
    assert comps["c"]["shifted"] is True
    assert comps["c"]["max_shift_cm1"] == pytest.approx(0.02, abs=1e-9)
    assert grid["n_shifted"] == 1 and grid["any_shifted"] is True
    assert grid["reference_kind"].startswith("element-wise median")
    # Overlap drops base[0]=1000 (c starts at 1000.02); reference is the median
    # grid == base[1:].
    np.testing.assert_allclose(result.wavenumber, base[1:])
    # Absorbance is carried over UNCHANGED (a pure x relabel, no interpolation):
    # each species' S row is exactly its own native intensity over the overlap.
    order = [d["id"] for d in grid["components"]]  # aligned order == request order
    np.testing.assert_allclose(result.ground_truth["S"][order.index("a")], a_int[1:])
    np.testing.assert_allclose(result.ground_truth["S"][order.index("c")], c_int[1:])


def test_identical_grids_report_no_shift() -> None:
    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(source="nist_quant_ir", n_samples=2, noise_sigma_au=0.0),
            components=[
                _grid_component("a", wavenumber=list(np.arange(1000.0, 1050.0, 1.0))),
                _grid_component("b", wavenumber=list(np.arange(1000.0, 1050.0, 1.0))),
            ],
        )
    )
    assert result.recipe["grid"]["any_shifted"] is False
    assert result.recipe["grid"]["n_shifted"] == 0


def test_widest_range_zero_pads_species_outside_native_coverage() -> None:
    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(
                source="nist_quant_ir",
                range_mode="widest",
                n_samples=2,
                pathlength_cm=100.0,
                noise_sigma_au=0.0,
            ),
            components=[
                _grid_component("left", wavenumber=[1000.0, 1001.0, 1002.0], ppm=1.0),
                _grid_component("right", wavenumber=[1001.0, 1002.0, 1003.0], ppm=1.0),
            ],
        )
    )

    assert result.wavenumber == [1000.0, 1001.0, 1002.0, 1003.0]
    grid = result.recipe["grid"]
    assert grid["range_mode"] == "widest"
    assert grid["components"][0]["zero_padded_points"] == 1
    assert grid["components"][1]["zero_padded_points"] == 1
    np.testing.assert_allclose(result.ground_truth["S"][0], [0.1, 0.55, 1.0, 0.0])
    np.testing.assert_allclose(result.ground_truth["S"][1], [0.0, 0.1, 0.55, 1.0])
    np.testing.assert_allclose(result.absorbance, [[0.1, 0.65, 1.55, 1.0]] * 2)


def test_widest_range_uses_closest_native_point_within_snap_window() -> None:
    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(
                source="nist_quant_ir",
                range_mode="widest",
                n_samples=2,
                pathlength_cm=100.0,
                noise_sigma_au=0.0,
                snap_tolerance_cm1=0.5,
            ),
            components=[
                _grid_component("reference-a", wavenumber=[1000.0, 1001.0, 1002.0], ppm=1.0),
                _grid_component("reference-b", wavenumber=[1000.0, 1001.0, 1002.0], ppm=1.0),
                _grid_component(
                    "dense",
                    wavenumber=[1000.1, 1000.45, 1000.85, 1001.25, 1001.75, 1002.2],
                    intensity=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
                    ppm=1.0,
                ),
            ],
        )
    )

    assert result.wavenumber == [1000.0, 1001.0, 1002.0]
    grid = result.recipe["grid"]
    assert grid["range_mode"] == "widest"
    assert grid["spacing_consistent"] is False
    assert grid["components"][2]["matched_points"] == 3
    assert grid["components"][2]["zero_padded_points"] == 0
    np.testing.assert_allclose(result.ground_truth["S"][2], [1.0, 3.0, 6.0])


def test_preview_interval_controls_common_output_grid() -> None:
    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(
                source="nist_quant_ir",
                range_mode="common",
                n_samples=2,
                pathlength_cm=100.0,
                noise_sigma_au=0.0,
                snap_tolerance_cm1=0.35,
                preview_wavenumber_min=1000.0,
                preview_wavenumber_max=1004.0,
                preview_wavenumber_interval_cm1=2.0,
            ),
            components=[
                _grid_component(
                    "exact",
                    wavenumber=[1000.0, 1001.0, 1002.0, 1003.0, 1004.0],
                    intensity=[10.0, 11.0, 12.0, 13.0, 14.0],
                    ppm=1.0,
                ),
                _grid_component(
                    "offset",
                    wavenumber=[1000.2, 1001.2, 1002.2, 1003.2, 1004.2],
                    intensity=[20.0, 21.0, 22.0, 23.0, 24.0],
                    ppm=1.0,
                ),
            ],
        )
    )

    assert result.wavenumber == [1000.0, 1002.0, 1004.0]
    grid = result.recipe["grid"]
    assert grid["preview_interval_cm1"] == 2.0
    assert grid["reference_kind"].startswith("requested interval grid")
    np.testing.assert_allclose(result.ground_truth["S"][0], [10.0, 12.0, 14.0])
    np.testing.assert_allclose(result.ground_truth["S"][1], [20.0, 22.0, 24.0])


def test_preview_interval_widest_zero_fills_bins_without_native_match() -> None:
    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(
                source="nist_quant_ir",
                range_mode="widest",
                n_samples=2,
                pathlength_cm=100.0,
                noise_sigma_au=0.0,
                snap_tolerance_cm1=0.2,
                preview_wavenumber_min=1000.0,
                preview_wavenumber_max=1004.0,
                preview_wavenumber_interval_cm1=2.0,
            ),
            components=[
                _grid_component(
                    "left",
                    wavenumber=[1000.0, 1002.0],
                    intensity=[1.0, 2.0],
                    ppm=1.0,
                ),
                _grid_component(
                    "right",
                    wavenumber=[1002.0, 1004.0],
                    intensity=[3.0, 4.0],
                    ppm=1.0,
                ),
            ],
        )
    )

    assert result.wavenumber == [1000.0, 1002.0, 1004.0]
    np.testing.assert_allclose(result.ground_truth["S"][0], [1.0, 2.0, 0.0])
    np.testing.assert_allclose(result.ground_truth["S"][1], [0.0, 3.0, 4.0])


def test_hitran_line_by_line_widest_bins_phase_shifted_grids_by_resolution() -> None:
    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(
                source="hitran",
                range_mode="widest",
                n_samples=2,
                pathlength_cm=1.0,
                noise_sigma_au=0.0,
                snap_tolerance_cm1=0.05,
                resolution_cm1=1.0,
            ),
            components=[
                _grid_component(
                    "Methane",
                    source="hitran",
                    wavenumber=[400.42, 401.42, 402.42, 403.42],
                    intensity=[1.0e-22, 2.0e-22, 3.0e-22, 4.0e-22],
                    ppm=1000.0,
                ),
                _grid_component(
                    "Nitrogen dioxide",
                    source="hitran",
                    wavenumber=[400.72, 401.72, 402.72, 403.72],
                    intensity=[2.0e-22, 3.0e-22, 4.0e-22, 5.0e-22],
                    ppm=1000.0,
                ),
                _grid_component(
                    "Water",
                    source="hitran",
                    wavenumber=[400.03, 401.03, 402.03, 403.03],
                    intensity=[3.0e-22, 4.0e-22, 5.0e-22, 6.0e-22],
                    ppm=1000.0,
                ),
            ],
        )
    )

    grid = result.recipe["grid"]
    assert grid["range_mode"] == "widest"
    assert grid["reference_kind"] == "HITRAN line-by-line resolution bins"
    assert grid["binning_method"] == "resolution_interval_mean"
    assert result.wavenumber == [400.03, 401.03, 402.03, 403.03]
    spectra = np.asarray(result.ground_truth["S"])
    assert np.count_nonzero(spectra[0]) == 4
    assert np.count_nonzero(spectra[1]) == 4
    assert np.count_nonzero(spectra[2]) == 4
    np.testing.assert_allclose(spectra[0], [1.0e-22, 2.0e-22, 3.0e-22, 4.0e-22])
    np.testing.assert_allclose(spectra[1], [2.0e-22, 3.0e-22, 4.0e-22, 5.0e-22])
    np.testing.assert_allclose(spectra[2], [3.0e-22, 4.0e-22, 5.0e-22, 6.0e-22])
    assert float(np.max(result.absorbance)) > 0.0


def test_hitran_line_by_line_common_bins_phase_shifted_grids_by_resolution() -> None:
    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(
                source="hitran",
                range_mode="common",
                n_samples=2,
                pathlength_cm=1.0,
                noise_sigma_au=0.0,
                snap_tolerance_cm1=0.05,
                resolution_cm1=1.0,
                preview_wavenumber_min=401.0,
                preview_wavenumber_max=403.0,
                preview_wavenumber_interval_cm1=0.25,
            ),
            components=[
                _grid_component(
                    "Methane",
                    source="hitran",
                    wavenumber=[400.42, 401.42, 402.42, 403.42],
                    intensity=[1.0e-22, 2.0e-22, 3.0e-22, 4.0e-22],
                    ppm=1000.0,
                ),
                _grid_component(
                    "Nitrogen dioxide",
                    source="hitran",
                    wavenumber=[400.72, 401.72, 402.72, 403.72],
                    intensity=[2.0e-22, 3.0e-22, 4.0e-22, 5.0e-22],
                    ppm=1000.0,
                ),
                _grid_component(
                    "Water",
                    source="hitran",
                    wavenumber=[400.03, 401.03, 402.03, 403.03],
                    intensity=[3.0e-22, 4.0e-22, 5.0e-22, 6.0e-22],
                    ppm=1000.0,
                ),
            ],
        )
    )

    assert result.wavenumber == [401.0, 402.0, 403.0]
    grid = result.recipe["grid"]
    assert grid["reference_kind"] == "HITRAN line-by-line resolution bins"
    assert grid["resolution_cm1"] == 1.0
    assert all(component["binning_method"] == "resolution_interval_mean" for component in grid["components"])
    spectra = np.asarray(result.ground_truth["S"])
    assert np.all(spectra > 0.0)
    np.testing.assert_allclose(spectra[0], [2.0e-22, 3.0e-22, 4.0e-22])
    np.testing.assert_allclose(spectra[1], [3.0e-22, 4.0e-22, 5.0e-22])
    np.testing.assert_allclose(spectra[2], [4.0e-22, 5.0e-22, 6.0e-22])
    assert float(np.max(result.absorbance)) > 0.0


def test_hitran_line_by_line_rejects_mixed_native_resolution() -> None:
    with pytest.raises(SynthesisError, match="must be loaded at the same resolution"):
        synthesize(
            SynthesisRequest(
                settings=SynthesisSettings(
                    source="hitran",
                    range_mode="widest",
                    n_samples=2,
                    pathlength_cm=1.0,
                    noise_sigma_au=0.0,
                    resolution_cm1=1.0,
                ),
                components=[
                    _grid_component(
                        "Methane",
                        source="hitran",
                        wavenumber=[400.0, 401.0, 402.0],
                        intensity=[1.0e-22, 2.0e-22, 3.0e-22],
                        ppm=1000.0,
                    ),
                    _grid_component(
                        "Water",
                        source="hitran",
                        wavenumber=[400.0, 400.5, 401.0, 401.5, 402.0],
                        intensity=[1.0e-22, 1.5e-22, 2.0e-22, 2.5e-22, 3.0e-22],
                        ppm=1000.0,
                    ),
                ],
            )
        )


def test_preview_interval_common_zero_fills_hitran_xsec_gaps() -> None:
    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(
                source="hitran_xsec",
                range_mode="common",
                n_samples=2,
                pathlength_cm=1.0,
                noise_sigma_au=0.0,
                snap_tolerance_cm1=0.1,
                preview_wavenumber_min=1000.0,
                preview_wavenumber_max=1004.0,
                preview_wavenumber_interval_cm1=1.0,
            ),
            components=[
                _grid_component(
                    "gapped-xsec",
                    source="hitran_xsec",
                    wavenumber=[1000.0, 1001.0, 1003.0, 1004.0],
                    intensity=[1.0e-22, 2.0e-22, 4.0e-22, 5.0e-22],
                    metadata={"gap_policy": "measured_points_only", "merged_gap_count": 1},
                    ppm=1.0,
                ),
            ],
        )
    )

    assert result.wavenumber == [1000.0, 1001.0, 1002.0, 1003.0, 1004.0]
    np.testing.assert_allclose(result.ground_truth["S"][0], [1.0e-22, 2.0e-22, 0.0, 4.0e-22, 5.0e-22])
    component_grid = result.recipe["grid"]["components"][0]
    assert component_grid["zero_padded_points"] == 1
    assert component_grid["gap_zero_filled_points"] == 1
    assert component_grid["gap_policy"] == "zero_fill_unmeasured_xsec_bins"


def test_common_hitran_xsec_gaps_are_zero_filled_without_explicit_interval() -> None:
    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(
                source="hitran_xsec",
                range_mode="common",
                n_samples=2,
                pathlength_cm=1.0,
                noise_sigma_au=0.0,
                snap_tolerance_cm1=0.1,
            ),
            components=[
                _grid_component(
                    "gapped-xsec",
                    source="hitran_xsec",
                    wavenumber=[1000.0, 1001.0, 1003.0, 1004.0],
                    intensity=[1.0e-22, 2.0e-22, 4.0e-22, 5.0e-22],
                    metadata={"gap_policy": "measured_points_only", "merged_gap_count": 1},
                    ppm=1.0,
                ),
            ],
        )
    )

    assert result.wavenumber == [1000.0, 1001.0, 1002.0, 1003.0, 1004.0]
    np.testing.assert_allclose(result.ground_truth["S"][0], [1.0e-22, 2.0e-22, 0.0, 4.0e-22, 5.0e-22])
    grid = result.recipe["grid"]
    assert grid["preview_interval_cm1"] == 1.0
    assert grid["components"][0]["zero_padded_points"] == 1
    assert grid["components"][0]["gap_policy"] == "zero_fill_unmeasured_xsec_bins"


def test_preview_interval_common_still_rejects_non_xsec_missing_bins() -> None:
    with pytest.raises(SynthesisError, match="no native point within snap tolerance"):
        synthesize(
            SynthesisRequest(
                settings=SynthesisSettings(
                    source="nist_quant_ir",
                    range_mode="common",
                    n_samples=2,
                    pathlength_cm=100.0,
                    noise_sigma_au=0.0,
                    snap_tolerance_cm1=0.1,
                    preview_wavenumber_min=1000.0,
                    preview_wavenumber_max=1004.0,
                    preview_wavenumber_interval_cm1=1.0,
                ),
                components=[
                    _grid_component(
                        "gapped-nist",
                        wavenumber=[1000.0, 1001.0, 1003.0, 1004.0],
                        intensity=[1.0, 2.0, 4.0, 5.0],
                    ),
                ],
            )
        )


def test_preview_wavenumber_range_crops_after_range_alignment() -> None:
    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(
                source="nist_quant_ir",
                range_mode="widest",
                n_samples=2,
                pathlength_cm=100.0,
                noise_sigma_au=0.0,
                preview_wavenumber_min=1001.0,
                preview_wavenumber_max=1002.0,
            ),
            components=[
                _grid_component("left", wavenumber=[1000.0, 1001.0, 1002.0], ppm=1.0),
                _grid_component("right", wavenumber=[1001.0, 1002.0, 1003.0], ppm=1.0),
            ],
        )
    )

    assert result.wavenumber == [1001.0, 1002.0]
    grid = result.recipe["grid"]
    assert grid["preview_crop_applied"] is True
    assert grid["range_before_preview_cm1"] == [1000.0, 1003.0]
    assert grid["range_cm1"] == [1001.0, 1002.0]
    np.testing.assert_allclose(result.ground_truth["S"][0], [0.55, 1.0])
    np.testing.assert_allclose(result.ground_truth["S"][1], [0.1, 0.55])


def test_common_range_error_names_limiting_components() -> None:
    with pytest.raises(SynthesisError, match="Latest start: right.*earliest end: left"):
        synthesize(
            SynthesisRequest(
                settings=SynthesisSettings(
                    source="nist_quant_ir",
                    range_mode="common",
                    n_samples=2,
                    pathlength_cm=100.0,
                    noise_sigma_au=0.0,
                    snap_tolerance_cm1=0.1,
                ),
                components=[
                    _grid_component("left", wavenumber=[400.0, 401.0, 402.0], ppm=1.0),
                    _grid_component("right", wavenumber=[1000.0, 1001.0, 1002.0], ppm=1.0),
                ],
            )
        )


def test_zero_tolerance_requires_coincident_grids() -> None:
    base = np.arange(1000.0, 1100.0, 1.0)
    with pytest.raises(SynthesisError, match="Cannot align"):
        synthesize(
            SynthesisRequest(
                settings=SynthesisSettings(
                    source="nist_quant_ir", n_samples=2, noise_sigma_au=0.0, snap_tolerance_cm1=0.0
                ),
                components=[
                    _grid_component("a", wavenumber=list(base)),
                    _grid_component("b", wavenumber=list(base + 0.02)),
                ],
            )
        )


def test_spacing_mismatch_raises_with_spacing_report() -> None:
    with pytest.raises(SynthesisError, match="spacing"):
        synthesize(
            SynthesisRequest(
                settings=SynthesisSettings(source="nist_quant_ir", n_samples=2, noise_sigma_au=0.0),
                components=[
                    _grid_component("coarse", wavenumber=list(np.arange(1000.0, 1100.0, 1.0))),
                    _grid_component("fine", wavenumber=list(np.arange(1000.0, 1100.0, 0.5))),
                ],
            )
        )


def test_synthesis_persists_seeded_noise_in_recipe() -> None:
    request = SynthesisRequest(
        settings=SynthesisSettings(source="nist_quant_ir", n_samples=3, noise_sigma_au=0.001, seed=123),
        components=[_component("water")],
    )

    first = synthesize(request)
    second = synthesize(request)

    assert first.absorbance == second.absorbance
    assert first.recipe["settings"]["seed"] == 123
    assert first.recipe["settings"]["noise_sigma_au"] == 0.001


def test_synthetic_npz_round_trip(tmp_path) -> None:
    from spectra_sherpa.app.services.synthesis import _write_synthesis_npz

    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(source="nist_quant_ir", n_samples=2, noise_sigma_au=0.0),
            components=[_component("water", x_end=1.0)],
        )
    )
    path = tmp_path / "synthetic.npz"
    _write_synthesis_npz(path, result)

    assert is_synthetic_npz(path)
    payload = load_synthetic_npz(path)
    assert payload["X"].shape == (2, 3)
    assert payload["wavenumber"].tolist() == [1000.0, 1001.0, 1002.0]
    assert json.loads(payload["recipe_json"])["version"] == 1
    assert payload["metadata"]["title"] is None
    assert payload["metadata"]["x_title"] == "Wavenumber"
    assert payload["metadata"]["x_units"] == "cm^-1"


def test_synthetic_npz_round_trip_preserves_xsec_gap_grid(tmp_path) -> None:
    from spectra_sherpa.app.services.synthesis import _write_synthesis_npz

    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(
                source="hitran_xsec",
                range_mode="common",
                n_samples=2,
                noise_sigma_au=0.0,
                snap_tolerance_cm1=0.1,
            ),
            components=[
                _grid_component(
                    "gapped-xsec",
                    source="hitran_xsec",
                    wavenumber=[1000.0, 1001.0, 1003.0, 1004.0],
                    intensity=[1.0e-22, 2.0e-22, 4.0e-22, 5.0e-22],
                    metadata={"gap_policy": "measured_points_only", "merged_gap_count": 1},
                    ppm=1.0,
                ),
            ],
        )
    )
    path = tmp_path / "gapped-synthetic.npz"
    _write_synthesis_npz(path, result)

    payload = load_synthetic_npz(path)
    assert payload["wavenumber"].tolist() == [1000.0, 1001.0, 1002.0, 1003.0, 1004.0]
    np.testing.assert_allclose(
        payload["S"][0],
        np.asarray([1.0e-22, 2.0e-22, 0.0, 4.0e-22, 5.0e-22]) * HITRAN_CROSS_SECTION_TO_MOLAR_ABSORPTIVITY,
    )
    ground_truth = json.loads(payload["ground_truth_json"])
    assert "C" not in ground_truth
    assert "S" not in ground_truth
    assert ground_truth["S_units"] == [MOLAR_ABSORPTION_COEFFICIENT_UNITS]
    assert ground_truth["grid"]["components"][0]["gap_policy"] == "zero_fill_unmeasured_xsec_bins"
    assert ground_truth["grid"]["components"][0]["zero_padded_points"] == 1


def test_synthetic_npz_metadata_updates_round_trip(tmp_path) -> None:
    pytest.importorskip("spectrochempy")

    from spectra_sherpa.app.lib.scp_compat import from_nddataset
    from spectra_sherpa.app.services.dag.node_base import node_registry
    from spectra_sherpa.app.services.prepared_data import save_prepared_data_overrides
    from spectra_sherpa.app.services.synthesis import _write_synthesis_npz

    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(source="nist_quant_ir", n_samples=2, noise_sigma_au=0.0),
            components=[_component("water", x_end=1.0)],
        )
    )
    path = tmp_path / "synthetic.npz"
    _write_synthesis_npz(path, result, title="Original")

    update_synthetic_npz_metadata(
        path,
        {
            "title": "Edited",
            "x_title": "Raman shift",
            "x_units": "cm^-1",
            "y_title": "Intensity",
            "is_time_series": True,
            "data_role": "X_spectra",
        },
    )

    payload = load_synthetic_npz(path)
    assert payload["X"].shape == (2, 3)
    assert payload["metadata"]["title"] == "Edited"
    assert payload["metadata"]["x_title"] == "Raman shift"
    assert payload["metadata"]["y_title"] == "Intensity"
    assert payload["metadata"]["data_quantity"] == "Intensity"
    assert payload["metadata"]["is_time_series"] is True

    save_prepared_data_overrides(
        {
            "x_title": "Shift after sidecar",
            "x_units": "cm^-1",
            "y_title": "Absorbance after sidecar",
            "is_time_series": False,
        },
        file_path=str(path.resolve()),
    )
    node = node_registry.create_node("data.my_dataset", "data_my_dataset_test", {"dataset_id": 1})
    loaded = node._load_file(str(path), file_name=path.name)
    workflow_dataset = node._apply_loaded_overrides(from_nddataset(loaded.dataset), [loaded])
    assert workflow_dataset.feature_axis.title == "Shift after sidecar"
    assert workflow_dataset.feature_axis.units == "cm^-1"
    assert workflow_dataset.domain.data_quantity == "Absorbance after sidecar"
    assert workflow_dataset.is_time_series is False


def test_synthetic_npz_payload_exposes_component_target_names(tmp_path) -> None:
    from spectra_sherpa.app.services.dag.nodes.data.loaders import _synthesis_target_names
    from spectra_sherpa.app.services.synthesis import _write_synthesis_npz

    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(source="nist_quant_ir", n_samples=2, noise_sigma_au=0.0),
            components=[_component("water", x_end=1.0)],
        )
    )
    path = tmp_path / "synthetic.npz"
    _write_synthesis_npz(path, result)

    payload = load_synthetic_npz(path)

    assert _synthesis_target_names(payload) == ["water"]


def test_synthetic_npz_loader_exposes_concentration_targets(tmp_path) -> None:
    pytest.importorskip("spectrochempy")

    from spectra_sherpa.app.services.dag.nodes.data.loaders import _load_synthesis_npz_as_loaded_dataset
    from spectra_sherpa.app.services.synthesis import _write_synthesis_npz

    result = synthesize(
        SynthesisRequest(
            settings=SynthesisSettings(source="nist_quant_ir", n_samples=2, noise_sigma_au=0.0),
            components=[_component("water", x_end=1.0)],
        )
    )
    path = tmp_path / "synthetic.npz"
    _write_synthesis_npz(path, result)

    loaded = _load_synthesis_npz_as_loaded_dataset(str(path))

    assert loaded.embedded_target_names == ["water"]
    assert loaded.embedded_target_units == "ppm"
    np.testing.assert_allclose(loaded.embedded_target_data, np.asarray(result.ground_truth["C"], dtype=float))
    assert loaded.ground_truth_spectra_names == ["water"]
    np.testing.assert_allclose(loaded.ground_truth_spectra, np.asarray(result.ground_truth["S"], dtype=float))
    np.testing.assert_allclose(loaded.ground_truth_spectra_x, np.asarray(result.wavenumber, dtype=float))


def test_synthetic_library_npz_loader_uses_molar_absorption_units() -> None:
    pytest.importorskip("spectrochempy")

    from spectra_sherpa.app.lib.synthetic_references import synthetic_reference_path
    from spectra_sherpa.app.services.dag.nodes.data.loaders import _load_synthesis_npz_as_loaded_dataset

    loaded = _load_synthesis_npz_as_loaded_dataset(str(synthetic_reference_path("Library_atmospheric-9")))

    assert str(loaded.dataset.units) == "l\u22c5cm\u207b\u00b9\u22c5mol\u207b\u00b9"
    assert loaded.dataset.meta["data_quantity"] == "Molar absorption coefficient"
    assert loaded.dataset.meta["value_units_label"] == "L mol^-1 cm^-1"
    assert loaded.ground_truth_spectra_units == ["L mol^-1 cm^-1"] * 9
    assert np.nanmax(np.asarray(loaded.dataset.data, dtype=float)) == pytest.approx(3053.589386031034)


def test_non_synthetic_npz_is_not_claimed_by_synthesis_loader(tmp_path) -> None:
    path = tmp_path / "arrays.npz"
    np.savez(path, data=np.asarray([[1.0, 2.0]]))

    assert not is_synthetic_npz(path)
    with pytest.raises(ValueError, match="not a SpectraSherpa synthetic dataset"):
        load_synthetic_npz(path)


def test_nist_variant_index_maps_quant_ir_links() -> None:
    from spectra_sherpa.app.services.synthesis import _nist_quant_ir_index

    assert _nist_quant_ir_index(1.0, "Blackman-Harris") == 16
    assert _nist_quant_ir_index(2.0, "Triangular") == 5
    assert _nist_quant_ir_index(0.125, "3-Term Blackmann-Harris") == 19


def test_nist_quant_ir_manifest_includes_full_source_table() -> None:
    from spectra_sherpa.app.services.synthesis import NIST_SOURCE, search_components

    all_components = search_components(NIST_SOURCE, "", limit=100)
    assert len(all_components) == 40
    assert {component.id for component in all_components} >= {
        "nist_quant_ir:benzene",
        "nist_quant_ir:dichloromethane",
        "nist_quant_ir:1-1-dichloroethene",
    }
    assert all(len(component.variants) == 25 for component in all_components)


async def test_nist_download_follows_quant_ir_page_jcamp_link(monkeypatch, tmp_path) -> None:
    from spectra_sherpa.app.services import synthesis as synthesis_service

    jcamp_text = "\n".join(
        [
            "##TITLE=Benzene",
            "##XUNITS=1/CM",
            "##YUNITS=(PPM*M)^-1",
            "##XYPOINTS= (XY..XY)",
            "1000 0.1",
            "1001 0.2",
        ]
    )
    calls: list[dict[str, object]] = []

    class _FakeResponse:
        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            assert kwargs.get("trust_env") is not False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url, params=None):
            calls.append({"url": str(url), "params": params})
            if params is not None:
                assert params == {"ID": "71-43-2", "Index": "QUANT-IR,16", "Type": "IR-SPEC"}
                return _FakeResponse(
                    '<html><a href="/cgi/cbook.cgi?Index=19&JCAMP=C71432&Type=IR">Download spectrum</a></html>'
                )
            assert "JCAMP=C71432" in str(url)
            assert "Type=IR" in str(url)
            return _FakeResponse(jcamp_text)

    monkeypatch.setattr(synthesis_service, "_synthesis_cache_dir", lambda _source: tmp_path)
    monkeypatch.setattr(synthesis_service.httpx, "AsyncClient", _FakeClient)

    spectrum = await synthesis_service.get_component_spectrum(
        "nist_quant_ir",
        "nist_quant_ir:benzene",
        resolution_cm1=1.0,
        apodization="Blackman-Harris",
    )

    assert len(calls) == 2
    assert spectrum.wavenumber == [1000.0, 1001.0]
    assert spectrum.intensity == [0.1, 0.2]
    assert (tmp_path / "nist_quant_ir-benzene-1-Blackman-Harris.jdx").exists()


def test_hapi_modules_receive_temporary_api_key(monkeypatch) -> None:
    from spectra_sherpa.app.services.synthesis import _temporary_hapi_api_key

    class _FakeHapi:
        SETTINGS: dict[str, str] = {"api_key": "previous"}
        VARIABLES: dict[str, str] = {"API_KEY": "previous", "api_key": "previous"}

    monkeypatch.delenv("HITRAN_API_KEY", raising=False)

    with _temporary_hapi_api_key(_FakeHapi, "hitran-secret"):
        assert _FakeHapi.SETTINGS["api_key"] == "hitran-secret"
        assert _FakeHapi.VARIABLES["API_KEY"] == "hitran-secret"
        assert _FakeHapi.VARIABLES["api_key"] == "hitran-secret"
        assert "HITRAN_API_KEY" not in os.environ

    assert _FakeHapi.SETTINGS["api_key"] == "previous"
    assert _FakeHapi.VARIABLES["API_KEY"] == "previous"
    assert _FakeHapi.VARIABLES["api_key"] == "previous"
    assert "HITRAN_API_KEY" not in os.environ


def test_hitran_catalog_includes_nitric_acid() -> None:
    from spectra_sherpa.app.services.synthesis import get_component_summary, search_components

    all_components = search_components("hitran", "", limit=100)
    ids = {component.id for component in all_components}
    assert len(all_components) == 57
    assert {"hitran:1", "hitran:12", "hitran:61"} <= ids
    assert {"hitran:30", "hitran:35", "hitran:42", "hitran:55"}.isdisjoint(ids)

    summary = get_component_summary("hitran", "hitran:12")
    assert summary.name == "Nitric acid"
    assert summary.formula == "HNO3"
    assert [item.id for item in search_components("hitran", "HNO3")] == ["hitran:12"]

    nitryl = get_component_summary("hitran", "hitran:61")
    assert nitryl.name == "Nitryl chloride"
    assert nitryl.formula == "ClNO2"


def test_hitran_xsec_catalog_exposes_measurement_options() -> None:
    from spectra_sherpa.app.services.synthesis import get_component_summary, search_components

    matches = search_components("hitran_xsec", "SF6", limit=10)
    assert matches
    sulfur_hexafluoride = matches[0]
    assert sulfur_hexafluoride.id == "hitran_xsec:30"
    assert sulfur_hexafluoride.name == "Sulfur Hexafluoride"
    assert sulfur_hexafluoride.formula == "SF6"
    assert sulfur_hexafluoride.xsec_options[0]["wavenumber_cm1"] == [560.0, 6500.0]
    assert sulfur_hexafluoride.xsec_options[0]["temperature_k"] == 278.15
    assert len(sulfur_hexafluoride.xsec_options) == 74

    summary = get_component_summary("hitran_xsec", "hitran_xsec:30#0")
    assert summary.name == "Sulfur Hexafluoride"

    all_components = search_components("hitran_xsec", "", limit=700)
    assert len(all_components) == 618
    assert any(component.id == "hitran_xsec:433" for component in all_components)
    assert all(component.id != "hitran_xsec:319" for component in all_components)


async def test_hitran_xsec_fetch_selects_measurement_and_caches(monkeypatch, tmp_path) -> None:
    from spectra_sherpa.app.services import synthesis as synthesis_service

    class _Molecule:
        id = 30
        formula = "SF6"
        name = "Sulfur hexafluoride"

    class _CrossSection:
        id = 321
        numin = 925.0
        numax = 955.0
        npnts = 4
        temperature = 296.0
        pressure = 760.0
        resolution = 0.1
        broadener = "air"
        filename = "SF6_TEST.xsc"

        @staticmethod
        def get_data():
            return np.array([925.0, 935.0, 945.0, 955.0]), np.array([0.0, 1e-20, 2e-20, 0.0])

    class _FakeHapi2:
        SETTINGS: dict[str, object] = {}
        VARIABLES: dict[str, str] = {}

        @staticmethod
        def fetch_info() -> None:
            assert _FakeHapi2.SETTINGS["api_key"] == "hitran-secret"

        @staticmethod
        def fetch_molecules() -> list[_Molecule]:
            return [_Molecule()]

        @staticmethod
        def fetch_cross_section_headers(molecule: _Molecule) -> list[_CrossSection]:
            assert molecule.formula == "SF6"
            return [_CrossSection()]

        @staticmethod
        def fetch_cross_section_spectra(headers: list[_CrossSection]) -> list[_CrossSection]:
            return headers

    monkeypatch.setattr(synthesis_service, "_synthesis_cache_dir", lambda _source: tmp_path)
    monkeypatch.setattr(synthesis_service, "_import_hapi2_module", lambda _work_dir=None: _FakeHapi2)

    first = await synthesis_service.get_component_spectrum(
        "hitran_xsec",
        "hitran_xsec:30#0",
        hitran_api_key="hitran-secret",
    )
    second = await synthesis_service.get_component_spectrum(
        "hitran_xsec",
        "hitran_xsec:30#0",
        hitran_api_key=None,
    )

    assert first.cached is False
    assert second.cached is True
    assert second.source == "hitran_xsec"
    assert second.wavenumber == [925.0, 935.0, 945.0, 955.0]
    assert second.y_units == "cm^2 molecule^-1"
    assert second.metadata["provider_id"] == 321
    assert second.metadata["broadener"] == "air"


async def test_hitran_xsec_fetch_merges_same_condition_regions_without_fabricating_gaps(monkeypatch, tmp_path) -> None:
    from spectra_sherpa.app.services import synthesis as synthesis_service

    class _Molecule:
        id = 999
        formula = "TG"
        name = "Test gas"

    class _CrossSection:
        temperature = 296.0
        pressure = 760.0
        resolution = 1.0
        broadener = "air"

        def __init__(self, provider_id: int, numin: float, numax: float, y: list[float], temperature: float = 296.0):
            self.id = provider_id
            self.numin = numin
            self.numax = numax
            self.npnts = len(y)
            self.temperature = temperature
            self.filename = f"TEST_{provider_id}.xsc"
            self._x = np.linspace(numin, numax, len(y))
            self._y = np.asarray(y, dtype=float)

        def get_data(self):
            return self._x, self._y

    selected_batches: list[list[int]] = []

    class _FakeHapi2:
        SETTINGS: dict[str, object] = {}
        VARIABLES: dict[str, str] = {}

        @staticmethod
        def fetch_info() -> None:
            assert _FakeHapi2.SETTINGS["api_key"] == "hitran-secret"

        @staticmethod
        def fetch_molecules() -> list[_Molecule]:
            return [_Molecule()]

        @staticmethod
        def fetch_cross_section_headers(molecule: _Molecule) -> list[_CrossSection]:
            assert molecule.formula == "TG"
            return [
                _CrossSection(1, 100.0, 102.0, [1.0, 2.0, 3.0]),
                _CrossSection(2, 105.0, 107.0, [4.0, 5.0, 6.0]),
                _CrossSection(3, 100.0, 107.0, [9.0, 9.0, 9.0], temperature=250.0),
            ]

        @staticmethod
        def fetch_cross_section_spectra(headers: list[_CrossSection]) -> list[_CrossSection]:
            selected_batches.append([header.id for header in headers])
            return headers

    monkeypatch.setattr(synthesis_service, "_synthesis_cache_dir", lambda _source: tmp_path)
    monkeypatch.setattr(synthesis_service, "_import_hapi2_module", lambda _work_dir=None: _FakeHapi2)
    monkeypatch.setattr(
        synthesis_service,
        "_load_hitran_xsec_manifest",
        lambda: {
            "components": [
                {
                    "id": "hitran_xsec:test",
                    "hitran_molecule_id": 999,
                    "name": "Test gas",
                    "formula": "TG",
                    "variants": [
                        {
                            "temperature_k": [295.0, 297.0],
                            "pressure_torr": [760.0, 760.0],
                            "resolution_cm1": 1.0,
                            "broadener": "air",
                            "sets": 1,
                            "wavenumber_cm1": [100.0, 102.0],
                        },
                        {
                            "temperature_k": [295.0, 297.0],
                            "pressure_torr": [760.0, 760.0],
                            "resolution_cm1": 1.0,
                            "broadener": "air",
                            "sets": 1,
                            "wavenumber_cm1": [105.0, 107.0],
                        },
                    ],
                }
            ]
        },
    )

    spectrum = await synthesis_service.get_component_spectrum(
        "hitran_xsec",
        "hitran_xsec:test#0",
        hitran_api_key="hitran-secret",
    )

    assert selected_batches == [[1, 2]]
    assert spectrum.wavenumber == [100.0, 101.0, 102.0, 105.0, 106.0, 107.0]
    assert spectrum.intensity == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert spectrum.metadata["provider_ids"] == [1, 2]
    assert spectrum.metadata["merged_region_count"] == 2
    assert spectrum.metadata["merged_gap_count"] == 1
    assert spectrum.metadata["gap_policy"] == "measured_points_only"


def test_hapi2_transition_fetch_uses_key_and_tmp_dir(monkeypatch, tmp_path) -> None:
    from spectra_sherpa.app.services import synthesis as synthesis_service

    class _Molecule:
        id = 2

    class _FakeHapi2:
        SETTINGS: dict[str, object] = {}
        VARIABLES: dict[str, str] = {}

        @staticmethod
        def fetch_info() -> None:
            assert (tmp_path / "~tmp").is_dir()
            assert _FakeHapi2.SETTINGS["api_key"] == "hitran-secret"
            assert _FakeHapi2.VARIABLES["API_KEY"] == "hitran-secret"

        @staticmethod
        def fetch_molecules() -> list[_Molecule]:
            return [_Molecule()]

        @staticmethod
        def fetch_isotopologues(molecule: _Molecule) -> list[str]:
            assert molecule.id == 2
            return ["main", "minor"]

        @staticmethod
        def fetch_transitions(isotopologues: list[str], wmin: float, wmax: float, table_name: str) -> None:
            assert isotopologues == ["main", "minor"]
            assert (wmin, wmax, table_name) == (2300.0, 2301.0, "co2-window")
            (tmp_path / "~tmp" / "co2-window.data").write_text("line data")

    def fake_import_hapi2_module(work_dir=None):
        assert work_dir == tmp_path
        return _FakeHapi2

    monkeypatch.setattr(synthesis_service, "_import_hapi2_module", fake_import_hapi2_module)

    synthesis_service._hapi2_fetch_transitions_with_api_key(
        tmp_path,
        "co2-window",
        2,
        2300.0,
        2301.0,
        api_key="hitran-secret",
    )

    assert "api_key" not in _FakeHapi2.SETTINGS
    assert "display_fetch_url" not in _FakeHapi2.SETTINGS
    assert "API_KEY" not in _FakeHapi2.VARIABLES
    assert "api_key" not in _FakeHapi2.VARIABLES
    assert (tmp_path / "~tmp" / "co2-window.data").exists()


def test_hitran_line_tables_are_cached_in_isolated_directories(monkeypatch, tmp_path) -> None:
    from spectra_sherpa.app.services import synthesis as synthesis_service

    table_name = "hitran-17-400-4000"
    monkeypatch.setattr(synthesis_service, "_synthesis_cache_dir", lambda _source: tmp_path)

    class _FakeHapi:
        db_path: str | None = None
        ISO_INDEX = {"id": 0, "abundance": 2}
        ISO = {(17, 1): [44, "main", 0.99]}
        LOCAL_TABLE_CACHE: dict[str, object] = {}

        @classmethod
        def db_begin(cls, path: str) -> None:
            cls.db_path = path
            cls.LOCAL_TABLE_CACHE = {
                table_name: {
                    "data": {
                        "molec_id": np.array([17, 17]),
                        "local_iso_id": np.array([0, 0]),
                    }
                }
            }

        @staticmethod
        def absorptionCoefficient_Voigt(**kwargs):
            assert kwargs["Components"] == [(17, 1)]
            return [400.0, 401.0], [0.0, 1e-22]

    def fake_fetch(cache_dir, fetched_table_name, *_args, **_kwargs) -> None:
        assert fetched_table_name == table_name
        assert cache_dir == tmp_path / "tables" / table_name
        (cache_dir / "~tmp").mkdir(parents=True, exist_ok=True)
        (cache_dir / "~tmp" / f"{table_name}.data").write_text("line data")

    monkeypatch.setattr(synthesis_service, "_hapi2_fetch_transitions_with_api_key", fake_fetch)

    nu, coef = synthesis_service._compute_hitran_spectrum_blocking(
        _FakeHapi,
        tmp_path / "tables" / table_name,
        tmp_path / "tables" / table_name / "~tmp",
        table_name,
        17,
        400.0,
        4000.0,
        296.0,
        1.0,
        1.0,
        "hitran-secret",
    )

    assert nu == [400.0, 401.0]
    assert coef == [0.0, 1e-22]
    assert _FakeHapi.db_path == str(tmp_path / "tables" / table_name / "~tmp")
    assert (tmp_path / "tables" / table_name / "~tmp" / f"{table_name}.data").exists()


def test_hitran_legacy_shared_cache_is_migrated_before_fetch(monkeypatch, tmp_path) -> None:
    from spectra_sherpa.app.services import synthesis as synthesis_service

    table_name = "hitran-17-400-4000"
    legacy_dir = tmp_path / "~tmp"
    legacy_dir.mkdir()
    (legacy_dir / f"{table_name}.data").write_text("legacy line data")
    (legacy_dir / f"{table_name}.header").write_text("legacy header")
    monkeypatch.setattr(synthesis_service, "_synthesis_cache_dir", lambda _source: tmp_path)

    class _FakeHapi:
        db_path: str | None = None
        ISO_INDEX = {"id": 0, "abundance": 2}
        ISO = {(17, 1): [44, "main", 0.99]}
        LOCAL_TABLE_CACHE: dict[str, object] = {}

        @classmethod
        def db_begin(cls, path: str) -> None:
            cls.db_path = path
            cls.LOCAL_TABLE_CACHE = {
                table_name: {
                    "data": {
                        "molec_id": np.array([17]),
                        "local_iso_id": np.array([44]),
                    }
                }
            }

        @staticmethod
        def absorptionCoefficient_Voigt(**kwargs):
            assert kwargs["Components"] == [(17, 1)]
            return [400.0, 401.0], [0.0, 1e-22]

    def fail_fetch(*_args, **_kwargs) -> None:
        raise AssertionError("legacy cache should avoid a HITRAN fetch")

    monkeypatch.setattr(synthesis_service, "_hapi2_fetch_transitions_with_api_key", fail_fetch)

    synthesis_service._compute_hitran_spectrum_blocking(
        _FakeHapi,
        tmp_path / "tables" / table_name,
        tmp_path / "tables" / table_name / "~tmp",
        table_name,
        17,
        400.0,
        4000.0,
        296.0,
        1.0,
        1.0,
        "hitran-secret",
    )

    isolated_dir = tmp_path / "tables" / table_name / "~tmp"
    assert (isolated_dir / f"{table_name}.data").read_text() == "legacy line data"
    assert (isolated_dir / f"{table_name}.header").read_text() == "legacy header"
    assert _FakeHapi.db_path == str(isolated_dir)


def test_hitran_global_isotopologue_id_mapping_prefers_global_over_zero_based() -> None:
    from spectra_sherpa.app.services import synthesis as synthesis_service

    class _FakeHapi:
        ISO_INDEX = {"id": 0}
        ISO = {
            (2, 1): [7],
            (2, 8): [14],
        }

    assert synthesis_service._resolve_hapi_local_isotope_id(_FakeHapi, 2, 7) == 1


async def test_hitran_component_spectrum_cache_reuses_voigt_coefficients(monkeypatch, tmp_path) -> None:
    from spectra_sherpa.app.services import synthesis as synthesis_service

    calls = 0

    def fake_compute(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return [400.0, 401.0, 402.0], [0.0, 1e-22, 2e-22]

    monkeypatch.setattr(synthesis_service, "_synthesis_cache_dir", lambda _source: tmp_path)
    monkeypatch.setattr(synthesis_service, "_import_hapi1_module", lambda: object())
    monkeypatch.setattr(synthesis_service, "_compute_hitran_spectrum_blocking", fake_compute)

    first = await synthesis_service.get_component_spectrum(
        "hitran",
        "hitran:17",
        resolution_cm1=1.0,
        wavenumber_min=400.0,
        wavenumber_max=402.0,
        temperature_k=296.0,
        pressure_atm=1.0,
        hitran_api_key="hitran-secret",
    )
    second = await synthesis_service.get_component_spectrum(
        "hitran",
        "hitran:17",
        resolution_cm1=1.0,
        wavenumber_min=400.0,
        wavenumber_max=402.0,
        temperature_k=296.0,
        pressure_atm=1.0,
        hitran_api_key=None,
    )

    assert calls == 1
    assert first.cached is False
    assert second.cached is True
    assert second.wavenumber == [400.0, 401.0, 402.0]
    assert second.intensity == [0.0, 1e-22, 2e-22]
    assert synthesis_service.is_component_spectrum_cached(
        "hitran",
        "hitran:17",
        resolution_cm1=1.0,
        wavenumber_min=400.0,
        wavenumber_max=402.0,
        temperature_k=296.0,
        pressure_atm=1.0,
    )


async def test_prewarm_hitran_default_library_skips_cached_and_generates(monkeypatch) -> None:
    from spectra_sherpa.app.services import synthesis as synthesis_service

    generated: list[dict[str, object]] = []

    def fake_cached(_source: str, component_id: str, **kwargs):
        assert kwargs["temperature_k"] == 293.0
        assert kwargs["pressure_atm"] == 1.0
        return component_id == "hitran:1"

    async def fake_spectrum(_source: str, component_id: str, **kwargs):
        generated.append({"component_id": component_id, **kwargs})
        return SynthesisSpectrumResponse(
            component_id=component_id,
            name=component_id,
            source="hitran",
            wavenumber=[400.0, 401.0],
            intensity=[0.0, 1e-22],
            y_quantity="absorption_cross_section",
            y_units="cm^2 molecule^-1",
            resolution_cm1=kwargs["resolution_cm1"],
            apodization="Voigt",
            cached=False,
        )

    monkeypatch.setattr(synthesis_service, "is_component_spectrum_cached", fake_cached)
    monkeypatch.setattr(synthesis_service, "get_component_spectrum", fake_spectrum)

    rows = await synthesis_service.prewarm_hitran_default_library(
        "hitran-secret",
        component_ids=["hitran:1", "CO2"],
    )

    assert [row["status"] for row in rows] == ["cached", "generated"]
    assert rows[1]["component_id"] == "hitran:2"
    assert generated == [
        {
            "component_id": "hitran:2",
            "resolution_cm1": 1.0,
            "wavenumber_min": 2250.0,
            "wavenumber_max": 2400.0,
            "temperature_k": 293.0,
            "pressure_atm": 1.0,
            "hitran_api_key": "hitran-secret",
        }
    ]


async def test_hitran_provider_errors_do_not_echo_api_key(monkeypatch) -> None:
    from spectra_sherpa.app.services import synthesis as synthesis_service

    class _FakeHapi:
        @staticmethod
        def db_begin(_path: str) -> None:
            return None

        @staticmethod
        def absorptionCoefficient_Voigt(**_kwargs):
            return [1.0, 2.0], [0.0, 0.0]

    def fail_fetch(*_args, **_kwargs) -> None:
        raise RuntimeError("download failed for https://hitran.org/api?apikey=hitran-secret")

    monkeypatch.setattr(synthesis_service, "_import_hapi1_module", lambda: _FakeHapi)
    monkeypatch.setattr(synthesis_service, "_hapi2_fetch_transitions_with_api_key", fail_fetch)
    monkeypatch.setattr(
        synthesis_service,
        "_synthesis_cache_dir",
        lambda _source: synthesis_service.Path("/tmp/missing"),
    )

    with pytest.raises(SynthesisError) as exc_info:
        await synthesis_service.get_component_spectrum(
            "hitran",
            "hitran:2",
            wavenumber_min=2300.0,
            wavenumber_max=2301.0,
            hitran_api_key="hitran-secret",
        )

    message = str(exc_info.value)
    assert "hitran-secret" not in message
    assert "apikey=" not in message.lower()
    assert "credential=[redacted]" in message
    assert "RuntimeError" in message
    assert "HITRAN spectrum generation failed" in message


async def test_hitran_key_validation_uses_hapi2_without_echoing_key(monkeypatch) -> None:
    from spectra_sherpa.app.services import synthesis as synthesis_service

    class _FakeHapi2:
        SETTINGS: ClassVar[dict[str, str]] = {}
        VARIABLES: ClassVar[dict[str, str]] = {}

        @staticmethod
        def fetch_info() -> None:
            assert _FakeHapi2.SETTINGS["api_key"] == "hitran-secret"

        @staticmethod
        def fetch_molecules() -> list[object]:
            return [object()]

    monkeypatch.setattr(synthesis_service, "_import_hapi2_module", lambda *_args, **_kwargs: _FakeHapi2)

    await synthesis_service.validate_hitran_api_key("hitran-secret")

    assert "api_key" not in _FakeHapi2.SETTINGS
    assert "API_KEY" not in _FakeHapi2.VARIABLES


async def test_hitran_key_validation_sanitizes_provider_errors(monkeypatch) -> None:
    from spectra_sherpa.app.services import synthesis as synthesis_service

    class _FakeHapi2:
        SETTINGS: ClassVar[dict[str, str]] = {}
        VARIABLES: ClassVar[dict[str, str]] = {}

        @staticmethod
        def fetch_info() -> None:
            raise RuntimeError("denied https://hitran.org/api?apikey=hitran-secret")

        @staticmethod
        def fetch_molecules() -> list[object]:
            return []

    monkeypatch.setattr(synthesis_service, "_import_hapi2_module", lambda *_args, **_kwargs: _FakeHapi2)

    with pytest.raises(SynthesisError) as exc_info:
        await synthesis_service.validate_hitran_api_key("hitran-secret")

    message = str(exc_info.value)
    assert "hitran-secret" not in message
    assert "apikey=" not in message.lower()
    assert "credential=[redacted]" in message
    assert "RuntimeError" in message


async def test_hitran_key_validate_endpoint_accepts_unsaved_key(auth_client, monkeypatch) -> None:
    from spectra_sherpa.app.api.v1.routes import api_keys as api_key_routes

    validated: list[str] = []

    async def fake_validate(key: str) -> None:
        validated.append(key)

    monkeypatch.setattr(api_key_routes.synthesis_service, "validate_hitran_api_key", fake_validate)

    response = await auth_client.post("/api/v1/api-keys/hitran/validate", json={"key": "hitran-secret"})

    assert response.status_code == 200
    assert response.json() == {
        "service_name": "hitran",
        "valid": True,
        "message": "HITRAN key validated.",
    }
    assert validated == ["hitran-secret"]


async def test_hitran_key_validate_endpoint_returns_provider_failure(auth_client, monkeypatch) -> None:
    from spectra_sherpa.app.api.v1.routes import api_keys as api_key_routes

    async def fake_validate(_key: str) -> None:
        raise SynthesisError("HITRAN key validation failed: RuntimeError: invalid credentials")

    monkeypatch.setattr(api_key_routes.synthesis_service, "validate_hitran_api_key", fake_validate)

    response = await auth_client.post("/api/v1/api-keys/hitran/validate", json={"key": "bad-key"})

    assert response.status_code == 200
    assert response.json() == {
        "service_name": "hitran",
        "valid": False,
        "message": "HITRAN key validation failed: RuntimeError: invalid credentials",
    }


async def test_synthesis_spectrum_endpoint_returns_component_spectrum(auth_client, monkeypatch) -> None:
    from spectra_sherpa.app.api.v1.routes import synthesis as synthesis_routes
    from spectra_sherpa.app.schemas.synthesis import SynthesisSpectrumResponse

    async def allow_egress(*args, **kwargs):
        return True

    async def fake_spectrum(*args, **kwargs):
        return SynthesisSpectrumResponse(
            component_id="nist_quant_ir:benzene",
            name="Benzene",
            source="nist_quant_ir",
            wavenumber=[1000.0, 1001.0],
            intensity=[0.01, 0.02],
            y_quantity="decadic_absorption_coefficient",
            y_units="ppm^-1 m^-1",
            resolution_cm1=1.0,
            apodization="Blackman-Harris",
        )

    monkeypatch.setattr(synthesis_routes, "check_egress_permission", allow_egress)
    monkeypatch.setattr(synthesis_routes.synthesis_service, "get_component_spectrum", fake_spectrum)

    response = await auth_client.get(
        "/api/v1/synthesis/spectrum",
        params={
            "source": "nist_quant_ir",
            "component_id": "nist_quant_ir:benzene",
            "resolution_cm1": 1.0,
            "apodization": "Blackman-Harris",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["component_id"] == "nist_quant_ir:benzene"
    assert body["y_units"] == "ppm^-1 m^-1"


async def test_hitran_spectrum_endpoint_requires_stored_key(auth_client, monkeypatch) -> None:
    from spectra_sherpa.app.api.v1.routes import synthesis as synthesis_routes

    async def allow_egress(*args, **kwargs):
        return True

    async def no_stored_key(*args, **kwargs):
        return None

    monkeypatch.setattr(synthesis_routes, "check_egress_permission", allow_egress)
    monkeypatch.setattr(synthesis_routes, "_stored_api_key", no_stored_key)

    response = await auth_client.get(
        "/api/v1/synthesis/spectrum",
        params={
            "source": "hitran",
            "component_id": "hitran:2",
            "resolution_cm1": 1.0,
        },
    )

    assert response.status_code == 400
    assert "HITRAN API key" in response.json()["detail"]


async def test_hitran_spectrum_endpoint_uses_cached_spectrum_without_key_or_egress(
    auth_client,
    monkeypatch,
) -> None:
    from spectra_sherpa.app.api.v1.routes import synthesis as synthesis_routes
    from spectra_sherpa.app.schemas.synthesis import SynthesisSpectrumResponse

    async def fail_egress(*args, **kwargs):
        raise AssertionError("cached HITRAN spectra should not require live egress")

    async def fail_stored_key(*args, **kwargs):
        raise AssertionError("cached HITRAN spectra should not require a stored API key")

    def cached(*args, **kwargs):
        assert kwargs["temperature_k"] == 296.0
        assert kwargs["pressure_atm"] == 1.0
        return True

    async def fake_spectrum(*args, **kwargs):
        assert kwargs["hitran_api_key"] is None
        return SynthesisSpectrumResponse(
            component_id="hitran:2",
            name="Carbon dioxide",
            source="hitran",
            wavenumber=[1000.0, 1001.0],
            intensity=[1e-20, 2e-20],
            y_quantity="absorption_cross_section",
            y_units="cm^2 molecule^-1",
            resolution_cm1=1.0,
            apodization="Voigt",
            cached=True,
        )

    monkeypatch.setattr(synthesis_routes, "check_egress_permission", fail_egress)
    monkeypatch.setattr(synthesis_routes, "_stored_api_key", fail_stored_key)
    monkeypatch.setattr(synthesis_routes.synthesis_service, "is_component_spectrum_cached", cached)
    monkeypatch.setattr(synthesis_routes.synthesis_service, "get_component_spectrum", fake_spectrum)

    response = await auth_client.get(
        "/api/v1/synthesis/spectrum",
        params={
            "source": "hitran",
            "component_id": "hitran:2",
            "resolution_cm1": 1.0,
            "temperature_k": 296.0,
            "pressure_atm": 1.0,
        },
    )

    assert response.status_code == 200
    assert response.json()["cached"] is True


async def test_hitran_spectrum_load_endpoint_queues_uncached_work(auth_client, monkeypatch) -> None:
    from spectra_sherpa.app.api.v1.routes import synthesis as synthesis_routes

    async def allow_egress(*args, **kwargs):
        return True

    async def stored_key(*args, **kwargs):
        return "hitran-secret"

    async def fake_run_job(job_id, work):
        assert job_id > 0
        assert callable(work)

    monkeypatch.setattr(synthesis_routes, "check_egress_permission", allow_egress)
    monkeypatch.setattr(synthesis_routes, "_stored_api_key", stored_key)
    monkeypatch.setattr(
        synthesis_routes.synthesis_service, "is_component_spectrum_cached", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(synthesis_routes.job_manager, "run_job", fake_run_job)

    response = await auth_client.post(
        "/api/v1/synthesis/spectrum/load",
        json={
            "source": "hitran",
            "component_id": "hitran:2",
            "resolution_cm1": 1.0,
            "wavenumber_min": 400.0,
            "wavenumber_max": 4000.0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["queued"] is True
    assert body["job_id"] is not None
    assert body["spectrum"] is None


async def test_nist_spectrum_endpoint_uses_cached_spectrum_without_egress(
    auth_client,
    monkeypatch,
) -> None:
    from spectra_sherpa.app.api.v1.routes import synthesis as synthesis_routes
    from spectra_sherpa.app.schemas.synthesis import SynthesisSpectrumResponse

    async def fail_egress(*args, **kwargs):
        raise AssertionError("cached NIST spectra should not require live egress")

    async def fake_spectrum(*args, **kwargs):
        return SynthesisSpectrumResponse(
            component_id="nist_quant_ir:benzene",
            name="Benzene",
            source="nist_quant_ir",
            wavenumber=[1000.0, 1001.0],
            intensity=[0.01, 0.02],
            y_quantity="decadic_absorption_coefficient",
            y_units="ppm^-1 m^-1",
            resolution_cm1=1.0,
            apodization="Blackman-Harris",
            cached=True,
        )

    monkeypatch.setattr(synthesis_routes, "check_egress_permission", fail_egress)
    monkeypatch.setattr(
        synthesis_routes.synthesis_service,
        "is_component_spectrum_cached",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(synthesis_routes.synthesis_service, "get_component_spectrum", fake_spectrum)

    response = await auth_client.get(
        "/api/v1/synthesis/spectrum",
        params={
            "source": "nist_quant_ir",
            "component_id": "nist_quant_ir:benzene",
            "resolution_cm1": 1.0,
            "apodization": "Blackman-Harris",
        },
    )

    assert response.status_code == 200
    assert response.json()["cached"] is True


async def test_nist_spectrum_endpoint_reports_network_failure_as_bad_gateway(
    auth_client,
    monkeypatch,
) -> None:
    from spectra_sherpa.app.api.v1.routes import synthesis as synthesis_routes

    async def allow_egress(*args, **kwargs):
        return True

    async def failing_spectrum(*args, **kwargs):
        raise httpx.ConnectError("network unreachable")

    monkeypatch.setattr(synthesis_routes, "check_egress_permission", allow_egress)
    monkeypatch.setattr(
        synthesis_routes.synthesis_service,
        "is_component_spectrum_cached",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(synthesis_routes.synthesis_service, "get_component_spectrum", failing_spectrum)

    response = await auth_client.get(
        "/api/v1/synthesis/spectrum",
        params={
            "source": "nist_quant_ir",
            "component_id": "nist_quant_ir:benzene",
            "resolution_cm1": 1.0,
            "apodization": "Blackman-Harris",
        },
    )

    assert response.status_code == 502
    assert "outbound network access" in response.json()["detail"]


async def test_hitran_spectrum_local_mode_uses_explicit_toggle_when_global_egress_disabled(
    auth_client,
    monkeypatch,
) -> None:
    from spectra_sherpa.app.api.v1.routes import synthesis as synthesis_routes
    from spectra_sherpa.app.schemas.synthesis import SynthesisSpectrumResponse

    monkeypatch.setattr(synthesis_routes.app_config, "mode", "local")
    monkeypatch.setattr(synthesis_routes.app_config, "egress_enabled", False)

    defaults = await auth_client.put("/api/v1/egress/defaults", json={"allow_hitran_queries": True})
    assert defaults.status_code == 200
    assert defaults.json()["allow_hitran_queries"] is True

    async def stored_key(*args, **kwargs):
        return "hitran-secret"

    async def fake_spectrum(*args, **kwargs):
        assert kwargs["hitran_api_key"] == "hitran-secret"
        return SynthesisSpectrumResponse(
            component_id="hitran:2",
            name="Carbon dioxide",
            source="hitran",
            wavenumber=[1000.0, 1001.0],
            intensity=[1e-20, 2e-20],
            y_quantity="absorption_cross_section",
            y_units="cm^2 molecule^-1",
            resolution_cm1=1.0,
            apodization="Voigt",
        )

    monkeypatch.setattr(synthesis_routes, "_stored_api_key", stored_key)
    monkeypatch.setattr(synthesis_routes.synthesis_service, "get_component_spectrum", fake_spectrum)

    response = await auth_client.get(
        "/api/v1/synthesis/spectrum",
        params={
            "source": "hitran",
            "component_id": "hitran:2",
            "resolution_cm1": 1.0,
        },
    )

    assert response.status_code == 200
    assert response.json()["component_id"] == "hitran:2"


async def test_hitran_spectrum_endpoint_passes_stored_key(auth_client, monkeypatch) -> None:
    from spectra_sherpa.app.api.v1.routes import synthesis as synthesis_routes
    from spectra_sherpa.app.schemas.synthesis import SynthesisSpectrumResponse

    async def allow_egress(*args, **kwargs):
        return True

    async def stored_key(*args, **kwargs):
        return "hitran-secret"

    async def fake_spectrum(*args, **kwargs):
        assert kwargs["hitran_api_key"] == "hitran-secret"
        return SynthesisSpectrumResponse(
            component_id="hitran:2",
            name="Carbon dioxide",
            source="hitran",
            wavenumber=[1000.0, 1001.0],
            intensity=[1e-20, 2e-20],
            y_quantity="absorption_cross_section",
            y_units="cm^2 molecule^-1",
            resolution_cm1=1.0,
            apodization="Voigt",
        )

    monkeypatch.setattr(synthesis_routes, "check_egress_permission", allow_egress)
    monkeypatch.setattr(synthesis_routes, "_stored_api_key", stored_key)
    monkeypatch.setattr(synthesis_routes.synthesis_service, "get_component_spectrum", fake_spectrum)

    response = await auth_client.get(
        "/api/v1/synthesis/spectrum",
        params={
            "source": "hitran",
            "component_id": "hitran:2",
            "resolution_cm1": 1.0,
        },
    )

    assert response.status_code == 200
    assert response.json()["component_id"] == "hitran:2"


async def test_hitran_key_validation_endpoint_validates_supplied_key(auth_client, monkeypatch) -> None:
    from spectra_sherpa.app.api.v1.routes import api_keys

    seen: list[str] = []

    async def fake_validate(key: str) -> None:
        seen.append(key)

    monkeypatch.setattr(api_keys.synthesis_service, "validate_hitran_api_key", fake_validate)

    response = await auth_client.post(
        "/api/v1/api-keys/hitran/validate",
        json={"key": "hitran-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "service_name": "hitran",
        "valid": True,
        "message": "HITRAN key validated.",
    }
    assert seen == ["hitran-secret"]


async def test_hitran_key_validation_endpoint_reports_provider_failure(auth_client, monkeypatch) -> None:
    from spectra_sherpa.app.api.v1.routes import api_keys

    async def fake_validate(key: str) -> None:
        raise SynthesisError("HITRAN key validation failed: unauthorized")

    monkeypatch.setattr(api_keys.synthesis_service, "validate_hitran_api_key", fake_validate)

    response = await auth_client.post(
        "/api/v1/api-keys/hitran/validate",
        json={"key": "hitran-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "service_name": "hitran",
        "valid": False,
        "message": "HITRAN key validation failed: unauthorized",
    }


async def test_nist_spectrum_endpoint_rate_limits_cache_misses(auth_client, monkeypatch) -> None:
    from spectra_sherpa.app.api.v1.routes import synthesis as synthesis_routes

    async def allow_egress(*args, **kwargs):
        return True

    class _DenyLimiter:
        def allow(self, key: str = "default") -> bool:
            return False

    monkeypatch.setattr(synthesis_routes, "check_egress_permission", allow_egress)
    monkeypatch.setattr(synthesis_routes, "_nist_download_limiter", _DenyLimiter())
    monkeypatch.setattr(
        synthesis_routes.synthesis_service, "is_component_spectrum_cached", lambda *args, **kwargs: False
    )

    response = await auth_client.get(
        "/api/v1/synthesis/spectrum",
        params={
            "source": "nist_quant_ir",
            "component_id": "nist_quant_ir:benzene",
            "resolution_cm1": 1.0,
            "apodization": "Blackman-Harris",
        },
    )

    assert response.status_code == 429
    assert "rate limit" in response.json()["detail"].lower()


async def test_synthesis_save_creates_synthetic_experiment_file(auth_client) -> None:
    payload = SynthesisSaveRequest(
        name="unit synthetic",
        settings=SynthesisSettings(source="nist_quant_ir", n_samples=2, noise_sigma_au=0.0),
        components=[_component("water", x_end=1.0)],
    ).model_dump(mode="json")

    response = await auth_client.post("/api/v1/synthesis/save", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["file_path"].startswith("synthetic/")
    experiment = await auth_client.get(f"/api/v1/experiments/{body['experiment_id']}")
    assert experiment.status_code == 200
    builder_state = experiment.json()["metadata"]["builder_state"]
    assert builder_state["kind"] == "synthesis_recipe"
    assert builder_state["version"] == 1
    assert builder_state["recipe"]["settings"]["source"] == "nist_quant_ir"
    assert builder_state["recipe"]["components"][0]["name"] == "water"
    files = await auth_client.get(f"/api/v1/experiments/{body['experiment_id']}/files?stage=synthetic")
    assert files.status_code == 200
    assert files.json()[0]["file_path"] == body["file_path"]

    dataset_info = await auth_client.post("/api/v1/builder/file-info", json={"experiment_id": body["experiment_id"]})
    assert dataset_info.status_code == 200
    dataset_json = dataset_info.json()
    assert dataset_json["target"] == [[100.0], [100.0]]
    assert dataset_json["target_context"]["target_type"] == "continuous"
    assert dataset_json["target_context"]["target_names"] == ["water"]
    assert dataset_json["target_context"]["target_units"] == "ppm"
    metadata = dataset_info.json()["metadata"]
    assert metadata["contents_stage"] == "synthetic"
    assert metadata["contents_file_count"] == 1
    assert metadata["recipe"]["settings"]["source"] == "nist_quant_ir"
    assert metadata["recipe"]["components"][0]["name"] == "water"

    matrix_info = await auth_client.post(
        "/api/v1/builder/data-matrix",
        json={
            "kind": "experiment_file",
            "experiment_id": body["experiment_id"],
            "file_id": body["file_id"],
        },
    )
    assert matrix_info.status_code == 200
    target_summary = matrix_info.json()["target"]
    assert target_summary["target_name"] == "synthetic concentration"
    assert target_summary["target_names"] == ["water"]
    assert target_summary["target_units"] == "ppm"
    assert target_summary["n_targets"] == 1

    patch = await auth_client.patch(
        "/api/v1/builder/file-metadata",
        json={
            "experiment_id": body["experiment_id"],
            "file_path": body["file_path"],
            "x_title": "Raman shift",
            "x_units": "cm^-1",
            "y_title": "Absorbance",
            "is_time_series": True,
        },
    )
    assert patch.status_code == 200

    from spectra_sherpa.app.services.experiments import experiment_dir

    payload = load_synthetic_npz(experiment_dir(body["experiment_id"]) / body["file_path"])
    assert payload["metadata"]["x_title"] == "Raman shift"
    assert payload["metadata"]["data_quantity"] == "Absorbance"
    assert payload["metadata"]["is_time_series"] is True

    edited_info = await auth_client.post("/api/v1/builder/file-info", json={"experiment_id": body["experiment_id"]})
    assert edited_info.status_code == 200
    edited_meta = edited_info.json()["metadata"]
    assert edited_meta["x_title"] == "Raman shift"
    assert edited_meta["data_quantity"] == "Absorbance"
    assert edited_meta["is_time_series"] is True


async def test_synthesis_save_rejects_foreign_project(test_session, test_user) -> None:
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.user import User

    other_user = User(username=f"synthesis-other-{uuid.uuid4().hex[:8]}")
    test_session.add(other_user)
    await test_session.flush()
    foreign_project = Project(user_id=other_user.id, name="Foreign project")
    test_session.add(foreign_project)
    await test_session.commit()

    payload = SynthesisSaveRequest(
        name="foreign project synthetic",
        settings=SynthesisSettings(source="nist_quant_ir", n_samples=2, noise_sigma_au=0.0),
        components=[_component("water", x_end=1.0)],
        project_id=foreign_project.id,
    )

    with pytest.raises(SynthesisError, match="Project is not accessible"):
        await save_synthesis_result(test_session, test_user, payload)


async def test_hitran_preview_does_not_require_egress_for_supplied_spectra(auth_client) -> None:
    payload = SynthesisRequest(
        settings=SynthesisSettings(source="hitran", n_samples=2, noise_sigma_au=0.0),
        components=[_component("hitran:2", source="hitran", y=[1.0e-22, 2.0e-22, 3.0e-22], x_end=1.0)],
    ).model_dump(mode="json")

    response = await auth_client.post("/api/v1/synthesis/preview", json=payload)

    assert response.status_code == 200
    assert response.json()["source"] == "hitran"


async def test_synthesis_save_reuses_name_without_overwriting(auth_client) -> None:
    dataset_name = f"duplicate synthetic {uuid.uuid4().hex[:8]}"
    stem = dataset_name.replace(" ", "-")
    payload = SynthesisSaveRequest(
        name=dataset_name,
        settings=SynthesisSettings(source="nist_quant_ir", n_samples=2, noise_sigma_au=0.0),
        components=[_component("water", x_end=1.0)],
    ).model_dump(mode="json")

    first = await auth_client.post("/api/v1/synthesis/save", json=payload)
    assert first.status_code == 200
    first_body = first.json()

    payload["experiment_id"] = first_body["experiment_id"]
    second = await auth_client.post("/api/v1/synthesis/save", json=payload)
    assert second.status_code == 200
    second_body = second.json()

    assert first_body["file_path"] == f"synthetic/{stem}.npz"
    assert second_body["file_path"] == f"synthetic/{stem}-2.npz"
    files = await auth_client.get(f"/api/v1/experiments/{first_body['experiment_id']}/files?stage=synthetic")
    assert files.status_code == 200
    assert [item["file_path"] for item in files.json()] == [
        first_body["file_path"],
        second_body["file_path"],
    ]


async def test_synthesis_preview_response_is_truncated(auth_client) -> None:
    payload = SynthesisRequest(
        settings=SynthesisSettings(source="nist_quant_ir", n_samples=60, noise_sigma_au=0.0),
        components=[
            SynthesisComponentInput(
                component_id="wide",
                name="wide",
                spectrum=SynthesisSpectrum(
                    component_id="wide",
                    name="wide",
                    source="nist_quant_ir",
                    wavenumber=[float(i) for i in range(3000)],
                    intensity=[0.001] * 3000,
                    y_quantity="absorption_coefficient",
                    y_units="ppm^-1 m^-1",
                ),
                control_points=[
                    SynthesisControlPoint(x=0, y_ppm=100.0),
                    SynthesisControlPoint(x=59, y_ppm=100.0),
                ],
            )
        ],
    ).model_dump(mode="json")

    response = await auth_client.post("/api/v1/synthesis/preview", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is True
    assert len(body["absorbance"]) == 50
    assert len(body["wavenumber"]) == 2000
    assert len(body["ground_truth"]["S"][0]) == 2000
