import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

import numpy as np
import asyncio
import json
import traceback
from spectra_sherpa.app.services.dag.nodes.modeling import HCANode
from spectrochempy import NDDataset
import spectrochempy as scp

async def debug_hca():
    print("--- STARTING HCA DEBUG ---")
    
    # 1. Create Dummy Data (Random)
    # 150 samples, 4 features (reflecting the user's shape mentioned earlier)
    np.random.seed(42)
    data = np.random.rand(150, 4)
    # Add some structure so clustering works well
    data[:50] += 5
    data[50:100] -= 5
    
    # Create NDDataset
    ds = scp.NDDataset(data)
    
    # 2. Instantiate Node
    node = HCANode(node_id="debug_hca_001")
    node.parameters = {
        "n_clusters": 3,
        "linkage": "ward",
        "metric": "euclidean"
    }
    
    print(f"Node initialized. Input shape: {ds.shape}")
    
    # 3. Execute Node
    try:
        result = await node.execute(ds)
        print("Execution successful.")
    except Exception:
        print("Execution failed.")
        traceback.print_exc()
        return

    # 4. Inspect Plot Data
    dendro = result.get("plots", {}).get("dendrogram", {})
    
    if not dendro:
        print("ERROR: No dendrogram plot found in result['plots'].")
        return
        
    traces = dendro.get("data", [])
    layout = dendro.get("layout", {})
    
    print(f"Num traces: {len(traces)}")
    print(f"Layout width: {layout.get('width')}")
    print(f"Layout xaxis tickvals count: {len(layout.get('xaxis', {}).get('tickvals', []))}")
    
    # 5. Check serialization and types
    if len(traces) > 0:
        first_trace = traces[0]
        x_vals = first_trace.get("x")
        y_vals = first_trace.get("y")
        
        print(f"First trace X type: {type(x_vals)}")
        if len(x_vals) > 0:
             print(f"First trace X[0] type: {type(x_vals[0])}")
             print(f"First trace X values: {x_vals}")
             
        print(f"First trace Y values: {y_vals}")
        
        # Try JSON dump to check for numpy types
        try:
            json_str = json.dumps(dendro)
            print("JSON serialization SUCCESS.")
        except TypeError as e:
            print("JSON serialization FAILED.")
            print(e)
            
            # Deep dive which part failed
            try:
                json.dumps(x_vals) # Check list
            except TypeError:
                print("Failed at x_vals list")
                
    else:
        print("ERROR: Traces list is empty!")

    print("--- END HCA DEBUG ---")

if __name__ == "__main__":
    asyncio.run(debug_hca())
