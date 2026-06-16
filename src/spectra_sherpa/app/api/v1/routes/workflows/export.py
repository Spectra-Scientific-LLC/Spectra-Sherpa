"""
Export endpoints: Python code, Jupyter notebook, download.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.api.v1.routes._http_utils import attachment_headers, safe_download_stem
from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.core.security import check_export_allowed
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.schemas.workflows import WorkflowPythonExportResponse
from spectra_sherpa.app.services.export_store import save_jupyter_workflow_export, save_python_workflow_export
from spectra_sherpa.app.services.notebook_export import generate_notebook
from spectra_sherpa.app.services.python_export import generate_python_code
from spectra_sherpa.app.services.workflow_export_context import build_workflow_export_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows")


@router.get("/{workflow_id}/export/python", response_model=WorkflowPythonExportResponse)
async def export_workflow_to_python(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowPythonExportResponse:
    """Export a workflow as executable Python code for the authenticated user."""
    if not await check_export_allowed(current_user):
        raise HTTPException(status_code=403, detail="Export not permitted for this user")

    user_id = current_user.id

    # Load workflow with nodes and edges
    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    try:
        export_context = await build_workflow_export_context(workflow, session)
        python_code = generate_python_code(workflow, export_context=export_context)
        saved_path = save_python_workflow_export(workflow.id, workflow.name, python_code)
        return {
            "workflow_id": workflow_id,
            "workflow_name": workflow.name,
            "python_code": python_code,
            "filename": f"{safe_download_stem(workflow.name, fallback='workflow', lowercase=True)}_workflow.py",
            "saved_path": str(saved_path.relative_to(settings.data_dir)),
        }
    except ValueError as e:
        # Unsupported node types or cycles — client-actionable error
        logger.info("Workflow %s Python export rejected: %s", workflow_id, e)
        raise HTTPException(
            status_code=422,
            detail="Workflow export could not be generated for this workflow.",
        ) from None
    except Exception:
        logger.exception("Unexpected error exporting workflow %s", workflow_id)
        raise HTTPException(status_code=500, detail="Failed to export workflow. Check server logs.")


@router.get("/{workflow_id}/export/notebook")
async def export_workflow_to_notebook(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Export a workflow as a Jupyter notebook (.ipynb) for the authenticated user."""
    if not await check_export_allowed(current_user):
        raise HTTPException(status_code=403, detail="Export not permitted for this user")

    user_id = current_user.id

    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    try:
        export_context = await build_workflow_export_context(workflow, session)
        notebook = generate_notebook(workflow, export_context=export_context)
        saved_path = save_jupyter_workflow_export(workflow.id, workflow.name, notebook)
        safe_name = safe_download_stem(workflow.name, fallback="workflow", lowercase=True)
        return {
            "workflow_id": workflow_id,
            "workflow_name": workflow.name,
            "notebook": notebook,
            "filename": f"{safe_name}_workflow.ipynb",
            "saved_path": str(saved_path.relative_to(settings.data_dir)),
        }
    except ValueError as e:
        logger.info("Workflow %s notebook export rejected: %s", workflow_id, e)
        raise HTTPException(
            status_code=422,
            detail="Workflow notebook export could not be generated for this workflow.",
        ) from None
    except Exception:
        logger.exception("Unexpected error exporting notebook for workflow %s", workflow_id)
        raise HTTPException(status_code=500, detail="Failed to export notebook. Check server logs.")


@router.get("/{workflow_id}/export/download")
async def download_workflow_export(
    workflow_id: int,
    format: str = Query("python", description="Export format: python, notebook, or zip"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Download workflow export as a file attachment.

    Supports three formats:
    - ``python``: Downloads the .py script directly
    - ``notebook``: Downloads the .ipynb notebook directly
    - ``zip``: Downloads a zip bundle containing the script, notebook,
      a requirements.txt, and a data/ directory stub

    This endpoint returns proper Content-Disposition headers for
    browser-initiated file downloads (enterprise/cloud mode).
    """
    import json
    import zipfile
    from io import BytesIO

    from starlette.responses import StreamingResponse

    if not await check_export_allowed(current_user):
        raise HTTPException(status_code=403, detail="Export not permitted for this user")

    user_id = current_user.id

    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    safe_name = safe_download_stem(workflow.name, fallback="workflow", lowercase=True)

    try:
        export_context = await build_workflow_export_context(workflow, session)
        python_code = generate_python_code(workflow, export_context=export_context)
    except ValueError as e:
        logger.info("Workflow %s download export rejected: %s", workflow_id, e)
        raise HTTPException(
            status_code=422,
            detail="Workflow export could not be generated for this workflow.",
        ) from None

    if format == "python":
        filename = f"{safe_name}_workflow.py"
        return StreamingResponse(
            BytesIO(python_code.encode("utf-8")),
            media_type="text/x-python",
            headers=attachment_headers(filename, fallback="workflow", lowercase=True),
        )

    elif format == "notebook":
        try:
            notebook = generate_notebook(workflow, export_context=export_context)
        except Exception:
            logger.exception("Failed to generate notebook for workflow %s", workflow_id)
            raise HTTPException(status_code=500, detail="Failed to generate notebook")

        filename = f"{safe_name}_workflow.ipynb"
        nb_bytes = json.dumps(notebook, indent=2).encode("utf-8")
        return StreamingResponse(
            BytesIO(nb_bytes),
            media_type="application/x-ipynb+json",
            headers=attachment_headers(filename, fallback="workflow", lowercase=True),
        )

    elif format == "zip":
        buf = BytesIO()
        try:
            notebook = generate_notebook(workflow, export_context=export_context)
        except Exception:
            notebook = None

        prepared_manifest = {
            "sources": [
                {
                    "node_id": spec.node_id,
                    "source": spec.source,
                    "loader_mode": spec.loader_mode,
                    "bundle_files": [bundle.bundle_relative_path for bundle in spec.bundle_files],
                    "source_files": [bundle.source_relative_path for bundle in spec.bundle_files],
                    "overrides": spec.overrides.to_sidecar_dict(),
                }
                for spec in export_context.source_specs.values()
            ]
        }
        workflow_manifest = {
            "workflow_id": workflow.id,
            "workflow_name": workflow.name,
            "description": workflow.description,
            "nodes": [
                {
                    "node_id": node.node_id,
                    "node_type": node.node_type,
                    "parameters": node.parameters,
                }
                for node in workflow.nodes
            ],
            "edges": [
                {
                    "from_node_id": edge.from_node_id,
                    "to_node_id": edge.to_node_id,
                    "from_output": edge.from_output,
                    "to_input": edge.to_input,
                }
                for edge in workflow.edges
            ],
        }

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # Python script
            zf.writestr(f"{safe_name}/{safe_name}_workflow.py", python_code)

            # Notebook (if generated)
            if notebook is not None:
                zf.writestr(
                    f"{safe_name}/{safe_name}_workflow.ipynb",
                    json.dumps(notebook, indent=2),
                )

            # Requirements file
            requirements = (
                "# Requirements for exported workflow\n"
                "spectra-sherpa\n"
                "numpy\n"
                "scipy\n"
                "scikit-learn\n"
                "plotly\n"
            )
            zf.writestr(f"{safe_name}/requirements.txt", requirements)

            for bundle in export_context.iter_bundle_files():
                if bundle.absolute_path.exists():
                    zf.write(bundle.absolute_path, f"{safe_name}/data/{bundle.bundle_relative_path}")

            zf.writestr(f"{safe_name}/prepared_data_manifest.json", json.dumps(prepared_manifest, indent=2))
            zf.writestr(f"{safe_name}/workflow_manifest.json", json.dumps(workflow_manifest, indent=2))

            # Data directory README
            data_readme = (
                "# Data Directory\n\n"
                "This folder contains the source files used by the exported workflow.\n\n"
                "The generated Python script and notebook look here by default, or you can\n"
                "set the `SHERPA_DATA_DIR` environment variable to point somewhere else.\n\n"
                "Supported formats:\n"
                "- CSV (.csv) — rows=samples, columns=wavelengths\n"
                "- SpectroChemPy (.scp)\n"
                "- JCAMP-DX (.dx, .jdx)\n"
                "- SPC (.spc)\n"
                "- MATLAB (.mat)\n"
            )
            zf.writestr(f"{safe_name}/data/README.md", data_readme)

        buf.seek(0)
        filename = f"{safe_name}_export.zip"
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers=attachment_headers(filename, fallback="workflow", lowercase=True),
        )

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format: {format}. Use 'python', 'notebook', or 'zip'.",
        )
