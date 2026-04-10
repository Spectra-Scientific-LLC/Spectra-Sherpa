"""
Workflow API endpoints for DAG-based analysis pipelines.

This package splits the workflow routes into focused sub-modules.
The composed ``router`` is the only public export needed by the app.
"""

from __future__ import annotations

from fastapi import APIRouter

from spectra_sherpa.app.api.v1.routes.workflows.catalog import router as _catalog_router
from spectra_sherpa.app.api.v1.routes.workflows.crud import router as _crud_router
from spectra_sherpa.app.api.v1.routes.workflows.execute import router as _execute_router
from spectra_sherpa.app.api.v1.routes.workflows.export import router as _export_router
from spectra_sherpa.app.api.v1.routes.workflows.versions import router as _versions_router

router = APIRouter()

# Sub-routers with fixed-path routes must be included before sub-routers
# that define /{workflow_id} catch-all patterns, so FastAPI matches them first.
router.include_router(_catalog_router)
router.include_router(_execute_router)
router.include_router(_crud_router)
router.include_router(_export_router)
router.include_router(_versions_router)

# Re-export endpoint functions for backward compatibility with test imports
from spectra_sherpa.app.api.v1.routes.workflows.catalog import get_node_library  # noqa: F401
from spectra_sherpa.app.api.v1.routes.workflows.crud import (  # noqa: F401
    create_workflow,
    list_workflows,
    update_workflow,
)
from spectra_sherpa.app.api.v1.routes.workflows.versions import restore_workflow_version  # noqa: F401
