# Example 2: Dataset Manipulation (Slicing & Selecting)

This example shows how to select specific regions (ROI) and handle coordinates.

## 1. Selecting by Index vs. Value

`NDDataset` allows slicing by index (standard Python/NumPy) or by coordinate value (using units).

```python
import numpy as np
import spectrochempy as scp

# Create a dataset
x = np.linspace(4000, 400, 1000)
data = np.random.rand(5, 1000)
dataset = scp.NDDataset(data, coordset={"x": scp.Coord(x, units="cm^-1")})

# Standard slicing (first 100 points)
subset_index = dataset[:, :100]

# Value-based slicing (Region of Interest)
# Select region from 3000 cm^-1 to 2800 cm^-1
# Note: SpectrochemPy handles the order (3000 down to 2800)
roi = dataset[:, 3000.0:2800.0]

print(f"Original shape: {dataset.shape}")
print(f"ROI shape: {roi.shape}")
```

## 2. Axis Operations

You can sum, mean, or integrate along axes.

```python
# Mean spectrum across all samples
mean_spectrum = dataset.mean(axis=0)

# Standard deviation
std_spectrum = dataset.std(axis=0)

print(f"Mean spectrum shape: {mean_spectrum.shape}")
```
