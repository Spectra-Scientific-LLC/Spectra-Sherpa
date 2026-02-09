"""
Tests for the MCP-compatible tool system.

Covers:
- Tool schemas (ToolDefinition, ToolInvocation, ToolResult)
- Tool registry (registration, lookup, listing, LLM format export)
- Tool executor (invocation, context injection, error handling)
- Built-in tools (list_node_types, describe_node, suggest_preprocessing,
  validate_workflow)

Run:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_tools.py -v --no-cov
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tools.schemas import (
    ToolCategory,
    ToolDefinition,
    ToolInvocation,
    ToolResult,
    ToolScope,
)
from app.services.tools.registry import ToolRegistry, register_tool, tool_registry
from app.services.tools.executor import ToolExecutionContext, execute_tool


# ===========================================================================
# 1. Schema tests
# ===========================================================================


class TestToolDefinition:
    """Verify ToolDefinition validation and format export."""

    def test_minimal_definition(self):
        defn = ToolDefinition(name="my_tool", description="A test tool")
        assert defn.name == "my_tool"
        assert defn.category == ToolCategory.system
        assert defn.parameters["type"] == "object"

    def test_name_regex(self):
        """Tool names must be lowercase, start with a letter, underscores allowed."""
        ToolDefinition(name="list_nodes", description="ok")
        ToolDefinition(name="a", description="ok")

        with pytest.raises(Exception):
            ToolDefinition(name="ListNodes", description="uppercase rejected")

        with pytest.raises(Exception):
            ToolDefinition(name="123bad", description="digit start rejected")

    def test_openai_format(self):
        defn = ToolDefinition(
            name="test_tool",
            description="Test",
            parameters={
                "type": "object",
                "properties": {"x": {"type": "integer"}},
                "required": ["x"],
            },
        )
        openai = defn.to_openai_tool()
        assert openai["type"] == "function"
        assert openai["function"]["name"] == "test_tool"
        assert openai["function"]["parameters"]["required"] == ["x"]

    def test_anthropic_format(self):
        defn = ToolDefinition(name="test_tool", description="Test")
        anthropic = defn.to_anthropic_tool()
        assert anthropic["name"] == "test_tool"
        assert "input_schema" in anthropic

    def test_categories(self):
        for cat in ToolCategory:
            defn = ToolDefinition(name="t", description="d", category=cat)
            assert defn.category == cat


class TestToolResult:
    """Verify ToolResult format helpers."""

    def test_openai_message_success(self):
        result = ToolResult(
            invocation_id="inv1",
            tool_name="test",
            success=True,
            result={"answer": 42},
        )
        msg = result.to_openai_message("call_123")
        assert msg["role"] == "tool"
        assert msg["tool_call_id"] == "call_123"
        assert '"answer"' in msg["content"]

    def test_openai_message_error(self):
        result = ToolResult(
            invocation_id="inv2",
            tool_name="test",
            success=False,
            error="Something went wrong",
        )
        msg = result.to_openai_message("call_456")
        assert msg["content"] == "Something went wrong"

    def test_anthropic_block_success(self):
        result = ToolResult(
            invocation_id="inv3",
            tool_name="test",
            success=True,
            result=[1, 2, 3],
        )
        block = result.to_anthropic_block("tu_123")
        assert block["type"] == "tool_result"
        assert block["tool_use_id"] == "tu_123"
        assert "is_error" not in block

    def test_anthropic_block_error(self):
        result = ToolResult(
            invocation_id="inv4",
            tool_name="test",
            success=False,
            error="fail",
        )
        block = result.to_anthropic_block("tu_456")
        assert block["is_error"] is True
        assert block["content"] == "fail"


# ===========================================================================
# 2. Registry tests
# ===========================================================================


class TestToolRegistry:
    """Verify registry CRUD and export operations."""

    def test_register_and_lookup(self):
        reg = ToolRegistry()
        defn = ToolDefinition(name="alpha", description="Alpha tool")
        handler = lambda: "ok"
        reg.register(defn, handler)

        assert "alpha" in reg
        assert len(reg) == 1
        entry = reg.get("alpha")
        assert entry is not None
        assert entry[0].name == "alpha"

    def test_lookup_missing(self):
        reg = ToolRegistry()
        assert reg.get("nonexistent") is None

    def test_unregister(self):
        reg = ToolRegistry()
        defn = ToolDefinition(name="beta", description="Beta tool")
        reg.register(defn, lambda: None)
        assert reg.unregister("beta") is True
        assert "beta" not in reg
        assert reg.unregister("beta") is False

    def test_list_definitions(self):
        reg = ToolRegistry()
        reg.register(
            ToolDefinition(name="b_tool", description="B", category=ToolCategory.workflow),
            lambda: None,
        )
        reg.register(
            ToolDefinition(name="a_tool", description="A", category=ToolCategory.spectral),
            lambda: None,
        )
        reg.register(
            ToolDefinition(name="c_tool", description="C", category=ToolCategory.workflow),
            lambda: None,
        )

        all_defs = reg.list_definitions()
        assert [d.name for d in all_defs] == ["a_tool", "b_tool", "c_tool"]

        wf_defs = reg.list_definitions(category=ToolCategory.workflow)
        assert [d.name for d in wf_defs] == ["b_tool", "c_tool"]

    def test_openai_tools_export(self):
        reg = ToolRegistry()
        reg.register(ToolDefinition(name="x", description="X"), lambda: None)
        tools = reg.to_openai_tools()
        assert len(tools) == 1
        assert tools[0]["type"] == "function"

    def test_anthropic_tools_export(self):
        reg = ToolRegistry()
        reg.register(ToolDefinition(name="y", description="Y"), lambda: None)
        tools = reg.to_anthropic_tools()
        assert len(tools) == 1
        assert "input_schema" in tools[0]

    def test_re_registration_warns(self):
        """Re-registering a tool overwrites the previous handler."""
        reg = ToolRegistry()
        defn = ToolDefinition(name="dup", description="First")
        reg.register(defn, lambda: "first")

        defn2 = ToolDefinition(name="dup", description="Second")
        reg.register(defn2, lambda: "second")

        assert reg.get("dup")[0].description == "Second"


class TestRegisterDecorator:
    """Verify the @register_tool decorator."""

    def test_decorator_registers_function(self):
        # Import built-in tools to trigger registration
        import app.services.tools.builtin  # noqa: F401

        assert len(tool_registry) > 0

    def test_decorator_preserves_function(self):
        """Decorated function is still callable directly."""
        from app.services.tools.builtin.spectral import list_node_types

        result = list_node_types()
        assert isinstance(result, list)


# ===========================================================================
# 3. Executor tests
# ===========================================================================


class TestToolExecutor:
    """Verify execute_tool() invocation, context injection, and error handling."""

    @pytest.mark.asyncio
    async def test_execute_sync_tool(self):
        """Sync tool handlers are wrapped in to_thread."""
        reg = ToolRegistry()
        defn = ToolDefinition(name="sync_tool", description="Sync")
        reg.register(defn, lambda: {"status": "ok"})

        with patch("app.services.tools.executor.tool_registry", reg):
            result = await execute_tool(
                ToolInvocation(tool_name="sync_tool"),
            )
        assert result.success is True
        assert result.result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_execute_async_tool(self):
        """Async tool handlers are awaited directly."""
        reg = ToolRegistry()
        defn = ToolDefinition(name="async_tool", description="Async")

        async def handler():
            return [1, 2, 3]

        reg.register(defn, handler)

        with patch("app.services.tools.executor.tool_registry", reg):
            result = await execute_tool(
                ToolInvocation(tool_name="async_tool"),
            )
        assert result.success is True
        assert result.result == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_execute_with_arguments(self):
        """Tool arguments are passed as kwargs."""
        reg = ToolRegistry()
        defn = ToolDefinition(
            name="add_tool",
            description="Add",
            parameters={
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"},
                },
                "required": ["a", "b"],
            },
        )
        reg.register(defn, lambda a, b: a + b)

        with patch("app.services.tools.executor.tool_registry", reg):
            result = await execute_tool(
                ToolInvocation(tool_name="add_tool", arguments={"a": 3, "b": 7}),
            )
        assert result.success is True
        assert result.result == 10

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        """Unknown tool returns error result (not exception)."""
        reg = ToolRegistry()
        with patch("app.services.tools.executor.tool_registry", reg):
            result = await execute_tool(
                ToolInvocation(tool_name="nonexistent"),
            )
        assert result.success is False
        assert "Unknown tool" in result.error

    @pytest.mark.asyncio
    async def test_execute_handler_exception(self):
        """Handler exceptions are caught and returned as error results."""
        reg = ToolRegistry()
        defn = ToolDefinition(name="fail_tool", description="Fails")

        def handler():
            raise ValueError("intentional failure")

        reg.register(defn, handler)

        with patch("app.services.tools.executor.tool_registry", reg):
            result = await execute_tool(
                ToolInvocation(tool_name="fail_tool"),
            )
        assert result.success is False
        assert "intentional failure" in result.error

    @pytest.mark.asyncio
    async def test_execute_requires_session(self):
        """Tools that need a session get it from context."""
        reg = ToolRegistry()
        defn = ToolDefinition(
            name="db_tool",
            description="Needs session",
            requires_session=True,
        )

        async def handler(session=None):
            return {"has_session": session is not None}

        reg.register(defn, handler)

        # Without context → error
        with patch("app.services.tools.executor.tool_registry", reg):
            result = await execute_tool(
                ToolInvocation(tool_name="db_tool"),
            )
        assert result.success is False
        assert "session" in result.error.lower()

        # With context → success
        ctx = ToolExecutionContext(session=MagicMock())
        with patch("app.services.tools.executor.tool_registry", reg):
            result = await execute_tool(
                ToolInvocation(tool_name="db_tool"),
                context=ctx,
            )
        assert result.success is True
        assert result.result["has_session"] is True

    @pytest.mark.asyncio
    async def test_execute_requires_egress(self):
        """Egress-dependent tools check is_egress_enabled."""
        reg = ToolRegistry()
        defn = ToolDefinition(
            name="net_tool",
            description="Needs egress",
            requires_egress=True,
        )
        reg.register(defn, lambda: "ok")

        with patch("app.services.tools.executor.tool_registry", reg), \
             patch("app.core.security.is_egress_enabled", return_value=False):
            result = await execute_tool(
                ToolInvocation(tool_name="net_tool"),
            )
        assert result.success is False
        assert "egress" in result.error.lower()


# ===========================================================================
# 4. Built-in tool tests
# ===========================================================================


class TestBuiltinSpectralTools:
    """Verify built-in spectral domain tools."""

    def test_list_node_types_all(self):
        from app.services.tools.builtin.spectral import list_node_types

        result = list_node_types()
        assert isinstance(result, list)
        assert len(result) > 0
        # Each entry should have expected keys
        first = result[0]
        assert "node_type" in first
        assert "label" in first
        assert "category" in first

    def test_list_node_types_filtered(self):
        from app.services.tools.builtin.spectral import list_node_types

        preprocessing = list_node_types(category="preprocessing")
        modeling = list_node_types(category="modeling")
        assert all(n["category"] == "preprocessing" for n in preprocessing)
        assert all(n["category"] == "modeling" for n in modeling)

    def test_list_node_types_empty_category(self):
        from app.services.tools.builtin.spectral import list_node_types

        result = list_node_types(category="nonexistent_category")
        assert result == []

    def test_describe_node_known(self):
        from app.services.tools.builtin.spectral import describe_node

        result = describe_node("model.pca")
        assert result["node_type"] == "model.pca"
        assert "parameters" in result
        assert "description" in result

    def test_describe_node_unknown(self):
        from app.services.tools.builtin.spectral import describe_node

        result = describe_node("nonexistent.node")
        assert "error" in result
        assert "available" in result

    def test_suggest_preprocessing_ir(self):
        from app.services.tools.builtin.spectral import suggest_preprocessing

        result = suggest_preprocessing(technique="IR")
        assert result["technique"] == "IR"
        steps = result["recommended_steps"]
        assert len(steps) > 0
        # IR should include baseline correction
        step_types = [s["step"] for s in steps]
        assert "baseline.als" in step_types

    def test_suggest_preprocessing_default(self):
        from app.services.tools.builtin.spectral import suggest_preprocessing

        result = suggest_preprocessing()
        assert result["technique"] == "generic"
        assert len(result["recommended_steps"]) > 0

    def test_suggest_preprocessing_with_goal(self):
        from app.services.tools.builtin.spectral import suggest_preprocessing

        result = suggest_preprocessing(technique="NIR", goal="classification")
        steps = [s["step"] for s in result["recommended_steps"]]
        # Should include both NIR-specific and classification-specific steps
        assert "normalize.snv" in steps
        assert "preprocess.autoscaling" in steps


class TestBuiltinWorkflowTools:
    """Verify built-in workflow tools."""

    def test_validate_workflow_valid(self):
        from app.services.tools.builtin.workflow import validate_workflow

        nodes = [
            {"node_id": "n1", "node_type": "data.source", "parameters": {}},
            {"node_id": "n2", "node_type": "model.pca", "parameters": {"n_components": 3}},
        ]
        edges = [{"from_node_id": "n1", "to_node_id": "n2"}]

        result = validate_workflow(nodes=nodes, edges=edges)
        assert result["valid"] is True

    def test_validate_workflow_unknown_node_type(self):
        from app.services.tools.builtin.workflow import validate_workflow

        nodes = [
            {"node_id": "n1", "node_type": "fake.node"},
        ]
        result = validate_workflow(nodes=nodes, edges=[])
        assert result["valid"] is False
        assert any("Unknown node type" in i["message"] for i in result["issues"])

    def test_validate_workflow_dangling_edge(self):
        from app.services.tools.builtin.workflow import validate_workflow

        nodes = [
            {"node_id": "n1", "node_type": "data.source"},
        ]
        edges = [{"from_node_id": "n1", "to_node_id": "n99"}]

        result = validate_workflow(nodes=nodes, edges=edges)
        assert result["valid"] is False
        assert any("not in node list" in i["message"] for i in result["issues"])

    def test_validate_workflow_cycle(self):
        from app.services.tools.builtin.workflow import validate_workflow

        nodes = [
            {"node_id": "n1", "node_type": "data.source"},
            {"node_id": "n2", "node_type": "data.source"},
        ]
        edges = [
            {"from_node_id": "n1", "to_node_id": "n2"},
            {"from_node_id": "n2", "to_node_id": "n1"},
        ]

        result = validate_workflow(nodes=nodes, edges=edges)
        assert result["valid"] is False
        assert any("cycle" in i["message"].lower() for i in result["issues"])


# ===========================================================================
# 5. Integration: global registry has built-in tools
# ===========================================================================


class TestGlobalRegistry:
    """Verify the global tool_registry contains all expected built-in tools."""

    def test_builtin_tools_registered(self):
        # Import triggers registration
        import app.services.tools.builtin  # noqa: F401

        expected = [
            "list_node_types",
            "describe_node",
            "suggest_preprocessing",
            "get_workflow_summary",
            "validate_workflow",
            "list_workflows",
        ]
        for name in expected:
            assert name in tool_registry, f"Built-in tool {name!r} not registered"

    def test_openai_export_complete(self):
        tools = tool_registry.to_openai_tools()
        assert len(tools) >= 6
        for t in tools:
            assert t["type"] == "function"
            assert "name" in t["function"]

    def test_anthropic_export_complete(self):
        tools = tool_registry.to_anthropic_tools()
        assert len(tools) >= 6
        for t in tools:
            assert "name" in t
            assert "input_schema" in t

    def test_spectral_category_filter(self):
        spectral = tool_registry.list_definitions(category=ToolCategory.spectral)
        assert len(spectral) >= 3  # list_node_types, describe_node, suggest_preprocessing
        for d in spectral:
            assert d.category == ToolCategory.spectral

    def test_workflow_category_filter(self):
        workflow = tool_registry.list_definitions(category=ToolCategory.workflow)
        assert len(workflow) >= 3  # get_workflow_summary, validate_workflow, list_workflows
        for d in workflow:
            assert d.category == ToolCategory.workflow


# ===========================================================================
# 6. Scope filtering tests
# ===========================================================================


class TestScopeFiltering:
    """Verify ToolScope-based listing and executor access control."""

    def test_exclude_internal_scope(self):
        reg = ToolRegistry()
        reg.register(
            ToolDefinition(name="public_tool", description="Public", scope=ToolScope.public),
            lambda: None,
        )
        reg.register(
            ToolDefinition(name="internal_tool", description="Internal", scope=ToolScope.internal),
            lambda: None,
        )
        reg.register(
            ToolDefinition(name="admin_tool", description="Admin", scope=ToolScope.admin),
            lambda: None,
        )

        visible = reg.list_definitions(exclude_scopes={ToolScope.internal})
        names = [d.name for d in visible]
        assert "public_tool" in names
        assert "admin_tool" in names
        assert "internal_tool" not in names

    def test_exclude_internal_and_admin(self):
        reg = ToolRegistry()
        reg.register(
            ToolDefinition(name="pub", description="P", scope=ToolScope.public),
            lambda: None,
        )
        reg.register(
            ToolDefinition(name="adm", description="A", scope=ToolScope.admin),
            lambda: None,
        )
        reg.register(
            ToolDefinition(name="intl", description="I", scope=ToolScope.internal),
            lambda: None,
        )

        visible = reg.list_definitions(exclude_scopes={ToolScope.internal, ToolScope.admin})
        names = [d.name for d in visible]
        assert names == ["pub"]

    @pytest.mark.asyncio
    async def test_admin_scope_requires_superuser(self):
        """Admin-scoped tools reject non-superuser callers."""
        reg = ToolRegistry()
        defn = ToolDefinition(name="admin_op", description="Admin only", scope=ToolScope.admin)
        reg.register(defn, lambda: "secret")

        # No user
        with patch("app.services.tools.executor.tool_registry", reg):
            result = await execute_tool(ToolInvocation(tool_name="admin_op"))
        assert result.success is False
        assert "admin" in result.error.lower()

        # Regular user (not superuser)
        regular = MagicMock()
        regular.is_superuser = False
        ctx = ToolExecutionContext(user=regular)
        with patch("app.services.tools.executor.tool_registry", reg):
            result = await execute_tool(ToolInvocation(tool_name="admin_op"), ctx)
        assert result.success is False
        assert "admin" in result.error.lower()

        # Superuser succeeds
        admin = MagicMock()
        admin.is_superuser = True
        ctx = ToolExecutionContext(user=admin)
        with patch("app.services.tools.executor.tool_registry", reg):
            result = await execute_tool(ToolInvocation(tool_name="admin_op"), ctx)
        assert result.success is True
        assert result.result == "secret"

    @pytest.mark.asyncio
    async def test_internal_scope_denied_by_default(self):
        """Internal tools cannot be invoked without allow_internal=True."""
        reg = ToolRegistry()
        defn = ToolDefinition(name="llm_only", description="LLM only", scope=ToolScope.internal)
        reg.register(defn, lambda: "internal data")

        with patch("app.services.tools.executor.tool_registry", reg):
            result = await execute_tool(ToolInvocation(tool_name="llm_only"))
        assert result.success is False
        assert "internal" in result.error.lower()

    @pytest.mark.asyncio
    async def test_internal_scope_allowed_with_flag(self):
        """Internal tools succeed when allow_internal=True (LLM caller)."""
        reg = ToolRegistry()
        defn = ToolDefinition(name="llm_tool", description="LLM tool", scope=ToolScope.internal)
        reg.register(defn, lambda: "llm result")

        with patch("app.services.tools.executor.tool_registry", reg):
            result = await execute_tool(
                ToolInvocation(tool_name="llm_tool"),
                allow_internal=True,
            )
        assert result.success is True
        assert result.result == "llm result"


# ===========================================================================
# 7. Argument validation tests
# ===========================================================================


class TestArgumentValidation:
    """Verify JSON Schema argument validation in executor."""

    @pytest.mark.asyncio
    async def test_missing_required_argument(self):
        reg = ToolRegistry()
        defn = ToolDefinition(
            name="needs_args",
            description="Requires 'name'",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        )
        reg.register(defn, lambda name: f"Hello {name}")

        with patch("app.services.tools.executor.tool_registry", reg):
            result = await execute_tool(
                ToolInvocation(tool_name="needs_args", arguments={}),
            )
        assert result.success is False
        assert "name" in result.error.lower()

    @pytest.mark.asyncio
    async def test_unknown_argument_rejected(self):
        reg = ToolRegistry()
        defn = ToolDefinition(
            name="strict_tool",
            description="No extra args",
            parameters={
                "type": "object",
                "properties": {"x": {"type": "integer"}},
                "required": [],
            },
        )
        reg.register(defn, lambda x=0: x)

        with patch("app.services.tools.executor.tool_registry", reg):
            result = await execute_tool(
                ToolInvocation(tool_name="strict_tool", arguments={"x": 1, "bogus": "bad"}),
            )
        # With jsonschema installed → ValidationError on additionalProperties
        # Without jsonschema → fallback catches unknown args
        assert result.success is False
        assert "bogus" in result.error.lower() or "unknown" in result.error.lower()

    @pytest.mark.asyncio
    async def test_valid_arguments_pass(self):
        reg = ToolRegistry()
        defn = ToolDefinition(
            name="ok_tool",
            description="Happy path",
            parameters={
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "string"},
                },
                "required": ["a"],
            },
        )
        reg.register(defn, lambda a, b="default": {"a": a, "b": b})

        with patch("app.services.tools.executor.tool_registry", reg):
            result = await execute_tool(
                ToolInvocation(tool_name="ok_tool", arguments={"a": 5}),
            )
        assert result.success is True
        assert result.result["a"] == 5


# ===========================================================================
# 8. Per-user egress permission tests
# ===========================================================================


class TestPerUserEgress:
    """Verify per-user egress permission checks in executor."""

    @pytest.mark.asyncio
    async def test_egress_permission_denied(self):
        """Tool with egress_permission rejects when user permission is denied."""
        reg = ToolRegistry()
        defn = ToolDefinition(
            name="cloud_tool",
            description="Needs egress perm",
            requires_egress=True,
            egress_permission="allow_cloud_sync",
        )
        reg.register(defn, lambda: "cloud data")

        mock_user = MagicMock()
        mock_session = MagicMock()
        ctx = ToolExecutionContext(session=mock_session, user=mock_user)

        async def deny_permission(*args, **kwargs):
            return False

        with patch("app.services.tools.executor.tool_registry", reg), \
             patch("app.core.security.is_egress_enabled", return_value=True), \
             patch("app.core.security.check_egress_permission", side_effect=deny_permission):
            result = await execute_tool(
                ToolInvocation(tool_name="cloud_tool"), ctx
            )
        assert result.success is False
        assert "egress permission" in result.error.lower()

    @pytest.mark.asyncio
    async def test_egress_permission_allowed(self):
        """Tool with egress_permission succeeds when permission granted."""
        reg = ToolRegistry()
        defn = ToolDefinition(
            name="cloud_tool_ok",
            description="OK egress",
            requires_egress=True,
            egress_permission="allow_cloud_sync",
        )
        reg.register(defn, lambda: "cloud ok")

        mock_user = MagicMock()
        mock_session = MagicMock()
        ctx = ToolExecutionContext(session=mock_session, user=mock_user)

        async def allow_permission(*args, **kwargs):
            return True

        with patch("app.services.tools.executor.tool_registry", reg), \
             patch("app.core.security.is_egress_enabled", return_value=True), \
             patch("app.core.security.check_egress_permission", side_effect=allow_permission):
            result = await execute_tool(
                ToolInvocation(tool_name="cloud_tool_ok"), ctx
            )
        assert result.success is True
        assert result.result == "cloud ok"

    @pytest.mark.asyncio
    async def test_global_egress_blocks_before_per_user(self):
        """Global egress disabled → fail before per-user check is reached."""
        reg = ToolRegistry()
        defn = ToolDefinition(
            name="net_perm_tool",
            description="Both checks",
            requires_egress=True,
            egress_permission="allow_something",
        )
        reg.register(defn, lambda: "unreachable")

        ctx = ToolExecutionContext(session=MagicMock(), user=MagicMock())

        with patch("app.services.tools.executor.tool_registry", reg), \
             patch("app.core.security.is_egress_enabled", return_value=False):
            result = await execute_tool(
                ToolInvocation(tool_name="net_perm_tool"), ctx
            )
        assert result.success is False
        assert "egress" in result.error.lower()
        # Should fail at global level, not per-user
        assert "disabled" in result.error.lower()


# ===========================================================================
# 9. Plugin trust boundary tests
# ===========================================================================


class TestPluginTrustBoundaries:
    """Verify origin-based constraints on plugin-registered tools."""

    def test_plugin_internal_scope_forced_to_public(self):
        """Plugins cannot register internal-scope tools — forced to public."""
        from app.services.tools.schemas import ToolOrigin

        reg = ToolRegistry()
        defn = ToolDefinition(
            name="sneaky_plugin",
            description="Tries to be internal",
            scope=ToolScope.internal,
            origin=ToolOrigin.plugin,
        )
        reg.register(defn, lambda: "hidden")

        entry = reg.get("sneaky_plugin")
        assert entry is not None
        assert entry[0].scope == ToolScope.public  # forced from internal

    def test_plugin_requires_user_forced_true(self):
        """Plugin tools always have requires_user=True regardless of declaration."""
        from app.services.tools.schemas import ToolOrigin

        reg = ToolRegistry()
        defn = ToolDefinition(
            name="anon_plugin",
            description="Wants anonymous access",
            requires_user=False,
            origin=ToolOrigin.plugin,
        )
        reg.register(defn, lambda: "no user")

        entry = reg.get("anon_plugin")
        assert entry is not None
        assert entry[0].requires_user is True

    def test_plugin_admin_scope_kept(self):
        """Plugin tools can use admin scope (only internal is blocked)."""
        from app.services.tools.schemas import ToolOrigin

        reg = ToolRegistry()
        defn = ToolDefinition(
            name="admin_plugin",
            description="Admin plugin",
            scope=ToolScope.admin,
            origin=ToolOrigin.plugin,
        )
        reg.register(defn, lambda: "admin ok")

        entry = reg.get("admin_plugin")
        assert entry[0].scope == ToolScope.admin

    def test_builtin_origin_preserved(self):
        """Built-in tools registered via @register_tool retain origin=builtin."""
        import app.services.tools.builtin  # noqa: F401

        entry = tool_registry.get("list_node_types")
        assert entry is not None
        from app.services.tools.schemas import ToolOrigin
        assert entry[0].origin == ToolOrigin.builtin

    def test_register_plugin_tool_sets_origin(self):
        """register_plugin_tool() forces origin=plugin."""
        from app.services.tools.registry import register_plugin_tool
        from app.services.tools.schemas import ToolOrigin

        # Use a fresh registry to avoid polluting global
        reg = ToolRegistry()
        defn = ToolDefinition(
            name="ext_tool",
            description="From a plugin",
            origin=ToolOrigin.builtin,  # caller tries builtin
        )
        # Patch the global so register_plugin_tool writes to our test registry
        with patch("app.services.tools.registry.tool_registry", reg):
            register_plugin_tool(defn, lambda: "ext")

        entry = reg.get("ext_tool")
        assert entry is not None
        assert entry[0].origin == ToolOrigin.plugin  # forced
        assert entry[0].requires_user is True  # plugin constraint

    @pytest.mark.asyncio
    async def test_plugin_tool_requires_user_context(self):
        """Plugin tool with requires_user=True fails without user in context."""
        from app.services.tools.schemas import ToolOrigin

        reg = ToolRegistry()
        defn = ToolDefinition(
            name="user_plugin",
            description="Needs user",
            origin=ToolOrigin.plugin,
            requires_user=False,  # will be forced True by registry
        )
        reg.register(defn, lambda user=None: f"hi {user}")

        # No context → requires_user was forced True → should fail
        with patch("app.services.tools.executor.tool_registry", reg):
            result = await execute_tool(
                ToolInvocation(tool_name="user_plugin"),
            )
        assert result.success is False
        assert "user" in result.error.lower()

    def test_plugin_context_forces_origin(self):
        """Tools registered inside plugin_context() get origin=plugin."""
        from app.services.tools.schemas import ToolOrigin

        reg = ToolRegistry()
        # Register via @register_tool-style (declares origin=builtin)
        defn = ToolDefinition(
            name="ctx_tool",
            description="Registered during plugin load",
            origin=ToolOrigin.builtin,
        )
        with reg.plugin_context():
            reg.register(defn, lambda: "from plugin")

        entry = reg.get("ctx_tool")
        assert entry is not None
        assert entry[0].origin == ToolOrigin.plugin
        assert entry[0].requires_user is True  # plugin constraint applied

    def test_plugin_context_does_not_affect_outside(self):
        """Tools registered outside plugin_context() keep their origin."""
        from app.services.tools.schemas import ToolOrigin

        reg = ToolRegistry()
        defn_inside = ToolDefinition(name="inside", description="Inside ctx", origin=ToolOrigin.builtin)
        defn_outside = ToolDefinition(name="outside", description="Outside ctx", origin=ToolOrigin.builtin)

        with reg.plugin_context():
            reg.register(defn_inside, lambda: "in")

        # After context exits, registrations should be normal
        reg.register(defn_outside, lambda: "out")

        assert reg.get("inside")[0].origin == ToolOrigin.plugin
        assert reg.get("outside")[0].origin == ToolOrigin.builtin

    def test_plugin_context_scope_and_user_enforced(self):
        """plugin_context() + scope=internal → forced public + requires_user."""
        from app.services.tools.schemas import ToolOrigin

        reg = ToolRegistry()
        defn = ToolDefinition(
            name="sneaky_ctx",
            description="Tries internal from plugin context",
            scope=ToolScope.internal,
            requires_user=False,
            origin=ToolOrigin.builtin,  # will be overridden
        )
        with reg.plugin_context():
            reg.register(defn, lambda: "hidden")

        entry = reg.get("sneaky_ctx")
        assert entry[0].origin == ToolOrigin.plugin
        assert entry[0].scope == ToolScope.public  # internal blocked
        assert entry[0].requires_user is True
