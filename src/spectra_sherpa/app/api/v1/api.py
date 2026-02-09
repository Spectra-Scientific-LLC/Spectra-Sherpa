from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, TypeAlias

from fastapi import APIRouter

from app.api.v1.routes import (
    analysis,
    api_keys,
    builder,
    calibrations,
    compute,
    config,
    datasets,
    doe,
    doe_config,
    egress,
    experiments,
    health,
    jobs,
    llm,
    llm_config,
    logs,
    nist,
    predict,
    process,
    workflow_export,
    workflow_organization,
    workflow_templates,
    workflows,
)

logger = logging.getLogger(__name__)

RouterInclude: TypeAlias = tuple[APIRouter, Mapping[str, Any]]


def get_server_routers() -> list[RouterInclude]:
    """Return server-only route modules for multi-user modes.

    This keeps Repo 1 router construction decoupled from server-only route
    modules. Repo 2 can inject its own server routes via build/create helpers.
    """
    from app.core.mode_policy import is_multi_user

    if not is_multi_user():
        return []

    try:
        from app.api.v1.routes import admin, auth
    except ImportError:
        # After repo split, Repo 1 may not carry these modules.
        logger.info("Server routes unavailable in this distribution; skipping auth/admin routers")
        return []

    return [
        (auth.router, {"prefix": "/auth", "tags": ["auth"]}),
        (admin.router, {"prefix": "/admin", "tags": ["admin"]}),
    ]


def build_api_router(
    *,
    extra_routers: list[RouterInclude] | None = None,
    include_server_routers: bool = True,
) -> APIRouter:
    """Build the v1 API router with all functional routes.

    Repo 2 (server) can call this with *extra_routers* to inject
    additional route modules without forking the function.
    """
    router = APIRouter()

    # --- Always registered (functional routes) ---
    router.include_router(health.router, tags=["health"])
    router.include_router(config.router, tags=["config"])
    router.include_router(logs.router, tags=["logs"])
    router.include_router(llm_config.router, tags=["llm-config"])
    router.include_router(experiments.router, tags=["experiments"])
    router.include_router(doe.router, tags=["doe"])
    router.include_router(doe_config.router, prefix="/doe-configs", tags=["doe-configs"])
    router.include_router(workflows.router, tags=["workflows"])
    router.include_router(
        workflow_organization.router, prefix="/workflows", tags=["workflow-organization"]
    )
    router.include_router(workflow_templates.router, tags=["workflow-templates"])
    router.include_router(workflow_export.router, tags=["workflow-export"])
    router.include_router(predict.router, tags=["predict"])
    router.include_router(builder.router, tags=["builder"])
    router.include_router(calibrations.router, tags=["calibrations"])
    router.include_router(compute.router, prefix="/compute", tags=["compute"])
    router.include_router(datasets.router, tags=["datasets"])
    router.include_router(nist.router, tags=["nist"])
    router.include_router(llm.router, tags=["llm"])
    router.include_router(jobs.router, tags=["jobs"])
    router.include_router(process.router, tags=["process"])
    router.include_router(analysis.router, tags=["analysis"])
    router.include_router(egress.router, tags=["egress"])

    # API key management (BYOK) — available in all modes
    router.include_router(api_keys.router, tags=["api-keys"])

    # Server-only routes are injected via helper to keep split seams explicit.
    if include_server_routers:
        for server_router, kwargs in get_server_routers():
            router.include_router(server_router, **dict(kwargs))

    # Extension point: Repo 2 passes extra routers here
    for extra, kwargs in (extra_routers or []):
        router.include_router(extra, **dict(kwargs))

    return router


# Backward-compat module-level singleton used by main.py and tests.
api_router = build_api_router()
