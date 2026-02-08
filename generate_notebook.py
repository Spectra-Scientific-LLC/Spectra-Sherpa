import json

notebook_content = {
 "cells": [
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "# SpectrochemPy Case Study: End-to-End Analysis\n",
    "\n",
    "This notebook serves as the ground truth for the Workflow Bench case study. We will:\n",
    "1. Generate a synthetic dataset.\n",
    "2. Apply Preprocessing (Savitzky-Golay Smoothing, ALS Baseline Correction).\n",
    "3. Perform Principal Component Analysis (PCA).\n",
    "4. Inspect quantitative results to verify against the UI."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "import numpy as np\n",
    "import spectrochempy as scp\n",
    "\n",
    "# 1. GENERATE SYNTHETIC DATA\n",
    "np.random.seed(42)\n",
    "n_samples = 20\n",
    "n_points = 200\n",
    "wavenumbers = np.linspace(4000, 400, n_points)\n",
    "\n",
    "# Create two pure components\n",
    "pure1 = np.exp(-((wavenumbers - 3000)**2) / (2 * 100**2))\n",
    "pure2 = np.exp(-((wavenumbers - 1500)**2) / (2 * 50**2))\n",
    "\n",
    "# Create mixtures\n",
    "concentrations = np.random.rand(n_samples, 2)\n",
    "spectra_data = concentrations @ np.vstack([pure1, pure2])\n",
    "\n",
    "# Add baseline drift and noise\n",
    "baseline = np.linspace(0, 0.5, n_points) * 0.2\n",
    "noise = np.random.normal(0, 0.01, (n_samples, n_points))\n",
    "spectra_data += baseline + noise\n",
    "\n",
    "dataset = scp.NDDataset(spectra_data)\n",
    "dataset.set_coordset(x=scp.Coord(wavenumbers, title=\"Wavenumber\", units=\"cm^-1\"))\n",
    "dataset.title = \"Synthetic Mixture\"\n",
    "\n",
    "print(f\"Created dataset: {dataset.shape}\")"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "# 2. PREPROCESSING\n",
    "\n",
    "# Step 2a: Savitzky-Golay Smoothing\n",
    "smoothed = dataset.copy()\n",
    "smoothed.smooth(size=11, order=2)\n",
    "print(f\"Smoothed data (sample 0, point 100): {smoothed.data[0, 100]:.5f}\")\n",
    "\n",
    "# Step 2b: ALS Baseline Correction\n",
    "corrected = smoothed.copy()\n",
    "corrected.basc(lamb=1000, p=0.001)\n",
    "print(f\"Baseline corrected (sample 0, point 100): {corrected.data[0, 100]:.5f}\")"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "# 3. PCA ANALYSIS\n",
    "\n",
    "pca = scp.PCA(n_components=3)\n",
    "pca.fit(corrected)\n",
    "\n",
    "scores = pca.transform(corrected)\n",
    "explained_var = pca.explained_variance_ratio\n",
    "\n",
    "print(\"Explained Variance Ratio:\")\n",
    "for i, val in enumerate(explained_var.data[:3]):\n",
    "    print(f\"  PC{i+1}: {val:.4f}\")\n",
    "\n",
    "print(f\"\nPC1 Score (Sample 0): {scores.data[0, 0]:.4f}\")"
   ]
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python 3",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 3
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython3",
   "version": "3.8.10"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 5
}

with open("Refactored/docs/examples/00_case_study_notebook.ipynb", "w") as f:
    json.dump(notebook_content, f, indent=1)

print("Notebook generated successfully.")
