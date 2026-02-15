# Synthesis Builder

The **Synthesis** module creates synthetic spectral datasets by blending reference species (pure components) according to defined concentration profiles. It uses advanced calibration models to simulate realistic detector responses.

## Preprocessing

Before blending, you can clean your source spectra. The builder uses `spectrochempy` for these operations.

1.  **Alignment**: Spectra must be on the same wavenumber grid. The system uses **PCHIP** (Piecewise Cubic Hermite Interpolating Polynomial) interpolation by default to preserve peak shapes without introducing ringing artifacts.
2.  **Clipping**:
    *   **Range**: Limits the spectral range (e.g., 400-4000 cm⁻¹).
    *   **Floor**: Sets a minimum absorbance value (e.g., 0.0) to remove non-physical negative noise.
3.  **Cosmic Ray Removal**: Uses a Z-score based algorithm (default Z=3.0) to detect and remove single-point spikes.

## Blending Algorithm

The synthesis engine implements a **multi-species superposition model**.

The total absorbance $A_{total}$ at wavenumber $\nu$ and time $t$ is the sum of individual component contributions:

$$ A_{total}(\nu, t) = \sum_{i=1}^{N} A_i(\nu, C_i(t)) $$

Where $C_i(t)$ is the concentration of species $i$ at time $t$.

### Calibration Models

Each species can use a different calibration model $A_i(\nu, C)$, defined per wavenumber:

#### 1. Linear Model (Beer's Law)
Standard for low concentrations.
$$ A = \text{slope}(\nu) \cdot C + \text{intercept}(\nu) $$

*   **Clipping**: To prevent non-physical extrapolation, linear models are capped at a "Safe Threshold" (default **1.8 AU**) or the saturation level $s$ if available.

#### 2. Saturation Model
Models non-linear detector response at high concentrations using a hyperbolic tangent function.
$$ A = s(\nu) \cdot \left[ \tanh\left( \left( \frac{c(\nu) \cdot C}{s(\nu)} \right)^{p(\nu)} \right) \right]^{1/p(\nu)} $$

*   $s(\nu)$: Saturation plateau (max absorbance).
*   $c(\nu)$: Linear sensitivity (slope at $C=0$).
*   $p(\nu)$: Shape parameter controlling the transition to saturation.

#### 3. Hybrid Model
Allows different wavenumbers to use different models (e.g., peaks use saturation, baseline uses linear).

### Concentration Modes

The system supports two concentration modes, critical for quantitative accuracy:

*   **Product Mode (`ppm·m`)**: Concentration-Pathlength product. This is the **standard mode**.
    *   If your input is in `ppm`, you must specify a `pathlength_m`.
    *   If your input is `ppm·m`, leave pathlength as None.
*   **Concentration Mode (`ppm`)**: Legacy mode. Assumes a fixed pathlength.

### System Saturation

After blending, a global "System Saturation" can be applied to simulate the detector's dynamic range limit on the *total* absorbance:

$$ A_{measured} = s_{sys} \cdot \tanh\left( (A_{total} / s_{sys})^{p_{sys}} \right)^{1/p_{sys}} $$

This is dimensionless and affects the entire spectrum.

## Generating Data

1.  **Define Profiles**: Create time-series concentrations ($C_i(t)$) for each species using the Curve Generator (Sigmoid, Gaussian, Linear, Step).
2.  **Run Blend**: The engine vectorizes the calculation across all wavenumbers and time points.
3.  **Statistics**: The result includes min, max, mean, and std deviation of the generated absorbance matrix.

## Export

Synthetic data can be exported as:
*   **CSV**: Simple matrix (rows=wavenumbers, cols=samples).
*   **JSON**: Full metadata including the `SpectrumRecord` structure and model parameters.
*   **NetCDF**: Standard scientific format.