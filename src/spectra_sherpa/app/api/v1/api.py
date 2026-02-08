from __future__ import annotations

from fastapi import APIRouter

from app.core.config import app_config
from app.api.v1.routes import (
    analysis,
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

api_router = APIRouter()

# --- Always registered (functional routes) ---
api_router.include_router(health.router, tags=["health"])
api_router.include_router(config.router, tags=["config"])
api_router.include_router(logs.router, tags=["logs"])
api_router.include_router(llm_config.router, tags=["llm-config"])
api_router.include_router(experiments.router, tags=["experiments"])
api_router.include_router(doe.router, tags=["doe"])
api_router.include_router(doe_config.router, prefix="/doe-configs", tags=["doe-configs"])
api_router.include_router(workflows.router, tags=["workflows"])
api_router.include_router(
    workflow_organization.router, prefix="/workflows", tags=["workflow-organization"]
)
api_router.include_router(workflow_templates.router, tags=["workflow-templates"])
api_router.include_router(workflow_export.router, tags=["workflow-export"])
api_router.include_router(predict.router, tags=["predict"])
api_router.include_router(builder.router, tags=["builder"])
api_router.include_router(calibrations.router, tags=["calibrations"])
api_router.include_router(compute.router, prefix="/compute", tags=["compute"])
api_router.include_router(datasets.router, tags=["datasets"])
api_router.include_router(nist.router, tags=["nist"])
api_router.include_router(llm.router, tags=["llm"])
api_router.include_router(jobs.router, tags=["jobs"])
api_router.include_router(process.router, tags=["process"])
api_router.include_router(analysis.router, tags=["analysis"])
api_router.include_router(egress.router, tags=["egress"])

# API key management (BYOK) — available in all modes
from app.api.v1.routes import api_keys

api_router.include_router(api_keys.router, tags=["api-keys"])

# Auth & Admin — multi-user modes only
if app_config.mode != "local":
    from app.api.v1.routes import admin, auth

    api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
    api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
