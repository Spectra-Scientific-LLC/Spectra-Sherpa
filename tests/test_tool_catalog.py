"""Closed catalog selection must not create implicit tool exposure."""

import pytest

from spectra_sherpa.app.services.tools.catalog import project_tool_catalog
from spectra_sherpa.app.services.tools.registry import ToolRegistry
from spectra_sherpa.app.services.tools.schemas import ToolDefinition


def classified(name, **overrides):
    values = dict(
        name=name,
        description="Inspect existing facts",
        version="1.0",
        output_schema={"type": "object", "properties": {"label": {"type": "string"}}},
        mutation="read",
        disclosure=["metadata"],
        distribution="oss",
        mcp_name=name,
    )
    values.update(overrides)
    return ToolDefinition(**values)


def test_selection_is_explicit_and_preserves_registry_identity():
    registry = ToolRegistry()
    registry.register(classified("old_name", mcp_name="inspect"), lambda: None)
    registry.register(ToolDefinition(name="legacy", description="Legacy"), lambda: None)
    assert project_tool_catalog(registry, []) == []
    result = project_tool_catalog(registry, ["old_name"])
    assert len(result) == 1
    assert result[0]["tool_id"] == "old_name"
    assert result[0]["name"] == "inspect"
    assert registry.get("inspect") is None
    assert registry.to_openai_tools()[1]["function"]["name"] == "old_name"


@pytest.mark.parametrize("field", ["version", "output_schema", "mutation", "disclosure", "distribution", "mcp_name"])
def test_missing_classification_refuses_entire_projection(field):
    registry = ToolRegistry()
    registry.register(classified("complete"), lambda: None)
    registry.register(classified("incomplete", **{field: None}), lambda: None)
    with pytest.raises(ValueError, match="Unclassified"):
        project_tool_catalog(registry, ["complete", "incomplete"])


@pytest.mark.parametrize("selection", [["absent"], ["present", "present"], "present"])
def test_invalid_selection_is_rejected(selection):
    registry = ToolRegistry()
    registry.register(classified("present"), lambda: None)
    with pytest.raises(ValueError):
        project_tool_catalog(registry, selection)


def test_alias_collision_is_rejected_without_overwriting_registry():
    registry = ToolRegistry()
    registry.register(classified("first", mcp_name="same"), lambda: "first")
    registry.register(classified("second", mcp_name="same"), lambda: "second")
    with pytest.raises(ValueError, match="Duplicate projected"):
        project_tool_catalog(registry, ["first", "second"])
    assert registry.get("first")[1]() == "first"
    assert registry.get("second")[1]() == "second"


def test_projection_is_order_independent_and_detached():
    registry = ToolRegistry()
    definition = classified("alpha")
    registry.register(definition, lambda: None)
    registry.register(classified("beta"), lambda: None)
    result = project_tool_catalog(registry, ["beta", "alpha"])
    assert result == project_tool_catalog(registry, ["alpha", "beta"])
    result[0]["output_schema"]["properties"].clear()
    result[0]["input_schema"]["properties"]["injected"] = {}
    result[0]["disclosure"].append("values")
    assert "label" in definition.output_schema["properties"]
    assert "injected" not in definition.parameters["properties"]
    assert definition.disclosure == ["metadata"]


def test_mutated_registry_identity_is_refused():
    registry = ToolRegistry()
    definition = classified("original")
    registry.register(definition, lambda: None)
    definition.name = "changed"
    with pytest.raises(ValueError, match="identity changed"):
        project_tool_catalog(registry, ["original"])


def test_mutated_classification_is_revalidated():
    registry = ToolRegistry()
    definition = classified("original")
    registry.register(definition, lambda: None)
    definition.disclosure.append("unknown")
    with pytest.raises(ValueError):
        project_tool_catalog(registry, ["original"])


def test_builtin_contract_is_registered_without_changing_provider_payload():
    from spectra_sherpa.app.services.tools import tool_registry
    from spectra_sherpa.app.services.tools.builtin.spectral import list_node_types

    definition, handler = tool_registry.get("list_node_types")
    assert handler is list_node_types
    catalog = project_tool_catalog(tool_registry, ["list_node_types"])
    assert catalog[0]["name"] == "list_node_types"
    assert catalog[0]["mutation"] == "read"
    assert catalog[0]["output_schema"]["items"]["required"] == ["node_type", "label", "category", "description"]
    legacy = definition.model_copy(
        update=dict(version=None, output_schema=None, mutation=None, disclosure=None, distribution=None, mcp_name=None)
    )
    assert definition.to_openai_tool() == legacy.to_openai_tool()
    assert definition.to_anthropic_tool() == legacy.to_anthropic_tool()
