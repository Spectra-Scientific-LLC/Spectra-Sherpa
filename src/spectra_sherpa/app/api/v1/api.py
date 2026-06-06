from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, TypeAlias

from fastapi import APIRouter

from spectra_sherpa.app.api.v1.routes import (
    api_keys,
    audit_events,
    builder,
    chat,
    compute,
    config,
    datasets,
    deploy,
    doe,
    doe_config,
    egress,
    execution_runs,
    experiments,
    health,
    jobs,
    logs,
    models,
    predict,
    project_scripts,
    projects,
    runs,
    synthesis,
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
    from spectra_sherpa.app.core.mode_policy import is_multi_user

    if not is_multi_user():
        return []

    routers: list[RouterInclude] = []
    try:
        from spectra_sherpa.app.api.v1.routes import admin
    except ImportError:
        logger.info("Server admin routes unavailable in this distribution; skipping admin router")
    else:
        routers.append((admin.router, {"prefix": "/admin", "tags": ["admin"]}))
    return routers


def build_api_router(
    *,
    extra_routers: list[RouterInclude] | None = None,
    include_server_routers: bool = True,
    include_actor_compat_route: bool = True,
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
    router.include_router(experiments.router, tags=["experiments"])
    router.include_router(doe.router, tags=["doe"])
    router.include_router(doe_config.router, prefix="/doe-configs", tags=["doe-configs"])
    router.include_router(workflows.router, tags=["workflows"])
    router.include_router(execution_runs.router, tags=["execution-runs"])
    router.include_router(runs.router, tags=["runs"])
    router.include_router(workflow_organization.router, prefix="/workflows", tags=["workflow-organization"])
    router.include_router(workflow_templates.router, tags=["workflow-templates"])
    router.include_router(workflow_export.router, tags=["workflow-export"])
    router.include_router(predict.router, tags=["predict"])
    router.include_router(builder.router, tags=["builder"])
    router.include_router(compute.router, prefix="/compute", tags=["compute"])
    router.include_router(datasets.router, tags=["datasets"])
    router.include_router(synthesis.router, tags=["synthesis"])
    router.include_router(jobs.router, tags=["jobs"])
    router.include_router(egress.router, tags=["egress"])
    router.include_router(deploy.router, tags=["deploy"])
    router.include_router(projects.router, tags=["projects"])
    router.include_router(project_scripts.router, tags=["project-scripts"])
    router.include_router(models.router, tags=["models"])
    # Phase 4 C2 — audit query API (gated on app_config.audit_enabled).
    router.include_router(audit_events.router, tags=["audit"])

    # BYO chat endpoint (OSS-only, capability-gated by CHAT_ASSISTANT)
    router.include_router(chat.router, tags=["chat"])

    # API key management (BYOK) — available in all modes
    router.include_router(api_keys.router, tags=["api-keys"])

    if include_actor_compat_route:
        # Actor compatibility route: available in OSS distributions so /auth/me
        # resolves for local and hybrid bootstrap without implying managed auth.
        from spectra_sherpa.app.api.v1.routes import auth_compat

        router.include_router(auth_compat.router, prefix="/auth", tags=["auth"])

    # Server/auth routes:
    # - non-local modes: include server-owned auth/admin when available
    if include_server_routers:
        server_routers = get_server_routers()
        for server_router, kwargs in server_routers:
            router.include_router(server_router, **dict(kwargs))

    # Extension point: Repo 2 passes extra routers here
    for extra, kwargs in extra_routers or []:
        router.include_router(extra, **dict(kwargs))

    return router


# Backward-compat module-level singleton used by main.py and tests.
api_router = build_api_router()
