"""Installer payload integrity and offline HITRAN qualification contracts."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

DESKTOP = Path(__file__).resolve().parents[1] / "desktop"


def load(name):
    spec = importlib.util.spec_from_file_location(name, DESKTOP / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def payload(tmp_path, monkeypatch):
    bundle = load("hitran_bundle")
    entries = {}
    archives = {}
    installed = {}
    for name, original in bundle.CLIENTS.items():
        entry = dict(original)
        source = entry["module"] + "/__init__.py"
        members = {
            entry["source_prefix"] + source: b"# original Python source\n",
            entry["license_member"]: b"upstream license\n",
        }
        buffer = io.BytesIO()
        if entry["filename"].endswith(".whl"):
            with zipfile.ZipFile(buffer, "w") as archive:
                for path, data in members.items():
                    archive.writestr(path, data)
        else:
            with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
                for path, data in members.items():
                    info = tarfile.TarInfo(path)
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
        data = buffer.getvalue()
        entry["sha256"] = hashlib.sha256(data).hexdigest()
        entries[name] = entry
        archives[entry["url"]] = data
        code = tmp_path / "installed" / source
        code.parent.mkdir(parents=True)
        code.write_bytes(members[entry["source_prefix"] + source])
        installed[name] = SimpleNamespace(
            version=entry["version"], files=[PurePosixPath(source)], locate_file=lambda f: tmp_path / "installed" / f
        )
    monkeypatch.setattr(bundle, "CLIENTS", entries)
    return bundle, installed, archives, tmp_path / "payload"


def prepare(payload):
    bundle, installed, archives, destination = payload
    return bundle.prepare(destination, distribution=installed.__getitem__, download=archives.__getitem__)


def test_source_notices_and_frozen_payload_are_verified(payload):
    destination = prepare(payload)
    verifier = load("verify_hitran_clients")
    verifier.verify_payload(destination)
    assert json.loads((destination / "manifest.json").read_text()) == payload[0].CLIENTS
    assert (destination / "README.txt").is_file()


@pytest.mark.parametrize("failure", ["version", "archive", "installed_source", "missing_source"])
def test_prepare_rejects_source_or_version_mismatch(payload, failure):
    bundle, installed, archives, destination = payload
    name = "hitran-api2"
    if failure == "version":
        installed[name].version = "0.0.0"
    elif failure == "archive":
        archives[bundle.CLIENTS[name]["url"]] = b"wrong archive"
    elif failure == "installed_source":
        installed[name].locate_file(installed[name].files[0]).write_text("changed")
    else:
        installed[name].files = []
    with pytest.raises(ValueError):
        prepare(payload)


@pytest.mark.parametrize("failure", ["source", "license", "manifest", "directions"])
def test_artifact_verifier_rejects_lost_or_changed_evidence(payload, failure):
    destination = prepare(payload)
    entry = payload[0].CLIENTS["hitran-api2"]
    name = {
        "source": entry["filename"],
        "license": "hitran-api2-LICENSE.txt",
        "manifest": "manifest.json",
        "directions": "README.txt",
    }[failure]
    (destination / name).write_text("{}" if failure == "manifest" else "")
    with pytest.raises(ValueError):
        load("verify_hitran_clients").verify_payload(destination)


def test_all_build_lanes_use_positive_client_qualification():
    verifier = (DESKTOP / "verify_optional_exclusions.py").read_text()
    assert "from verify_hitran_clients import verify" in verifier
    assert "verify(args.bundle)" in verifier
    spec = (DESKTOP / "spectrasherpa.spec").read_text()
    assert "hiddenimports += HIDDEN_IMPORTS" in spec
    assert "copy_metadata(distribution)" in spec
    assert 'module_collection_mode={"hapi2": "py"}' in spec
    assert '"third_party/hitran"' in spec
    entry = (DESKTOP / "desktop_entry.py").read_text()
    assert 'sys.argv[1] == "--verify-hitran-clients"' in entry
    assert "sys.dont_write_bytecode = True" in entry


def test_desktop_pins_match_package_lock():
    import tomllib

    bundle = load("hitran_bundle")
    package = DESKTOP.parent
    lock = tomllib.loads((package / "poetry.lock").read_text())
    locked = {row["name"]: row["version"] for row in lock["package"]}
    requirements = (DESKTOP / "requirements.txt").read_text()
    for name, entry in bundle.CLIENTS.items():
        assert locked[name] == entry["version"]
        assert f"{name}=={entry['version']}" in requirements


def test_offline_real_clients_when_installed(tmp_path):
    # Base pip installs intentionally do not require the optional clients.
    if importlib.util.find_spec("hapi") is None or importlib.util.find_spec("hapi2") is None:
        pytest.skip("real client imports are mandatory in every frozen-build verifier")
    output = tmp_path / "receipt.json"
    subprocess.run(
        [sys.executable, str(DESKTOP / "hitran_runtime_check.py"), str(output)],
        check=True,
        timeout=120,
        capture_output=True,
    )
    result = json.loads(output.read_text())
    assert result["offline"] is True
    assert result["sqlite_query"] == 1
    assert result["lorentz_profile"][1] == pytest.approx(1 / 3.141592653589793)


def test_frozen_offline_cache_is_parent_owned_and_removed_after_child_exit(tmp_path, monkeypatch):
    runtime = load("hitran_runtime_check")
    verifier = load("verify_hitran_clients")
    root = tmp_path / "bundle"
    payload = root / "third_party" / "hitran"
    payload.mkdir(parents=True)
    (payload / "manifest.json").write_text("{}", encoding="utf-8")
    (root / "SpectraSherpa.exe").write_bytes(b"fake executable")
    monkeypatch.setattr(verifier, "verify_payload", lambda _: None)
    cache_paths = []

    def finished_child(argv, *, cwd, env, check, timeout):
        receipt = Path(argv[2])
        cache = runtime._offline_cache(receipt)
        cache_paths.append(cache)
        assert cache.parent == receipt.parent
        (cache / "headers.sqlite").write_bytes(b"sqlite fixture")
        receipt.write_text(
            json.dumps(
                {
                    "versions": {name: entry["version"] for name, entry in verifier.CLIENTS.items()},
                    "offline": True,
                    "sqlite_query": 1,
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(verifier.subprocess, "run", finished_child)
    verifier.verify(root)
    assert len(cache_paths) == 1
    assert not cache_paths[0].exists()


def test_frozen_hapi2_cache_is_profile_owned(tmp_path, monkeypatch):
    from spectra_sherpa.app.services import synthesis

    original_cwd = Path.cwd()
    cache = tmp_path / "profile" / "hapi2"
    config = SimpleNamespace(CACHE_DIR="unrelated-build-cache")
    fake_hapi2 = SimpleNamespace()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setitem(sys.modules, "numba", SimpleNamespace(config=config))
    monkeypatch.setitem(sys.modules, "hapi2", fake_hapi2)
    assert synthesis._import_hapi2_module(cache) is fake_hapi2
    assert config.CACHE_DIR == str(cache / "numba-cache")
    assert Path(config.CACHE_DIR).is_dir()
    assert Path.cwd() == original_cwd
