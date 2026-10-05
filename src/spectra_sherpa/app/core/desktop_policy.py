"""Local-only boundary for the signed desktop application.

The desktop launcher sets ``SPECTRA_SHERPA_DESKTOP=1`` before any application
module is imported. In that product the workbench never connects to a
Spectra Scientific service: Hybrid enrollment, cloud sync and remote log
upload are unavailable, and their client modules are excluded from the frozen
bundle. The only outbound requests are the ones a user configures and
triggers (their own AI provider, and public reference-data downloads).
"""

from __future__ import annotations

import os

from fastapi import HTTPException

DESKTOP_ENV = "SPECTRA_SHERPA_DESKTOP"
UNAVAILABLE = "Spectra Scientific hosted services are not available in the desktop application."

# Configuration that would connect the workbench to a hosted service. The
# launcher strips these, and configuration refuses them if they reappear.
HOSTED_SERVICE_ENV = (
    "SPECTRASHERPA_LOG_URL",
    "SPECTRASHERPA_API_KEY",
    "SPECTRASHERPA_API_URL",
    "SPECTRASHERPA_DEPLOYMENT_ID",
    "SPECTRASHERPA_DEPLOYMENT_KEY",
    "GRADIENT_API_KEY",
)


def is_desktop() -> bool:
    return os.getenv(DESKTOP_ENV) == "1"


def scrub_hosted_service_environment() -> None:
    """Pin local mode and drop hosted-service settings, e.g. from an old .env."""
    if not is_desktop():
        return
    os.environ["APP_MODE"] = "local"
    for name in HOSTED_SERVICE_ENV:
        os.environ.pop(name, None)


class LinkedConfigurationRefused(RuntimeError):
    """The desktop profile's configuration file is a link; it is never written through."""

    def __init__(self) -> None:
        super().__init__(
            "The profile's .env file is a link to another file. Spectra Sherpa does not modify linked "
            "configuration files; replace the link with a regular file to save settings."
        )


def refuse_linked_configuration(path: str | os.PathLike[str]) -> None:
    """On desktop, refuse to write a .env that is a symbolic or hard link to another file."""
    if not is_desktop():
        return
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    if os.path.islink(path) or info.st_nlink > 1 or getattr(os.path, "isjunction", lambda _p: False)(path):
        raise LinkedConfigurationRefused()


def refuse_on_desktop() -> None:
    """FastAPI dependency for hosted-service routes; hidden as not found."""
    if is_desktop():
        raise HTTPException(status_code=404, detail=UNAVAILABLE)
