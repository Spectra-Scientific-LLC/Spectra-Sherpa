#!/usr/bin/env python3
"""
Node Template Generator for Spectra Scientific Platform.

Usage:
    python node_template.py <node_type> <ClassName> <category>
    
Example:
    python node_template.py model.xgboost XGBoostNode modeling
"""

import sys
import os
from datetime import datetime

TEMPLATE = """from typing import Any, Dict, List, Optional
import numpy as np
from spectrochempy import NDDataset

from app.services.dag.node_base import (
    Node, 
    NodeMetadata, 
    NodeParameter, 
    PortMetadata, 
    register_node
)

@register_node
class {class_name}(Node):
    metadata = NodeMetadata(
        node_type="{node_type}",
        category="{category}",
        label="{label}",
        description="{description}",
        
        # Define Input Ports
        input_ports=[
            PortMetadata(
                name="X",
                port_type="dataset",
                required=True,
                label="Input Dataset",
                description="Primary input spectra or data"
            ),
            PortMetadata(
                name="y",
                port_type="target",
                required=False,
                label="Target/Labels",
                description="Target values for training"
            ),
        ],
        
        # Define Output Ports (Multi-Output)
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="model",
                port_type="model",
                label="Model",
                description="Trained model object"
            ),
            PortMetadata(
                name="predictions",
                port_type="array",
                label="Predictions",
                description="Model predictions"
            ),
        ],
        
        # Define Parameters
        parameters=[
            NodeParameter(
                name="n_components",
                label="Components",
                param_type="number",
                default=5,
                min_value=1,
                request=True
            ),
        ]
    )

    async def execute(self, X: NDDataset = None, y: Any = None, **kwargs) -> Dict[str, Any]:
        # 1. Parameter Validation
        n_components = self.parameters.get("n_components", 5)
        
        # 2. Logic Implementation
        # ... logic here ...
        
        # 3. Construct Return Dictionary (Must match output_ports)
        return {{
            "model": "model_placeholder",
            "predictions": "predictions_placeholder"
        }}
"""

def generate_node(node_type, class_name, category):
    label = class_name.replace("Node", "").replace("PLS", "PLS ").strip()
    content = TEMPLATE.format(
        node_type=node_type,
        class_name=class_name,
        category=category,
        label=label,
        description=f"Standard implementation of {label}"
    )
    
    filename = f"{class_name.lower()}.py"
    print(f"Generating {filename}...")
    
    # In a real scenario, this might write to a file, 
    # but here we just output to stdout or a specific location if needed.
    # For now, let's just print it or save it if run as a script.
    return content

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
        
    node_type = sys.argv[1]
    class_name = sys.argv[2]
    category = sys.argv[3]
    
    print(generate_node(node_type, class_name, category))
