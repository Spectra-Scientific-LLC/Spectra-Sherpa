# Example 4: Smoothing and Denoising

Noise reduction is critical in spectroscopy.

## 1. Savitzky-Golay Smoothing

The most common filter in chemistry.

```python
import numpy as np
import spectrochempy as scp

# Create noisy data
x = np.linspace(4000, 400, 1000)
signal = np.exp(-((x - 2000)**2) / (2 * 100**2))
noise = np.random.normal(0, 0.05, 1000)
dataset = scp.NDDataset(signal + noise, coordset={"x": scp.Coord(x, units="cm^-1")})

# Apply Smoothing
# size: window size (number of points), order: polynomial order
smoothed = dataset.copy()
smoothed.smooth(size=21, order=2)

# Compare
dataset.plot(title="Original (Noisy)")
smoothed.plot(title="Smoothed (SG)")
```

## 2. Derivatives

Derivatives help resolve overlapping peaks but amplify noise (so smooth first!).

```python
# Calculate 2nd derivative
# (Often done simultaneously with smoothing in Savitzky-Golay)
deriv2 = dataset.copy()
deriv2.smooth(size=21, order=2, deriv=2)

deriv2.plot(title="2nd Derivative")
```
