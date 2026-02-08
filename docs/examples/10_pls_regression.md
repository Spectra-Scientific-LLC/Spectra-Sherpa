# Example 10: PLS Regression

Predicting a property (Y) from spectra (X).

## 1. PLS Calibration

```python
import numpy as np
import spectrochempy as scp

# X: Spectra (from Example 8)
X = dataset
# Y: Reference values (e.g., Concentration 1)
Y = scp.NDDataset(c1, title="Concentration")

# Split data (simple manual split)
X_train = X[::2]
Y_train = Y[::2]
X_test = X[1::2]
Y_test = Y[1::2]

# Initialize PLS
try:
    pls = scp.PLSRegression(n_components=2)
    pls.fit(X_train, Y_train)
    
    # Predict
    Y_pred = pls.predict(X_test)
    
    # RMSEP
    rmsep = np.sqrt(np.mean((Y_test.data - Y_pred.data)**2))
    print(f"RMSEP: {rmsep:.4f}")
except AttributeError:
    print("PLSRegression not found in this version.")
```
