"""Every local MCP refusal says why and where, and never echoes server text."""

import json

import pytest

from spectra_sherpa.mcp.bridge_client import _refusal_code
from spectra_sherpa.mcp.refusals import REFUSALS, refusal_text


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()

    async def aread(self):
        return self._body


@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (422, {"detail": "privacy_denied"}, "privacy_denied"),
        (422, {"detail": "object_unavailable"}, "object_unavailable"),
        (429, {"detail": "busy"}, "busy"),
        (401, {"detail": "Inspection access denied"}, "access_denied"),
        (403, {"detail": "Inspection access denied"}, "access_denied"),
        (408, {"detail": "Inspection timed out"}, "timeout"),
        (422, {"detail": "/private/path secret-token"}, "inspection_failed"),
        (500, b"not json", "inspection_failed"),
        (422, b"x" * 5000, "inspection_failed"),
    ],
)
async def test_refused_calls_map_to_fixed_codes(status, body, code):
    assert await _refusal_code(FakeResponse(status, body)) == code


def test_every_refusal_has_why_and_where():
    for code, (why, where) in REFUSALS.items():
        assert why.strip() and where.strip(), code
        assert refusal_text(code) == f"{why} {where}"
    assert "read-only" in refusal_text("unsupported_operation")
    assert "Settings" in refusal_text("privacy_denied")
    assert refusal_text("something unknown") == refusal_text("inspection_failed")
