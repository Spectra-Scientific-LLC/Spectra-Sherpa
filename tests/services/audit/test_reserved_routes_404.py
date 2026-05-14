"""OSS-only snapshot: only ``/audit/events`` is bound under ``/api/v1/audit``.

The OSS package owns ``GET /api/v1/audit/events`` (the ``audit.basic``
capability — query within caller's own tenant). All other audit routes
are server-only and ride entitlement gates the OSS package does not
ship.

We pin this by inspecting the FastAPI route table directly rather than
HTTP-roundtripping. The OSS app installs a SPA catch-all
``GET /{path:path}`` to serve the frontend, which would shadow a 404 for
any GET path with the SPA's index.html. Inspecting routes is the
honest signal — "what does the OSS router actually bind?"

If a future feature legitimately adds a route under ``/api/v1/audit/``
on the OSS side, update ``EXPECTED_OSS_AUDIT_ROUTES`` below explicitly
so the change is visible in review.

Why pin this:
- ``mirror.yml`` runs the OSS package alone via ``git subtree split``.
  If a server route ever leaked into the OSS router (or someone added a
  shim with a 401/402 instead of letting it 404), the public mirror
  would advertise an endpoint it cannot serve.
- A net-new OSS audit route is a deliberate decision (it crosses the
  audit-capability boundary). This test forces the conversation.
"""

from __future__ import annotations

EXPECTED_OSS_AUDIT_ROUTES: set[tuple[frozenset[str], str]] = {
    (frozenset({"GET"}), "/api/v1/audit/events"),
}


def test_oss_audit_router_binds_only_events_endpoint():
    """OSS app must bind exactly the ``audit.basic`` query route.

    Anything else under ``/api/v1/audit/...`` means a server-owned
    route (verify, export, report-pack, admin/*) leaked into the OSS
    router graph, or someone added an OSS audit feature without
    updating this snapshot.
    """
    from spectra_sherpa.app.main import app

    actual: set[tuple[frozenset[str], str]] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        if not path.startswith("/api/v1/audit"):
            continue
        actual.add((frozenset(methods), path))

    unexpected = actual - EXPECTED_OSS_AUDIT_ROUTES
    missing = EXPECTED_OSS_AUDIT_ROUTES - actual

    assert not unexpected, (
        "OSS app bound an unexpected /api/v1/audit/* route(s): "
        f"{sorted((sorted(m), p) for m, p in unexpected)}. "
        "Either remove the route from the OSS router (server-only routes "
        "live in the server package) or update EXPECTED_OSS_AUDIT_ROUTES "
        "in this file with a clear rationale."
    )
    assert not missing, (
        f"OSS app is missing expected audit route(s): "
        f"{sorted((sorted(m), p) for m, p in missing)}. "
        "If this was intentional, update EXPECTED_OSS_AUDIT_ROUTES."
    )
