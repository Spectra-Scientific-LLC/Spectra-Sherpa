"""The desktop product never connects to a Spectra Scientific hosted service."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "desktop"))
from optional_exclusions import HOSTED_SERVICE_MODULES  # noqa: E402


def _desktop_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("APP_MODE", "SPECTRASHERPA_", "SITE_PROFILE"))}
    env.update(
        SPECTRA_SHERPA_DESKTOP="1",
        APP_MODE="local",
        DATA_DIR=str(tmp_path),
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'desktop.db'}",
        HOME=str(tmp_path),
        USERPROFILE=str(tmp_path),
    )
    env.update(extra)
    return env


def _run(tmp_path: Path, code: str, **extra: str) -> dict:
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=_desktop_env(tmp_path, **extra),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_desktop_app_starts_without_importing_hosted_service_clients(tmp_path) -> None:
    """The frozen bundle omits these modules, so startup must never need them."""
    report = _run(
        tmp_path,
        "import json, sys\n"
        "from spectra_sherpa.app.main import create_app\n"
        "app = create_app()\n"
        "paths = sorted({getattr(r, 'path', '') for r in app.routes})\n"
        "print(json.dumps({'modules': sorted(m for m in sys.modules if 'hybrid' in m), 'paths': paths}))\n",
    )

    assert not set(HOSTED_SERVICE_MODULES) & set(report["modules"])
    assert not [path for path in report["paths"] if path.startswith("/api/v1/hybrid")]


def test_desktop_configuration_pins_local_mode_and_drops_hosted_settings(tmp_path) -> None:
    # A profile .env left by an earlier Hybrid activation must not reconnect it.
    (tmp_path / ".env").write_text(
        "APP_MODE=hybrid\nSPECTRASHERPA_API_KEY=leftover\nSPECTRASHERPA_LOG_URL=https://example.invalid/logs\n",
        encoding="utf-8",
    )
    report = _run(
        tmp_path,
        "import json, os\n"
        "from spectra_sherpa._paths import load_layered_env_files\n"
        "load_layered_env_files()\n"
        "from spectra_sherpa.app.core.config import AppConfig\n"
        "config = AppConfig.from_env().to_client_safe()\n"
        "print(json.dumps({'mode': config['mode'], 'desktop': config['desktop'],\n"
        "  'hybridActivation': config['features'].get('hybridActivation'),\n"
        "  'env': {k: os.environ.get(k) for k in ('APP_MODE', 'SPECTRASHERPA_API_KEY', 'SPECTRASHERPA_LOG_URL')}}))\n",
        APP_MODE="hybrid",
    )

    assert report["mode"] == "local"
    assert report["desktop"] is True
    assert report["hybridActivation"] is None
    assert report["env"] == {"APP_MODE": "local", "SPECTRASHERPA_API_KEY": None, "SPECTRASHERPA_LOG_URL": None}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/config/spectrasherpa"),
        ("get", "/api/v1/config/spectrasherpa/user"),
        ("get", "/api/v1/config/spectrasherpa/keys"),
        ("post", "/api/v1/config/activate-hybrid"),
        ("post", "/api/v1/config/deactivate-hybrid"),
    ],
)
def test_desktop_refuses_hosted_service_routes(tmp_path, method, path) -> None:
    report = _run(
        tmp_path,
        "import json\n"
        "from fastapi.testclient import TestClient\n"
        "from spectra_sherpa.app.main import create_app\n"
        "with TestClient(create_app(), client=('127.0.0.1', 50000)) as client:\n"
        f"    response = client.{method}({path!r}"
        + (", json={'server_url': 'https://example.invalid', 'code': 'x'}" if method == "post" else "")
        + ")\n"
        "print(json.dumps({'status': response.status_code, 'body': response.json()}))\n",
    )

    assert report["status"] == 404
    assert report["body"]["detail"] == "Not Found"  # The implementation is absent, not merely gated.


def test_unprotected_desktop_refuses_key_storage_but_serves_analysis(tmp_path) -> None:
    report = _run(
        tmp_path,
        "import json\n"
        "from fastapi.testclient import TestClient\n"
        "from spectra_sherpa.app.main import create_app\n"
        "with TestClient(create_app(), client=('127.0.0.1', 50000)) as client:\n"
        "    saved = client.post('/api/v1/api-keys', json={'service_name': 'hitran', 'key': 'hitran-secret'})\n"
        "    config = client.get('/api/v1/config').json()\n"
        "    health = client.get('/api/health')\n"
        "print(json.dumps({'saved': saved.status_code, 'code': saved.json().get('code'),\n"
        "  'storage': config['features']['credentialStorage'], 'health': health.status_code}))\n",
    )

    assert report == {"saved": 409, "code": "credential_storage_unavailable", "storage": False, "health": 200}
