"""Import sanity tests to prevent circular dependencies and missing modules.

Tests Issue #3: Circular imports must not prevent library usage.
"""

from __future__ import annotations

import importlib
import sys
from importlib.util import find_spec

import pytest


def test_core_modules_importable():
    """Test that core modules can be imported without circular dependency errors."""
    core_modules = [
        "spectra_sherpa",
        "spectra_sherpa.app",
        "spectra_sherpa.app.core",
        "spectra_sherpa.app.core.config",
        "spectra_sherpa.app.services",
        "spectra_sherpa.app.services.dag",
        "spectra_sherpa.app.lib",
    ]

    for module_name in core_modules:
        try:
            importlib.import_module(module_name)
        except ImportError as e:
            pytest.fail(f"Failed to import {module_name}: {e}")


def test_node_modules_importable():
    """Test that all node modules can be imported.

    This is the critical test for Issue #3: ensuring cloud.py removal
    doesn't break imports.
    """
    node_modules = [
        "spectra_sherpa.app.services.dag.nodes",
        "spectra_sherpa.app.services.dag.nodes.data",
        "spectra_sherpa.app.services.dag.nodes.preprocessing",
        "spectra_sherpa.app.services.dag.nodes.modeling",
        "spectra_sherpa.app.services.dag.nodes.output",
        "spectra_sherpa.app.services.dag.nodes.blend",
        "spectra_sherpa.app.services.dag.nodes.classification",
        "spectra_sherpa.app.services.dag.nodes.diagnostics",
        "spectra_sherpa.app.services.dag.nodes.time_series",
        "spectra_sherpa.app.services.dag.nodes.custom",
        "spectra_sherpa.app.services.dag.nodes.deploy_nodes",
    ]

    for module_name in node_modules:
        try:
            importlib.import_module(module_name)
        except ImportError as e:
            pytest.fail(f"Failed to import {module_name}: {e}")


def test_cloud_module_not_imported():
    """Test that deleted cloud.py module is NOT imported.

    This verifies Issue #3 fix: cloud import was removed from __init__.py.
    """
    # Import the nodes package
    import spectra_sherpa.app.services.dag.nodes as nodes_pkg

    # Verify cloud is not in the package's __all__
    assert "cloud" not in nodes_pkg.__all__, "cloud should not be in __all__ (deleted module)"

    # Verify cloud module doesn't exist
    cloud_spec = find_spec("spectra_sherpa.app.services.dag.nodes.cloud")
    assert cloud_spec is None, "cloud.py should not exist (was deleted during cleanup)"


def test_no_circular_import_on_fresh_import():
    """Test that importing nodes from a clean slate works (no circular deps)."""
    saved = {k: v for k, v in sys.modules.items() if k.startswith("spectra_sherpa")}
    for key in list(saved):
        del sys.modules[key]

    try:
        import spectra_sherpa.app.services.dag.nodes  # noqa: F401
    except ImportError as e:
        pytest.fail(f"Circular import or missing module detected: {e}")
    finally:
        # Restore original modules to prevent poisoning subsequent tests
        for k in [k for k in sys.modules if k.startswith("spectra_sherpa")]:
            del sys.modules[k]
        sys.modules.update(saved)


def test_library_usage_example():
    """Test that SpectraSherpa can be used as a library (not just via CLI).

    This is the user scenario that was failing before Issue #3 fix.
    """
    saved = {k: v for k, v in sys.modules.items() if k.startswith("spectra_sherpa")}
    for key in list(saved):
        del sys.modules[key]

    try:
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset  # noqa: F401
        from spectra_sherpa.app.services.dag import DAGExecutor, WorkflowEdge, WorkflowNode  # noqa: F401

        executor = DAGExecutor()
        executor.add_node(
            WorkflowNode(
                node_id="src",
                node_type="data.source",
                parameters={"source": "sklearn", "dataset_name": "iris"},
            )
        )
        assert True

    except ImportError as e:
        pytest.fail(f"Library usage failed due to import error: {e}")
    finally:
        for k in [k for k in sys.modules if k.startswith("spectra_sherpa")]:
            del sys.modules[k]
        sys.modules.update(saved)


def test_executor_importable_standalone():
    """Test that DAGExecutor can be imported without importing all nodes."""
    saved = {k: v for k, v in sys.modules.items() if k.startswith("spectra_sherpa")}
    for key in list(saved):
        del sys.modules[key]

    try:
        from spectra_sherpa.app.services.dag.executor import DAGExecutor

        assert DAGExecutor is not None
    except ImportError as e:
        pytest.fail(f"Failed to import DAGExecutor standalone: {e}")
    finally:
        for k in [k for k in sys.modules if k.startswith("spectra_sherpa")]:
            del sys.modules[k]
        sys.modules.update(saved)


def test_all_registered_nodes_have_modules():
    """Test that all nodes listed in __all__ have corresponding modules."""
    import spectra_sherpa.app.services.dag.nodes as nodes_pkg

    for module_name in nodes_pkg.__all__:
        full_name = f"spectra_sherpa.app.services.dag.nodes.{module_name}"
        spec = find_spec(full_name)
        assert spec is not None, f"Module {full_name} listed in __all__ but doesn't exist"


def test_no_stale_imports_in_init():
    """Test that nodes/__init__.py doesn't import deleted modules.

    Regression test for Issue #3: cloud.py deletion.
    """
    import inspect

    import spectra_sherpa.app.services.dag.nodes as nodes_pkg

    # Read the source of __init__.py
    init_source = inspect.getsource(nodes_pkg)

    # Verify 'cloud' is not imported
    assert "from . import" in init_source
    assert (
        "cloud," not in init_source and "cloud\n" not in init_source
    ), "Deleted module 'cloud' should not be imported in __init__.py"


def test_headless_api_importable():
    """Test that headless API can be imported (depends on executor)."""
    try:
        from spectra_sherpa.app.api.headless_app import app

        assert app is not None
    except ImportError as e:
        pytest.fail(f"Failed to import headless_app: {e}")


def test_cli_importable():
    """Test that CLI module can be imported."""
    try:
        from spectra_sherpa.cli import main

        assert main is not None
    except ImportError as e:
        pytest.fail(f"Failed to import CLI: {e}")


@pytest.mark.parametrize(
    "module_path",
    [
        "spectra_sherpa.app.services.dag.executor",
        "spectra_sherpa.app.services.dag.node_base",
        "spectra_sherpa.app.services.dag.graph_utils",
        "spectra_sherpa.app.lib.sherpa_dataset",
        "spectra_sherpa.app.lib.adapters.scp_adapter",
    ],
)
def test_critical_modules_importable(module_path):
    """Test that critical modules can be imported individually."""
    try:
        importlib.import_module(module_path)
    except ImportError as e:
        pytest.fail(f"Failed to import critical module {module_path}: {e}")


def test_import_speed_reasonable():
    """Test that import time is reasonable (< 5 seconds).

    Circular imports or excessive eager loading can cause slow imports.
    """
    import time

    saved = {k: v for k, v in sys.modules.items() if k.startswith("spectra_sherpa")}
    for key in list(saved):
        del sys.modules[key]

    try:
        start = time.time()
        import spectra_sherpa.app.services.dag.nodes  # noqa: F401

        elapsed = time.time() - start
        assert elapsed < 5.0, f"Import took {elapsed:.2f}s (too slow, possible circular imports)"
    finally:
        for k in [k for k in sys.modules if k.startswith("spectra_sherpa")]:
            del sys.modules[k]
        sys.modules.update(saved)


def test_top_level_front_door_exports():
    """Top-level package should expose stable front-door symbols."""
    import spectra_sherpa as ss
    from spectra_sherpa.app.lib.adapters.numpy_adapter import from_numpy, to_numpy
    from spectra_sherpa.app.lib.axes import (
        AxisInfo,
        FeatureAxis,
        FrequencyAxis,
        MZAxis,
        PotentialAxis,
        SampleAxis,
        SpatialAxis,
        SpectralAxis,
        TimeAxis,
    )
    from spectra_sherpa.app.lib.sherpa_dataset import (
        DomainContext,
        EvaluationResult,
        Provenance,
        QualityMetrics,
        SherpaDataset,
        TargetContext,
    )

    assert ss.SherpaDataset is SherpaDataset
    assert ss.Provenance is Provenance
    assert ss.DomainContext is DomainContext
    assert ss.TargetContext is TargetContext
    assert ss.QualityMetrics is QualityMetrics
    assert ss.EvaluationResult is EvaluationResult

    assert ss.AxisInfo is AxisInfo
    assert ss.FeatureAxis is FeatureAxis
    assert ss.SpectralAxis is SpectralAxis
    assert ss.TimeAxis is TimeAxis
    assert ss.MZAxis is MZAxis
    assert ss.PotentialAxis is PotentialAxis
    assert ss.FrequencyAxis is FrequencyAxis
    assert ss.SpatialAxis is SpatialAxis
    assert ss.SampleAxis is SampleAxis

    assert ss.from_numpy is from_numpy
    assert ss.to_numpy is to_numpy


def test_top_level_lazy_submodules():
    """`io` and `preprocessing` should load lazily via package __getattr__."""
    saved = {k: v for k, v in sys.modules.items() if k.startswith("spectra_sherpa")}
    for key in list(saved):
        del sys.modules[key]

    try:
        import spectra_sherpa as ss

        assert "spectra_sherpa.app.lib.io" not in sys.modules
        assert "spectra_sherpa.app.lib.preprocessing" not in sys.modules
        assert "spectra_sherpa.app.lib.scp_compat" not in sys.modules

        _ = ss.io
        assert "spectra_sherpa.app.lib.io" in sys.modules

        _ = ss.preprocessing
        assert "spectra_sherpa.app.lib.preprocessing" in sys.modules
    finally:
        for k in [k for k in sys.modules if k.startswith("spectra_sherpa")]:
            del sys.modules[k]
        sys.modules.update(saved)
