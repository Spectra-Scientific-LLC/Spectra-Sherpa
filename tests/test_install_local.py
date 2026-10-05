"""Installation choice tests never install packages or contact an index."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install_local.py"
spec = importlib.util.spec_from_file_location("install_local", SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_guided_choices_precede_one_pip_call(monkeypatch):
    monkeypatch.setattr(installer.sys.stdin, "isatty", lambda: True)
    answers = iter(["invalid", "yes", "y", "no"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    run = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(installer.subprocess, "run", run)
    assert installer.main(["--version", "0.6.0"]) == 0
    assert run.call_args.args[0] == [
        installer.sys.executable,
        "-m",
        "pip",
        "install",
        "spectra-sherpa[scp,hitran]==0.6.0",
    ]


@pytest.mark.parametrize("kind", ["source", "wheel"])
def test_exact_local_target_with_spaces(kind, tmp_path, monkeypatch):
    target = tmp_path / ("candidate source" if kind == "source" else "candidate build.whl")
    if kind == "source":
        target.mkdir()
        (target / "pyproject.toml").touch()
    else:
        target.touch()
    run = Mock(return_value=Mock(returncode=7))
    monkeypatch.setattr(installer.subprocess, "run", run)
    assert installer.main([f"--{kind}", str(target), "--extras", "hitran,nist"]) == 7
    assert run.call_args.args[0][-1] == f"{target}[hitran,nist]"
    assert "shell" not in run.call_args.kwargs


def test_dry_run_and_base_do_not_install(monkeypatch, capsys):
    run = Mock()
    monkeypatch.setattr(installer.subprocess, "run", run)
    assert installer.main(["--version", "0.6.0", "--base", "--dry-run"]) == 0
    assert "spectra-sherpa==0.6.0" in capsys.readouterr().out
    run.assert_not_called()


@pytest.mark.parametrize("choices", [[], ["--extras", "unknown"], ["--extras", ""]])
def test_noninteractive_or_invalid_choices_fail_before_pip(choices, monkeypatch):
    monkeypatch.setattr(installer.sys.stdin, "isatty", lambda: False)
    run = Mock()
    monkeypatch.setattr(installer.subprocess, "run", run)
    with pytest.raises(SystemExit):
        installer.main(["--version", "0.6.0", *choices])
    run.assert_not_called()
