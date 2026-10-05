"""Delete-all only removes entries in the profile layout; keep it complete.

A profile entry the backend creates but the layout omits would survive
"Delete all local data" (it is reported to the user, never lost). These tests
fail when the backend starts creating a new top-level entry or .env key.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PACKAGE_ROOT / "src" / "spectra_sherpa"
LAYOUT = json.loads((PACKAGE_ROOT / "desktop/electron/profile-layout.json").read_text(encoding="utf-8"))


def _owned(name: str) -> bool:
    return name in LAYOUT["entries"] or any(name.startswith(prefix) for prefix in LAYOUT["prefixes"])


def test_static_profile_roots_are_in_the_layout():
    root_expression = re.compile(
        r"(?:settings\.data_dir|Path\(settings\.data_dir\)|get_default_data_dir\(\)|\broot|\bdata_dir)\s*/\s*[\"']([^\"'/]+)[\"']"
    )
    # Directory-name constants joined onto the profile root elsewhere.
    constant = re.compile(r"^_?[A-Z_]*(?:ARTIFACT_DIRECTORY|_DIRECTORY)\s*=\s*\"([^\"/]+)\"", re.MULTILINE)
    found = set()
    for path in SOURCE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        found.update(root_expression.findall(text))
        found.update(constant.findall(text))
    # Constants for folders outside the profile (user working directory, SDK state).
    found -= {"reference-data", "states"}
    ignored = {".env", "data", "backend"}  # .env is key-scrubbed; others are checkout paths
    assert {name for name in found - ignored if not _owned(name)} == set()


def test_env_keys_the_app_writes_are_in_the_layout():
    writers = re.compile(r"(?:dotenv_set_key|set_key)\([^,]+,\s*\"([A-Z_]+)\"")
    keys = set()
    for path in SOURCE.rglob("*.py"):
        keys.update(writers.findall(path.read_text(encoding="utf-8")))
    keys |= {"MASTER_ENCRYPTION_KEY", "CHAT_ENDPOINT_KEY_ENCRYPTED"}
    assert keys - set(LAYOUT["env_keys"]) == set()


def test_a_fresh_desktop_profile_contains_only_owned_entries(tmp_path) -> None:
    profile = tmp_path / "profile"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("APP_MODE", "SPECTRASHERPA_", "SITE_PROFILE"))}
    env.update(
        SPECTRA_SHERPA_DESKTOP="1",
        APP_MODE="local",
        DATA_DIR=str(profile),
        DATABASE_URL=f"sqlite+aiosqlite:///{profile / 'spectra_platform.db'}",
        LOG_FILE_PATH=str(profile / "logs" / "desktop.log"),
        HOME=str(tmp_path),
        USERPROFILE=str(tmp_path),
    )
    code = (
        "import json, os\n"
        "from fastapi.testclient import TestClient\n"
        "from spectra_sherpa.app.main import create_app\n"
        "with TestClient(create_app(), client=('127.0.0.1', 50000)) as client:\n"
        "    client.get('/api/v1/config')\n"
        "    client.get('/api/v1/projects')\n"
        "print(json.dumps(sorted(os.listdir(os.environ['DATA_DIR']))))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, cwd=tmp_path, capture_output=True, text=True, timeout=180, check=False
    )
    assert result.returncode == 0, result.stderr[-4000:]
    created = json.loads(result.stdout.strip().splitlines()[-1])

    assert "spectra_platform.db" in created
    assert [name for name in created if name != ".env" and not _owned(name)] == []
