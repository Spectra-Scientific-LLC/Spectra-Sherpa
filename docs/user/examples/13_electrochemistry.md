# Electrochemistry Analysis with PotentialAxis

This example demonstrates electrochemical data analysis (CV, DPV, SWV) using `PotentialAxis` for voltage measurements.

## Complete Example: Cyclic Voltammetry

```python
import numpy as np
import matplotlib.pyplot as plt
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.lib.axes import PotentialAxis

# ============================================================================
# 1. Generate Synthetic CV Data
# ============================================================================

# Potential scan: -2V to +2V and back
n_points = 400
potentials_forward = np.linspace(-2.0, 2.0, n_points // 2)
potentials_reverse = np.linspace(2.0, -2.0, n_points // 2)
potentials = np.concatenate([potentials_forward, potentials_reverse])

# Generate 5 CV cycles with redox peaks
n_samples = 5
cv_data = np.zeros((n_samples, n_points))

def redox_peak(E, E0, alpha=0.5, n=1, k0=0.01, T=298):
    """Generate redox peak using Butler-Volmer model (simplified)."""
    F = 96485  # Faraday constant
    R = 8.314  # Gas constant

    # Oxidation and reduction currents
    i_ox = np.exp(alpha * n * F * (E - E0) / (R * T))
    i_red = np.exp(-(1-alpha) * n * F * (E - E0) / (R * T))

    return k0 * (i_ox - i_red)

np.random.seed(42)
# Define redox couples (E0, k0)
redox_couples = [
    (0.5, 0.8),   # Oxidation peak
    (-0.5, 0.6),  # Reduction peak
]

for i in range(n_samples):
    for E0, k0 in redox_couples:
        # Add variation
        E0_varied = E0 + np.random.normal(0, 0.02)
        k0_varied = k0 * (1 + np.random.normal(0, 0.1))

        # Generate forward scan
        cv_data[i, :n_points//2] += redox_peak(potentials_forward, E0_varied, k0=k0_varied)
        # Generate reverse scan (with hysteresis)
        cv_data[i, n_points//2:] += redox_peak(potentials_reverse, E0_varied-0.05, k0=k0_varied*0.9)

    # Add capacitive current and noise
    cv_data[i, :] += 0.05 * potentials + np.random.normal(0, 0.02, n_points)

# ============================================================================
# 2. Create SherpaDataset with PotentialAxis
# ============================================================================

pot_ax = PotentialAxis(
    values=potentials,
    units="V",  # Can be "V" or "mV"
    title="Potential"
)

dataset = SherpaDataset(
    X=cv_data,
    feature_axis=pot_ax,  # Use PotentialAxis
    title="Cyclic Voltammetry - Ferrocene Analysis",
    units="µA"  # Microamperes
)

print(f"Dataset shape: {dataset.shape}")
print(f"Feature axis type: {dataset.get_feature_axis().axis_type}")
print(f"Potential range: {pot_ax.range} V")

# ============================================================================
# 3. Visualization
# ============================================================================

# Plot all CV cycles
plt.figure(figsize=(10, 6))
for i in range(n_samples):
    plt.plot(potentials, cv_data[i, :], alpha=0.7, label=f'Cycle {i+1}')

plt.axhline(y=0, color='k', linestyle='--', alpha=0.3)
plt.axvline(x=0, color='k', linestyle='--', alpha=0.3)
plt.xlabel(f"{pot_ax.title} ({pot_ax.units})")
plt.ylabel("Current (µA)")
plt.title("Cyclic Voltammograms")
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()

# Plot average CV
mean_cv = np.mean(cv_data, axis=0)
std_cv = np.std(cv_data, axis=0)

plt.figure(figsize=(10, 6))
plt.plot(potentials, mean_cv, 'b-', linewidth=2, label='Mean')
plt.fill_between(potentials, mean_cv - std_cv, mean_cv + std_cv,
                 alpha=0.3, label='±1 SD')
plt.axhline(y=0, color='k', linestyle='--', alpha=0.3)
plt.axvline(x=0, color='k', linestyle='--', alpha=0.3)
plt.xlabel(f"{pot_ax.title} ({pot_ax.units})")
plt.ylabel("Current (µA)")
plt.title("Average Cyclic Voltammogram")
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()

# ============================================================================
# 4. Peak Detection and Analysis
# ============================================================================

from scipy.signal import find_peaks

# Analyze forward scan only
forward_scan = mean_cv[:n_points//2]
forward_potentials = potentials[:n_points//2]

# Find oxidation peaks (positive current)
ox_peaks, _ = find_peaks(forward_scan, height=0.2, distance=20)

# Find reduction peaks (negative current, so invert)
red_peaks, _ = find_peaks(-forward_scan, height=0.2, distance=20)

print(f"\\nPeak Analysis:")
print(f"  Oxidation peaks: {len(ox_peaks)}")
for peak_idx in ox_peaks:
    E_peak = forward_potentials[peak_idx]
    i_peak = forward_scan[peak_idx]
    print(f"    E = {E_peak:.3f} V, i = {i_peak:.3f} µA")

print(f"  Reduction peaks: {len(red_peaks)}")
for peak_idx in red_peaks:
    E_peak = forward_potentials[peak_idx]
    i_peak = forward_scan[peak_idx]
    print(f"    E = {E_peak:.3f} V, i = {i_peak:.3f} µA")

# Calculate formal potential (midpoint between ox/red peaks)
if len(ox_peaks) > 0 and len(red_peaks) > 0:
    E_ox = forward_potentials[ox_peaks[0]]
    E_red = forward_potentials[red_peaks[0]]
    E_formal = (E_ox + E_red) / 2
    delta_E = E_ox - E_red
    print(f"\\nFormal Potential (E°'): {E_formal:.3f} V")
    print(f"Peak Separation (ΔE): {delta_E:.3f} V")

# ============================================================================
# 5. Region Selection (Anodic Region)
# ============================================================================

# Focus on anodic region (0 to +1 V)
anodic_mask = pot_ax.select_region(0.0, 1.0)
anodic_data = cv_data[:, anodic_mask]
anodic_potentials = potentials[anodic_mask]

print(f"\\nAnodic Region (0 to +1 V):")
print(f"  Data shape: {anodic_data.shape}")

plt.figure(figsize=(10, 5))
for i in range(n_samples):
    plt.plot(anodic_potentials, anodic_data[i, :], alpha=0.7)

plt.axhline(y=0, color='k', linestyle='--', alpha=0.3)
plt.xlabel(f"{pot_ax.title} ({pot_ax.units})")
plt.ylabel("Current (µA)")
plt.title("Anodic Region - All Cycles")
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()

# ============================================================================
# 6. Scan Rate Analysis (if multiple scan rates available)
# ============================================================================

# Simulate different scan rates (mV/s)
scan_rates = np.array([25, 50, 100, 200, 500])  # mV/s
peak_currents = []

# Generate CV at different scan rates
for v in scan_rates:
    # Simulate: peak current proportional to sqrt(scan rate) for reversible system
    i_p = 0.5 * np.sqrt(v/25)  # Normalized to 25 mV/s
    i_p_with_noise = i_p * (1 + np.random.normal(0, 0.05))
    peak_currents.append(i_p_with_noise)

peak_currents = np.array(peak_currents)

# Randles-Sevcik plot (i_p vs sqrt(v))
plt.figure(figsize=(10, 5))

plt.subplot(1, 2, 1)
plt.plot(scan_rates, peak_currents, 'bo-', markersize=8)
plt.xlabel('Scan Rate (mV/s)')
plt.ylabel('Peak Current (µA)')
plt.title('Peak Current vs Scan Rate')
plt.grid(True, alpha=0.3)

plt.subplot(1, 2, 2)
plt.plot(np.sqrt(scan_rates), peak_currents, 'ro-', markersize=8)
plt.xlabel('√(Scan Rate) (mV/s)^0.5')
plt.ylabel('Peak Current (µA)')
plt.title('Randles-Sevcik Plot')
plt.grid(True, alpha=0.3)

plt.tight_layout()
plt.show()

# Check linearity (R²)
from scipy.stats import linregress
slope, intercept, r_value, p_value, std_err = linregress(np.sqrt(scan_rates), peak_currents)
print(f"\\nScan Rate Analysis:")
print(f"  Linear fit (i_p vs √v): R² = {r_value**2:.4f}")
if r_value**2 > 0.95:
    print(f"  Conclusion: Reversible/quasi-reversible redox couple")
else:
    print(f"  Conclusion: Irreversible or complex system")

# ============================================================================
# 7. Summary Report
# ============================================================================

print(f"\\n{'='*60}")
print("CYCLIC VOLTAMMETRY ANALYSIS SUMMARY")
print(f"{'='*60}")
print(f"Dataset: {dataset.title}")
print(f"Number of cycles: {dataset.shape[0]}")
print(f"Potential range: {pot_ax.range[0]:.1f} to {pot_ax.range[1]:.1f} V")
print(f"Scan points: {len(potentials)}")

if len(ox_peaks) > 0 and len(red_peaks) > 0:
    print(f"\\nRedox Properties:")
    print(f"  Formal Potential (E°'): {E_formal:.3f} V")
    print(f"  Peak Separation (ΔE): {delta_E:.3f} V")

    if delta_E < 0.070:  # ~59 mV for n=1 at 25°C
        print(f"  System: Reversible (ΔE ≈ 59 mV)")
    elif delta_E < 0.150:
        print(f"  System: Quasi-reversible")
    else:
        print(f"  System: Irreversible")

print(f"{'='*60}")
```

## Key Concepts

### 1. PotentialAxis for Voltage

```python
pot_ax = PotentialAxis(
    values=potentials,
    units="V",  # Or "mV" for millivolts
    title="Potential"
)
```

### 2. Electrochemical Analysis

CV is used for:
- Redox potential determination (E°')
- Reversibility assessment (ΔE_p)
- Electron transfer kinetics
- Concentration measurements

### 3. Region Selection

```python
# Select specific potential window
anodic_mask = pot_ax.select_region(0.0, 1.0)  # 0 to +1V
cathodic_mask = pot_ax.select_region(-1.0, 0.0)  # -1 to 0V
```

### 4. Workflow Integration

SpectraSherpa nodes handle `PotentialAxis`:
- **PlotNode**: Axes labeled "Potential (V)" not "Index"
- **SmoothNode**: Savitzky-Golay smoothing of voltammograms
- **BaselineNode**: Background current subtraction
- **Peak Detection**: Find oxidation/reduction peaks

## Advanced: Differential Pulse Voltammetry (DPV)

```python
# DPV: smaller potential steps with pulse
potentials_dpv = np.linspace(-1.0, 1.0, 200)
current_dpv = np.random.randn(200) * 0.01

# Peaks are sharper in DPV
# Use same PotentialAxis
pot_ax_dpv = PotentialAxis(values=potentials_dpv, units="V", title="Potential")
dataset_dpv = SherpaDataset(X=current_dpv.reshape(1, -1), feature_axis=pot_ax_dpv)
```

## See Also

- [PotentialAxis API Reference](../api/axes.md#potentialaxis)
- [SherpaDataset API Reference](../api/sherpa_dataset.md)
- [Chromatography Example](11_chromatography.md)
- [Mass Spectrometry Example](12_mass_spectrometry.md)
