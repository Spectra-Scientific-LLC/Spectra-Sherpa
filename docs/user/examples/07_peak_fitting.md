# Example 7: Peak Fitting / Integration

Calculating area under the curve.

## 1. Simple Integration (Simpson's Rule)

```python
import numpy as np
import spectrochempy as scp

# Define a peak
x = np.linspace(1100, 900, 200)
y = np.exp(-((x - 1000)**2) / (2 * 10**2))
dataset = scp.NDDataset(y, coordset={"x": scp.Coord(x, units="cm^-1")})

# Integrate over the whole range
# trapz or simps (trapezoidal or Simpson's rule)
area = dataset.integrate(method="trapz")

print(f"Calculated Area: {area.data[0]}")
```

## 2. ROI Integration

```python
# Select a region first
roi = dataset[:, 1020.0:980.0]
area_roi = roi.integrate()
print(f"Area in ROI (1020-980): {area_roi.data[0]}")
```
