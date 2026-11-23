"""A governed template is the single definition of its procedure."""

import copy

import pytest

from spectra_sherpa.app.api.v1.routes.workflow_templates import DataBindingSpec
from spectra_sherpa.app.core.template_loader import TemplateLoader
from spectra_sherpa.app.services.procedures import ProcedureRefused, build_procedure, governed_procedure_ids

BINDING = DataBindingSpec(experiment_id=17, file_id=23)


def _template(slug):
    return next(item for item in TemplateLoader().load_all() if item["slug"] == slug)


def test_only_ready_declared_templates_are_governed():
    assert governed_procedure_ids() == ("pls_calibration",)


def test_procedure_is_the_template_graph_with_only_its_source_bound():
    template = copy.deepcopy(_template("pls_calibration")["template_data"])
    procedure = build_procedure("pls_calibration", source_binding=BINDING)
    by_id = {node["node_id"]: node for node in procedure["nodes"]}
    assert [node["node_id"] for node in procedure["nodes"]] == [node["node_id"] for node in template["nodes"]]
    assert by_id["data_1"]["parameters"]["experiment_id"] == 17
    assert "example_binding" not in by_id["data_1"]
    for node in template["nodes"]:
        if node["node_id"] != "data_1":
            assert by_id[node["node_id"]]["node_type"] == node["node_type"]
            assert by_id[node["node_id"]]["parameters"] == node["parameters"]
    assert {(e["from_node_id"], e["to_node_id"]) for e in procedure["edges"]} == {
        (e["from_node_id"], e["to_node_id"]) for e in template["edges"]
    }


def test_only_declared_parameters_can_change():
    procedure = build_procedure(
        "pls_calibration",
        source_binding=BINDING,
        parameters={"model_1": {"scale": True}, "partition_1": {"test_size": 0.3}},
    )
    by_id = {node["node_id"]: node for node in procedure["nodes"]}
    assert by_id["model_1"]["parameters"]["scale"] is True
    assert by_id["partition_1"]["parameters"]["test_size"] == 0.3
    for parameters in ({"eval_1": {"anything": 1}}, {"model_1": {"implementation": "other"}}, {"missing": {"x": 1}}):
        with pytest.raises(ProcedureRefused):
            build_procedure("pls_calibration", source_binding=BINDING, parameters=parameters)


def test_unknown_or_undeclared_procedures_are_refused():
    for procedure_id in ("not_a_template", "representative_calibration", "peak_guided_pls"):
        with pytest.raises(ProcedureRefused):
            build_procedure(procedure_id, source_binding=BINDING)


def test_ai_light_reports_local_only_for_endpoints_on_this_computer():
    from spectra_sherpa.app.core.config import LLMConfig, _runs_on_this_machine

    assert _runs_on_this_machine(LLMConfig(provider="ollama", model="m"))
    assert _runs_on_this_machine(
        LLMConfig(provider="openai_compatible", model="m", base_url="http://127.0.0.1:1234/v1")
    )
    assert _runs_on_this_machine(LLMConfig(provider="openai_compatible", model="m", base_url="http://localhost:8080"))
    assert not _runs_on_this_machine(
        LLMConfig(provider="openai_compatible", model="m", base_url="https://api.example.com")
    )
    assert not _runs_on_this_machine(LLMConfig(provider="anthropic", model="m"))
    assert not _runs_on_this_machine(LLMConfig(provider="ollama", model="m", base_url="http://gpu-box.lan:11434"))
