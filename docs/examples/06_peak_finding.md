# Example 6: Peak Finding

Automated detection of peak positions.

## 1. Finding Peaks

```python
import numpy as np
import spectrochempy as scp

# Generate spectrum with multiple peaks
x = np.linspace(4000, 400, 1000)
# Peaks at 3000, 1700, 1000
y = np.zeros_like(x)
for pos in [3000, 1700, 1000]:
    y += np.exp(-((x - pos)**2) / (2 * 20**2))

dataset = scp.NDDataset(y, coordset={"x": scp.Coord(x, units="cm^-1")})

# Find peaks
# height: minimum height
# distance: minimum distance between peaks
peaks_indices, _ = dataset.find_peaks(height=0.1, distance=50)

print(f"Found {len(peaks_indices)} peaks.")
for idx in peaks_indices:
    pos = dataset.x[idx].values
    val = dataset.data[0, idx]
    print(f"Peak at {pos:.2f} cm^-1, Intensity: {val:.4f}")
```
