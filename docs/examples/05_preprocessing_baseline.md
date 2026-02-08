# Example 5: Baseline Correction

Removing background drift or fluorescence.

## 1. Asymmetric Least Squares (ALS)

A powerful method for estimating baselines.

```python
import numpy as np
import spectrochempy as scp

# Create data with a baseline drift
x = np.linspace(4000, 400, 1000)
peaks = np.exp(-((x - 2000)**2) / (2 * 50**2))
baseline = 0.5 + 0.0005 * x  # Linear slope
dataset = scp.NDDataset(peaks + baseline, coordset={"x": scp.Coord(x, units="cm^-1")})

print("Applying ALS baseline correction...")

# Corrected dataset
corrected = dataset.copy()
# lamb: smoothness (higher = smoother baseline)
# p: asymmetry (0.001 - 0.01 usually)
corrected.basc(lamb=1e5, p=0.001)

# Plotting
dataset.plot(title="Original with Baseline")
corrected.plot(title="Corrected")
```

## 2. Rubberband / Linear

Simple methods are also available.

```python
# Linear detrending (if you just want to remove slope)
detrended = dataset.copy()
detrended.basc(method="linear")
```
