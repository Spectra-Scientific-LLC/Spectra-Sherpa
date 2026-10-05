"""Every source file that can open an outbound connection is reviewed here.

The desktop privacy statement lists the only destinations the application can
contact. A new network client must be added to this table, with its purpose,
before it can ship; hosted-service clients must also be excluded from the
desktop bundle.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PACKAGE_ROOT / "src"
sys.path.insert(0, str(PACKAGE_ROOT / "desktop"))
from optional_exclusions import HOSTED_SERVICE_MODULES  # noqa: E402

NETWORK_CLIENT = re.compile(
    r"^\s*(?:import|from)\s+(?:httpx|requests|aiohttp|urllib\.request|http\.client|websockets|urllib3)\b"
    r"|socket\.create_connection|\burlopen\(",
    re.MULTILINE,
)

# module -> why it may connect (destination), or "hosted" when it is a
# Spectra Scientific hosted-service client that the desktop bundle excludes.
REVIEWED = {
    "spectra_sherpa.app.services.chat_providers.anthropic": "user-configured AI provider (BYOK)",
    "spectra_sherpa.app.services.chat_providers.openai_compatible": "user-configured AI provider (BYOK)",
    "spectra_sherpa.app.services.synthesis": "NIST WebBook / HITRAN reference data, on request",
    "spectra_sherpa.app.api.v1.routes.synthesis": "error types for reference-data downloads",
    "spectra_sherpa.app.api.v1.routes.datasets": "error types for reference-data downloads",
    "spectra_sherpa.cli": "loopback: the local server started by this CLI",
}


def _network_modules() -> set[str]:
    found = set()
    for path in (SOURCE / "spectra_sherpa").rglob("*.py"):
        if NETWORK_CLIENT.search(path.read_text(encoding="utf-8")):
            found.add(".".join(path.relative_to(SOURCE).with_suffix("").parts))
    return found


def test_every_network_client_is_reviewed():
    found = _network_modules()
    assert found - set(REVIEWED) == set(), "new outbound network client needs privacy review"
    assert set(REVIEWED) - found == set(), "stale entry: remove it from REVIEWED"


def test_hosted_service_clients_are_excluded_from_the_desktop_bundle():
    hosted = {module for module, purpose in REVIEWED.items() if purpose == "hosted"}
    assert hosted <= set(HOSTED_SERVICE_MODULES)


def test_electron_shell_has_no_update_crash_or_remote_request_channel():
    electron = PACKAGE_ROOT / "desktop" / "electron"
    forbidden = re.compile(
        r"autoUpdater|crashReporter|\bnet\.(?:request|fetch)\b|require\('(?:node:)?https'\)|\bfetch\("
    )
    offenders = [
        path.name
        for path in electron.glob("*.cjs")
        if not path.name.endswith("smoke.cjs") and forbidden.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
