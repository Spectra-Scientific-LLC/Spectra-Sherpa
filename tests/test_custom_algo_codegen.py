"""Tests for custom algo code generation and registry lifecycle."""

import ast
from unittest.mock import patch

import pytest

from spectra_sherpa.app.services.custom_algo_codegen import (
    generate_plugin_source,
    make_node_type,
    validate_code_syntax,
    validate_loader_plugin_source,
    validate_slug,
    write_plugin_file,
)

# ── Slug validation ─────────────────────────────────────────────────


class TestValidateSlug:
    def test_valid_slug(self):
        assert validate_slug("my_algo") == "my_algo"

    def test_valid_slug_with_numbers(self):
        assert validate_slug("algo42") == "algo42"

    def test_strips_whitespace(self):
        assert validate_slug("  my_algo  ") == "my_algo"

    def test_lowercases(self):
        assert validate_slug("MyAlgo") == "myalgo"

    def test_rejects_starts_with_number(self):
        with pytest.raises(ValueError, match="Invalid slug"):
            validate_slug("42algo")

    def test_rejects_starts_with_underscore(self):
        with pytest.raises(ValueError, match="Invalid slug"):
            validate_slug("_algo")

    def test_rejects_special_chars(self):
        with pytest.raises(ValueError, match="Invalid slug"):
            validate_slug("my-algo")

    def test_rejects_too_long(self):
        with pytest.raises(ValueError, match="Invalid slug"):
            validate_slug("a" * 65)

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="Invalid slug"):
            validate_slug("")


# ── Code syntax validation ──────────────────────────────────────────


class TestValidateCodeSyntax:
    def test_valid_code(self):
        validate_code_syntax("result = data * 2")

    def test_multiline_code(self):
        validate_code_syntax("x = 1\ny = 2\nresult = x + y")

    def test_syntax_error(self):
        with pytest.raises(SyntaxError):
            validate_code_syntax("def foo(")


# ── Node type generation ────────────────────────────────────────────


class TestMakeNodeType:
    def test_format(self):
        assert make_node_type(3, "my_snv") == "ualgo.3.my_snv"

    def test_different_project(self):
        assert make_node_type(42, "foo") == "ualgo.42.foo"


# ── Code generation ─────────────────────────────────────────────────


class _FakeAlgo:
    """Minimal duck-type for CustomAlgo used by codegen functions."""

    def __init__(
        self,
        *,
        project_id=1,
        slug="test_algo",
        name="Test Algo",
        description="A test",
        code="result = data",
        mode="simple",
        icon="\U0001f9ea",
    ):
        self.project_id = project_id
        self.slug = slug
        self.name = name
        self.description = description
        self.code = code
        self.mode = mode
        self.icon = icon
        self.node_type = make_node_type(project_id, slug)


class TestGeneratePluginSource:
    def test_generates_valid_python(self):
        algo = _FakeAlgo()
        source = generate_plugin_source(algo)
        # Must be parseable
        ast.parse(source)

    def test_contains_register_node(self):
        algo = _FakeAlgo()
        source = generate_plugin_source(algo)
        assert "@register_node" in source

    def test_contains_correct_node_type(self):
        algo = _FakeAlgo(project_id=7, slug="snv_var")
        source = generate_plugin_source(algo)
        assert 'node_type="ualgo.7.snv_var"' in source

    def test_contains_correct_category(self):
        algo = _FakeAlgo()
        source = generate_plugin_source(algo)
        assert 'category="custom_algo"' in source

    def test_contains_offload_to_pool_false(self):
        algo = _FakeAlgo()
        source = generate_plugin_source(algo)
        assert "offload_to_pool=False" in source

    def test_simple_mode_has_to_numpy_2d(self):
        algo = _FakeAlgo(mode="simple")
        source = generate_plugin_source(algo)
        assert "to_numpy_2d" in source

    def test_advanced_mode_uses_sherpa_dataset(self):
        algo = _FakeAlgo(mode="advanced")
        source = generate_plugin_source(algo)
        assert "input_ds" in source

    def test_user_code_embedded(self):
        algo = _FakeAlgo(code="result = data * 2 + 1")
        source = generate_plugin_source(algo)
        assert "result = data * 2 + 1" in source

    def test_multiline_user_code(self):
        algo = _FakeAlgo(code="mean = data.mean(axis=0)\nresult = data - mean")
        source = generate_plugin_source(algo)
        tree = ast.parse(source)
        assert tree  # Valid AST

    def test_special_chars_in_name(self):
        algo = _FakeAlgo(name='My "Special" Algo')
        source = generate_plugin_source(algo)
        ast.parse(source)  # Should not raise

    def test_user_code_with_braces(self):
        """User code containing braces must not break the generated f-strings."""
        algo = _FakeAlgo(code='result = {"a": 1, "b": data.shape}')
        source = generate_plugin_source(algo)
        ast.parse(source)  # Must be valid Python
        # The braces should be doubled in generate_python so they survive f-string interpolation
        assert "generate_python" in source

    def test_loader_mode_keeps_raw_module(self):
        code = """from spectra_sherpa.app.services.dag.node_base import Node, NodeMetadata, register_node

@register_node
class LoaderNode(Node):
    metadata = NodeMetadata(
        node_type="ualgo.1.test_algo",
        category="custom_algo",
        label="Loader",
        description="Load data",
        input_ports=[],
        output_ports=[],
        )
"""
        algo = _FakeAlgo(code=code, mode="loader")
        source = generate_plugin_source(algo)
        assert source == code.rstrip() + "\n"


class TestValidateLoaderPluginSource:
    def test_accepts_project_scoped_loader(self):
        code = """from spectra_sherpa.app.services.dag.node_base import Node, NodeMetadata, register_node

@register_node
class LoaderNode(Node):
    metadata = NodeMetadata(
        node_type="ualgo.7.uv_csv_load",
        category="custom_algo",
        label="UV CSV Load",
        description="Load UV CSV data",
        input_ports=[],
        output_ports=[],
    )
"""
        metadata = validate_loader_plugin_source(code, project_id=7, slug="uv_csv_load")
        assert metadata["node_type"] == "ualgo.7.uv_csv_load"
        assert metadata["label"] == "UV CSV Load"

    def test_rejects_wrong_category(self):
        code = """from spectra_sherpa.app.services.dag.node_base import Node, NodeMetadata, register_node

@register_node
class LoaderNode(Node):
    metadata = NodeMetadata(
        node_type="ualgo.7.uv_csv_load",
        category="data",
        label="UV CSV Load",
        description="Load UV CSV data",
        input_ports=[],
        output_ports=[],
    )
"""
        with pytest.raises(ValueError, match="category='custom_algo'"):
            validate_loader_plugin_source(code, project_id=7, slug="uv_csv_load")


# ── Atomic file write ───────────────────────────────────────────────


class TestWritePluginFile:
    def test_writes_file(self, tmp_path):
        algo = _FakeAlgo()
        with patch(
            "spectra_sherpa.app.services.custom_algo_codegen.get_plugin_dir",
            return_value=tmp_path,
        ):
            path = write_plugin_file(algo)
            assert path.exists()
            assert path.suffix == ".py"
            content = path.read_text()
            assert "@register_node" in content

    def test_no_tmp_file_left_on_success(self, tmp_path):
        algo = _FakeAlgo()
        with patch(
            "spectra_sherpa.app.services.custom_algo_codegen.get_plugin_dir",
            return_value=tmp_path,
        ):
            write_plugin_file(algo)
            tmp_files = list(tmp_path.glob("*.tmp"))
            assert len(tmp_files) == 0

    def test_replaces_existing_file(self, tmp_path):
        algo = _FakeAlgo()
        with patch(
            "spectra_sherpa.app.services.custom_algo_codegen.get_plugin_dir",
            return_value=tmp_path,
        ):
            path1 = write_plugin_file(algo)
            content1 = path1.read_text()

            algo.code = "result = data * 99"
            path2 = write_plugin_file(algo)
            content2 = path2.read_text()

            assert path1 == path2
            assert "data * 99" in content2
            assert content1 != content2


# ── Registry lifecycle ──────────────────────────────────────────────


class TestNodeRegistryLifecycle:
    def test_unregister_removes_type(self):
        from spectra_sherpa.app.services.dag.node_base import NodeRegistry

        registry = NodeRegistry()

        # Create a minimal node class
        from spectra_sherpa.app.services.dag.node_base import Node, NodeMetadata

        class TestNode(Node):
            metadata = NodeMetadata(
                node_type="ualgo.99.test",
                category="custom_algo",
                label="Test",
                description="test",
            )

            async def execute(self, *args, **kwargs):
                pass

        registry.register(TestNode)
        assert any(m.node_type == "ualgo.99.test" for m in registry.list_nodes())

        removed = registry.unregister("ualgo.99.test")
        assert removed is True
        assert not any(m.node_type == "ualgo.99.test" for m in registry.list_nodes())

    def test_unregister_returns_false_for_unknown(self):
        from spectra_sherpa.app.services.dag.node_base import NodeRegistry

        registry = NodeRegistry()
        assert registry.unregister("ualgo.99.nonexistent") is False

    def test_unregister_builtin_raises(self):
        from spectra_sherpa.app.services.dag.node_base import Node, NodeMetadata, NodeRegistry

        registry = NodeRegistry()

        class BuiltinNode(Node):
            metadata = NodeMetadata(
                node_type="builtin.test",
                category="preprocessing",
                label="Builtin",
                description="builtin test",
            )

            async def execute(self, *args, **kwargs):
                pass

        registry.register(BuiltinNode)
        registry.freeze_builtins()

        with pytest.raises(ValueError, match="Cannot unregister built-in"):
            registry.unregister("builtin.test")

    def test_offload_to_pool_default_true(self):
        from spectra_sherpa.app.services.dag.node_base import NodePolicy

        policy = NodePolicy()
        assert policy.offload_to_pool is True

    def test_offload_to_pool_can_be_false(self):
        from spectra_sherpa.app.services.dag.node_base import NodePolicy

        policy = NodePolicy(offload_to_pool=False)
        assert policy.offload_to_pool is False


# ── Ownership validation ────────────────────────────────────────────


class TestCustomCodePolicy:
    def test_mode_policy_allows_when_enabled_and_not_demo(self, monkeypatch):
        from spectra_sherpa.app.core.config import app_config
        from spectra_sherpa.app.core.mode_policy import allows_custom_code_execution

        monkeypatch.setattr(app_config, "custom_code_execution_enabled", True)
        monkeypatch.setattr(app_config, "site_profile", None)
        assert allows_custom_code_execution() is True

    def test_mode_policy_blocks_when_disabled(self, monkeypatch):
        from spectra_sherpa.app.core.config import app_config
        from spectra_sherpa.app.core.mode_policy import allows_custom_code_execution

        monkeypatch.setattr(app_config, "custom_code_execution_enabled", False)
        monkeypatch.setattr(app_config, "site_profile", None)
        assert allows_custom_code_execution() is False

    def test_mode_policy_blocks_demo(self, monkeypatch):
        from spectra_sherpa.app.core.config import app_config
        from spectra_sherpa.app.core.mode_policy import allows_custom_code_execution

        monkeypatch.setattr(app_config, "custom_code_execution_enabled", True)
        monkeypatch.setattr(app_config, "site_profile", "demo")
        assert allows_custom_code_execution() is False

    def test_custom_algo_route_guard_raises_when_blocked(self, monkeypatch):
        from fastapi import HTTPException

        from spectra_sherpa.app.api.v1.routes.custom_algos import _check_custom_code_allowed
        from spectra_sherpa.app.core.config import app_config

        monkeypatch.setattr(app_config, "custom_code_execution_enabled", False)
        monkeypatch.setattr(app_config, "site_profile", None)
        with pytest.raises(HTTPException) as exc_info:
            _check_custom_code_allowed()
        assert exc_info.value.status_code == 403


class TestUalgoNodeValidation:
    def test_requires_project_id_for_trial(self, monkeypatch):
        from fastapi import HTTPException

        from spectra_sherpa.app.api.v1.routes.workflows import _validate_ualgo_node_types
        from spectra_sherpa.app.core.config import app_config

        monkeypatch.setattr(app_config, "custom_code_execution_enabled", True)
        monkeypatch.setattr(app_config, "site_profile", None)

        with pytest.raises(HTTPException) as exc_info:
            _validate_ualgo_node_types(
                ["ualgo.3.my_algo"],
                project_id=None,
                require_project_id=True,
            )
        assert exc_info.value.status_code == 400

    def test_rejects_project_mismatch(self, monkeypatch):
        from fastapi import HTTPException

        from spectra_sherpa.app.api.v1.routes.workflows import _validate_ualgo_node_types
        from spectra_sherpa.app.core.config import app_config

        monkeypatch.setattr(app_config, "custom_code_execution_enabled", True)
        monkeypatch.setattr(app_config, "site_profile", None)

        with pytest.raises(HTTPException) as exc_info:
            _validate_ualgo_node_types(
                ["ualgo.3.my_algo"],
                project_id=4,
                require_project_id=True,
            )
        assert exc_info.value.status_code == 403

    def test_accepts_matching_project(self, monkeypatch):
        from spectra_sherpa.app.api.v1.routes.workflows import _validate_ualgo_node_types
        from spectra_sherpa.app.core.config import app_config

        monkeypatch.setattr(app_config, "custom_code_execution_enabled", True)
        monkeypatch.setattr(app_config, "site_profile", None)

        ualgo_types, resolved_project_id = _validate_ualgo_node_types(
            ["ualgo.3.my_algo", "model.pca"],
            project_id=3,
            require_project_id=True,
        )
        assert ualgo_types == ["ualgo.3.my_algo"]
        assert resolved_project_id == 3
