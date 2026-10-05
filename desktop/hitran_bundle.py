"""Build-time HAPI packaging: exact versions, notices and matching source.

Downloads only immutable, hash-pinned upstream code archives, never spectra.
Archives are retained intact inside the installer; no tar extraction occurs.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import io
import json
import tarfile
import urllib.request
import zipfile
from pathlib import Path

CLIENTS = {
    "hitran-api": {
        "module": "hapi",
        "version": "1.3.0.0",
        "license": "MIT",
        "filename": "hitran_api-1.3.0.0-py2.py3-none-any.whl",
        "url": "https://files.pythonhosted.org/packages/74/d8/4fa0fb59ce8d29cd153496b6e8f92c4fdee070dfc78724daab0008a0fe38/hitran_api-1.3.0.0-py2.py3-none-any.whl",
        "sha256": "ce4129913c64e1c40700d059c117c774704eafcc49faece61d875e08220950f5",
        "license_member": "hitran_api-1.3.0.0.dist-info/LICENSE.txt",
        "source_prefix": "",
    },
    "hitran-api2": {
        "module": "hapi2",
        "version": "0.2.2",
        "license": "GPL-3.0",
        "filename": "hitran_api2-0.2.2.tar.gz",
        "url": "https://files.pythonhosted.org/packages/fe/11/003c7202037cc8f9d7cbc8fb52f794be30422e5993987e5378da6883384f/hitran_api2-0.2.2.tar.gz",
        "sha256": "6add079c75c1bb4cfa3554022d868a9e1b9c818e55a06d9424cbb0e02a8d9c13",
        "license_member": "hitran_api2-0.2.2/LICENSE.md",
        "source_prefix": "hitran_api2-0.2.2/",
    },
}

# HAPI2 selects these modules using importlib; ordinary graph analysis misses them.
HIDDEN_IMPORTS = [
    "hapi",
    "hapi2",
    "hapi2.db.sqlalchemy.sqlite",
    "hapi2.provenance.types",
    "hapi2.opacity.models",
]


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def _read_member(data: bytes, filename: str, member: str) -> bytes:
    if filename.endswith(".whl"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return archive.read(member)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        stream = archive.extractfile(member)
        if stream is None:
            raise ValueError(f"Missing source member: {member}")
        return stream.read()


def prepare(destination: Path, *, distribution=importlib.metadata.distribution, download=_download) -> Path:
    """Refuse mismatched installs or archives before constructing the payload."""
    destination.mkdir(parents=True, exist_ok=True)
    for name, entry in CLIENTS.items():
        installed = distribution(name)
        if installed.version != entry["version"]:
            raise ValueError(f"{name}: expected {entry['version']}, installed {installed.version}")
        path = destination / entry["filename"]
        data = path.read_bytes() if path.exists() else download(entry["url"])
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError(f"{name}: source archive SHA256 mismatch")
        # The source shipped must match the Python code actually being frozen.
        sources = [
            f for f in installed.files or [] if str(f).startswith(entry["module"] + "/") and str(f).endswith(".py")
        ]
        if not sources:
            raise ValueError(f"{name}: installed source is missing")
        for source in sources:
            retained = _read_member(data, entry["filename"], entry["source_prefix"] + str(source))
            if retained != Path(installed.locate_file(source)).read_bytes():
                raise ValueError(f"{name}: installed source differs from retained archive: {source}")
        license_text = _read_member(data, entry["filename"], entry["license_member"])
        path.write_bytes(data)
        (destination / f"{name}-LICENSE.txt").write_bytes(license_text)
    (destination / "manifest.json").write_text(json.dumps(CLIENTS, indent=2) + "\n", encoding="utf-8")
    (destination / "README.txt").write_text(
        "HAPI / HAPI2 bundled clients\n"
        "HAPI is MIT licensed; HAPI2 is GPLv3. Original notices are alongside this file.\n"
        "Unmodified matching Python source is in the retained wheel (HAPI) and source\n"
        "tarball (HAPI2, including its setup.py). No API keys or downloaded line lists\n"
        "are included. To rebuild the SpectraSherpa installer, use the matching release\n"
        "tag and desktop/README.md at https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.\n"
        "Keep these notices and source archives when redistributing the installer.\n",
        encoding="utf-8",
    )
    return destination
