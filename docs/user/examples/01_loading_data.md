# Example 1: Loading and Creating Data

This example demonstrates how to create a `NDDataset` from scratch using NumPy arrays and how to save/load it.

## 1. Creating a Dataset from NumPy Arrays

The core object in SpectrochemPy is the `NDDataset`. It wraps a NumPy array with metadata (units, coordinates, title).

```python
import numpy as np
import spectrochempy as scp

# 1. Generate synthetic data (e.g., 10 samples, 100 spectral points)
data = np.random.normal(0, 0.1, (10, 100)) + 1.0

# 2. Create the NDDataset
dataset = scp.NDDataset(data)

# 3. Add metadata
dataset.title = "Synthetic Data"
dataset.name = "experiment_01"
dataset.units = "absorbance"

# 4. Define coordinates
# X-axis: Wavenumbers
wavenumbers = np.linspace(4000, 400, 100)
dataset.set_coordset(x=wavenumbers)
dataset.x.title = "Wavenumber"
dataset.x.units = "cm^-1"

# Y-axis: Time or Sample ID
times = np.arange(10)
dataset.set_coordset(y=times)
dataset.y.title = "Time"
dataset.y.units = "min"

print(dataset)
```

## 2. Saving Data

SpectrochemPy supports various formats. The native format is `.scp` (based on HDF5), but it can also export to CSV, etc.

```python
# Save as SpectrochemPy format (preserves all metadata)
dataset.save("my_dataset.scp")

# Save as CSV (metadata might be lost or stored in headers)
dataset.write_csv("my_dataset.csv")
```

## 3. Loading Data

```python
# Load .scp file
loaded_ds = scp.read("my_dataset.scp")
print("Loaded dataset shape:", loaded_ds.shape)

# Read generic CSV
# (Note: reading raw CSVs often requires specifying delimiters/headers)
# csv_ds = scp.read_csv("my_dataset.csv")
```
