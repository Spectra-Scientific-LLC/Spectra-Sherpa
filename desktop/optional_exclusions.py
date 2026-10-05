"""Explicit desktop classification of every optional Python distribution.

HAPI/HAPI2 are approved for redistribution with their upstream notices and
matching source (see hitran_bundle.py). Other extras remain excluded by
product policy. The pip extras remain available independently.
"""

from __future__ import annotations

# Distribution name (as pyproject declares it) -> top-level import module.
# ``tests/test_desktop_optional_exclusions.py`` asserts this covers every
# optional dependency across the included and excluded maps.
OPTIONAL_DISTRIBUTION_MODULES: dict[str, str] = {
    "spectrochempy": "spectrochempy",
    "beautifulsoup4": "bs4",
    "asyncpg": "asyncpg",
    "gunicorn": "gunicorn",
}

BUNDLED_OPTIONAL_DISTRIBUTION_MODULES: dict[str, str] = {
    "hitran-api": "hapi",
    "hitran-api2": "hapi2",
}

# Clients for Spectra Scientific hosted services (Hybrid enrollment, advisor
# relay and the enrollment CLI). The desktop product is local-only: its
# runtime refuses these routes (``app.core.desktop_policy``) and the bundle
# does not carry the code that could reach a hosted service.
HOSTED_SERVICE_MODULES: tuple[str, ...] = (
    "spectra_hybrid",
    "spectra_hybrid_contracts",
    "spectra_sherpa.app.api.v1.routes.hybrid",
    "spectra_sherpa.app.services.commercial_hybrid_client",
    "spectra_sherpa.app.services.hybrid_advisor_client",
    "spectra_sherpa.app.services.hybrid_device_client",
    "spectra_sherpa.commercial_hybrid",
)

# What PyInstaller must refuse to follow into the bundle.
EXCLUDED_MODULES: tuple[str, ...] = tuple(sorted(OPTIONAL_DISTRIBUTION_MODULES.values())) + HOSTED_SERVICE_MODULES
