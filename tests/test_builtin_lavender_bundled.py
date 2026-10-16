"""The Lavender Essential Oil FTIR Corpus v1 ships with SpectraSherpa."""

import hashlib
import json
import zipfile

from spectra_sherpa.app.lib.builtin_lavender import (
    LAVENDER_ARCHIVE_ENV,
    PACKAGED_LAVENDER_ARCHIVE,
    catalogued_reference_definition,
)
from spectra_sherpa.app.lib.collection_definition import validate_collection_definition
from spectra_sherpa.app.services import experiments

# The exact qualified archive (docs/evidence/avatar-essential-oils-v1-*.json);
# the hosted trial pins the same bytes.
QUALIFIED_ARCHIVE_SHA256 = "42565d51e2969c26ee24171f848ff9c3ab5cb429cd6250568993dffa738cd05c"
QUALIFIED_ARCHIVE_SIZE = 397_185


def test_packaged_archive_is_the_qualified_corpus():
    payload = PACKAGED_LAVENDER_ARCHIVE.read_bytes()
    assert len(payload) == QUALIFIED_ARCHIVE_SIZE
    assert hashlib.sha256(payload).hexdigest() == QUALIFIED_ARCHIVE_SHA256
    # Inside the package data tree, so the wheel and sdist include it.
    assert PACKAGED_LAVENDER_ARCHIVE.parent.parent.name == "data"


def test_available_without_configuration(monkeypatch):
    monkeypatch.delenv(LAVENDER_ARCHIVE_ENV, raising=False)
    assert experiments._builtin_lavender_archive_path() == PACKAGED_LAVENDER_ARCHIVE
    files = experiments.builtin_lavender_source_files()
    assert len(files) == 33
    assert all(path.startswith("data/") and path.endswith(".spa") for path in files)


def test_reference_definition_is_recognized_by_exact_digest(monkeypatch):
    monkeypatch.delenv(LAVENDER_ARCHIVE_ENV, raising=False)
    with zipfile.ZipFile(PACKAGED_LAVENDER_ARCHIVE) as archive:
        member = next(name for name in archive.namelist() if name.endswith("/collection-definition.json"))
        payload = json.loads(archive.read(member))
    definition = validate_collection_definition(payload)
    assert catalogued_reference_definition(definition.sha256)
    from spectra_sherpa.app.api.v1.routes.experiments import _definition_receipt

    receipt = _definition_receipt(experiment_id=1, status="attached", definition=definition, message="Current")
    assert receipt.reference_governed is True
    payload["collection"]["title"] = "Scientist modified collection"
    assert not catalogued_reference_definition(validate_collection_definition(payload).sha256)


def test_configured_copy_takes_precedence(monkeypatch, tmp_path):
    configured = tmp_path / "other.zip"
    monkeypatch.setenv(LAVENDER_ARCHIVE_ENV, str(configured))
    assert experiments._builtin_lavender_archive_path() == configured
    # A missing configured copy is reported as unavailable, never silently replaced.
    assert experiments.builtin_lavender_source_files() == []
