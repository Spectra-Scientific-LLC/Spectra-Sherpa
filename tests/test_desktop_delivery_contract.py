"""Native packaging paths and retained evidence must survive workflow edits.

These are source contract tests, not a substitute for native installer runs.
"""

import re
from pathlib import Path

import pytest
import yaml

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[1]
PUBLIC = PACKAGE / ".github/workflows/desktop-release.yml"
SMOKE = ROOT / ".github/workflows/desktop-bundle.yml"
WORKFLOWS = [PUBLIC] + ([SMOKE] if SMOKE.exists() else [])


def workflow(path):
    return yaml.load(path.read_text(), Loader=yaml.BaseLoader)


def test_inno_input_is_exact_pyinstaller_output_directory():
    source = (PACKAGE / "desktop/windows_installer.iss").read_text()
    inputs = re.findall(r'^Source: "([^"]+)"', source, re.MULTILINE)
    source_dirs = {
        (PACKAGE / "desktop" / relative.replace("\\", "/").removesuffix("/*")).resolve() for relative in inputs
    }
    assert source_dirs == {
        PACKAGE / "desktop/dist/SpectraSherpa",
        PACKAGE / "desktop/electron/out/SpectraSherpa-win32-x64",
    }
    assert "PrivilegesRequired=lowest" in source
    assert "{userprofile}" not in source
    assert "{%USERPROFILE}" in source
    flags = re.search(r"^Source:.*Flags: (.+)$", source, re.MULTILINE).group(1).split()
    assert flags == ["ignoreversion", "recursesubdirs", "createallsubdirs"]


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.parent.parent.parent.name)
def test_windows_smoke_waits_for_installation_and_preserves_real_data(path):
    jobs = workflow(path)["jobs"]
    steps = next(job["steps"] for job in jobs.values() if "strategy" in job)
    script = next(step["run"] for step in steps if step.get("name") == "Verify Windows Installer")
    for process in ("Install", "Uninstall"):
        line = next(line for line in script.splitlines() if line.strip().startswith(f"${process} ="))
        assert "Start-Process" in line and "-Wait" in line and "-PassThru" in line
        assert f"${process}.ExitCode -ne 0" in script
    for line in script.splitlines():
        if "-RedirectStandardError" in line:
            stderr = re.search(r'-RedirectStandardError "([^"]+)"', line).group(1)
            stdout = re.search(r'-RedirectStandardOutput "([^"]+)"', line).group(1)
            assert stderr != stdout
    assert "Set-Content -LiteralPath $Sentinel" in script
    assert "Get-Content -LiteralPath $Sentinel -Raw" in script
    assert "Get-ChildItem -LiteralPath $DataDir -Recurse -File" in script
    assert script.index("$BeforeData =") < script.index("$Uninstall =") < script.index("$AfterData =")
    assert "$BeforeData.Count -eq 0" in script
    assert "Silent uninstall changed persisted workflow data" in script


@pytest.mark.skipif(not SMOKE.exists(), reason="Monorepo smoke workflow is not exported")
def test_unsigned_outputs_are_retained_separately_from_public_releases():
    spec = workflow(SMOKE)
    assert spec["permissions"]["contents"] == "read"
    steps = spec["jobs"]["bundle-smoke"]["steps"]
    upload = next(s for s in steps if s.get("name") == "Retain unsigned candidates (not public releases)")
    assert upload["with"]["name"].startswith("unsigned-desktop-")
    assert upload["with"]["if-no-files-found"] == "error"
    assert "SpectraSherpa-macos-unsigned.zip" in upload["with"]["path"]
    assert "SpectraSherpa_Setup.exe" in upload["with"]["path"]
    assert "gh release" not in SMOKE.read_text()


def test_migration_import_discovery_covers_scripts_loaded_as_data(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("desktop_migration_imports", PACKAGE / "desktop/migration_imports.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "env.py").write_text(
        "from spectra_sherpa.app.db.sqlite_migration import migration_transaction\n"
        "import spectra_sherpa.app.models\n"
        "raise RuntimeError('must never execute migration during discovery')\n"
    )
    assert module.migration_hidden_imports(tmp_path) == [
        "spectra_sherpa.app.db.sqlite_migration",
        "spectra_sherpa.app.models",
    ]
    actual = module.migration_hidden_imports(PACKAGE / "src/spectra_sherpa/alembic")
    assert "spectra_sherpa.app.db.sqlite_migration" in actual
    assert "spectra_sherpa.app.db.retired_doe_migration" in actual
    assert "spectra_sherpa.app.db.run_evidence_migration" in actual
    assert (
        'migration_hidden_imports(PACKAGE_SOURCE / "alembic")' in (PACKAGE / "desktop/spectrasherpa.spec").read_text()
    )


@pytest.mark.parametrize("path", WORKFLOWS)
def test_frontend_probe_uses_supported_get_not_head(path):
    source = path.read_text()
    assert "-Method Head" not in source
    assert "curl --fail --silent -I " not in source
    if path == PUBLIC:
        assert "npm --prefix desktop/electron run smoke" in source
        assert "hardened-smoke.cjs" in source
    else:
        assert "-Method Get -UseBasicParsing" in source
        assert "--dump-header - --output /dev/null" in source


def test_signing_lane_has_pinned_actions_and_job_scoped_authority():
    spec = workflow(PUBLIC)
    assert spec["permissions"] == {}
    assert spec["jobs"]["build"]["permissions"] == {"contents": "read", "id-token": "write", "attestations": "write"}
    assert spec["jobs"]["upload"]["permissions"] == {"contents": "write"}
    for job in spec["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[\w/-]+@[a-f0-9]{40}", step["uses"])
    steps = spec["jobs"]["build"]["steps"]
    named = {step.get("name"): step for step in steps}
    assert named["Retain signing evidence"]["with"]["if-no-files-found"] == "error"
    assert steps.index(named["Validate required signing evidence"]) < steps.index(
        named["Prepare versioned artifact and identity manifest"]
    )
    assert named["Install Inno Setup"]["run"] == "./desktop/install_inno.ps1"
    source = (PACKAGE / "desktop/install_inno.ps1").read_text()
    assert source.index("Get-FileHash") < source.index("Start-Process")
    assert "0bcb2a409dea17e305a27a6b09555cabe600e984f88570ab72575cd7e93c95e6" in source


def test_pinned_inno_compiler_is_used_instead_of_runner_preinstallation():
    bootstrap = (PACKAGE / "desktop/install_inno.ps1").read_text()
    compiler = (PACKAGE / "desktop/build_windows.ps1").read_text()
    assert "[guid]::NewGuid()" in bootstrap
    assert '/DIR=`"$InstallDir`"' in bootstrap
    assert "INNO_ISCC_PATH=$Compiler" in bootstrap
    assert "$env:INNO_ISCC_PATH" in compiler
    assert "VersionInfo.FileVersion" not in bootstrap


def test_uninstall_removes_runtime_cache_but_keeps_user_data_unless_asked():
    source = (PACKAGE / "desktop/windows_installer.iss").read_text()
    section = source.split("[UninstallDelete]", 1)[1].split("[", 1)[0]
    assert 'Name: "{userappdata}\\Spectra Sherpa"' in section
    assert ".spectra_sherpa" not in section
    # The profile is deleted only after an interactive, default-No question.
    assert "MB_DEFBUTTON2" in source and "if not UninstallSilent() then" in source


def test_operator_can_pause_tag_desktop_builds_without_blocking_manual_candidates():
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/desktop-release.yml").read_text())
    assert workflow["jobs"]["ubuntu"]["if"] == (
        "${{ github.event_name == 'workflow_dispatch' || vars.DESKTOP_RELEASE_PAUSED != 'true' }}"
    )
    assert workflow["jobs"]["build"]["needs"] == "ubuntu"
