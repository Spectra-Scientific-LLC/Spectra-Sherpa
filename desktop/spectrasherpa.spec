# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for the unsigned local desktop bundle.

Build this specification natively on its target operating system. Signing and
notarization belong to the later release lane, not this local build recipe.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

sys.path.insert(0, SPECPATH)
from hitran_bundle import CLIENTS, HIDDEN_IMPORTS, prepare  # noqa: E402
from migration_imports import migration_hidden_imports  # noqa: E402
from optional_exclusions import EXCLUDED_MODULES  # noqa: E402  (SPECPATH-relative)

PACKAGE_ROOT = Path(SPECPATH).parent
PACKAGE_SOURCE = PACKAGE_ROOT / "src" / "spectra_sherpa"
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

datas = collect_data_files("spectra_sherpa", excludes=["**/__pycache__/*"])
# Alembic executes ``env.py`` and revision scripts by file path. PyInstaller
# therefore needs the entire script directory as data rather than only as
# Python modules reachable from the desktop entry point.
datas.append((str(PACKAGE_SOURCE / "alembic"), "spectra_sherpa/alembic"))
# Regular application imports are discovered by PyInstaller's analysis. The
# Uvicorn target below is intentionally a string in ``cli.py``, and SQLAlchemy
# selects its local SQLite driver dynamically, so those entries need to be
# explicit. Do not collect every package submodule here:
# doing that imports optional scientific integrations while *building* and
# turns an ordinary local bundle into an environment-dependent build.
# Third-party plugins are intentionally discovered at runtime from the user's
# data directory or entry points.
hiddenimports = ["aiosqlite", "spectra_sherpa.app.main"]
hiddenimports += migration_hidden_imports(PACKAGE_SOURCE / "alembic")
hiddenimports += HIDDEN_IMPORTS
for distribution in CLIENTS:
    datas += copy_metadata(distribution)
# The HAPI2 source distribution and HAPI source wheel accompany every installer.
source_payload = prepare(Path(SPECPATH) / "build" / "hitran-sources")
datas.append((str(source_payload), "third_party/hitran"))

a = Analysis(
    [str(Path(SPECPATH) / "desktop_entry.py")],
    pathex=[str(PACKAGE_ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Only explicitly approved extras ship; the classification is tested
    # against pyproject's optional dependencies.
    excludes=list(EXCLUDED_MODULES),
    # HAPI2's @njit(cache=True) functions need real source paths. Loading them
    # from .py also lets Numba use the profile-owned cache rather than an
    # unavailable user-global fallback for anonymous PYZ code objects.
    module_collection_mode={"hapi2": "py"},
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    [],
    name="SpectraSherpa",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Native-parent mode needs inherited stdio pipes on Windows. Electron hides
    # the child console; the existing standalone/browser lane stays windowed.
    console=os.environ.get("SPECTRA_DESKTOP_NATIVE_BACKEND") == "1",
    exclude_binaries=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="SpectraSherpa",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="SpectraSherpa.app",
        icon=None,
        bundle_identifier="ai.spectrascientific.sherpa",
        info_plist={
            "LSMinimumSystemVersion": "14.0.0",
            "NSHighResolutionCapable": True,
        },
    )
