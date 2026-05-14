"""Phase 4 C2 — tests for ``GET /api/v1/audit/events``.

Pins:
  * 403 when audit is disabled at the deployment level.
  * Strict tenant scoping (other-tenant rows must not leak).
  * Each filter actually narrows results (no missed AND-clause).
  * Cursor-based pagination is correct AND idempotent (paging through
    a stable dataset returns every row exactly once).
  * Reading the audit log does NOT itself produce an audit row
    (per design §6 — would create a feedback loop).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.models.audit_event import AuditEvent
from spectra_sherpa.app.services.audit import install_audit_flush_listener
from spectra_sherpa.app.services.audit.boot import _reset_process_boot_id_for_tests

#: Default actor id for seeded events. Matches the ``test_user``
#: fixture (first row in the in-memory user table → id=1) so the
#: ``auth_client`` fixture sees the seeded events under the route's
#: actor-scope rule (non-admins only see ``actor_id == self``).
#: Tests that need to seed events for *other* actors pass
#: ``actor_id=`` explicitly and read with ``admin_auth_client``.
_DEFAULT_ACTOR_ID = 1


def _seed_event(
    *,
    action: str,
    target_type: str,
    target_id: str,
    tenant_id: str = "default",
    actor_id: int | None = _DEFAULT_ACTOR_ID,
    actor_kind: str = "user",
    request_id: str = "req-test",
    ts_app_utc: datetime | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
    context: dict | None = None,
) -> AuditEvent:
    """Build a minimal AuditEvent suitable for direct session.add().

    Using direct insertion (rather than emit() through the middleware)
    lets these tests reach pre-determined tenant/actor combinations
    without standing up a multi-tenant auth fixture.
    """
    now = ts_app_utc or datetime.now(timezone.utc)
    return AuditEvent(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_kind=actor_kind,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before_state=before_state,
        after_state=after_state,
        context=context,
        request_id=request_id,
        ts_app_utc=now,
        app_monotonic_ns=0,
        process_boot_id="00000000-0000-0000-0000-000000000000",
    )


@pytest.fixture(autouse=True)
def _enable_audit_for_query_tests(monkeypatch):
    install_audit_flush_listener()
    _reset_process_boot_id_for_tests()
    monkeypatch.setattr(app_config, "audit_enabled", True)


@pytest.fixture
async def admin_auth_client(test_session, test_user):
    """Auth client whose user passes the server admin-resolver check.

    The OSS ``User`` model intentionally has no ``is_superuser``
    column (per v0.4.1 monorepo split — the flag lives on
    ManagedUserAccount in spectra-server). The audit route must use
    the OSS admin-resolver contract that the server injects at startup;
    otherwise real server admins silently fail closed and see only
    their own audit rows.
    """
    from httpx import ASGITransport, AsyncClient

    from spectra_sherpa.app.api.deps import get_current_user, get_session
    from spectra_sherpa.app.contracts.auth_resolver import clear_extra_admin_resolver, set_extra_admin_resolver
    from spectra_sherpa.app.main import app as fastapi_app

    async def override_get_session():
        yield test_session

    async def override_get_current_user():
        return test_user

    async def resolve_is_admin(user_id: int) -> bool:
        return user_id == test_user.id

    fastapi_app.dependency_overrides[get_session] = override_get_session
    fastapi_app.dependency_overrides[get_current_user] = override_get_current_user
    set_extra_admin_resolver(resolve_is_admin)

    try:
        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as ac:
            yield ac
    finally:
        clear_extra_admin_resolver()
        fastapi_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Deployment gate
# ---------------------------------------------------------------------------


async def test_returns_403_when_audit_disabled(auth_client, monkeypatch):
    """Per design §3 line 82 — handler 403s when audit_enabled=false."""
    monkeypatch.setattr(app_config, "audit_enabled", False)
    resp = await auth_client.get("/api/v1/audit/events")
    assert resp.status_code == 403
    assert "SHERPA_AUDIT_ENABLED" in resp.json()["detail"]


# Note: an explicit "unauthenticated → 401" test was considered but
# dropped — OSS local mode synthesizes a default user when no auth
# header is present, so the assertion would test the deployment mode,
# not the route. The route declares ``Depends(get_current_user)`` so
# FastAPI handles whatever the deployment's auth posture is.


# ---------------------------------------------------------------------------
# Empty / happy-path
# ---------------------------------------------------------------------------


async def test_returns_empty_when_no_events(auth_client, test_session):
    """Empty audit table → empty response, has_more=False, no cursor."""
    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.get("/api/v1/audit/events")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"events": [], "next_cursor": None, "has_more": False}


async def test_returns_seeded_events_in_descending_id_order(auth_client, test_session):
    """Default order is id DESC (newest first)."""
    await test_session.execute(AuditEvent.__table__.delete())
    test_session.add_all(
        [
            _seed_event(action="experiment.created", target_type="Experiment", target_id="1"),
            _seed_event(action="experiment.updated", target_type="Experiment", target_id="1"),
            _seed_event(action="experiment.deleted", target_type="Experiment", target_id="1"),
        ]
    )
    await test_session.commit()

    resp = await auth_client.get("/api/v1/audit/events")
    assert resp.status_code == 200
    body = resp.json()
    actions = [e["action"] for e in body["events"]]
    assert actions == ["experiment.deleted", "experiment.updated", "experiment.created"]


# ---------------------------------------------------------------------------
# Tenant scoping
# ---------------------------------------------------------------------------


async def test_other_tenant_rows_do_not_leak(auth_client, test_session):
    """Hard isolation: rows tagged with a different tenant_id must
    NOT appear in a caller's query result. ISO 17025 review will
    look here first.
    """
    await test_session.execute(AuditEvent.__table__.delete())
    test_session.add_all(
        [
            _seed_event(
                action="experiment.created",
                target_type="Experiment",
                target_id="1",
                tenant_id="default",
            ),
            _seed_event(
                action="project.deleted",
                target_type="Project",
                target_id="42",
                tenant_id="other-tenant",
            ),
        ]
    )
    await test_session.commit()

    resp = await auth_client.get("/api/v1/audit/events")
    body = resp.json()
    target_ids = [(e["target_type"], e["target_id"]) for e in body["events"]]
    assert ("Project", "42") not in target_ids
    assert ("Experiment", "1") in target_ids


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


@pytest.fixture
async def _filter_dataset(test_session, test_user):
    """Seed a small mixed dataset for filter tests. Each test starts
    from a clean table so order assertions stay deterministic.

    Two events belong to ``test_user`` (visible to non-admin auth);
    one event belongs to a synthetic actor_id=2 + api_key actor_kind
    (visible only to admin) so the actor-scope rule has something to
    suppress.
    """
    # Pin the test_user.id == _DEFAULT_ACTOR_ID invariant — if this
    # ever drifts, the non-admin filter tests below would silently
    # return empty results and pass for the wrong reason.
    assert test_user.id == _DEFAULT_ACTOR_ID, (
        f"test fixture assumption broken: test_user.id={test_user.id} " f"but _DEFAULT_ACTOR_ID={_DEFAULT_ACTOR_ID}"
    )

    await test_session.execute(AuditEvent.__table__.delete())
    test_session.add_all(
        [
            _seed_event(
                action="experiment.created",
                target_type="Experiment",
                target_id="1",
                actor_id=test_user.id,
                actor_kind="user",
                request_id="req-A",
                ts_app_utc=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            ),
            _seed_event(
                action="workflow.run.completed",
                target_type="ExecutionRun",
                target_id="7",
                actor_id=test_user.id,
                actor_kind="user",
                request_id="req-A",
                ts_app_utc=datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc),
            ),
            _seed_event(
                action="project.deleted",
                target_type="Project",
                target_id="3",
                actor_id=test_user.id + 1,  # other actor; visible to admin only
                actor_kind="api_key",
                request_id="req-B",
                ts_app_utc=datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc),
            ),
        ]
    )
    await test_session.commit()


# Tests that filter through the cross-actor row in ``_filter_dataset``
# (the ``actor_id=2`` / ``api_key`` event) MUST use ``admin_auth_client``
# — the actor-scope rule on the route means a non-admin would never see
# that row. The mechanic of the filter (action/actor_id/actor_kind/since
# narrowing the result set) is what's under test here, so admin scope
# is the right context.


async def test_filter_by_action(admin_auth_client, _filter_dataset):
    resp = await admin_auth_client.get("/api/v1/audit/events", params={"action": "project.deleted"})
    body = resp.json()
    assert len(body["events"]) == 1
    assert body["events"][0]["action"] == "project.deleted"


async def test_filter_by_target_type(auth_client, _filter_dataset):
    """test_user (id=1) sees only their own events; the Experiment
    event in the dataset is theirs, so this works under non-admin scope.
    """
    resp = await auth_client.get("/api/v1/audit/events", params={"target_type": "Experiment"})
    body = resp.json()
    assert {e["target_type"] for e in body["events"]} == {"Experiment"}


async def test_filter_by_target_id(auth_client, _filter_dataset):
    resp = await auth_client.get(
        "/api/v1/audit/events",
        params={"target_type": "ExecutionRun", "target_id": "7"},
    )
    body = resp.json()
    assert len(body["events"]) == 1
    assert body["events"][0]["target_id"] == "7"


async def test_filter_by_actor_id(admin_auth_client, _filter_dataset):
    """Filtering by another actor's id requires admin — non-admins
    never reach other-actor rows because of the implicit scope filter.
    """
    resp = await admin_auth_client.get("/api/v1/audit/events", params={"actor_id": 2})
    body = resp.json()
    assert {e["actor_id"] for e in body["events"]} == {2}


async def test_filter_by_actor_kind(admin_auth_client, _filter_dataset):
    resp = await admin_auth_client.get("/api/v1/audit/events", params={"actor_kind": "api_key"})
    body = resp.json()
    assert {e["actor_kind"] for e in body["events"]} == {"api_key"}


async def test_filter_by_request_id(auth_client, _filter_dataset):
    """``req-A`` events both have actor_id=1, so non-admin sees them."""
    resp = await auth_client.get("/api/v1/audit/events", params={"request_id": "req-A"})
    body = resp.json()
    assert {e["request_id"] for e in body["events"]} == {"req-A"}
    assert len(body["events"]) == 2


async def test_filter_since(admin_auth_client, _filter_dataset):
    """``since`` is an inclusive lower bound on ts_app_utc.
    Spans both actors → admin scope.
    """
    resp = await admin_auth_client.get(
        "/api/v1/audit/events",
        params={"since": "2026-01-02T00:00:00+00:00"},
    )
    body = resp.json()
    actions = {e["action"] for e in body["events"]}
    assert actions == {"workflow.run.completed", "project.deleted"}


async def test_filter_until(auth_client, _filter_dataset):
    """``until`` is an exclusive upper bound — equal-to-until must NOT match.
    The single matching event has actor_id=1 so non-admin scope works.
    """
    resp = await auth_client.get(
        "/api/v1/audit/events",
        params={"until": "2026-01-02T12:00:00+00:00"},
    )
    body = resp.json()
    actions = {e["action"] for e in body["events"]}
    assert actions == {"experiment.created"}


async def test_filter_combined_and_clauses(auth_client, _filter_dataset):
    """Multiple filters AND together — each must narrow the set."""
    resp = await auth_client.get(
        "/api/v1/audit/events",
        params={"actor_id": 1, "target_type": "ExecutionRun"},
    )
    body = resp.json()
    assert len(body["events"]) == 1
    assert body["events"][0]["action"] == "workflow.run.completed"


# ---------------------------------------------------------------------------
# Validation (422 paths)
# ---------------------------------------------------------------------------


async def test_invalid_actor_kind_returns_422(auth_client):
    resp = await auth_client.get("/api/v1/audit/events", params={"actor_kind": "ghost"})
    assert resp.status_code == 422
    assert "actor_kind" in resp.json()["detail"]


async def test_invalid_cursor_returns_422(auth_client):
    resp = await auth_client.get("/api/v1/audit/events", params={"cursor": "not-an-int"})
    assert resp.status_code == 422
    assert "cursor" in resp.json()["detail"]


async def test_since_after_until_returns_422(auth_client):
    resp = await auth_client.get(
        "/api/v1/audit/events",
        params={"since": "2026-02-01T00:00:00+00:00", "until": "2026-01-01T00:00:00+00:00"},
    )
    assert resp.status_code == 422


async def test_limit_above_max_rejected(auth_client):
    """Pagination cap is 500. Above-cap requests must 422 (FastAPI's
    Query(le=...) handles this — pinned so a future bump must update
    both the route and the test.
    """
    resp = await auth_client.get("/api/v1/audit/events", params={"limit": 5000})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


async def test_limit_caps_returned_events(auth_client, test_session):
    await test_session.execute(AuditEvent.__table__.delete())
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    test_session.add_all(
        [
            _seed_event(
                action="experiment.created",
                target_type="Experiment",
                target_id=str(i),
                ts_app_utc=base + timedelta(seconds=i),
            )
            for i in range(5)
        ]
    )
    await test_session.commit()

    resp = await auth_client.get("/api/v1/audit/events", params={"limit": 2})
    body = resp.json()
    assert len(body["events"]) == 2
    assert body["has_more"] is True
    assert body["next_cursor"] is not None


async def test_cursor_paging_returns_each_event_exactly_once(auth_client, test_session):
    """Page through the full dataset using next_cursor. Every seeded
    event must appear exactly once across the pages — no overlap, no
    gap. Catches off-by-one in the < vs <= cursor predicate.
    """
    await test_session.execute(AuditEvent.__table__.delete())
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    seeded = [
        _seed_event(
            action="experiment.created",
            target_type="Experiment",
            target_id=str(i),
            ts_app_utc=base + timedelta(seconds=i),
        )
        for i in range(7)
    ]
    test_session.add_all(seeded)
    await test_session.commit()

    seen_target_ids: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict = {"limit": 3}
        if cursor is not None:
            params["cursor"] = cursor
        resp = await auth_client.get("/api/v1/audit/events", params=params)
        assert resp.status_code == 200
        body = resp.json()
        seen_target_ids.extend(e["target_id"] for e in body["events"])
        cursor = body["next_cursor"]
        pages += 1
        if not body["has_more"]:
            break
        # Defence against an infinite loop on a buggy cursor.
        assert pages < 10, "paging did not terminate"

    assert sorted(seen_target_ids) == sorted(str(i) for i in range(7))
    # 7 rows / 3-per-page → 3 pages (3, 3, 1).
    assert pages == 3


async def test_no_more_pages_when_under_limit(auth_client, test_session):
    """A single-page result must NOT advertise has_more or a cursor."""
    await test_session.execute(AuditEvent.__table__.delete())
    test_session.add(_seed_event(action="experiment.created", target_type="Experiment", target_id="1"))
    await test_session.commit()

    resp = await auth_client.get("/api/v1/audit/events", params={"limit": 50})
    body = resp.json()
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    assert len(body["events"]) == 1


# ---------------------------------------------------------------------------
# Audit-of-audit: reads MUST NOT emit
# ---------------------------------------------------------------------------


async def test_query_does_not_emit_audit_event(auth_client, test_session):
    """Per design §6: 'Audit-event read queries themselves are NOT
    audited (would create a feedback loop; the export event captures
    the auditable case).' Test pins this so a future refactor can't
    accidentally wrap the read handler in an audit emit.
    """
    await test_session.execute(AuditEvent.__table__.delete())
    test_session.add(_seed_event(action="experiment.created", target_type="Experiment", target_id="1"))
    await test_session.commit()

    pre_count = (await test_session.execute(select(AuditEvent))).scalars().all()
    assert len(pre_count) == 1

    resp = await auth_client.get("/api/v1/audit/events")
    assert resp.status_code == 200

    post_count = (await test_session.execute(select(AuditEvent))).scalars().all()
    # Same row count → the read did NOT add an audit event.
    assert len(post_count) == len(pre_count)


# ---------------------------------------------------------------------------
# Within-tenant actor scoping
#
# Closes the Phase 4 review-feedback critical: in multi-user OSS / Team
# deployments, the previous /audit/events handler was tenant-wide for
# any authenticated user, leaking other users' before/after state
# snapshots. Default scope now restricts to the caller's own actor_id;
# admin (is_superuser) bypass remains for the audit.full UI path.
# ---------------------------------------------------------------------------


async def test_non_admin_cannot_see_other_actors_events(auth_client, test_session, test_user):
    """An authenticated non-admin must NOT see audit rows whose
    actor_id differs from their own. Pinned regression: prior to this
    fix, the route returned every row in the tenant.
    """
    await test_session.execute(AuditEvent.__table__.delete())
    test_session.add_all(
        [
            _seed_event(
                action="experiment.created",
                target_type="Experiment",
                target_id="1",
                actor_id=test_user.id,
            ),
            _seed_event(
                action="model_artifact.deleted",
                target_type="ModelArtifact",
                target_id="99",
                actor_id=test_user.id + 100,  # someone else
                before_state={"name": "secret-model", "training_data_hash": "leak-me-not"},
            ),
        ]
    )
    await test_session.commit()

    resp = await auth_client.get("/api/v1/audit/events")
    body = resp.json()

    target_ids = [(e["target_type"], e["target_id"]) for e in body["events"]]
    # Only the test_user's own event must be visible.
    assert ("Experiment", "1") in target_ids
    assert ("ModelArtifact", "99") not in target_ids
    # The leaked before_state from the other actor's event must not
    # appear anywhere in the response.
    assert "leak-me-not" not in resp.text


async def test_non_admin_does_not_see_system_events(auth_client, test_session):
    """System-emitted events (actor_id=None) are not "yours" — only
    admins see them. Catches a confusion where actor_id IS NULL might
    be treated as 'matches anyone'.
    """
    await test_session.execute(AuditEvent.__table__.delete())
    test_session.add(
        _seed_event(
            action="workflow.run.completed",
            target_type="ExecutionRun",
            target_id="42",
            actor_id=None,
            actor_kind="system",
        )
    )
    await test_session.commit()

    resp = await auth_client.get("/api/v1/audit/events")
    body = resp.json()
    assert body["events"] == []


async def test_admin_sees_all_actors_in_tenant(admin_auth_client, test_session, test_user):
    """``is_superuser`` bypasses the actor scope filter. Tenant-wide
    visibility for forensic / compliance work is the expected path
    for the audit.full admin UI.
    """
    await test_session.execute(AuditEvent.__table__.delete())
    test_session.add_all(
        [
            _seed_event(action="a", target_type="X", target_id="1", actor_id=test_user.id),
            _seed_event(action="b", target_type="X", target_id="2", actor_id=test_user.id + 100),
            _seed_event(action="c", target_type="X", target_id="3", actor_id=None, actor_kind="system"),
        ]
    )
    await test_session.commit()

    resp = await admin_auth_client.get("/api/v1/audit/events")
    body = resp.json()
    assert len(body["events"]) == 3


async def test_admin_actor_filter_still_restricts(admin_auth_client, test_session, test_user):
    """Admin bypass removes the implicit scope but does NOT remove
    explicit ``actor_id=`` filters — admin can still drill into one
    user's history.
    """
    await test_session.execute(AuditEvent.__table__.delete())
    other_id = test_user.id + 50
    test_session.add_all(
        [
            _seed_event(action="a", target_type="X", target_id="1", actor_id=test_user.id),
            _seed_event(action="b", target_type="X", target_id="2", actor_id=other_id),
        ]
    )
    await test_session.commit()

    resp = await admin_auth_client.get("/api/v1/audit/events", params={"actor_id": other_id})
    body = resp.json()
    assert {e["actor_id"] for e in body["events"]} == {other_id}
    assert {e["target_id"] for e in body["events"]} == {"2"}
