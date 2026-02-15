# Example 8: Principal Component Analysis (PCA)

Dimensionality reduction for spectral data.

## 1. Running PCA

```python
import numpy as np
import spectrochempy as scp

# Generate a dataset with 2 varying components
n_samples = 20
x = np.linspace(1000, 2000, 100)
c1 = np.random.rand(n_samples, 1)  # Concentration of component 1
c2 = np.random.rand(n_samples, 1)  # Concentration of component 2

s1 = np.exp(-((x - 1200)**2) / (2 * 20**2)) # Spectrum 1
s2 = np.exp(-((x - 1800)**2) / (2 * 20**2)) # Spectrum 2

# Mix
data = c1 @ s1.reshape(1, -1) + c2 @ s2.reshape(1, -1)
# Add noise
data += 0.01 * np.random.randn(*data.shape)

dataset = scp.NDDataset(data, coordset={"x": scp.Coord(x, units="cm^-1")})

# Initialize PCA
pca = scp.PCA(n_components=2)
pca.fit(dataset)

# Scores and Loadings
scores = pca.transform(dataset)
loadings = pca.components

print("Explained Variance Ratio:", pca.explained_variance_ratio.data)

# Plot
# scores.plot_scatter(title="PCA Scores") # Hypothetical plot method
# loadings.plot(title="PCA Loadings")
```
