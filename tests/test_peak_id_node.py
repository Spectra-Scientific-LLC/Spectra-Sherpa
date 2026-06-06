from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from spectra_sherpa.app.api.v1.routes.workflows.catalog import filter_unavailable_node_types
from spectra_sherpa.app.api.v1.routes.workflows.execute import _enforce_advisor_node_egress_policy
from spectra_sherpa.app.contracts.ai_provider_registry import reset_sherpa_advisor, set_sherpa_advisor
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.modeling.peak_id_node import (
    PeakIDNode,
    _parse_peak_id_response,
)


class FakeAdvisor:
    is_available = True

    def __init__(self, response: str):
        self.response = response
        self.messages: list[str] = []

    def has_feature(self, feature: str) -> bool:
        return True

    async def stream_llm_chat(self, message: str, **kwargs):
        self.messages.append(message)
        midpoint = len(self.response) // 2
        yield {"type": "chunk", "text": self.response[:midpoint]}
        yield {"type": "chunk", "text": self.response[midpoint:]}
        yield {"type": "done"}


@pytest.fixture(autouse=True)
def clean_advisor():
    reset_sherpa_advisor()
    yield
    reset_sherpa_advisor()


def peak_payload():
    return {
        "data": [
            {"median_pos": 1710.2, "median_height": 0.8},
            {"median_pos": 1601.5, "median_height": 0.4},
        ],
        "metadata": {
            "technique": "FTIR",
            "x_title": "Wavenumber",
            "x_units": "cm-1",
        },
    }


@pytest.mark.asyncio
async def test_peak_id_node_prompts_primary_llm_and_returns_table():
    response = json.dumps(
        {
            "assignments": [
                {
                    "peak_position": "1710.2",
                    "vibration_mode": "C=O stretch",
                    "structural_origin": "carbonyl group",
                },
                {
                    "peak_position": "1601.5",
                    "vibration_mode": "aromatic C=C stretch",
                    "structural_origin": "conjugated ring",
                },
            ],
            "summary": "The peaks are consistent with carbonyl and aromatic contributions.",
        }
    )
    advisor = FakeAdvisor(response)
    set_sherpa_advisor(advisor)  # type: ignore[arg-type]

    node = PeakIDNode("peak_id_1", {"compound": "acetophenone"})
    result = await node.run(peaks=peak_payload())

    output = result.outputs["default"]
    assert output["data"] == [
        {
            "peak_position": "1710.2",
            "vibration_mode": "C=O stretch",
            "structural_origin": "carbonyl group",
        },
        {
            "peak_position": "1601.5",
            "vibration_mode": "aromatic C=C stretch",
            "structural_origin": "conjugated ring",
        },
    ]
    assert output["metadata"]["summary"] == "The peaks are consistent with carbonyl and aromatic contributions."
    assert output["metadata"]["technique"] == "FTIR"
    assert output["metadata"]["x_title"] == "Wavenumber"
    assert output["metadata"]["x_units"] == "cm-1"
    assert output["metadata"]["compound"] == "acetophenone"
    assert result.diagnostics == {"n_assignments": 2, "n_prompt_peaks": 2, "n_omitted_peaks": 0}
    assert "Given my FTIR spectra" in advisor.messages[0]
    assert "1710.2, 1601.5" in advisor.messages[0]
    assert "acetophenone" in advisor.messages[0]


@pytest.mark.asyncio
async def test_peak_id_node_filters_minor_peaks_before_prompting_llm():
    response = json.dumps(
        {
            "assignments": [
                {
                    "peak_position": "1000",
                    "vibration_mode": "major mode",
                    "structural_origin": "dominant group",
                },
                {
                    "peak_position": "1200",
                    "vibration_mode": "secondary mode",
                    "structural_origin": "secondary group",
                },
            ],
            "summary": "Major peaks were assigned.",
        }
    )
    advisor = FakeAdvisor(response)
    set_sherpa_advisor(advisor)  # type: ignore[arg-type]

    payload = peak_payload()
    payload["data"] = [
        {"median_pos": 900.0, "median_height": 2.0, "count": 1},
        {"median_pos": 1000.0, "median_height": 100.0, "count": 2},
        {"median_pos": 1100.0, "median_height": 1.0, "count": 1},
        {"median_pos": 1200.0, "median_height": 60.0, "count": 2},
    ]

    node = PeakIDNode("peak_id_1", {"compound": "sample", "min_relative_height": 0.05})
    result = await node.run(peaks=payload)

    prompt = advisor.messages[0]
    assert "1000" in prompt
    assert "1200" in prompt
    assert "900" not in prompt
    assert "1100" not in prompt
    metadata = result.outputs["default"]["metadata"]
    assert metadata["n_peaks"] == 4
    assert metadata["n_prompt_peaks"] == 2
    assert metadata["n_omitted_peaks"] == 2
    assert result.diagnostics["n_omitted_peaks"] == 2


@pytest.mark.asyncio
async def test_peak_id_node_caps_prompt_to_strongest_peaks():
    response = json.dumps(
        {
            "assignments": [
                {
                    "peak_position": "1010",
                    "vibration_mode": "strongest mode",
                    "structural_origin": "strongest group",
                },
                {
                    "peak_position": "1030",
                    "vibration_mode": "second mode",
                    "structural_origin": "second group",
                },
            ],
            "summary": "The strongest peaks were assigned.",
        }
    )
    advisor = FakeAdvisor(response)
    set_sherpa_advisor(advisor)  # type: ignore[arg-type]

    payload = peak_payload()
    payload["data"] = [
        {"median_pos": 1000.0, "median_height": 10.0},
        {"median_pos": 1010.0, "median_height": 90.0},
        {"median_pos": 1020.0, "median_height": 20.0},
        {"median_pos": 1030.0, "median_height": 80.0},
    ]

    node = PeakIDNode("peak_id_1", {"max_peaks": 2, "min_relative_height": 0})
    result = await node.run(peaks=payload)

    prompt = advisor.messages[0]
    assert "1010" in prompt
    assert "1030" in prompt
    assert "1000" not in prompt
    assert "1020" not in prompt
    assert result.outputs["default"]["metadata"]["peak_selection"]["max_peaks"] == 2


@pytest.mark.asyncio
async def test_peak_id_node_rejects_non_finite_peak_positions_before_llm_call():
    advisor = FakeAdvisor("{}")
    set_sherpa_advisor(advisor)  # type: ignore[arg-type]
    payload = peak_payload()
    payload["data"] = [
        {"median_pos": 1710.2},
        {"median_pos": float("nan")},
    ]

    node = PeakIDNode("peak_id_1", {"compound": "acetophenone"})
    with pytest.raises(ValueError, match="finite numeric peak positions"):
        await node.run(peaks=payload)

    assert advisor.messages == []


@pytest.mark.asyncio
async def test_peak_id_node_rejects_non_finite_peak_position_strings_before_llm_call():
    advisor = FakeAdvisor("{}")
    set_sherpa_advisor(advisor)  # type: ignore[arg-type]
    payload = peak_payload()
    payload["data"] = [
        {"median_pos": "1710.2"},
        {"median_pos": "inf"},
    ]

    node = PeakIDNode("peak_id_1", {"compound": "acetophenone"})
    with pytest.raises(ValueError, match="finite numeric peak positions"):
        await node.run(peaks=payload)

    assert advisor.messages == []


def test_peak_id_parser_accepts_markdown_table():
    assignments, summary = _parse_peak_id_response("""
        | peak position | vibration mode | structural origin |
        | --- | --- | --- |
        | 1004 | ring breathing | substituted benzene |

        These assignments are tentative and should be checked against standards.
        """)

    assert assignments == [
        {
            "peak_position": "1004",
            "vibration_mode": "ring breathing",
            "structural_origin": "substituted benzene",
        }
    ]
    assert summary == "These assignments are tentative and should be checked against standards."


@pytest.mark.asyncio
async def test_peak_id_node_requires_sherpa_advisor():
    node = PeakIDNode("peak_id_1", {"compound": ""})
    with pytest.raises(ValueError, match="requires Sherpa Advisor"):
        await node.run(peaks=peak_payload())


def test_peak_id_node_is_registered_in_exploratory_category():
    metadata = node_registry.get_metadata("analysis.peak_id")

    assert metadata.label == "Peak ID"
    assert metadata.category == "exploratory"
    assert metadata.input_ports[0].name == "peaks"
    assert metadata.parameters[0].name == "compound"
    assert metadata.policy is not None
    assert metadata.policy.data_egress_risk == "metadata"
    assert metadata.policy.offload_to_pool is False


def test_peak_id_node_is_hidden_when_sherpa_advisor_is_unavailable():
    nodes = node_registry.list_nodes()

    visible_types = {node.node_type for node in filter_unavailable_node_types(nodes)}

    assert "analysis.peak_id" not in visible_types


def test_peak_id_node_is_visible_when_sherpa_advisor_is_available():
    set_sherpa_advisor(FakeAdvisor("{}"))  # type: ignore[arg-type]
    nodes = node_registry.list_nodes()

    visible_types = {node.node_type for node in filter_unavailable_node_types(nodes)}

    assert "analysis.peak_id" in visible_types


@pytest.mark.asyncio
async def test_peak_id_egress_policy_ignores_unreached_advisor_nodes(monkeypatch):
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("egress permission should not be checked for unreached nodes")

    monkeypatch.setattr("spectra_sherpa.app.core.security.check_egress_permission", fail_if_called)
    nodes = [
        SimpleNamespace(node_id="source", node_type="data.source"),
        SimpleNamespace(node_id="peak_id", node_type="analysis.peak_id"),
    ]
    edges = []

    await _enforce_advisor_node_egress_policy(
        nodes,
        edges,
        current_user=SimpleNamespace(id=1),
        session=SimpleNamespace(),
        target_node_id="source",
    )


@pytest.mark.asyncio
async def test_peak_id_egress_policy_blocks_when_llm_context_is_disabled(monkeypatch):
    async def fake_check(_user, permission, **kwargs):
        return permission == "allow_llm_chat"

    monkeypatch.setattr("spectra_sherpa.app.core.security.check_egress_permission", fake_check)
    nodes = [SimpleNamespace(node_id="peak_id", node_type="analysis.peak_id")]
    edges = []

    with pytest.raises(HTTPException) as exc_info:
        await _enforce_advisor_node_egress_policy(
            nodes,
            edges,
            current_user=SimpleNamespace(id=1),
            session=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 403
    assert "LLM context sharing" in exc_info.value.detail
