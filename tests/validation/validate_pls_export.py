"""
End-to-end validation: PLS analysis of Corn MP5 dataset.

1. Backend analysis via SpectroChemPy (same code path as PLSNode.execute)
2. Python export code generation (same code path as /export/python endpoint)
3. Execute the exported script and compare R² values

Tests single-target PLS for Moisture and Protein.
"""

import sys
import textwrap
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from spectra_sherpa.app.lib.eigenvector import load_eigenvector_dataset


def r2_score(y_true, y_pred):
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    return 1.0 - (ss_res / ss_tot)


def main():
    # =====================================================================
    # Load Corn MP5 dataset
    # =====================================================================
    print("=" * 60)
    print("Loading Corn MP5 dataset...")
    result = load_eigenvector_dataset("corn_mp5")
    spectra = result["spectra"]  # (80, 700)
    properties = result["properties"]  # (80, 4): Moisture, Oil, Protein, Starch
    prop_names = result["prop_names"]

    print(f"  Spectra shape: {spectra.shape}")
    print(f"  Properties shape: {properties.shape}")
    print(f"  Property names: {prop_names}")

    moisture_idx = prop_names.index("Moisture")
    protein_idx = prop_names.index("Protein")

    n_components = 5
    scale = True

    # =====================================================================
    # PHASE 1: Backend PLS (SpectroChemPy)
    # =====================================================================
    print("\n" + "=" * 60)
    print("PHASE 1: Backend PLS analysis (SpectroChemPy)")
    print("=" * 60)

    import spectrochempy as scp

    X_ndd = scp.NDDataset(spectra.astype(np.float64))

    backend_r2 = {}
    for target_name, target_idx in [("Moisture", moisture_idx), ("Protein", protein_idx)]:
        y_col = properties[:, target_idx].astype(np.float64)
        y_2d = y_col.reshape(-1, 1)
        Y_ndd = scp.NDDataset(y_2d)

        pls = scp.PLSRegression(n_components=n_components, scale=scale)
        pls.fit(X_ndd, Y_ndd)

        y_pred_raw = pls.predict(X_ndd)
        y_pred = np.asarray(
            y_pred_raw.data if hasattr(y_pred_raw, "data") else y_pred_raw,
            dtype=np.float64,
        ).ravel()

        r2 = r2_score(y_col, y_pred)
        backend_r2[target_name] = r2
        print(f"  {target_name}: R² = {r2:.6f}")

    # =====================================================================
    # PHASE 2: Generate Python export code via the export system
    # =====================================================================
    print("\n" + "=" * 60)
    print("PHASE 2: Generate Python export code")
    print("=" * 60)

    import spectra_sherpa.app.services.dag.nodes.data.source  # noqa: F401

    # Import node modules to register them
    import spectra_sherpa.app.services.dag.nodes.modeling.pls_nodes  # noqa: F401
    from spectra_sherpa.app.services.dag.graph_utils import Edge, build_input_map
    from spectra_sherpa.app.services.dag.node_base import node_registry

    # Simulate a workflow: DataSource → PLS
    # The PLS node needs X and y inputs
    edges = [
        Edge(from_node="source_1", to_node="pls_1", from_output="default", to_input="X"),
        Edge(from_node="source_1", to_node="pls_1", from_output="target", to_input="y"),
    ]

    # Test that build_input_map correctly qualifies multi-port references
    input_map = build_input_map("pls_1", edges)
    print(f"  Input map for pls_1: {input_map}")
    assert "X" in input_map, "Missing X in input_map"
    assert "y" in input_map, "Missing y in input_map"
    # Since source_1 uses both 'default' and 'target' ports, both should be qualified
    assert "['default']" in input_map["X"], f"Expected dict-qualified X, got: {input_map['X']}"
    assert "['target']" in input_map["y"], f"Expected dict-qualified y, got: {input_map['y']}"
    print("  build_input_map multi-port detection: OK")

    # Generate PLS export code for each target
    export_r2 = {}
    for target_name, target_idx in [("Moisture", moisture_idx), ("Protein", protein_idx)]:
        pls_node = node_registry.create_node(
            "model.pls",
            "pls_1",
            {"n_components": n_components, "scale": scale},
        )

        assert pls_node.supports_python_export(), "PLSNode should support Python export"

        # Use no indent since we'll exec() at top level
        code_lines = pls_node.generate_python(input_map, indent="", use_scp=True)
        code_block = "\n".join(code_lines)

        # Build the full executable script
        y_col = properties[:, target_idx].astype(np.float64)
        script = textwrap.dedent(
            f"""\
            import numpy as np
            import spectrochempy as scp

            results = {{}}

            # Source node: provide data as a dict (multi-port)
            results['source_1'] = {{
                'default': scp.NDDataset(np.array({spectra.tolist()}, dtype=np.float64)),
                'target': np.array({y_col.tolist()}, dtype=np.float64),
            }}

        """
        )
        script += code_block
        script += "\n"

        # Execute the generated code
        exec_globals = {}
        exec(script, exec_globals)

        # Extract R² from results
        pls_result = exec_globals["results"]["pls_1"]
        r2_values = pls_result["r2"]
        r2_export = float(r2_values.flat[0])
        export_r2[target_name] = r2_export
        print(f"  {target_name} (export): R² = {r2_export:.6f}")

    # =====================================================================
    # PHASE 3: Compare backend vs export R²
    # =====================================================================
    print("\n" + "=" * 60)
    print("PHASE 3: Comparison")
    print("=" * 60)

    all_match = True
    for target_name in ["Moisture", "Protein"]:
        r2_be = backend_r2[target_name]
        r2_ex = export_r2[target_name]
        diff = abs(r2_be - r2_ex)
        status = "MATCH" if diff < 1e-10 else f"MISMATCH (diff={diff:.2e})"
        if diff >= 1e-10:
            all_match = False
        print(f"  {target_name}: backend={r2_be:.6f}  export={r2_ex:.6f}  {status}")

    print("\n" + "=" * 60)
    if all_match:
        print("VALIDATION PASSED: Backend and export R² values match.")
    else:
        print("VALIDATION FAILED: R² values do not match.")
        sys.exit(1)
    print("=" * 60)


if __name__ == "__main__":
    main()
