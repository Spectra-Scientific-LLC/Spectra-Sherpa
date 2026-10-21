"""Publication admission is independent of navigation and scientific checks."""

import importlib.util
import json
from pathlib import Path

MODULE = Path(__file__).parents[1] / "scripts/check_public_docs.py"
spec = importlib.util.spec_from_file_location("public_docs", MODULE)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture(tmp_path, names):
    (tmp_path / "docs").mkdir()
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# User guide\n", encoding="utf-8")
    (tmp_path / "docs-publication.json").write_text(json.dumps({"schema_version": 1, "pages": names}), encoding="utf-8")
    return tmp_path


def test_current_public_docs():
    assert module.check(MODULE.parents[1]) == []


def test_unlisted_page_cannot_hide_outside_navigation(tmp_path):
    root = fixture(tmp_path, ["docs/index.md"])
    (root / "docs/secret.md").write_text("# Internal plan\n", encoding="utf-8")
    assert any("Unreviewed" in value for value in module.check(root))


def test_listing_a_known_internal_document_does_not_admit_it(tmp_path):
    root = fixture(tmp_path, ["docs/vision_audit_062425.md"])
    assert any("Internal document" in value for value in module.check(root))


def test_private_marker_is_rejected_even_in_an_admitted_page(tmp_path):
    root = fixture(tmp_path, ["docs/index.md"])
    (root / "docs/index.md").write_text("<!-- SPECTRA-" + "COMMERCIAL-DOC -->", encoding="utf-8")
    assert any("marker" in value for value in module.check(root))


def test_removed_page_requires_inventory_update(tmp_path):
    root = fixture(tmp_path, ["docs/index.md"])
    (root / "docs/index.md").unlink()
    assert any("Missing" in value for value in module.check(root))
