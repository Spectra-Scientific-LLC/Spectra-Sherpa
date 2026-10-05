"""Every optional dependency has an explicit desktop shipping classification."""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DESKTOP = PACKAGE_ROOT / "desktop"


def _load(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, DESKTOP / f"{module_name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules.setdefault(module_name, module)
    spec.loader.exec_module(module)
    return module


def _optional_distributions() -> set[str]:
    pyproject = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["tool"]["poetry"]["dependencies"]
    return {name for name, value in dependencies.items() if isinstance(value, dict) and value.get("optional") is True}


def test_exclusion_list_covers_every_optional_dependency() -> None:
    """A new extra must be classified here before it can reach a release."""
    exclusions = _load("optional_exclusions")
    excluded = set(exclusions.OPTIONAL_DISTRIBUTION_MODULES)
    included = set(exclusions.BUNDLED_OPTIONAL_DISTRIBUTION_MODULES)
    assert not excluded & included
    declared = excluded | included
    optional = _optional_distributions()

    assert declared == optional, (
        "desktop/optional_exclusions.py is out of step with pyproject's optional "
        f"dependencies. Missing: {sorted(optional - declared)}; "
        f"stale: {sorted(declared - optional)}"
    )


def test_only_approved_optional_clients_are_included() -> None:
    """HAPI clients are approved; unrelated extras and hosted code stay excluded."""
    exclusions = _load("optional_exclusions")

    assert exclusions.OPTIONAL_DISTRIBUTION_MODULES["spectrochempy"] == "spectrochempy"
    assert exclusions.BUNDLED_OPTIONAL_DISTRIBUTION_MODULES == {"hitran-api": "hapi", "hitran-api2": "hapi2"}
    assert "hapi2" not in exclusions.EXCLUDED_MODULES
    assert "hapi" not in exclusions.EXCLUDED_MODULES
    assert "spectrochempy" in exclusions.EXCLUDED_MODULES


def test_spec_sources_its_excludes_from_the_shared_list() -> None:
    """The PyInstaller spec must not keep a second, drifting copy."""
    spec_text = (DESKTOP / "spectrasherpa.spec").read_text(encoding="utf-8")

    assert "from optional_exclusions import EXCLUDED_MODULES" in spec_text
    assert "excludes=list(EXCLUDED_MODULES)" in spec_text


def test_verifier_passes_a_clean_bundle(tmp_path) -> None:
    verifier = _load("verify_optional_exclusions")
    (tmp_path / "_internal" / "spectra_sherpa").mkdir(parents=True)
    (tmp_path / "_internal" / "spectra_sherpa" / "app.py").write_text("x", encoding="utf-8")

    assert verifier.find_violations(tmp_path) == []


@pytest.mark.parametrize(
    ("relative", "kind"),
    [
        ("_internal/asyncpg/__init__.py", "module package"),
        ("_internal/spectrochempy/__init__.py", "module package"),
        ("Contents/Frameworks/asyncpg/__init__.py", "macOS app layout"),
        ("_internal/asyncpg-0.30.0.dist-info/METADATA", "distribution metadata"),
        ("_internal/asyncpg.cpython-311-x86_64-linux-gnu.so", "compiled extension"),
    ],
)
def test_verifier_catches_bundled_extras(tmp_path, relative, kind) -> None:
    """Each shape an optional distribution can take in a real bundle."""
    verifier = _load("verify_optional_exclusions")
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")

    violations = verifier.find_violations(tmp_path)

    assert violations, f"{kind} went undetected: {relative}"


def test_hosted_service_clients_are_excluded_from_the_bundle() -> None:
    exclusions = _load("optional_exclusions")

    for module in exclusions.HOSTED_SERVICE_MODULES:
        assert module in exclusions.EXCLUDED_MODULES
    assert "spectra_sherpa.app.services.hybrid_device_client" in exclusions.HOSTED_SERVICE_MODULES


def _backend(root: Path) -> Path:
    executable = root / "SpectraSherpa.exe"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"synthetic")
    return root


@pytest.mark.parametrize(
    "module",
    [
        "spectra_sherpa.app.services.hybrid_device_client",
        "spectra_sherpa.app.api.v1.routes.hybrid",
        "spectra_sherpa.commercial_hybrid",
        "asyncpg",
        "spectrochempy",
    ],
)
def test_verifier_catches_modules_packed_inside_the_executable(tmp_path, module) -> None:
    """Pure-Python modules live in PyInstaller's embedded archive, not on disk."""
    verifier = _load("verify_optional_exclusions")
    root = _backend(tmp_path)

    violations = verifier.embedded_module_violations(root, lambda _exe: ["spectra_sherpa.app.main", module])

    assert violations == [f"embedded module present: SpectraSherpa.exe:{module}"]


def test_verifier_accepts_local_modules_and_requires_an_executable(tmp_path) -> None:
    verifier = _load("verify_optional_exclusions")
    local = [
        "spectra_sherpa.app.main",
        "spectra_sherpa.app.core.desktop_policy",
        "hapi_like_name",
        "hapi",
        "hapi2.db.sqlalchemy.sqlite",
    ]

    assert verifier.embedded_module_violations(_backend(tmp_path / "ok"), lambda _exe: local) == []
    missing = verifier.embedded_module_violations(tmp_path / "empty", lambda _exe: local)
    assert missing == ["backend executable not found; embedded modules were not inspected"]


def test_jedi_stubs_are_not_runtime_packages(tmp_path) -> None:
    verifier = _load("verify_optional_exclusions")
    stubs = tmp_path / "_internal/jedi/third_party/typeshed/stubs/gunicorn"
    module = stubs / "gunicorn"
    module.mkdir(parents=True)
    (stubs / "METADATA.toml").write_text('version = "23.*"')
    (module / "__init__.pyi").write_text("VERSION: str")
    assert verifier.find_violations(tmp_path) == []


@pytest.mark.parametrize("filename", ["__init__.py", "__init__.pyc", "worker.so", "worker.pyd"])
def test_jedi_stub_path_cannot_hide_runtime_code(tmp_path, filename) -> None:
    verifier = _load("verify_optional_exclusions")
    module = tmp_path / "_internal/jedi/third_party/typeshed/stubs/gunicorn/gunicorn"
    module.mkdir(parents=True)
    (module / "__init__.pyi").write_text("VERSION: str")
    (module / filename).write_bytes(b"runtime code")
    assert verifier.find_violations(tmp_path)
