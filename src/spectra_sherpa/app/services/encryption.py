from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

from spectra_sherpa._paths import get_default_data_dir

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


def get_master_key() -> bytes:
    key = os.getenv("MASTER_ENCRYPTION_KEY")
    if key:
        return key.encode()

    data = _data_dir()
    env_path = data / ENV_FILENAME
    key = _read_env_key(env_path)
    if key:
        return key.encode()

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
