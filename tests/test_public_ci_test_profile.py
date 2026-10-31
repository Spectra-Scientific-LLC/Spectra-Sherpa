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


def test_timing_environment_reaches_real_pytest_without_opening_runner_parser(tmp_path):
    import os
    import subprocess
    import sys

    probe = tmp_path / "test_timing_probe.py"
    probe.write_text("def test_failure():\n    assert False, 'timing-exit-proof'\n")
    # Exercise the actual closed parser and pytest.main; replace only the test
    # population so this contract does not recursively run the public suite.
    code = (
        "import runpy,sys; "
        f"module=runpy.run_path({str(SCRIPT)!r}); "
        "main=module['main']; "
        f"main.__globals__['pytest_arguments']=lambda: [{str(probe)!r}, '-o', 'addopts=']; "
        "sys.argv=['run_public_tests.py']; sys.exit(main())"
    )
    env = {**os.environ, "PYTEST_ADDOPTS": "--durations=0 --durations-min=0", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "timing-exit-proof" in result.stdout
    assert "slowest durations" in result.stdout and "call" in result.stdout
    refused = subprocess.run(
        [sys.executable, str(SCRIPT), "--durations=0"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert refused.returncode == 2 and "unrecognized arguments" in refused.stderr
