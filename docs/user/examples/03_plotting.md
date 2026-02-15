# Example 3: Plotting

SpectrochemPy has built-in plotting capabilities based on matplotlib.

## 1. Simple 1D Plot

```python
import numpy as np
import spectrochempy as scp

# Generate data with a peak
x = np.linspace(1000, 2000, 500)
y = np.exp(-((x - 1500)**2) / (2 * 50**2))
dataset = scp.NDDataset(y, coordset={"x": scp.Coord(x, units="cm^-1")})

# Plot
# Note: In a script, you might need scp.show() or use matplotlib backend
dataset.plot(title="Single Spectrum")
```

## 2. Multi-Plot (Stack)

```python
# Create multiple spectra
data = np.zeros((5, 500))
for i in range(5):
    data[i] = y * (1 + i * 0.2) + np.random.normal(0, 0.05, 500)

ds_multi = scp.NDDataset(data, coordset={"x": scp.Coord(x, units="cm^-1")})

# Plot all overlaid
ds_multi.plot(title="Overlay Plot")

# Stacked plot (offset)
ds_multi.plot(method="stack", offset=0.5, title="Stacked Plot")
```

## 3. 2D Map (Image)

```python
# Useful for time-series or hyperspectral images
ds_multi.plot(method="map", title="2D Intensity Map")
```
