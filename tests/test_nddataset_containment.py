"""CI enforcement: NDDataset imports must be confined to approved modules.

This test scans all Python files in the spectra_sherpa package and asserts
that NDDataset is only referenced in files that are approved to use it.

As the SherpaDataset migration progresses, the approved set shrinks.

Run with:
    cd spectra-sherpa && .venv/bin/pytest tests/test_nddataset_containment.py -v
"""

from __future__ import annotations

from pathlib import Path

# Modules approved to reference NDDataset.
# This list should shrink over time as compatibility shims are removed.
# When migrating a module away from NDDataset, remove it from this list.
APPROVED_NDDATASET_MODULES = {
    # Adapter layer (core SCP interop)
    "app/lib/scp_compat.py",
    "app/lib/adapters/scp_adapter.py",
    "app/lib/adapters/scp_extractors.py",
    # SCP-backed modeling/classification nodes
    "nodes/modeling/pca_nodes.py",
    "nodes/modeling/pls_nodes.py",
    "nodes/modeling/mcr_nodes.py",
    "nodes/modeling/efa_nodes.py",
    "nodes/modeling/simplisma_nodes.py",
    "nodes/modeling/decomposition_nodes.py",
    "nodes/modeling/peak_finding_nodes.py",
    "nodes/modeling/regression_nodes.py",
    "nodes/modeling/load_apply_node.py",
    "nodes/modeling/clustering_nodes.py",
    "nodes/modeling/core_utils.py",
    "nodes/classification/plsda_nodes.py",
    "nodes/classification/simca_nodes.py",
    "nodes/classification/knn_nodes.py",
    "nodes/classification/predict_node.py",
    # Data source / preprocessing / utility nodes
    "nodes/data/loaders.py",
    "nodes/data/source.py",
    "nodes/data/_utils.py",
    "nodes/data/synthetic.py",
    "nodes/data/transforms.py",
    "nodes/preprocessing.py",
    "nodes/blend.py",
    "nodes/custom.py",
    "nodes/deploy_nodes.py",
    "nodes/selection/sample_partition_node.py",
    "nodes/selection/variable_select_node.py",
    "nodes/selection/ipls_node.py",
    "nodes/selection/cars_node.py",
    "nodes/selection/spa_node.py",
    "nodes/selection/uve_node.py",
    "nodes/selection/stability_node.py",
    "nodes/selection/nested_cv_node.py",
    "nodes/selection/selection_audit_node.py",
    "nodes/selection/compare_selections_node.py",
    "nodes/transfer/pds_node.py",
    "nodes/transfer/sbc_node.py",
    "nodes/modeling/_artifact_builder.py",
    "nodes/diagnostics.py",
    "nodes/output.py",
    "nodes/time_series.py",
    # DAG infrastructure
    "services/dag/io_contracts.py",
    "services/dag/executor.py",
    "services/dag/executor_validation.py",
    "services/dag/serialize.py",
    "services/dag/export_helpers.py",
    "services/dag/meta_helpers.py",
    "services/dag/node_base.py",
    # Services
    "services/serialization.py",
    "services/python_export.py",
    "services/builder.py",
    "services/cache.py",
    "services/metadata/__init__.py",
    "services/metadata/extractor_base.py",
    # API layer
    "api/v1/routes/predict.py",
    "api/v1/routes/builder.py",
    "api/v1/routes/compute.py",
    # Library modules (legacy SCP interop)
    "app/lib/__init__.py",
    "app/lib/io.py",
    "app/lib/preprocessing.py",
    "app/lib/blending/__init__.py",
    "app/lib/blending/blend.py",
    "app/lib/spectral/conversions.py",
    "app/lib/spectral/dataset.py",
    "app/lib/spectral/metadata.py",
    "app/lib/spectral/validators.py",
    # Models
    "app/models/spectra_meta.py",
    # SDK
    "sdk_nodes.py",
}


def _find_src_root() -> Path:
    """Locate the spectra_sherpa source root."""
    candidate = Path(__file__).resolve().parent.parent / "src" / "spectra_sherpa"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"Cannot find spectra_sherpa source at {candidate}")


def test_nddataset_import_containment():
    """NDDataset references must be confined to approved modules."""
    src_root = _find_src_root()
    violations = []

    for py_file in sorted(src_root.rglob("*.py")):
        relative = str(py_file.relative_to(src_root))

        # Skip if it's an approved module
        if any(relative.endswith(approved) for approved in APPROVED_NDDATASET_MODULES):
            continue

        content = py_file.read_text(errors="replace")
        if "NDDataset" in content:
            violations.append(relative)

    assert not violations, (
        "NDDataset referenced in unapproved modules:\n"
        + "\n".join(f"  - {v}" for v in violations)
        + "\n\nEither add these to APPROVED_NDDATASET_MODULES or "
        "remove the NDDataset reference."
    )
