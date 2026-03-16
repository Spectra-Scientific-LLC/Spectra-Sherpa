"""Test that exported workflows correctly use SherpaDataset.

Tests that nodes use SherpaDataset (not bare _Result) in numpy mode,
and scp.NDDataset in SCP mode.
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
    """Test DeployInputNode exports SherpaDataset when use_scp=False."""
    node = DeployInputNode(node_id="deploy_in_1", parameters={"stream_name": "test"})
    lines = node.generate_python(input_map={}, indent="    ", use_scp=False)

    code = "\n".join(lines)
    assert "SherpaDataset(" in code
    assert "scp.NDDataset" not in code


def test_clip_range_node_scp_export():
    """Test ClipRangeNode doesn't use _Result when use_scp=True."""
    node = ClipRangeNode(node_id="clip_1", parameters={"min_wavenumber": 400, "max_wavenumber": 4000})
    lines = node.generate_python(inputs={"default": "data_in"}, indent="    ", use_scp=True)

    code = "\n".join(lines)
    assert "_Result" not in code
    # Should use .copy() and slicing operations that work on SCP objects
    assert ".copy()" in code


def test_clip_range_node_numpy_export_with_axis():
    """Test ClipRangeNode exports SherpaDataset with axis handling when use_scp=False."""
    node = ClipRangeNode(node_id="clip_1", parameters={"min_wavenumber": 400, "max_wavenumber": 4000})
    lines = node.generate_python(inputs={"default": "data_in"}, indent="    ", use_scp=False)

    code = "\n".join(lines)
    assert "SherpaDataset(" in code
    # Should include axis handling with masked x values
    assert "_x_vals[_mask]" in code or "_new_data" in code
    # Should not use scp.NDDataset
    assert "scp.NDDataset" not in code
    assert "_Result" not in code


def test_clip_range_node_numpy_export_fallback():
    """Test ClipRangeNode fallback case exports SherpaDataset when use_scp=False."""
    node = ClipRangeNode(node_id="clip_1", parameters={"min_wavenumber": 0, "max_wavenumber": 100})
    lines = node.generate_python(inputs={"default": "data_in"}, indent="    ", use_scp=False)

    code = "\n".join(lines)
    # Should include fallback case with SherpaDataset
    assert "else:" in code  # The fallback branch
    assert "SherpaDataset(" in code
    assert "_Result" not in code
    # Check that both branches exist (with axis and without axis)
    assert "if _x_vals is not None:" in code


def test_both_nodes_respect_use_scp_flag():
    """Test that both DeployInputNode and ClipRangeNode respect use_scp flag."""
    deploy_node = DeployInputNode(node_id="deploy_in_1", parameters={"stream_name": "sample"})
    clip_node = ClipRangeNode(node_id="clip_1", parameters={"min_wavenumber": 400, "max_wavenumber": 4000})

    # Test both modes for deploy node
    deploy_scp_code = "\n".join(deploy_node.generate_python({}, use_scp=True))
    deploy_numpy_code = "\n".join(deploy_node.generate_python({}, use_scp=False))

    assert "_Result" not in deploy_scp_code
    assert "scp.NDDataset" in deploy_scp_code
    assert "SherpaDataset(" in deploy_numpy_code
    assert "scp.NDDataset" not in deploy_numpy_code

    # Test both modes for clip node
    clip_scp_code = "\n".join(clip_node.generate_python({"default": "data_in"}, use_scp=True))
    clip_numpy_code = "\n".join(clip_node.generate_python({"default": "data_in"}, use_scp=False))

    assert "_Result" not in clip_scp_code
    assert "SherpaDataset(" in clip_numpy_code
    assert "_Result" not in clip_numpy_code
