"""Ubuntu packaging preserves application bytes, sandbox and release authority."""

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

PACKAGE = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name == "nt", reason="Ubuntu AppImage tools require a POSIX filesystem and shell")


def load(name):
    spec = importlib.util.spec_from_file_location(name, PACKAGE / f"desktop/ubuntu/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_appdir_preserves_backend_and_symlinks_and_launcher_arguments(tmp_path):
    source = tmp_path / "electron"
    (source / "resources").mkdir(parents=True)
    (source / "resources/app.asar").write_bytes(b"app")
    (source / "resources/backend").write_bytes(b"exact-model-runtime")
    (source / "backend-link").symlink_to("resources/backend")
    binary = source / "SpectraSherpa"
    binary.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    binary.chmod(0o755)
    target = tmp_path / "Application.AppDir"
    load("package").stage(source, target)
    assert (target / "backend-link").is_symlink()
    assert (target / "backend-link").read_bytes() == b"exact-model-runtime"
    result = subprocess.run(
        [str(target / "AppRun"), "argument with spaces"], capture_output=True, text=True, check=True
    )
    assert result.stdout == "argument with spaces\n"
    assert "--no-sandbox" not in result.stdout
    assert (target / "spectrasherpa.png").is_file()


def test_checksum_mismatch_refuses_cached_build_tool(tmp_path):
    path = tmp_path / "tool"
    path.write_bytes(b"untrusted")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        load("package").fetch_tool({"sha256": "0" * 64}, path)


def test_ci_policy_is_path_scoped_and_rejects_policy_injection():
    policy = load("ci_policy")
    text = policy.policy(["/tmp/approved/SpectraSherpa"])
    assert f'"{Path("/tmp/approved/SpectraSherpa").resolve()}"' in text and "userns," in text
    for unsafe in ("/tmp/*", '/tmp/evil" { userns, }', "/tmp/a\nprofile other"):
        with pytest.raises(ValueError):
            policy.policy([unsafe])


def test_installer_can_print_only_its_own_policy_without_running_backend(tmp_path):
    script = PACKAGE / "desktop/ubuntu/AppRun"
    result = subprocess.run(
        ["sh", str(script), "--print-sandbox-policy"],
        env={**os.environ, "APPIMAGE": "/home/scientist/Applications/SpectraSherpa.AppImage"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert '"/home/scientist/Applications/SpectraSherpa.AppImage"' in result.stdout
    assert "userns," in result.stdout and "sysctl" not in result.stdout


def test_ubuntu_precedes_signed_native_builds_and_is_part_of_release():
    public = yaml.load((PACKAGE / ".github/workflows/desktop-release.yml").read_text(), Loader=yaml.BaseLoader)
    assert public["jobs"]["build"]["needs"] == "ubuntu"
    assert set(public["jobs"]["upload"]["needs"]) == {"ubuntu", "build"}
    ubuntu = public["jobs"]["ubuntu"]
    assert ubuntu["runs-on"] == "ubuntu-24.04"
    assert "ubuntu-x86_64" in str(ubuntu)
    for name, record in json.loads((PACKAGE / "desktop/ubuntu/tools.json").read_text()).items():
        assert len(record["sha256"]) == 64
        assert "/continuous/" not in record["url"]
    source = (PACKAGE / "desktop/ubuntu/qualify.sh").read_text()
    assert 'hardened-smoke.cjs "$PWD/desktop/dist/SpectraSherpa.AppImage"' in source
    assert "--no-sandbox" not in source


def test_failed_native_qualification_retains_failure_evidence(tmp_path):
    commands = tmp_path / "bin"
    commands.mkdir()
    keyring = commands / "gnome-keyring-daemon"
    keyring.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
    keyring.chmod(0o755)
    result = subprocess.run(
        ["bash", str(PACKAGE / "desktop/ubuntu/qualify.sh")],
        cwd=tmp_path,
        env={**os.environ, "PATH": str(commands) + os.pathsep + os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 7
    receipt = json.loads((tmp_path / "desktop/ubuntu-evidence/qualification.json").read_text())
    assert receipt["native_startup_and_restart"] == "failed"
    assert receipt["stage"] == "credential_store"
    assert receipt["clean_machine_acceptance"] == "pending"
