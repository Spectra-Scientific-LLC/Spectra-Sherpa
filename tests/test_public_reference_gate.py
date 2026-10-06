from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("public_references", PACKAGE / "scripts/verify_public_references.py")
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


@pytest.fixture
def public_root(tmp_path: Path) -> Path:
    files = {
        ".github/workflows/ci.yml": (
            "jobs:\n  check:\n    steps:\n" "      - run: pytest tests/test_contract.py::test_real\n"
        ),
        "tests/test_contract.py": "def test_real(): pass\n",
        "frontend/package.json": json.dumps({"scripts": {"types": "openapi-typescript schema.json"}}),
        "frontend/schema.json": "{}",
        "desktop/electron/package.json": json.dumps(
            {"main": "main.cjs", "scripts": {"test": "node --test test/*.cjs"}}
        ),
        "desktop/electron/main.cjs": "",
        "desktop/electron/test/contract.cjs": "",
        "pyproject.toml": '[tool.poetry.scripts]\napp = "app.cli:main"\n',
        "src/app/cli.py": "def main(): pass\n",
        "README.md": "[guide](docs/guide.md)\n",
        "docs/guide.md": "# Guide\n",
    }
    for relative, text in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def test_current_public_references_resolve_in_this_layout() -> None:
    assert GATE.audit(PACKAGE)["failures"] == []


def test_stale_scp_selector_fails_before_test_execution(public_root: Path) -> None:
    workflow = public_root / ".github/workflows/ci.yml"
    workflow.write_text("- run: pytest tests/test_scp_compat.py\n")
    assert any("missing tests/test_scp_compat.py" in failure for failure in GATE.audit(public_root)["failures"])


def test_missing_test_function_is_not_mistaken_for_existing_file(public_root: Path) -> None:
    (public_root / "tests/test_contract.py").write_text("def test_renamed(): pass\n")
    assert any("missing selector" in failure for failure in GATE.audit(public_root)["failures"])


@pytest.mark.parametrize(
    "relative", ["frontend/schema.json", "desktop/electron/main.cjs", "src/app/cli.py", "docs/guide.md"]
)
def test_missing_entrypoint_or_link_fails(public_root: Path, relative: str) -> None:
    assert GATE.audit(public_root)["failures"] == []
    (public_root / relative).unlink()
    assert GATE.audit(public_root)["failures"]


def test_dynamic_artifacts_are_not_treated_as_checked_in_source(public_root: Path) -> None:
    workflow = public_root / ".github/workflows/ci.yml"
    workflow.write_text("- run: python scripts/runner.py --output desktop/evidence.json\n")
    script = public_root / "scripts/runner.py"
    script.parent.mkdir()
    script.write_text("pass\n")
    assert GATE.audit(public_root)["failures"] == []


def test_existing_private_file_cannot_satisfy_a_public_reference(public_root: Path) -> None:
    private = public_root.parent / "private-evidence.md"
    private.write_text("Private evidence exists in the monorepo only.\n")
    (public_root / "README.md").write_text("[evidence](../private-evidence.md)\n")
    assert any("escapes standalone package" in failure for failure in GATE.audit(public_root)["failures"])
