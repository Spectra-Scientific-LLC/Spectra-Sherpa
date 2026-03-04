"""
Full pipeline validation: generate_python_code() → exec() → compare R².

Uses mock workflow objects to test the exact same code path as the
/workflows/{id}/export/python API endpoint.
"""

import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

# Register nodes
import spectra_sherpa.app.services.dag.nodes.modeling.pls_nodes  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.data.source  # noqa: F401

from spectra_sherpa.app.lib.eigenvector import load_eigenvector_dataset
from spectra_sherpa.app.services.python_export import generate_python_code


@dataclass
class MockNode:
    node_id: str
    node_type: str
    parameters: dict = field(default_factory=dict)


@dataclass
class MockEdge:
    from_node_id: str
    to_node_id: str
    from_output: str = "default"
    to_input: str = "default"


@dataclass
class MockWorkflow:
    name: str
    description: str = ""
    integrity_hash: str = ""
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)


def r2_score(y_true, y_pred):
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    return 1.0 - (ss_res / ss_tot)


def main():
    print("=" * 60)
    print("Full Export Pipeline Validation")
    print("=" * 60)

    # Load dataset
    result = load_eigenvector_dataset("corn_mp5")
    spectra = result["spectra"].astype(np.float64)
    properties = result["properties"].astype(np.float64)
    prop_names = result["prop_names"]

    moisture_idx = prop_names.index("Moisture")
    protein_idx = prop_names.index("Protein")

    n_components = 5
    scale = True

    # =====================================================================
    # Backend R² (reference)
    # =====================================================================
    import spectrochempy as scp

    X_ndd = scp.NDDataset(spectra)
    backend_r2 = {}
    for name, idx in [("Moisture", moisture_idx), ("Protein", protein_idx)]:
        y = properties[:, idx].reshape(-1, 1)
        pls = scp.PLSRegression(n_components=n_components, scale=scale)
        pls.fit(X_ndd, scp.NDDataset(y))
        y_pred = np.asarray(pls.predict(X_ndd).data, dtype=np.float64).ravel()
        backend_r2[name] = r2_score(y.ravel(), y_pred)

    print(f"\nBackend (reference):")
    for name, r2 in backend_r2.items():
        print(f"  {name}: R² = {r2:.6f}")

    # =====================================================================
    # Generate and run exported code for each target
    # =====================================================================
    all_match = True
    for target_name, target_idx in [("Moisture", moisture_idx), ("Protein", protein_idx)]:
        print(f"\n--- Testing {target_name} ---")

        workflow = MockWorkflow(
            name=f"PLS Corn MP5 {target_name}",
            description=f"PLS regression for {target_name}",
            nodes=[
                MockNode("source_1", "data.source", {"source": "eigenvector", "eigenvector_dataset": "corn_mp5"}),
                MockNode("pls_1", "model.pls", {"n_components": n_components, "scale": scale}),
            ],
            edges=[
                MockEdge("source_1", "pls_1", "default", "X"),
                MockEdge("source_1", "pls_1", "target", "y"),
            ],
        )

        code = generate_python_code(workflow)

        # Fill in the source placeholder with actual Corn MP5 data
        # Replace the placeholder block with actual data loading
        y_col = properties[:, target_idx]
        source_replacement = (
            f"    # --- Source: source_1 (data.source) ---\n"
            f"    # Corn MP5 {target_name} data\n"
            f"    from spectra_sherpa.app.lib.eigenvector import load_eigenvector_dataset as _load\n"
            f"    _ds = _load('corn_mp5')\n"
            f"    results['source_1'] = {{\n"
            f"        'default': scp.NDDataset(_ds['spectra'].astype(np.float64)),\n"
            f"        'target': _ds['properties'][:, {target_idx}].astype(np.float64),\n"
            f"    }}\n"
        )

        # Find and replace the source placeholder section
        lines = code.split("\n")
        new_lines = []
        skip_until_next_section = False
        for line in lines:
            if "# --- Source: source_1" in line:
                skip_until_next_section = True
                new_lines.append("")  # blank line
                new_lines.extend(source_replacement.split("\n"))
                continue
            if skip_until_next_section:
                if line.strip() == "" and not any(
                    marker in line for marker in ["EDIT", "results['source_1']"]
                ):
                    skip_until_next_section = False
                    new_lines.append(line)
                continue
            new_lines.append(line)

        filled_code = "\n".join(new_lines)

        # Write to temp file for inspection
        tmp = Path(tempfile.mktemp(suffix=f"_pls_{target_name.lower()}.py"))
        tmp.write_text(filled_code)
        print(f"  Script: {tmp}")

        # Execute the complete script
        exec_globals = {}
        exec(filled_code, exec_globals)

        # Call run_workflow()
        results = exec_globals["run_workflow"]()

        # Extract R²
        export_r2 = float(results["pls_1"]["r2"].flat[0])
        diff = abs(backend_r2[target_name] - export_r2)
        status = "MATCH" if diff < 1e-10 else f"MISMATCH (diff={diff:.2e})"
        if diff >= 1e-10:
            all_match = False
        print(f"  Backend R²: {backend_r2[target_name]:.6f}")
        print(f"  Export R²:  {export_r2:.6f}")
        print(f"  Status: {status}")

    # =====================================================================
    # Show the template script (before data fill-in)
    # =====================================================================
    print("\n" + "=" * 60)
    print("Generated Template (before data fill-in):")
    print("=" * 60)

    workflow = MockWorkflow(
        name="PLS Corn MP5 Moisture",
        nodes=[
            MockNode("source_1", "data.source"),
            MockNode("pls_1", "model.pls", {"n_components": n_components, "scale": scale}),
        ],
        edges=[
            MockEdge("source_1", "pls_1", "default", "X"),
            MockEdge("source_1", "pls_1", "target", "y"),
        ],
    )
    print(generate_python_code(workflow))

    # =====================================================================
    # Result
    # =====================================================================
    print("\n" + "=" * 60)
    if all_match:
        print("VALIDATION PASSED: Backend and export R² values match exactly.")
    else:
        print("VALIDATION FAILED: R² mismatch detected.")
        sys.exit(1)
    print("=" * 60)


if __name__ == "__main__":
    main()
