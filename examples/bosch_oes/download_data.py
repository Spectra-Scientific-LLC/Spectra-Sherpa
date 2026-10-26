"""Fetch/check the tested Zenodo subset; raw data is never bundled in OSS."""

from __future__ import annotations

import argparse
import hashlib
import tempfile
from pathlib import Path
from urllib.request import urlopen

# Published checksums from https://zenodo.org/records/17122442 (version 1).
FILES = {
    "Dictionary_OES.nc": "e7979670371604ff6f46d75dc3221cb0",
    "Dictionary_process.nc": "0dde5a3a913eb1fa8512ef2f8748fb34",
    "Process_data.nc": "4567d24ec2125102a2e5129203ba31fa",
    "Day_2024_08_05.nc": "4d13022c1817334dd02ffdfa936c4469",
}


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "md5").hexdigest()


def fetch(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name, expected in FILES.items():
        target = destination / name
        if target.exists():
            if checksum(target) != expected:
                raise ValueError(f"Existing {name} fails the published checksum; it was not overwritten")
            print(f"Verified {name}")
            continue
        with tempfile.TemporaryDirectory(prefix=f".{name}-", dir=destination) as temporary:
            partial = Path(temporary) / name
            with urlopen(f"https://zenodo.org/records/17122442/files/{name}?download=1", timeout=120) as response:
                with partial.open("xb") as output:
                    while block := response.read(1024 * 1024):
                        output.write(block)
            if checksum(partial) != expected:
                raise ValueError(f"Downloaded {name} fails the published checksum")
            partial.replace(target)
        print(f"Downloaded and verified {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    fetch(parser.parse_args().destination)


if __name__ == "__main__":
    main()
