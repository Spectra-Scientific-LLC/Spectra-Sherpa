"""Where the Lavender Essential Oil FTIR Corpus v1 is read from.

The qualified archive ships inside SpectraSherpa as a default dataset
(CC BY 4.0; see NOTICE.md). ``TRIAL_AVATAR_ARCHIVE_PATH`` may point at another
copy; every reader still admits the bytes against its manifest before use.
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

LAVENDER_ARCHIVE_ENV = "TRIAL_AVATAR_ARCHIVE_PATH"
PACKAGED_LAVENDER_ARCHIVE = Path(__file__).resolve().parents[2] / "data" / "reference" / "lavender-essential-oil-v1.zip"


def lavender_archive_path() -> Path:
    """Return the configured archive, else the copy shipped with SpectraSherpa."""
    configured = os.getenv(LAVENDER_ARCHIVE_ENV, "").strip()
    return Path(configured) if configured else PACKAGED_LAVENDER_ARCHIVE


def catalogued_reference_definition(definition_sha256: str) -> bool:
    """Identify provider-owned collection definitions by their catalog digest."""
    from spectra_sherpa.app.lib.collection_definition import (
        MAX_COLLECTION_DEFINITION_BYTES,
        validate_collection_definition,
    )

    archives = set(PACKAGED_LAVENDER_ARCHIVE.parent.glob("*.zip"))
    archives.add(lavender_archive_path())
    for path in archives:
        try:
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    if (
                        not member.filename.endswith("/collection-definition.json")
                        or member.file_size > MAX_COLLECTION_DEFINITION_BYTES
                    ):
                        continue
                    definition = validate_collection_definition(json.loads(archive.read(member)))
                    if definition.sha256 == definition_sha256:
                        return True
        except (OSError, ValueError, zipfile.BadZipFile):
            continue
    return False
