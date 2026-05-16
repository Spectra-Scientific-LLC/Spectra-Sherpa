"""Regression tests for audit follow-up Items 1, 2, 4 (PR #101)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Item 1: WS workflow-channel subscription must be ownership-gated
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, val):
        self._v = val

    def scalar_one_or_none(self):
        return self._v


class _Session:
    def __init__(self, val):
        self._v = val

    async def execute(self, *_a, **_k):
        return _Result(self._v)


class _SessionCtx:
    def __init__(self, val):
        self._v = val

    async def __aenter__(self):
        return _Session(self._v)

    async def __aexit__(self, *_a):
        return False


@pytest.fixture()
def patch_wf_session(monkeypatch):
    def _set(owner_id, *, admin=False):
        import spectra_sherpa.app.contracts.auth_resolver as ar
        import spectra_sherpa.app.db.session as dbs

        monkeypatch.setattr(dbs, "async_session", lambda: _SessionCtx(owner_id))

        async def _is_admin(_u):
            return admin

        monkeypatch.setattr(ar, "is_admin_user", _is_admin)

    return _set


async def test_workflow_channel_allows_owner(patch_wf_session):
    from spectra_sherpa.app.main import _authorize_workflow_channel

    patch_wf_session(owner_id=7)
    assert await _authorize_workflow_channel("workflow:42", SimpleNamespace(id=7)) == "workflow:42"


async def test_workflow_channel_denies_non_owner(patch_wf_session):
    from spectra_sherpa.app.main import _authorize_workflow_channel

    patch_wf_session(owner_id=7, admin=False)
    # Attacker (id=9) guessing another user's workflow id → denied.
    assert await _authorize_workflow_channel("workflow:42", SimpleNamespace(id=9)) is None


async def test_workflow_channel_allows_admin(patch_wf_session):
    from spectra_sherpa.app.main import _authorize_workflow_channel

    patch_wf_session(owner_id=7, admin=True)
    assert await _authorize_workflow_channel("workflow:42", SimpleNamespace(id=9)) == "workflow:42"


async def test_workflow_channel_unknown_id_denied_without_confirming(patch_wf_session):
    from spectra_sherpa.app.main import _authorize_workflow_channel

    patch_wf_session(owner_id=None)  # no such workflow
    assert await _authorize_workflow_channel("workflow:999999", SimpleNamespace(id=7)) is None


async def test_workflow_channel_rejects_unauthenticated_and_garbage(patch_wf_session):
    from spectra_sherpa.app.main import _authorize_workflow_channel

    patch_wf_session(owner_id=7)
    assert await _authorize_workflow_channel("workflow:42", None) is None
    assert await _authorize_workflow_channel("workflow:not-an-int", SimpleNamespace(id=7)) is None


# ---------------------------------------------------------------------------
# Item 2: demo execution-quota contract hook + enforcement helper
# ---------------------------------------------------------------------------


@pytest.fixture()
def reset_quota_provider():
    import spectra_sherpa.app.contracts.demo_policy as dp

    saved = dp._demo_execution_quota_provider
    yield dp
    dp._demo_execution_quota_provider = saved


def test_quota_unlimited_when_no_provider(reset_quota_provider):
    dp = reset_quota_provider
    dp._demo_execution_quota_provider = None
    assert dp.consume_demo_execution_quota(1) == (True, -1)


def test_quota_uses_installed_provider(reset_quota_provider):
    dp = reset_quota_provider
    calls = []

    def _provider(uid):
        calls.append(uid)
        return (False, 0)

    dp.set_demo_execution_quota_provider(_provider)
    assert dp.consume_demo_execution_quota(7) == (False, 0)
    assert calls == [7]


def test_enforce_helper_raises_429_when_exhausted(reset_quota_provider):
    dp = reset_quota_provider
    dp.set_demo_execution_quota_provider(lambda _uid: (False, 0))
    from spectra_sherpa.app.api.deps import enforce_demo_execution_quota

    with pytest.raises(HTTPException) as ei:
        enforce_demo_execution_quota(7)
    assert ei.value.status_code == 429
    assert "demo execution limit" in ei.value.detail.lower()


def test_enforce_helper_noop_when_allowed(reset_quota_provider):
    dp = reset_quota_provider
    dp.set_demo_execution_quota_provider(lambda _uid: (True, 4))
    from spectra_sherpa.app.api.deps import enforce_demo_execution_quota

    enforce_demo_execution_quota(7)  # must not raise

    dp._demo_execution_quota_provider = None
    enforce_demo_execution_quota(7)  # unlimited path, must not raise


# ---------------------------------------------------------------------------
# Item 4: hybrid credential-free fallback must not grant on missing host
# ---------------------------------------------------------------------------


@pytest.fixture()
def hybrid_mode(monkeypatch):
    import spectra_sherpa.app.api.deps as deps

    monkeypatch.setattr(deps, "is_local", lambda: False)
    monkeypatch.setattr(deps, "is_hybrid", lambda: True)
    monkeypatch.setattr(deps, "is_loopback", lambda h: h in ("127.0.0.1", "::1", "localhost"))
    return deps


async def test_hybrid_missing_host_denies_implicit_local(hybrid_mode, test_session):
    deps = hybrid_mode
    # No credentials, host unknown (the /config bug) → must NOT grant.
    user = await deps._resolve_user(test_session, client_host=None)
    assert user is None


async def test_hybrid_nonloopback_host_denies(hybrid_mode, test_session):
    deps = hybrid_mode
    user = await deps._resolve_user(test_session, client_host="203.0.113.5")
    assert user is None


async def test_hybrid_loopback_host_still_grants(hybrid_mode, test_session):
    deps = hybrid_mode
    user = await deps._resolve_user(test_session, client_host="127.0.0.1")
    assert user is not None  # implicit local identity for a real loopback caller


# ---------------------------------------------------------------------------
# Review follow-up (Item 2): batch predict must not burn a demo slot when
# there is no work to run (bad folder / empty discovery).
# ---------------------------------------------------------------------------


@pytest.fixture()
def batch_predict_env(monkeypatch, reset_quota_provider):
    import spectra_sherpa.app.services.batch_predict as bp

    calls: list = []
    reset_quota_provider.set_demo_execution_quota_provider(lambda uid: (calls.append(uid) or (True, 3)))

    async def _load_wf(_s, _wid, _uid):
        return SimpleNamespace(nodes=[], versions=[])

    monkeypatch.setattr(bp, "load_workflow_with_graph", _load_wf)

    async def _run_batch(*_a, **_k):  # pragma: no cover - must not be reached
        raise AssertionError("run_batch_prediction reached unexpectedly")

    monkeypatch.setattr(bp, "run_batch_prediction", _run_batch)
    return bp, calls


async def test_batch_predict_no_files_does_not_consume_quota(batch_predict_env, monkeypatch):
    bp, calls = batch_predict_env
    monkeypatch.setattr(bp, "discover_files", lambda *_a, **_k: [])  # bad folder / no matches

    from spectra_sherpa.app.api.v1.routes import deploy
    from spectra_sherpa.app.schemas.deploy import BatchPredictRequest

    with pytest.raises(HTTPException) as ei:
        await deploy.batch_predict(
            workflow_id=1,
            payload=BatchPredictRequest(folder_path="/nope", file_pattern="*.json"),
            session=object(),
            current_user=SimpleNamespace(id=7),
        )

    assert ei.value.status_code == 422
    assert calls == []  # quota NOT consumed for a no-op request


async def test_batch_predict_enforces_quota_after_discovery(batch_predict_env, monkeypatch):
    import spectra_sherpa.app.contracts.demo_policy as dp

    bp, _calls = batch_predict_env
    monkeypatch.setattr(bp, "discover_files", lambda *_a, **_k: ["file-a.json"])  # real work present
    dp.set_demo_execution_quota_provider(lambda _uid: (False, 0))  # exhausted

    from spectra_sherpa.app.api.v1.routes import deploy
    from spectra_sherpa.app.schemas.deploy import BatchPredictRequest

    with pytest.raises(HTTPException) as ei:
        await deploy.batch_predict(
            workflow_id=1,
            payload=BatchPredictRequest(folder_path="/data", file_pattern="*.json"),
            session=object(),
            current_user=SimpleNamespace(id=7),
        )
    assert ei.value.status_code == 429
