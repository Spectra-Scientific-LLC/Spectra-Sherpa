
import sys
import os
import asyncio
import numpy as np
import spectrochempy as scp
import plotly.graph_objects as go
from pathlib import Path

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

from spectra_sherpa.app.services.dag.nodes.modeling import PCANode
from spectra_sherpa.app.services.dag.nodes.data import DataSourceNode

async def run_demo():
    print("Starting PCA Demo...")
    
    # 1. Load Data
    print("Loading 'irdata' from Spectrochempy examples...")
    # We can use DataSourceNode logic or direct SCP calls. 
    # Let's use SCP directly to ensure we get what we want, similar to DataSourceNode.
    try:
        # DataSourceNode uses scp.read_omnic("irdata/nh4y-activation.spg")
        # We need to find where spectrochempy stores examples or download it if needed.
        # But wait, scp has a 'read' function that might handle it.
        # The node implementation: dataset = scp.read_omnic("irdata/nh4y-activation.spg")
        
        # Spectrochempy examples might need specific setup. 
        # Let's try to find a file locally or use scp's example loader.
        
        # Check standard paths
        home_scp = Path.home() / ".spectrochempy" / "data" / "irdata" / "nh4y-activation.spg"
        if home_scp.exists():
            print(f"Loading from {home_scp}")
            X = scp.read_omnic(str(home_scp))
        else:
            print("Trying generic 'irdata/nh4y-activation.spg'...")
            try:
                X = scp.read_omnic("irdata/nh4y-activation.spg")
            except Exception as e:
                print(f"Failed to load via scp: {e}")
                print("Generating synthetic data with 10 samples instead...")
                # Synthetic fallback if example load fails
                wavenumbers = np.linspace(400, 4000, 200)
                n_samples = 10
                data = np.random.rand(n_samples, 200)
                # Add some structure
                data += np.outer(np.linspace(0, 1, n_samples), np.sin(wavenumbers/100))
                X = scp.NDDataset(data, x=scp.Coord(wavenumbers, title="Wavenumber"), y=scp.Coord(np.arange(n_samples), title="Sample"))

        print(f"Data loaded: {X.shape} (Samples x Features)")
        if X.shape[0] < 5:
            print("Warning: Fewer than 5 samples loaded.")
        
    except Exception as e:
        print(f"Error loading data: {e}")
        return

    # 2. Run PCA
    print("Running PCA Analysis...")
    pca_node = PCANode()
    # Configure parameters
    pca_node.parameters = {"n_components": "3", "standardized": False}
    
    try:
        results = await pca_node.execute(X)
        scores_dataset = results["default"]
        loadings_dataset = results["loadings"]
        variance = results.get("explained_variance", [])
        
        print("PCA Complete.")
        print(f"Scores Info: {scores_dataset.shape}")
        
        # 3. Generate Plot
        print("Generating Scores Plot...")
        
        # Extract scores
        scores = scores_dataset.data
        if hasattr(scores, "values"): scores = scores.values
        
        pc1 = scores[:, 0]
        pc2 = scores[:, 1]
        
        fig = go.Figure(data=go.Scatter(
            x=pc1, y=pc2, mode='markers',
            marker=dict(size=10, color=np.arange(len(pc1))),
            text=[f"Sample {i}" for i in range(len(pc1))]
        ))
        
        fig.update_layout(
            title="PCA Scores Plot (PC1 vs PC2)",
            xaxis_title=f"PC1",
            yaxis_title=f"PC2"
        )
        
        # 4. Attempt to Capture Image
        print("Attempting to capture image...")
        
        # Save HTML (always works)
        html_path = "pca_scores_plot.html"
        fig.write_html(html_path)
        print(f"Saved interactive plot to {html_path}")
        
        # Try PNG export
        png_path = "pca_scores_plot.png"
        try:
            fig.write_image(png_path)
            print(f"Success! Captured static image to {png_path}")
        except Exception as e:
            print(f"Could not capture static PNG image: {e}")
            print("Reason: likely missing 'kaleido' package.")

    except Exception as e:
        print(f"PCA execution failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_demo())
