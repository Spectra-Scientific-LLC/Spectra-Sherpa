from __future__ import annotations

import io
import json
import secrets

import httpx
import pytest

from spectra_sherpa.desktop_session import AUTH_HEADER, DesktopAccess, DesktopProtocolError, DesktopSession


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token,host,origin,expected",
    [
        (False, "127.0.0.1:3456", None, 403),
        (True, "127.0.0.1:3456", None, 200),
        (True, "127.0.0.1:3456", "http://127.0.0.1:3456", 200),
        (True, "127.0.0.1:3456", "https://unrelated.example", 403),
        (True, "attacker.example", None, 403),
        (True, "127.0.0.1:3456", "null", 403),
    ],
)
async def test_http_boundary_including_health_and_static_ui(token, host, origin, expected):
    secret = secrets.token_urlsafe(32)

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"scientific data"})

    headers = {"host": host}
    if token:
        headers[AUTH_HEADER.decode()] = secret
    if origin:
        headers["origin"] = origin
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=DesktopAccess(app, secret)), base_url="http://127.0.0.1:3456"
    ) as client:
        for path in ("/", "/api/health", "/api/v1/experiments"):
            response = await client.get(path, headers=headers)
            assert response.status_code == expected
            assert secret not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("authenticated", [False, True])
async def test_websocket_boundary(authenticated):
    secret = secrets.token_urlsafe(32)
    messages = []

    async def app(scope, receive, send):
        await send({"type": "websocket.accept"})

    headers = [(b"host", b"127.0.0.1:3456"), (b"origin", b"http://127.0.0.1:3456")]
    if authenticated:
        headers.append((AUTH_HEADER, secret.encode()))

    async def send(message):
        messages.append(message)

    await DesktopAccess(app, secret)(
        {"type": "websocket", "server": ("127.0.0.1", 3456), "headers": headers}, None, send
    )
    assert messages == (
        [{"type": "websocket.accept"}] if authenticated else [{"type": "websocket.close", "code": 1008}]
    )


def test_launch_protocol_never_returns_secret():
    secret = secrets.token_urlsafe(32)
    outgoing = io.StringIO()
    session = DesktopSession(
        io.StringIO(json.dumps({"protocol": 1, "type": "launch", "secret": secret}) + "\n"), outgoing
    )
    session.initialize()
    session.fail("test", "accidental echo " + secret)
    frames = [json.loads(line) for line in outgoing.getvalue().splitlines()]
    assert [frame["type"] for frame in frames] == ["starting", "error"]
    assert secret not in outgoing.getvalue()


@pytest.mark.parametrize("frame", ["", "{}\n", "[]\n", "not json\n", "x" * 5000 + "\n"])
def test_invalid_launch_frames_refuse(frame):
    with pytest.raises(DesktopProtocolError):
        DesktopSession(io.StringIO(frame), io.StringIO()).initialize()


@pytest.mark.parametrize("message", ["漢" * 1024, "😀" * 1024, "x" * 10000])
def test_error_frame_bound_is_encoded_bytes(message):
    outgoing = io.StringIO()
    session = DesktopSession(io.StringIO(), outgoing)
    session.fail("startup_failed", message)
    assert len(outgoing.getvalue().encode("utf-8")) <= 4096
    assert json.loads(outgoing.getvalue())["type"] == "error"


def test_non_error_oversized_frame_refused():
    with pytest.raises(DesktopProtocolError):
        DesktopSession(io.StringIO(), io.StringIO()).emit("ready", endpoint="x" * 5000)
