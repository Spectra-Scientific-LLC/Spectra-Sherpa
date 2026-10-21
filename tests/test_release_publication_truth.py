"""Public install guidance distinguishes source candidates from published packages."""

from __future__ import annotations

import re
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1]
INSTALL = re.compile(r"pip install[^\n]*spectra-sherpa", re.IGNORECASE)


def _current_install_guidance_failures(docs_root: Path) -> list[str]:
    failures = []
    for path in sorted(docs_root.rglob("*.md")):
        if "releases" in path.relative_to(docs_root).parts:
            continue  # Historical release instructions remain historical.
        source = path.read_text(encoding="utf-8")
        if not INSTALL.search(source):
            continue
        normalized = " ".join(source.replace(">", "").split()).lower()
        central_guide = "local-30-minutes.md" in source
        if not central_guide and not ("published" in normalized and "exact reviewed" in normalized):
            failures.append(f"missing publication/source guidance:{path.relative_to(docs_root)}")
        if re.search(r"pip install[^\n]*==0\.6\.0", source):
            failures.append(f"stale current install pin:{path.relative_to(docs_root)}")
    return failures


def test_current_candidate_and_published_install_are_distinct():
    index = (PACKAGE_ROOT / "docs/index.md").read_text(encoding="utf-8")
    local = (PACKAGE_ROOT / "docs/onboarding/local-30-minutes.md").read_text(encoding="utf-8")
    migration = (PACKAGE_ROOT / "docs/onboarding/migrate-to-0.6.md").read_text(encoding="utf-8")
    assert "v0.6.4" in index and "unreleased" in index.lower()
    assert "--source ." in local
    assert "latest published package" in local
    assert "exact reviewed revision" in local
    assert "==VERSION" in migration and "only after" in migration
    assert _current_install_guidance_failures(PACKAGE_ROOT / "docs") == []


def test_historical_release_is_not_rewritten_as_candidate():
    release = (PACKAGE_ROOT / "docs/releases/0.6.0.md").read_text(encoding="utf-8")
    assert 'pip install "spectra-sherpa==0.6.0"' in release
    assert "v0.6.4" not in release
    changelog = (PACKAGE_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert len(re.findall(r"^## \[0\.6\.0\] - (Unreleased|20\d{2}-\d{2}-\d{2})$", changelog, re.MULTILINE)) == 1


def test_new_install_page_cannot_escape_publication_truth_gate(tmp_path):
    (tmp_path / "new.md").write_text('pip install "spectra-sherpa[scp]"\n', encoding="utf-8")
    assert _current_install_guidance_failures(tmp_path)


def test_old_release_pin_cannot_be_reintroduced_as_current(tmp_path):
    (tmp_path / "new.md").write_text('See local-30-minutes.md\npip install "spectra-sherpa==0.6.0"\n', encoding="utf-8")
    assert any("stale" in value for value in _current_install_guidance_failures(tmp_path))
