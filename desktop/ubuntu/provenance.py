#!/usr/bin/env python3
"""Write the same scoped provenance as signed targets before native packaging."""

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import spectra_sherpa

commit = os.environ["BUILD_COMMIT"]
if not re.fullmatch(r"[0-9a-f]{40}", commit):
    raise ValueError("Require full build commit")
internal = Path("desktop/dist/SpectraSherpa/_internal")
hashes = {}
for name, root in (
    ("spectra_sherpa", internal / "spectra_sherpa"),
    ("frontend_static", internal / "spectra_sherpa/static"),
):
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise ValueError(f"Missing bundled tree: {name}")
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    hashes[name] = digest.hexdigest()
(internal / "provenance.json").write_text(
    json.dumps(
        {
            "version": spectra_sherpa.__version__,
            "python_version": sys.version.split()[0],
            "build_commit": commit,
            "signing_identity": None,
            "package_hashes": hashes,
            "dependency_provenance": json.loads(Path("desktop/runtime-provenance.json").read_text()),
        },
        indent=2,
    )
    + "\n"
)
