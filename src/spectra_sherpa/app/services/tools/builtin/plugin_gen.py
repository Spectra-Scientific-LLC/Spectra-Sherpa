"""
Built-in tools for LLM-driven plugin generation.

Three tools that enable the LLM chat to:
1. Inspect data files to understand their format
2. Generate and hot-load data loader plugin nodes
3. Create experiments in "My Dataset"
"""

from __future__ import annotations

import csv
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import select

from spectra_sherpa.app.services.tools.registry import register_tool
from spectra_sherpa.app.services.tools.schemas import ToolCategory, ToolScope

logger = logging.getLogger(__name__)

# Allowed data file extensions for inspect_file
_DATA_EXTENSIONS = {
    ".csv",
    ".tsv",
    ".txt",
    ".dat",
    ".tab",
    ".xlsx",
    ".xls",
    ".spc",
    ".jdx",
    ".dx",
    ".json",
}

_MAX_IMPORT_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


def _allowed_import_roots() -> tuple[Path, ...]:
    """Return the local roots LLM data import tools may access."""
    from spectra_sherpa.app.core.config import settings

    roots = {
        Path.home().resolve(),
        Path(tempfile.gettempdir()).resolve(),
        Path(settings.data_dir).resolve(),
    }
    return tuple(sorted(roots))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_import_path(
    file_path: str,
    *,
    require_supported_extension: bool = True,
    enforce_size_limit: bool = True,
) -> Path:
    """Resolve a local import file path and enforce the import path policy."""
    path = Path(file_path).expanduser().resolve()

    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    if not any(_is_relative_to(path, root) for root in _allowed_import_roots()):
        raise PermissionError("File path is outside the allowed local import roots")

    suffix = path.suffix.lower()
    if require_supported_extension and suffix not in _DATA_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {suffix}. " f"Supported: {', '.join(sorted(_DATA_EXTENSIONS))}")

    if enforce_size_limit:
        file_size = path.stat().st_size
        if file_size > _MAX_IMPORT_FILE_SIZE:
            raise ValueError(f"File too large ({file_size / 1e6:.1f} MB). Max 100 MB.")

    return path


# ---------------------------------------------------------------------------
# Tool 1: inspect_file
# ---------------------------------------------------------------------------


@register_tool(
    "inspect_file",
    "Read the first N lines of a data file to understand its format, "
    "structure, delimiter, and column count. Use this before generating "
    "a loader plugin to understand the file layout.",
    category=ToolCategory.data,
    scope=ToolScope.internal,
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the data file to inspect",
            },
            "max_lines": {
                "type": "integer",
                "description": "Maximum number of lines to read (default 30)",
            },
        },
        "required": ["file_path"],
    },
)
def inspect_file(file_path: str, max_lines: int = 30) -> dict[str, Any]:
    """Read first N lines of a data file and detect its structure."""
    path = _resolve_import_path(file_path)

    file_size = path.stat().st_size
    suffix = path.suffix.lower()

    # Binary formats — return metadata only
    if suffix in {".spc", ".xlsx", ".xls"}:
        return {
            "file_path": str(path),
            "file_name": path.name,
            "file_size_bytes": file_size,
            "file_type": suffix,
            "note": f"Binary format ({suffix}). Use appropriate library to parse.",
        }

    # Text-based files — read first N lines
    max_lines = min(max_lines, 100)
    lines: list[str] = []
    total_lines = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            total_lines += 1
            if len(lines) < max_lines:
                lines.append(line.rstrip("\n\r"))

    # Detect delimiter and column count from first few data lines
    delimiter = None
    column_count = None
    has_header = False
    if lines:
        sample = "\n".join(lines[:5])
        try:
            dialect = csv.Sniffer().sniff(sample)
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = None

        if delimiter:
            counts = [len(line.split(delimiter)) for line in lines[:5] if line.strip()]
            if counts:
                column_count = max(set(counts), key=counts.count)

            # Simple header detection: first row has non-numeric values
            try:
                first_row = lines[0].split(delimiter)
                all_numeric = all(_is_numeric(v.strip()) for v in first_row if v.strip())
                has_header = not all_numeric
            except (IndexError, ValueError):
                pass

    return {
        "file_path": str(path),
        "file_name": path.name,
        "file_size_bytes": file_size,
        "total_lines": total_lines,
        "lines_returned": len(lines),
        "lines": lines,
        "detected_delimiter": delimiter,
        "column_count": column_count,
        "has_header": has_header,
    }


def _is_numeric(s: str) -> bool:
    """Check if a string looks numeric."""
    try:
        float(s)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Tool 2: generate_loader_plugin
# ---------------------------------------------------------------------------


@register_tool(
    "generate_loader_plugin",
    "Generate, validate, and persist a project-scoped loader node from Python source code. "
    "The code must define a @register_node class with "
    "node_type matching the current project slug namespace and category='custom_algo'. "
    "Creates or updates a project-managed custom node and reloads it into the registry.",
    category=ToolCategory.data,
    scope=ToolScope.internal,
    requires_session=True,
    requires_user=True,
    parameters={
        "type": "object",
        "properties": {
            "project_id": {
                "type": "integer",
                "description": "Current project id from context; required for project-scoped custom nodes",
            },
            "slug": {
                "type": "string",
                "description": (
                    "Unique identifier for the custom node (lowercase, underscores, "
                    "e.g. 'uv_csv_load', 'raman_spc_load')"
                ),
            },
            "code": {
                "type": "string",
                "description": "Complete Python source code for the plugin module",
            },
        },
        "required": ["project_id", "slug", "code"],
    },
)
async def generate_loader_plugin(
    project_id: int,
    slug: str,
    code: str,
    session: Any = None,
    user: Any = None,
) -> dict[str, Any]:
    """Validate, persist, and hot-load a project-scoped loader custom node."""
    from spectra_sherpa.app.core.mode_policy import allows_custom_code_execution

    if not allows_custom_code_execution():
        return {"success": False, "error": "Custom code execution is disabled in this deployment"}

    from spectra_sherpa.app.api.deps import require_project
    from spectra_sherpa.app.models.custom_algo import CustomAlgo
    from spectra_sherpa.app.services.custom_algo_codegen import (
        make_node_type,
        reload_into_registry,
        validate_code_syntax,
        validate_loader_plugin_source,
        validate_slug,
    )

    await require_project(project_id, user.id, session)
    slug = validate_slug(slug)
    node_type = make_node_type(project_id, slug)

    try:
        validate_code_syntax(code)
        metadata = validate_loader_plugin_source(code, project_id=project_id, slug=slug)
    except (SyntaxError, ValueError) as e:
        return {
            "success": False,
            "error": str(e),
        }

    label = metadata.get("label") or slug.replace("_", " ").title()
    description = metadata.get("description") or f"Load data from {slug} files"

    existing = await session.execute(
        select(CustomAlgo).where(CustomAlgo.project_id == project_id, CustomAlgo.slug == slug)
    )
    algo = existing.scalar_one_or_none()
    created = algo is None

    if created:
        algo = CustomAlgo(
            project_id=project_id,
            user_id=user.id,
            name=label,
            slug=slug,
            description=description,
            code=code,
            mode="loader",
            icon="\U0001f4e5",
            node_type=node_type,
        )
        session.add(algo)
        await session.commit()
        await session.refresh(algo)
        try:
            reload_into_registry(algo)
        except Exception as exc:
            await session.delete(algo)
            await session.commit()
            return {"success": False, "error": f"Failed to load project custom node: {exc}"}
    else:
        old_values = {
            "name": algo.name,
            "description": algo.description,
            "code": algo.code,
            "mode": algo.mode,
            "icon": algo.icon,
        }
        algo.name = label
        algo.description = description
        algo.code = code
        algo.mode = "loader"
        algo.icon = "\U0001f4e5"
        await session.commit()
        await session.refresh(algo)
        try:
            reload_into_registry(algo)
        except Exception as exc:
            for key, value in old_values.items():
                setattr(algo, key, value)
            await session.commit()
            await session.refresh(algo)
            try:
                reload_into_registry(algo)
            except Exception:
                logger.exception("Failed to restore previous loader node for %s", node_type)
            return {"success": False, "error": f"Failed to update project custom node: {exc}"}

    logger.info("LLM project loader saved: %s → %s", slug, node_type)
    return {
        "success": True,
        "project_id": project_id,
        "algo_id": algo.id,
        "node_type": algo.node_type,
        "label": algo.name,
        "slug": slug,
        "created": created,
    }


# ---------------------------------------------------------------------------
# Tool 3: create_experiment_with_file
# ---------------------------------------------------------------------------


@register_tool(
    "create_experiment_with_file",
    "Create a new Experiment (dataset entry) in My Dataset and link "
    "an existing data file to it. The file is copied into the experiment "
    "directory so the original is preserved.",
    category=ToolCategory.data,
    scope=ToolScope.internal,
    requires_session=True,
    requires_user=True,
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name for the dataset (e.g. 'UV Spectra')",
            },
            "file_path": {
                "type": "string",
                "description": "Absolute path to the data file to add",
            },
            "description": {
                "type": "string",
                "description": "Optional description for the dataset",
            },
            "project_id": {
                "type": "integer",
                "description": "Optional current project id to link the dataset into",
            },
        },
        "required": ["name", "file_path"],
    },
)
async def create_experiment_with_file(
    name: str,
    file_path: str,
    description: str | None = None,
    project_id: int | None = None,
    session: Any = None,
    user: Any = None,
) -> dict[str, Any]:
    """Create an Experiment and copy the data file into it."""
    from spectra_sherpa.app.api.deps import require_project
    from spectra_sherpa.app.services.experiments import (
        add_experiment_file,
        create_experiment,
        ensure_experiment_dirs,
        experiment_dir,
    )

    path = _resolve_import_path(file_path)
    if project_id is not None:
        await require_project(project_id, user.id, session)

    file_size = path.stat().st_size
    file_type = path.suffix.lower().lstrip(".")

    # Create the experiment
    experiment = await create_experiment(
        session=session,
        user_id=user.id,
        name=name,
        description=description,
        metadata={"source": "llm_plugin_gen", "original_path": str(path)},
    )
    if project_id is not None:
        experiment.project_id = project_id

    # Copy file into experiment directory
    ensure_experiment_dirs(experiment.id)
    dest_dir = experiment_dir(experiment.id) / "objects"
    dest_path = dest_dir / path.name
    shutil.copy2(str(path), str(dest_path))

    # Create the ExperimentFile record
    from spectra_sherpa.app.services.experiments import relative_to_data_dir

    rel_path = str(relative_to_data_dir(dest_path))
    await add_experiment_file(
        session=session,
        experiment_id=experiment.id,
        stage="raw",
        file_path=rel_path,
        file_size_bytes=file_size,
        file_type=file_type,
    )

    await session.commit()

    logger.info(
        "LLM created experiment '%s' (id=%d) with file %s",
        name,
        experiment.id,
        path.name,
    )

    return {
        "success": True,
        "experiment_id": experiment.id,
        "experiment_name": name,
        "project_id": experiment.project_id,
        "file_name": path.name,
        "file_size_bytes": file_size,
    }
