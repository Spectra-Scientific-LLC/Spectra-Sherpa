"""Saved credentials are encrypted with an OS-protected key on the desktop."""

from __future__ import annotations

import io
import json
import secrets

import pytest
from cryptography.fernet import Fernet
from dotenv import dotenv_values

from spectra_sherpa.app.services import basic_chat, encryption
from spectra_sherpa.desktop_session import DesktopProtocolError, DesktopSession


def _launch(**extra) -> DesktopSession:
    frame = {"protocol": 1, "type": "launch", "secret": secrets.token_urlsafe(32), **extra}
    session = DesktopSession(io.StringIO(json.dumps(frame) + "\n"), io.StringIO())
    session.initialize()
    return session


def test_launch_frame_carries_an_optional_credential_key():
    key = Fernet.generate_key().decode()
    assert _launch(credential_key=key).credential_key == key
    assert _launch().credential_key is None


@pytest.mark.parametrize("bad", ["short", "x" * 300, "has space in it!!", 42])
def test_malformed_credential_key_refuses_launch(bad):
    with pytest.raises(DesktopProtocolError):
        _launch(credential_key=bad)


@pytest.fixture
def process_key(monkeypatch):
    monkeypatch.setattr(encryption, "_process_master_key", None)
    encryption.set_process_master_key(Fernet.generate_key().decode())
    yield
    monkeypatch.setattr(encryption, "_process_master_key", None)


def test_process_key_is_used_and_no_plaintext_key_file_is_written(tmp_path, monkeypatch, process_key):
    monkeypatch.setattr(encryption, "_data_dir", lambda: tmp_path)
    monkeypatch.delenv("MASTER_ENCRYPTION_KEY", raising=False)

    token = encryption.encrypt_value("hitran-secret")

    assert encryption.decrypt_value(token) == "hitran-secret"
    assert not (tmp_path / ".env").exists()


def test_endpoint_key_is_saved_encrypted_and_read_back(tmp_path, monkeypatch, process_key):
    env = tmp_path / ".env"
    env.write_text("CHAT_ENDPOINT_URL=https://api.example.com\n", encoding="utf-8")
    monkeypatch.delenv("CHAT_ENDPOINT_KEY", raising=False)
    monkeypatch.delenv(basic_chat.ENCRYPTED_KEY_ENV, raising=False)

    basic_chat.persist_endpoint_key(str(env), "sk-live-secret")

    saved = dotenv_values(env)
    assert "sk-live-secret" not in env.read_text(encoding="utf-8")
    assert "CHAT_ENDPOINT_KEY" not in saved
    assert basic_chat.get_config().key == "sk-live-secret"


def test_plaintext_endpoint_key_is_migrated_at_desktop_startup(tmp_path, monkeypatch, process_key):
    env = tmp_path / ".env"
    env.write_text("CHAT_ENDPOINT_URL=https://api.example.com\nCHAT_ENDPOINT_KEY=sk-old-plaintext\n", encoding="utf-8")
    monkeypatch.delenv("CHAT_ENDPOINT_KEY", raising=False)
    monkeypatch.delenv(basic_chat.ENCRYPTED_KEY_ENV, raising=False)

    assert basic_chat.protect_plaintext_endpoint_key([env]) is True

    assert "sk-old-plaintext" not in env.read_text(encoding="utf-8")
    assert dotenv_values(env)["CHAT_ENDPOINT_URL"] == "https://api.example.com"
    assert basic_chat.get_config().key == "sk-old-plaintext"


def test_without_an_os_protected_key_behavior_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(encryption, "_process_master_key", None)
    env = tmp_path / ".env"
    env.write_text("CHAT_ENDPOINT_KEY=sk-plain\n", encoding="utf-8")

    assert basic_chat.protect_plaintext_endpoint_key([env]) is False
    assert dotenv_values(env)["CHAT_ENDPOINT_KEY"] == "sk-plain"


def test_unreadable_saved_key_degrades_to_reentry(monkeypatch, process_key):
    monkeypatch.delenv("CHAT_ENDPOINT_KEY", raising=False)
    monkeypatch.setenv(basic_chat.ENCRYPTED_KEY_ENV, Fernet(Fernet.generate_key()).encrypt(b"x").decode())

    assert basic_chat.get_config().key == ""


# --- Scope: only the admitted profile, only after exclusive ownership -------

from spectra_sherpa import desktop_launcher  # noqa: E402
from spectra_sherpa._paths import get_env_file_search_paths  # noqa: E402


def test_desktop_reads_and_writes_only_its_profile_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPECTRA_SHERPA_DESKTOP", "1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.chdir(tmp_path)

    assert get_env_file_search_paths() == [(tmp_path / "profile" / ".env").resolve()]


def _project_and_profile(tmp_path):
    project = tmp_path / "unrelated-project"
    project.mkdir()
    (project / ".env").write_text("CHAT_ENDPOINT_KEY=sk-other-project\n", encoding="utf-8")
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / ".env").write_text("CHAT_ENDPOINT_KEY=sk-profile\n", encoding="utf-8")
    return project, profile


def test_launch_migrates_only_the_admitted_profile_after_the_lock(tmp_path, monkeypatch, process_key):
    project, profile = _project_and_profile(tmp_path)
    monkeypatch.chdir(project)
    locked_at_migration = []
    real_protect = desktop_launcher._protect_profile_credentials

    def observe(data_dir):
        locked_at_migration.append((data_dir / desktop_launcher.DesktopInstanceLock.filename).exists())
        real_protect(data_dir)

    monkeypatch.setattr(desktop_launcher, "_protect_profile_credentials", observe)
    monkeypatch.setattr("spectra_sherpa.cli.main", lambda args: None)

    desktop_launcher.main(["--data-dir", str(profile), "--no-browser"])

    assert locked_at_migration == [True]
    assert (project / ".env").read_text(encoding="utf-8") == "CHAT_ENDPOINT_KEY=sk-other-project\n"
    assert "sk-profile" not in (profile / ".env").read_text(encoding="utf-8")


def test_launch_refused_for_a_busy_profile_leaves_credentials_unchanged(tmp_path, monkeypatch, process_key):
    _, profile = _project_and_profile(tmp_path)
    before = (profile / ".env").read_bytes()
    lock = desktop_launcher.DesktopInstanceLock(profile)
    lock.acquire()
    try:
        with pytest.raises(SystemExit):
            desktop_launcher.main(["--data-dir", str(profile), "--no-browser"])
    finally:
        lock.release()

    assert (profile / ".env").read_bytes() == before


def test_legacy_plaintext_master_key_is_retired_only_when_it_matches(tmp_path, monkeypatch):
    legacy = Fernet.generate_key().decode()
    monkeypatch.setattr(encryption, "_process_master_key", None)
    encryption.set_process_master_key(legacy)
    env = tmp_path / ".env"
    env.write_text(f"KEEP=1\nMASTER_ENCRYPTION_KEY={legacy}\n", encoding="utf-8")
    other = tmp_path / "other.env"
    other.write_text(f"MASTER_ENCRYPTION_KEY={Fernet.generate_key().decode()}\n", encoding="utf-8")

    assert encryption.retire_plaintext_master_key(env) is True
    assert env.read_text(encoding="utf-8") == "KEEP=1\n"
    assert encryption.retire_plaintext_master_key(other) is False
    monkeypatch.setattr(encryption, "_process_master_key", None)


# --- No OS protection: refuse persistent credentials, keep analysis ---------


@pytest.fixture
def unprotected_desktop(monkeypatch, tmp_path):
    monkeypatch.setattr(encryption, "_process_master_key", None)
    monkeypatch.setenv("SPECTRA_SHERPA_DESKTOP", "1")
    monkeypatch.setattr(encryption, "_data_dir", lambda: tmp_path)
    monkeypatch.delenv("MASTER_ENCRYPTION_KEY", raising=False)
    return tmp_path


def test_unprotected_desktop_refuses_to_encrypt_or_decrypt(unprotected_desktop):
    with pytest.raises(encryption.CredentialStorageUnavailable):
        encryption.encrypt_value("hitran-secret")
    with pytest.raises(encryption.CredentialStorageUnavailable):
        encryption.decrypt_value("anything")
    assert not (unprotected_desktop / ".env").exists()


def test_unprotected_desktop_never_uses_or_saves_a_plaintext_ai_key(unprotected_desktop, monkeypatch):
    env = unprotected_desktop / ".env"
    env.write_text("CHAT_ENDPOINT_KEY=sk-plain\n", encoding="utf-8")
    monkeypatch.setenv("CHAT_ENDPOINT_KEY", "sk-plain")

    assert basic_chat.get_config().key == ""
    with pytest.raises(encryption.CredentialStorageUnavailable):
        basic_chat.persist_endpoint_key(str(env), "sk-new")
    assert env.read_text(encoding="utf-8") == "CHAT_ENDPOINT_KEY=sk-plain\n"


def test_pip_installs_keep_their_file_based_behavior(monkeypatch, tmp_path):
    monkeypatch.setattr(encryption, "_process_master_key", None)
    monkeypatch.delenv("SPECTRA_SHERPA_DESKTOP", raising=False)
    monkeypatch.setattr(encryption, "_data_dir", lambda: tmp_path)
    monkeypatch.delenv("MASTER_ENCRYPTION_KEY", raising=False)

    assert encryption.credential_storage_available() is True
    assert encryption.decrypt_value(encryption.encrypt_value("x")) == "x"


from spectra_sherpa.app.core.desktop_policy import LinkedConfigurationRefused  # noqa: E402

LINKS = ["symlink", "hardlink"]


def _linked_env(tmp_path, kind: str):
    outside = tmp_path / "other-project" / ".env"
    outside.parent.mkdir()
    original = "CHAT_ENDPOINT_KEY=sk-other-project\nMASTER_ENCRYPTION_KEY=other\n"
    outside.write_text(original, encoding="utf-8")
    profile = tmp_path / "profile"
    profile.mkdir()
    env = profile / ".env"
    try:
        env.symlink_to(outside) if kind == "symlink" else env.hardlink_to(outside)
    except OSError:
        pytest.skip(f"{kind} unavailable on this filesystem")
    return profile, env, outside, original


@pytest.mark.parametrize("kind", LINKS)
def test_saving_a_key_never_writes_through_a_linked_env(tmp_path, monkeypatch, process_key, kind):
    monkeypatch.setenv("SPECTRA_SHERPA_DESKTOP", "1")
    _, env, outside, original = _linked_env(tmp_path, kind)

    with pytest.raises(LinkedConfigurationRefused):
        basic_chat.persist_endpoint_key(str(env), "sk-new")

    assert outside.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("kind", LINKS)
def test_startup_migration_skips_a_linked_env(tmp_path, monkeypatch, process_key, kind):
    monkeypatch.setenv("SPECTRA_SHERPA_DESKTOP", "1")
    profile, _, outside, original = _linked_env(tmp_path, kind)

    desktop_launcher._protect_profile_credentials(profile)

    assert outside.read_text(encoding="utf-8") == original
