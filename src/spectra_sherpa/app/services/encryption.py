from __future__ import annotations

import base64
import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

from spectra_sherpa._paths import get_default_data_dir

logger = logging.getLogger(__name__)

ENV_FILENAME = ".env"


def _data_dir() -> Path:
    return get_default_data_dir()


def _read_env_key(env_path: Path) -> Optional[str]:
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith("MASTER_ENCRYPTION_KEY="):
            return line.split("=", 1)[1].strip() or None
    return None


def _looks_like_fernet_key(value: str) -> bool:
    try:
        decoded = base64.urlsafe_b64decode(value.encode())
    except Exception:
        logger.debug("Value does not look like a Fernet key (decode failed)", exc_info=True)
        return False
    return len(decoded) == 32


def _normalize_master_key(value: str) -> bytes:
    """Return a Fernet-compatible key from either a raw Fernet key or a secret."""
    if _looks_like_fernet_key(value):
        return value.encode()
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest())


class CredentialStorageUnavailable(RuntimeError):
    """Saved credentials are refused because OS credential protection is unavailable."""

    MESSAGE = (
        "Saved API keys are unavailable because this computer's credential protection "
        "could not be used. Analysis still works; AI and HITRAN features that need a "
        "saved key are disabled until protection is available."
    )

    def __init__(self) -> None:
        super().__init__(self.MESSAGE)


def credential_storage_available() -> bool:
    """False only in the desktop app when the OS-protected key is missing."""
    from spectra_sherpa.app.core.desktop_policy import is_desktop

    return _process_master_key is not None or not is_desktop()


# Set by the desktop launcher from the OS-protected key the native shell sends
# over its private launch pipe. When present it is the only key source, and no
# plaintext key is ever written to the profile.
_process_master_key: Optional[bytes] = None


def set_process_master_key(value: str) -> None:
    global _process_master_key
    _process_master_key = _normalize_master_key(value)


def has_process_master_key() -> bool:
    return _process_master_key is not None


def retire_plaintext_master_key(env_path: Path) -> bool:
    """Remove a legacy plaintext key from the profile ``.env`` once it is protected.

    Only a line whose value matches the OS-protected process key is removed, so
    a different project's key or an unrelated secret is never touched.
    """
    if _process_master_key is None or not env_path.is_file():
        return False
    from spectra_sherpa.app.core.desktop_policy import refuse_linked_configuration

    refuse_linked_configuration(env_path)
    lines = env_path.read_text().splitlines(keepends=True)
    kept = [
        line
        for line in lines
        if not (
            line.startswith("MASTER_ENCRYPTION_KEY=")
            and line.split("=", 1)[1].strip()
            and _normalize_master_key(line.split("=", 1)[1].strip()) == _process_master_key
        )
    ]
    if len(kept) == len(lines):
        return False
    env_path.write_text("".join(kept))
    return True


def get_master_key() -> bytes:
    if _process_master_key is not None:
        return _process_master_key
    if not credential_storage_available():
        # Never fall back to a plaintext key file in the desktop app.
        raise CredentialStorageUnavailable()
    key = os.getenv("MASTER_ENCRYPTION_KEY")
    if key:
        return _normalize_master_key(key)

    data = _data_dir()
    env_path = data / ENV_FILENAME
    key = _read_env_key(env_path)
    if key:
        return _normalize_master_key(key)

    generated_key = Fernet.generate_key()
    try:
        data.mkdir(parents=True, exist_ok=True)
        with env_path.open("a") as env_file:
            env_file.write(f"\nMASTER_ENCRYPTION_KEY={generated_key.decode()}\n")
        os.chmod(env_path, 0o600)
    except OSError:
        pass

    return generated_key


def encrypt_value(value: str) -> str:
    fernet = Fernet(get_master_key())
    return fernet.encrypt(value.encode()).decode()


def decrypt_value(value: str) -> str:
    fernet = Fernet(get_master_key())
    return fernet.decrypt(value.encode()).decode()
