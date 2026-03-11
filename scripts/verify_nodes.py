import asyncio
import sys
from pathlib import Path

# Add repo root to path
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))


async def verify():
    print("Verifying Node Metadata...")

    # Import modules to register nodes
    from spectra_sherpa.app.models.workflow_node import registry

    nodes_to_check = [
        # Phase 2
        "TrainTestSplitNode",
        "PCANode",
        "PLSNode",
        "PLSDANode",
        "KNNNode",
        "MCRNode",
        # Phase 3
        "PCRNode",
        "SVRNode",
        "LinearRegressionNode",
        "EFANode",
        "NMFNode",
        "FastICANode",
        "SIMPLISMANode",
        # Phase 4
        "HCANode",
        "KMeansNode",
        "DBSCANNode",
        # Phase 5
        "OutlierDetectionNode",
        "CrossValidationNode",
        "PlotNode",
        "ExportNode",
        "StatsSummaryNode",
        "ContourPlotNode",
        "DataTableNode",
    ]

    success = True
    for node_name in nodes_to_check:
        node_cls = registry.get(node_name)
        if not node_cls:
            # Try looking up by label or reverse map if registry stores by type string
            # Detailed check: iterate registry values
            found = False
            for cls in registry.values():
                if cls.__name__ == node_name:
                    node_cls = cls
                    found = True
                    break

            if not found:
                print(f"❌ {node_name} NOT FOUND in registry")
                success = False
                continue

        # Check output ports
        metadata = node_cls.metadata
        if not metadata.output_ports and metadata.output_type == "dict":
            print(f"⚠️  {node_name} missing output_ports definition but has output_type='dict'")
            # Not necessarily a failure if it's intentional, but for this refactor we expect ports
            # actually we expect ALL of these to have ports now.
            success = False

        # Count ports
        n_ports = len(metadata.output_ports) if metadata.output_ports else 0
        print(f"✅ {node_name}: Found {n_ports} output ports")

    if success:
        print("\nAll nodes verified successfully!")
    else:
        print("\nVerification FAILED.")


if __name__ == "__main__":
    asyncio.run(verify())
