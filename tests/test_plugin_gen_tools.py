"""Tests for LLM-driven plugin generation tools (inspect_file, generate_loader_plugin, create_experiment_with_file)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_sherpa.app.services.tools.builtin.plugin_gen import (
    create_experiment_with_file,
    generate_loader_plugin,
    inspect_file,
)

# ═══════════════════════════════════════════════════════════════════
# inspect_file
# ═══════════════════════════════════════════════════════════════════


class TestInspectFile:
    def test_csv_basic(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        f.write_text("wavelength,sample1,sample2\n200,0.1,0.2\n201,0.3,0.4\n")
        result = inspect_file(str(f))
        assert result["file_name"] == "data.csv"
        assert result["total_lines"] == 3
        assert result["lines_returned"] == 3
        assert result["column_count"] == 3
        assert result["has_header"] is True
        assert result["detected_delimiter"] == ","

    def test_tsv_file(self, tmp_path: Path):
        f = tmp_path / "data.tsv"
        f.write_text("col1\tcol2\n1.0\t2.0\n3.0\t4.0\n")
        result = inspect_file(str(f))
        assert result["detected_delimiter"] == "\t"
        assert result["column_count"] == 2
        assert result["has_header"] is True

    def test_numeric_only_no_header(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        f.write_text("1.0,2.0,3.0\n4.0,5.0,6.0\n")
        result = inspect_file(str(f))
        assert result["has_header"] is False

    def test_respects_max_lines(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        lines = [f"{i},{i+1}" for i in range(200)]
        f.write_text("\n".join(lines) + "\n")
        result = inspect_file(str(f), max_lines=5)
        assert result["lines_returned"] == 5
        assert result["total_lines"] == 200

    def test_max_lines_clamped_to_100(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        lines = [f"{i},{i+1}" for i in range(200)]
        f.write_text("\n".join(lines) + "\n")
        result = inspect_file(str(f), max_lines=150)
        assert result["lines_returned"] == 100

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="File not found"):
            inspect_file("/nonexistent/path/data.csv")

    def test_rejects_path_outside_allowed_roots(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        outside_root = tmp_path / "outside"
        outside_root.mkdir()
        f = outside_root / "data.csv"
        f.write_text("a,b\n1,2\n")

        allowed_root = tmp_path / "allowed"
        allowed_root.mkdir()
        monkeypatch.setattr(
            "spectra_sherpa.app.services.tools.builtin.plugin_gen._allowed_import_roots",
            lambda: (allowed_root.resolve(),),
        )

        with pytest.raises(PermissionError, match="outside the allowed local import roots"):
            inspect_file(str(f))

    def test_unsupported_extension(self, tmp_path: Path):
        f = tmp_path / "data.pdf"
        f.write_text("fake")
        with pytest.raises(ValueError, match="Unsupported file type"):
            inspect_file(str(f))

    def test_binary_format_metadata_only(self, tmp_path: Path):
        f = tmp_path / "data.spc"
        f.write_bytes(b"\x00\x01\x02")
        result = inspect_file(str(f))
        assert result["file_type"] == ".spc"
        assert "note" in result
        assert "lines" not in result

    def test_size_limit_exists_in_source(self):
        """The 100 MB guard is present (integration test would need a real large file)."""
        from spectra_sherpa.app.services.tools.builtin import plugin_gen

        assert plugin_gen._MAX_IMPORT_FILE_SIZE == 100 * 1024 * 1024

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        f.write_text("")
        result = inspect_file(str(f))
        assert result["total_lines"] == 0
        assert result["lines_returned"] == 0
        assert result["detected_delimiter"] is None

    def test_file_size_bytes_returned(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        content = "a,b\n1,2\n"
        f.write_text(content)
        result = inspect_file(str(f))
        assert result["file_size_bytes"] == f.stat().st_size

    def test_xlsx_returns_metadata(self, tmp_path: Path):
        f = tmp_path / "data.xlsx"
        f.write_bytes(b"\x00" * 100)
        result = inspect_file(str(f))
        assert result["file_type"] == ".xlsx"
        assert "note" in result


# ═══════════════════════════════════════════════════════════════════
# generate_loader_plugin
# ═══════════════════════════════════════════════════════════════════


def _make_loader_code(project_id: int = 1, slug: str = "xyz") -> str:
    """Build a minimal valid loader plugin source matching project namespace."""
    return textwrap.dedent(
        f"""\
        from __future__ import annotations
        from typing import Any
        import numpy as np
        from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
        from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset
        from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
        from spectra_sherpa.app.services.dag.node_base import (
            Node, NodeMetadata, NodeParameter, PortMetadata, register_node,
        )

        @register_node
        class XyzLoaderNode(Node):
            metadata = NodeMetadata(
                node_type="ualgo.{project_id}.{slug}",
                category="custom_algo",
                label="XYZ Loader",
                description="Load XYZ data",
                parameters=[
                    NodeParameter(name="file_path", label="File", param_type="text", default="", required=True),
                ],
                input_ports=[],
                output_ports=[
                    PortMetadata(name="default", type_ref="spectrasherpa://types/SpectralDataset/1.0", label="Data"),
                ],
            )

            async def execute(self, *args: Any, **kwargs: Any) -> SherpaDataset:
                raise NotImplementedError
    """
    )


class _FakeProject:
    id = 1
    user_id = 10
    name = "Test Project"


class _FakeUser:
    id = 10


class _FakeAlgo:
    def __init__(self, **overrides: Any):
        defaults = dict(
            id=42,
            project_id=1,
            user_id=10,
            name="XYZ Loader",
            slug="xyz",
            description="Load XYZ data",
            code="",
            mode="loader",
            icon="\U0001f4e5",
            node_type="ualgo.1.xyz",
        )
        defaults.update(overrides)
        for k, v in defaults.items():
            setattr(self, k, v)


def _mock_session(existing_algo: Any = None) -> AsyncMock:
    """Build an AsyncMock session that returns *existing_algo* for scalar_one_or_none."""
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = existing_algo
    session.execute.return_value = result_mock
    return session


# Patch targets — imports are inside function bodies, so patch at source module.
_REQUIRE_PROJECT = "spectra_sherpa.app.api.deps.require_project"
_RELOAD_INTO_REGISTRY = "spectra_sherpa.app.services.custom_algo_codegen.reload_into_registry"


@pytest.mark.asyncio
class TestGenerateLoaderPlugin:
    async def test_create_new_algo(self):
        code = _make_loader_code(project_id=1, slug="xyz")
        session = _mock_session(existing_algo=None)
        user = _FakeUser()

        with (
            patch(_REQUIRE_PROJECT, new_callable=AsyncMock, return_value=_FakeProject()),
            patch(_RELOAD_INTO_REGISTRY) as mock_reload,
        ):
            result = await generate_loader_plugin(
                project_id=1,
                slug="xyz",
                code=code,
                session=session,
                user=user,
            )

        assert result["success"] is True
        assert result["node_type"] == "ualgo.1.xyz"
        assert result["created"] is True
        assert result["slug"] == "xyz"
        session.add.assert_called_once()
        session.commit.assert_called()
        mock_reload.assert_called_once()

    async def test_update_existing_algo(self):
        code = _make_loader_code(project_id=1, slug="xyz")
        existing = _FakeAlgo()
        session = _mock_session(existing_algo=existing)
        user = _FakeUser()

        with (
            patch(_REQUIRE_PROJECT, new_callable=AsyncMock, return_value=_FakeProject()),
            patch(_RELOAD_INTO_REGISTRY),
        ):
            result = await generate_loader_plugin(
                project_id=1,
                slug="xyz",
                code=code,
                session=session,
                user=user,
            )

        assert result["success"] is True
        assert result["created"] is False
        assert existing.code == code
        assert existing.mode == "loader"

    async def test_syntax_error_returns_failure(self):
        session = _mock_session()
        user = _FakeUser()

        with patch(_REQUIRE_PROJECT, new_callable=AsyncMock, return_value=_FakeProject()):
            result = await generate_loader_plugin(
                project_id=1,
                slug="xyz",
                code="def broken(",
                session=session,
                user=user,
            )

        assert result["success"] is False
        assert "error" in result

    async def test_wrong_node_type_returns_failure(self):
        """node_type doesn't match ualgo.<project_id>.<slug>."""
        code = _make_loader_code(project_id=99, slug="wrong")
        session = _mock_session()
        user = _FakeUser()

        with patch(_REQUIRE_PROJECT, new_callable=AsyncMock, return_value=_FakeProject()):
            result = await generate_loader_plugin(
                project_id=1,
                slug="xyz",
                code=code,
                session=session,
                user=user,
            )

        assert result["success"] is False
        assert "node_type" in result["error"].lower() or "ualgo" in result["error"]

    async def test_wrong_category_returns_failure(self):
        code = _make_loader_code(project_id=1, slug="xyz").replace('category="custom_algo"', 'category="data"')
        session = _mock_session()
        user = _FakeUser()

        with patch(_REQUIRE_PROJECT, new_callable=AsyncMock, return_value=_FakeProject()):
            result = await generate_loader_plugin(
                project_id=1,
                slug="xyz",
                code=code,
                session=session,
                user=user,
            )

        assert result["success"] is False
        assert "custom_algo" in result["error"]

    async def test_no_register_node_class_returns_failure(self):
        code = "import numpy as np\nx = 1\n"
        session = _mock_session()
        user = _FakeUser()

        with patch(_REQUIRE_PROJECT, new_callable=AsyncMock, return_value=_FakeProject()):
            result = await generate_loader_plugin(
                project_id=1,
                slug="xyz",
                code=code,
                session=session,
                user=user,
            )

        assert result["success"] is False
        assert "register_node" in result["error"].lower() or "No @register_node" in result["error"]

    async def test_invalid_slug_raises(self):
        code = _make_loader_code(project_id=1, slug="xyz")
        session = _mock_session()
        user = _FakeUser()

        with patch(_REQUIRE_PROJECT, new_callable=AsyncMock, return_value=_FakeProject()):
            with pytest.raises(ValueError, match="Invalid slug"):
                await generate_loader_plugin(
                    project_id=1,
                    slug="123bad",
                    code=code,
                    session=session,
                    user=user,
                )

    async def test_reload_failure_rolls_back_new_algo(self):
        code = _make_loader_code(project_id=1, slug="xyz")
        session = _mock_session(existing_algo=None)
        user = _FakeUser()

        with (
            patch(_REQUIRE_PROJECT, new_callable=AsyncMock, return_value=_FakeProject()),
            patch(_RELOAD_INTO_REGISTRY, side_effect=RuntimeError("import failed")),
        ):
            result = await generate_loader_plugin(
                project_id=1,
                slug="xyz",
                code=code,
                session=session,
                user=user,
            )

        assert result["success"] is False
        assert "Failed to load" in result["error"]
        session.delete.assert_called_once()

    async def test_reload_failure_restores_existing_algo(self):
        old_code = "# old code"
        existing = _FakeAlgo(code=old_code, name="Old Name", description="Old desc")
        code = _make_loader_code(project_id=1, slug="xyz")
        session = _mock_session(existing_algo=existing)
        user = _FakeUser()

        call_count = 0

        def fail_first_reload(algo: Any) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("import failed")

        with (
            patch(_REQUIRE_PROJECT, new_callable=AsyncMock, return_value=_FakeProject()),
            patch(_RELOAD_INTO_REGISTRY, side_effect=fail_first_reload),
        ):
            result = await generate_loader_plugin(
                project_id=1,
                slug="xyz",
                code=code,
                session=session,
                user=user,
            )

        assert result["success"] is False
        # Should have restored old values
        assert existing.code == old_code
        assert existing.name == "Old Name"

    async def test_project_not_found_raises(self):
        from fastapi import HTTPException

        code = _make_loader_code(project_id=1, slug="xyz")
        session = _mock_session()
        user = _FakeUser()

        with patch(
            _REQUIRE_PROJECT,
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Project not found"),
        ):
            with pytest.raises(HTTPException):
                await generate_loader_plugin(
                    project_id=999,
                    slug="xyz",
                    code=code,
                    session=session,
                    user=user,
                )

    async def test_label_extracted_from_metadata(self):
        code = _make_loader_code(project_id=1, slug="xyz")
        session = _mock_session(existing_algo=None)
        user = _FakeUser()

        with (
            patch(_REQUIRE_PROJECT, new_callable=AsyncMock, return_value=_FakeProject()),
            patch(_RELOAD_INTO_REGISTRY),
        ):
            result = await generate_loader_plugin(
                project_id=1,
                slug="xyz",
                code=code,
                session=session,
                user=user,
            )

        assert result["label"] == "XYZ Loader"


# ═══════════════════════════════════════════════════════════════════
# validate_loader_plugin_source — additional edge cases
# ═══════════════════════════════════════════════════════════════════


class TestValidateLoaderPluginSource:
    def test_rejects_wrong_node_type(self):
        from spectra_sherpa.app.services.custom_algo_codegen import (
            validate_loader_plugin_source,
        )

        code = _make_loader_code(project_id=5, slug="abc")
        with pytest.raises(ValueError, match="node_type must be"):
            validate_loader_plugin_source(code, project_id=1, slug="xyz")

    def test_rejects_no_class(self):
        from spectra_sherpa.app.services.custom_algo_codegen import (
            validate_loader_plugin_source,
        )

        code = "x = 1\n"
        with pytest.raises(ValueError, match="No @register_node"):
            validate_loader_plugin_source(code, project_id=1, slug="xyz")

    def test_rejects_syntax_error(self):
        from spectra_sherpa.app.services.custom_algo_codegen import (
            validate_loader_plugin_source,
        )

        with pytest.raises(SyntaxError):
            validate_loader_plugin_source("def oops(", project_id=1, slug="xyz")

    def test_accepts_matching_code(self):
        from spectra_sherpa.app.services.custom_algo_codegen import (
            validate_loader_plugin_source,
        )

        code = _make_loader_code(project_id=3, slug="my_loader")
        metadata = validate_loader_plugin_source(code, project_id=3, slug="my_loader")
        assert metadata["node_type"] == "ualgo.3.my_loader"
        assert metadata["category"] == "custom_algo"

    def test_returns_label_and_description(self):
        from spectra_sherpa.app.services.custom_algo_codegen import (
            validate_loader_plugin_source,
        )

        code = _make_loader_code(project_id=1, slug="xyz")
        metadata = validate_loader_plugin_source(code, project_id=1, slug="xyz")
        assert metadata["label"] == "XYZ Loader"
        assert metadata["description"] == "Load XYZ data"


# ═══════════════════════════════════════════════════════════════════
# create_experiment_with_file
# ═══════════════════════════════════════════════════════════════════

# Patch targets for experiment helpers (imported inside function body)
_CREATE_EXPERIMENT = "spectra_sherpa.app.services.experiments.create_experiment"
_ENSURE_DIRS = "spectra_sherpa.app.services.experiments.ensure_experiment_dirs"
_EXPERIMENT_DIR = "spectra_sherpa.app.services.experiments.experiment_dir"
_ADD_EXPERIMENT_FILE = "spectra_sherpa.app.services.experiments.add_experiment_file"
_RELATIVE_TO_DATA_DIR = "spectra_sherpa.app.services.experiments.relative_to_data_dir"


@pytest.mark.asyncio
class TestCreateExperimentWithFile:
    async def test_creates_experiment_and_copies_file(self, tmp_path: Path):
        src_file = tmp_path / "spectra.csv"
        src_file.write_text("wl,s1\n200,0.5\n")

        objects_dir = tmp_path / "objects"
        objects_dir.mkdir()

        fake_experiment = MagicMock()
        fake_experiment.id = 7
        fake_experiment.project_id = None

        session = AsyncMock()
        user = _FakeUser()

        with (
            patch(_CREATE_EXPERIMENT, new_callable=AsyncMock, return_value=fake_experiment) as mock_create,
            patch(_ENSURE_DIRS),
            patch(_EXPERIMENT_DIR, return_value=tmp_path),
            patch(_ADD_EXPERIMENT_FILE, new_callable=AsyncMock),
            patch(_RELATIVE_TO_DATA_DIR, return_value="objects/spectra.csv"),
        ):
            result = await create_experiment_with_file(
                name="UV Spectra",
                file_path=str(src_file),
                session=session,
                user=user,
            )

        assert result["success"] is True
        assert result["experiment_id"] == 7
        assert result["experiment_name"] == "UV Spectra"
        assert result["file_name"] == "spectra.csv"
        assert (objects_dir / "spectra.csv").exists()
        mock_create.assert_called_once()
        session.commit.assert_called_once()

    async def test_file_not_found_raises(self):
        session = AsyncMock()
        user = _FakeUser()

        with pytest.raises(FileNotFoundError, match="File not found"):
            await create_experiment_with_file(
                name="Missing",
                file_path="/nonexistent/file.csv",
                session=session,
                user=user,
            )

    async def test_rejects_path_outside_allowed_roots(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        src_file = tmp_path / "outside" / "spectra.csv"
        src_file.parent.mkdir()
        src_file.write_text("wl,s1\n200,0.5\n")

        allowed_root = tmp_path / "allowed"
        allowed_root.mkdir()
        monkeypatch.setattr(
            "spectra_sherpa.app.services.tools.builtin.plugin_gen._allowed_import_roots",
            lambda: (allowed_root.resolve(),),
        )

        session = AsyncMock()
        user = _FakeUser()

        with pytest.raises(PermissionError, match="outside the allowed local import roots"):
            await create_experiment_with_file(
                name="Blocked",
                file_path=str(src_file),
                session=session,
                user=user,
            )

    async def test_with_project_id_links_to_project(self, tmp_path: Path):
        src_file = tmp_path / "data.csv"
        src_file.write_text("a,b\n1,2\n")

        objects_dir = tmp_path / "objects"
        objects_dir.mkdir()

        fake_experiment = MagicMock()
        fake_experiment.id = 10
        fake_experiment.project_id = None

        session = AsyncMock()
        user = _FakeUser()

        with (
            patch("spectra_sherpa.app.api.deps.require_project", new_callable=AsyncMock),
            patch(_CREATE_EXPERIMENT, new_callable=AsyncMock, return_value=fake_experiment),
            patch(_ENSURE_DIRS),
            patch(_EXPERIMENT_DIR, return_value=tmp_path),
            patch(_ADD_EXPERIMENT_FILE, new_callable=AsyncMock),
            patch(_RELATIVE_TO_DATA_DIR, return_value="objects/data.csv"),
        ):
            result = await create_experiment_with_file(
                name="Linked Data",
                file_path=str(src_file),
                project_id=5,
                session=session,
                user=user,
            )

        assert result["success"] is True
        assert result["project_id"] == 5
        assert fake_experiment.project_id == 5

    async def test_description_passed_through(self, tmp_path: Path):
        src_file = tmp_path / "data.csv"
        src_file.write_text("a,b\n1,2\n")

        objects_dir = tmp_path / "objects"
        objects_dir.mkdir()

        fake_experiment = MagicMock()
        fake_experiment.id = 1
        fake_experiment.project_id = None

        session = AsyncMock()
        user = _FakeUser()

        with (
            patch(_CREATE_EXPERIMENT, new_callable=AsyncMock, return_value=fake_experiment) as mock_create,
            patch(_ENSURE_DIRS),
            patch(_EXPERIMENT_DIR, return_value=tmp_path),
            patch(_ADD_EXPERIMENT_FILE, new_callable=AsyncMock),
            patch(_RELATIVE_TO_DATA_DIR, return_value="objects/data.csv"),
        ):
            await create_experiment_with_file(
                name="Described",
                file_path=str(src_file),
                description="UV-Vis spectra from lab",
                session=session,
                user=user,
            )

        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs.get("description") == "UV-Vis spectra from lab"

    async def test_file_copied_to_objects_dir(self, tmp_path: Path):
        src_file = tmp_path / "input" / "spectra.csv"
        src_file.parent.mkdir()
        src_file.write_text("wl,intensity\n200,1.5\n")

        exp_base = tmp_path / "experiment"
        exp_base.mkdir()
        (exp_base / "objects").mkdir()

        fake_experiment = MagicMock()
        fake_experiment.id = 3
        fake_experiment.project_id = None

        session = AsyncMock()
        user = _FakeUser()

        with (
            patch(_CREATE_EXPERIMENT, new_callable=AsyncMock, return_value=fake_experiment),
            patch(_ENSURE_DIRS),
            patch(_EXPERIMENT_DIR, return_value=exp_base),
            patch(_ADD_EXPERIMENT_FILE, new_callable=AsyncMock),
            patch(_RELATIVE_TO_DATA_DIR, return_value="experiment/objects/spectra.csv"),
        ):
            result = await create_experiment_with_file(
                name="Copy Test",
                file_path=str(src_file),
                session=session,
                user=user,
            )

        dest = exp_base / "objects" / "spectra.csv"
        assert dest.exists()
        assert dest.read_text() == "wl,intensity\n200,1.5\n"
        assert result["file_size_bytes"] == src_file.stat().st_size
