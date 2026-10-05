from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_public_tests.py"
SPEC = importlib.util.spec_from_file_location("run_public_tests", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
PROFILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILE)


def test_public_profile_is_closed_and_current() -> None:
    assert PROFILE.profile_failures() == []
    arguments = PROFILE.pytest_arguments()
    assert arguments[:3] == ["tests", "-v", "--no-cov"]
    assert sum(argument.startswith("--ignore=") for argument in arguments) == len(PROFILE.UPSTREAM_AUTHORITY_MODULES)
    assert sum(argument.startswith("--deselect=") for argument in arguments) == len(PROFILE.UPSTREAM_AUTHORITY_NODE_IDS)


def test_public_profile_never_excludes_the_lifecycle_or_profile_guards() -> None:
    excluded = "\n".join((*PROFILE.UPSTREAM_AUTHORITY_MODULES, *PROFILE.UPSTREAM_AUTHORITY_NODE_IDS))
    assert "test_release_publication_truth.py" not in excluded
    assert "test_public_ci_test_profile.py" not in excluded


def test_missing_private_authority_function_refuses(monkeypatch) -> None:
    monkeypatch.setattr(
        PROFILE,
        "UPSTREAM_AUTHORITY_NODE_IDS",
        ("tests/test_collection_definition.py::test_does_not_exist",),
    )
    assert PROFILE.profile_failures() == [
        "missing upstream-authority test function:tests/test_collection_definition.py::test_does_not_exist"
    ]
