"""Generated Python must delegate to canonical node implementations."""

from __future__ import annotations

from spectra_sherpa.app.services.dag.nodes.deploy_nodes import DeployInputNode, DeployOutputNode
from spectra_sherpa.app.services.dag.nodes.preprocessing.clip_range_node import ClipRangeNode


def test_deploy_input_export_requires_exact_external_payload():
    node = DeployInputNode(node_id="deploy_in_1", parameters={"stream_name": "test"})
    code = "\n".join(node.generate_python(input_map={}, indent="    ", use_scp=False))

    assert "admit_deployment_input" in code
    assert "deployment_inputs['test']" in code
    assert "np.zeros" not in code
    assert "Dummy" not in code


def test_deploy_output_export_uses_canonical_formatter():
    node = DeployOutputNode(node_id="deploy_out_1", parameters={"output_format": "json"})
    code = "\n".join(node.generate_python({"default": "results['model']"}, use_scp=False))

    assert "format_deployment_output" in code
    assert "results['model']" in code


def test_clip_range_export_delegates_in_both_environment_modes():
    node = ClipRangeNode(node_id="clip_1", parameters={"minimum": 400, "maximum": 4000})
    scp_code = "\n".join(node.generate_python({"default": "data_in"}, use_scp=True))
    native_code = "\n".join(node.generate_python({"default": "data_in"}, use_scp=False))

    assert scp_code == native_code
    assert "_clip_range_dataset_dispatch" in native_code
    assert "_build_clip_range_result" in native_code
    assert "np.ones" not in native_code
    assert "NDDataset" not in native_code
    assert "_Result" not in native_code
