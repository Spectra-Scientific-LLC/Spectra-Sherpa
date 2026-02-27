"""Test that exported workflows correctly handle _Result class.

Tests Issue #4: Exported workflows should not crash with NameError when
_Result is omitted in SCP mode, and should include _Result definition in
numpy mode.
"""

from __future__ import annotations

from spectra_sherpa.app.services.dag.nodes.deploy_nodes import DeployInputNode
from spectra_sherpa.app.services.dag.nodes.preprocessing import ClipRangeNode


def test_deploy_input_node_scp_export():
    """Test DeployInputNode exports scp.NDDataset when use_scp=True."""
    node = DeployInputNode(node_id="deploy_in_1", parameters={"stream_name": "test"})
    lines = node.generate_python(input_map={}, indent="    ", use_scp=True)

    code = "\n".join(lines)
    assert "scp.NDDataset" in code
    assert "_Result" not in code


def test_deploy_input_node_numpy_export():
    """Test DeployInputNode exports _Result when use_scp=False."""
    node = DeployInputNode(node_id="deploy_in_1", parameters={"stream_name": "test"})
    lines = node.generate_python(input_map={}, indent="    ", use_scp=False)

    code = "\n".join(lines)
    assert "_Result" in code
    assert "scp.NDDataset" not in code


def test_clip_range_node_scp_export():
    """Test ClipRangeNode doesn't use _Result when use_scp=True."""
    node = ClipRangeNode(node_id="clip_1", parameters={"min_wavenumber": 400, "max_wavenumber": 4000})
    lines = node.generate_python(inputs={"default": "data_in"}, indent="    ", use_scp=True)

    code = "\n".join(lines)
    # SCP mode operates on SCP objects directly (no need to explicitly wrap)
    # The important thing is that it doesn't use _Result
    assert "_Result" not in code
    # Should use .copy() and slicing operations that work on SCP objects
    assert ".copy()" in code


def test_clip_range_node_numpy_export_with_axis():
    """Test ClipRangeNode exports _Result with axis handling when use_scp=False."""
    node = ClipRangeNode(node_id="clip_1", parameters={"min_wavenumber": 400, "max_wavenumber": 4000})
    lines = node.generate_python(inputs={"default": "data_in"}, indent="    ", use_scp=False)

    code = "\n".join(lines)
    # numpy mode should use _Result
    assert "_Result" in code
    # Should include axis handling with masked x values
    assert "_x_vals[_mask]" in code or "_new_data" in code
    # Should not use scp.NDDataset
    assert "scp.NDDataset" not in code


def test_clip_range_node_numpy_export_fallback():
    """Test ClipRangeNode fallback case exports _Result when use_scp=False."""
    node = ClipRangeNode(node_id="clip_1", parameters={"min_wavenumber": 0, "max_wavenumber": 100})
    lines = node.generate_python(inputs={"default": "data_in"}, indent="    ", use_scp=False)

    code = "\n".join(lines)
    # Should include fallback case with _Result
    assert "else:" in code  # The fallback branch
    assert "_Result" in code
    # Check that both branches exist (with axis and without axis)
    assert "if _x_vals is not None:" in code


def test_both_nodes_respect_use_scp_flag():
    """Test that both DeployInputNode and ClipRangeNode respect use_scp flag."""
    # Deploy node
    deploy_node = DeployInputNode(node_id="deploy_in_1", parameters={"stream_name": "sample"})
    clip_node = ClipRangeNode(node_id="clip_1", parameters={"min_wavenumber": 400, "max_wavenumber": 4000})

    # Test both modes for deploy node
    deploy_scp_code = "\n".join(deploy_node.generate_python({}, use_scp=True))
    deploy_numpy_code = "\n".join(deploy_node.generate_python({}, use_scp=False))

    # SCP mode should not have _Result
    assert "_Result" not in deploy_scp_code
    assert "scp.NDDataset" in deploy_scp_code
    # Numpy mode should have _Result
    assert "_Result" in deploy_numpy_code
    assert "scp.NDDataset" not in deploy_numpy_code

    # Test both modes for clip node
    clip_scp_code = "\n".join(clip_node.generate_python({"default": "data_in"}, use_scp=True))
    clip_numpy_code = "\n".join(clip_node.generate_python({"default": "data_in"}, use_scp=False))

    # SCP mode should not have _Result (operates on SCP objects directly)
    assert "_Result" not in clip_scp_code
    # Numpy mode should have _Result
    assert "_Result" in clip_numpy_code
