from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]
STATIC_PATH = "packages/spectra-sherpa/src/spectra_sherpa/static"


def _workflow(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_vite_output_is_ignored_and_not_tracked() -> None:
    ignored = (PACKAGE_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "src/spectra_sherpa/static/" in ignored
    tracked = subprocess.run(
        ["git", "ls-files", "src/spectra_sherpa/static"],
        cwd=PACKAGE_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert tracked == ""


def test_wheel_and_sdist_both_admit_generated_frontend() -> None:
    config = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    static = next(
        item for item in config["tool"]["poetry"]["include"] if item["path"] == "src/spectra_sherpa/static/**/*"
    )
    assert static["format"] == ["sdist", "wheel"]


def test_monorepo_ci_regenerates_compares_and_qualifies_distributions(monorepo_root: Path) -> None:
    source = _workflow(".github/workflows/ci.yml")
    frontend = source.split("  sherpa-frontend:\n", 1)[1].split("  server-frontend:\n", 1)[0]
    assert "Refuse tracked Vite output" in frontend
    assert "SHERPA_FRONTEND_OUT_DIR" in frontend
    assert "compare-frontends" in frontend
    assert "verify-frontends" in frontend
    assert frontend.index("compare-frontends") < frontend.index("python -m build")


def test_public_ci_regenerates_compares_and_qualifies_distributions() -> None:
    public_source = (PACKAGE_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    public_frontend = public_source.split("  frontend:\n", 1)[1].split("  security:\n", 1)[0]
    assert "Refuse tracked Vite output" in public_frontend
    assert "git ls-files src/spectra_sherpa/static" in public_frontend
    assert "SHERPA_FRONTEND_OUT_DIR" in public_frontend
    assert "compare-frontends" in public_frontend
    assert "verify-frontends" in public_frontend
    assert "git status --porcelain -- src/spectra_sherpa/static" not in public_frontend


def test_public_scp_ci_selects_existing_compatibility_contracts() -> None:
    source = (PACKAGE_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    job = source.split("  scp-compat:\n", 1)[1].split("  frontend:\n", 1)[0]
    paths = set(re.findall(r"tests/[\w/]+\.py", job))
    assert {
        "tests/test_scp_contracts.py",
        "tests/test_scp_node_contracts.py",
        "tests/test_c2_scp_unmixing_contracts.py",
        "tests/test_nddataset_containment.py",
    } <= paths
    for path in paths:
        assert (PACKAGE_ROOT / path).is_file(), f"Public SCP CI names a missing test: {path}"


def test_security_and_curated_publish_build_frontend_before_python_artifacts(monorepo_root: Path) -> None:
    for path in (".github/workflows/oss-security-preflight.yml", ".github/workflows/oss-publish.yml"):
        source = _workflow(path)
        assert "npm ci" in source
        assert "npm run build" in source
        assert "verify-frontends" in source
        assert source.index("npm run build") < source.index("python -m build")


def test_backend_docker_builds_and_qualifies_frontend_inside_public_wheel(monorepo_root: Path) -> None:
    dockerfile = (REPO_ROOT / "packages/spectra-ops/docker/Dockerfile.backend").read_text(encoding="utf-8")
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "FROM node:22-slim AS sherpa-ui-build" in dockerfile
    sherpa_ui_stage = dockerfile.split("FROM node:22-slim AS sherpa-ui-build", 1)[1].split(
        "FROM python:3.11-slim AS public-wheel-build", 1
    )[0]
    registry = "packages/spectra-sherpa/src/spectra_sherpa/data/plate_formats_v1.json"
    assert registry in sherpa_ui_stage
    assert sherpa_ui_stage.index(registry) < sherpa_ui_stage.index("RUN npm run build")
    assert "COPY --from=sherpa-ui-build" in dockerfile
    assert "verify-frontend-archive" in dockerfile
    assert dockerfile.index("COPY --from=sherpa-ui-build") < dockerfile.index("python -m build --wheel")
    assert STATIC_PATH in dockerignore

    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    image_job = workflow.split("  staging-backend-image:\n", 1)[1]
    assert "if: needs.changes.outputs.backend_image == 'true'" in image_job
    assert "github.event_name == 'push'" not in image_job


def test_public_frontend_docker_builds_from_locked_source() -> None:
    public_frontend = (PACKAGE_ROOT / "frontend/Dockerfile").read_text(encoding="utf-8")
    assert "FROM node:22-slim AS build-stage" in public_frontend
    assert "COPY frontend/package*.json ./" in public_frontend
    assert "COPY src/spectra_sherpa/data/plate_formats_v1.json" in public_frontend
    assert "COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf" in public_frontend
    assert public_frontend.index("plate_formats_v1.json") < public_frontend.index("RUN npm run build")
    assert "RUN npm ci" in public_frontend
    assert "node:20" not in public_frontend


def test_clean_source_launch_instructions_generate_the_ignored_frontend() -> None:
    paths = (
        PACKAGE_ROOT / "README.md",
        PACKAGE_ROOT / "docs/onboarding/local-30-minutes.md",
        PACKAGE_ROOT / "docs/onboarding/choose-your-path.md",
        PACKAGE_ROOT / "docs/releases/0.6.0.md",
        PACKAGE_ROOT / "docs/developers/setup.md",
        PACKAGE_ROOT / "docs/onboarding/migrate-to-0.6.md",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "npm --prefix frontend ci" in source, path
        assert "npm --prefix frontend run build" in source, path
