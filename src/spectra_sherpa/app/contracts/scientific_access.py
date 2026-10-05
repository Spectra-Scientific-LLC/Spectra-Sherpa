"""Commercial science hooks; standalone resource ownership remains unchanged."""

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.contracts.project_access import uses_managed_project_access


class ScientificAccessDenied(HTTPException):
    """Admission failed; callers must never fall back to partial outputs."""


# PCA consumes the already-authorized dataset and fits in memory; it does not
# add an ambient file/provider/model-read capability. New node admissions need
# their own qualified journey and refusal tests.
QUALIFIED_SCIENTIFIC_NODES = frozenset(
    {
        "data.file_load",
        # Exact experiment/stage/member manifest; the bounded reader rechecks
        # membership, immutable bytes and scientific collection identity.
        "data.collection_load",
        "data.filter_samples",
        "preprocess.scale",
        "preprocess.apply_fitted_scale",
        # Reviewed in-memory spectral transforms, diagnostics and presentation.
        # Synthetic HTTP journeys assert numerical/population results for each.
        "preprocess.normalize",
        # Frozen reference fits over already-authorized graph inputs; no IO.
        "preprocess.msc",
        "preprocess.smooth",
        "preprocess.derivative",
        "baseline.penalized_ls",
        "selection.variable_select",
        "preprocess.clip_range",
        "baseline.rubberband",
        "analysis.peak_finding",
        "model.kmeans",
        "stats.summary",
        "output.data_table",
        "output.plot",
        "diagnostics.outliers",
        "model.pca",
        # The held-out PLS journey partitions an admitted dataset and passes typed
        # fitted state by graph edge. Imported bindings still require their existing
        # canonical-artifact custody grant before any fitted-state read.
        "data.train_test_split",
        "model.fitted_pls",
        "model.apply_fitted_pls",
        "model.predict_regression",
        "model.fitted_pcr",
        "model.apply_fitted_pcr",
        "model.fitted_svr",
        "model.apply_fitted_svr",
        "model.fitted_linear_regression",
        "model.apply_fitted_linear_regression",
        # Pure evaluation of explicit predictions and held-out truth; no resource IO.
        "diagnostics.regression_evaluator",
        "diagnostics.labeled_regression_evaluator",
        # DB custody is checked before execution; local and worker artifact readers
        # receive only the validated model_id set for this exact run.
        "model.load_apply",
    }
)

# Node admission alone does not qualify every composition in the starter library.
# Each listed starter has an end-to-end managed journey with retained evidence.
QUALIFIED_SCIENTIFIC_TEMPLATES = frozenset({"msc_reference_correction", "pca", "pls_calibration", "peaks"})

ScienceOperation = Literal["read", "write", "execute"]
_provider: Callable[..., Awaitable[None]] | None = None
_creator: Callable[..., Awaitable[Any]] | None = None
_candidates: Callable[..., Awaitable[list[int]]] | None = None


def set_scientific_access_provider(provider=None, creator=None, candidates=None):
    global _provider, _creator, _candidates
    _provider, _creator, _candidates = provider, creator, candidates


async def require_scientific_access(
    session: AsyncSession,
    user_id: int,
    project_id: int | None,
    operation: ScienceOperation = "read",
    *,
    resource_owner_id: int | None = None,
) -> None:
    if uses_managed_project_access():
        if _provider is None or project_id is None:
            raise HTTPException(404, "Authorized project required")
        try:
            await _provider(session, user_id, project_id, operation)
        except HTTPException as exc:
            raise ScientificAccessDenied(exc.status_code, detail=exc.detail) from exc
    else:
        if resource_owner_id is not None and resource_owner_id != user_id:
            raise HTTPException(404, "Resource not found")
        if project_id is not None:
            from spectra_sherpa.app.api.deps import require_project

            await require_project(project_id, user_id, session)


async def create_managed_project(session, user_id, payload):
    if not uses_managed_project_access():
        return None
    if _creator is None:
        raise HTTPException(503, "Project creation is unavailable")
    return await _creator(session, user_id, payload)


async def scientific_project_ids(session, user_id) -> list[int] | None:
    if not uses_managed_project_access():
        return None
    if _candidates is None:
        return []
    return await _candidates(session, user_id)
