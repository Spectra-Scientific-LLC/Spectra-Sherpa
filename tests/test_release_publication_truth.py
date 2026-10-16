"""Keep public 0.6 install guidance truthful across its release lifecycle."""

from __future__ import annotations

import re
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1]
PUBLIC_INSTALL_PATTERN = re.compile(r"pip install[^\n]*spectra-sherpa", re.IGNORECASE)
PUBLICATION_SENTENCE = "Install 0.6.0 from PyPI only after the public index reports that exact version"
SOURCE_AUTHORITY_SENTENCE = (
    "Before the public tag exists, use only the exact monorepo commit named by the qualification record"
)
TAG_AUTHORITY_SENTENCE = (
    "After the tag exists but before PyPI reports 0.6.0, use the exact `spectra-sherpa-v0.6.0` source tag"
)
CURRENT_PUBLICATION_SENTENCE = "Check the public index for the version you intend to install"
CURRENT_SOURCE_AUTHORITY = "exact reviewed revision"
CURRENT_TAG_AUTHORITY = "public source tag"


def _current_install_guidance_failures(docs_root: Path) -> list[str]:
    failures: list[str] = []
    for path in sorted(docs_root.rglob("*.md")):
        source = path.read_text(encoding="utf-8")
        if "SUPERSEDED" in source[:500]:
            continue
        if not PUBLIC_INSTALL_PATTERN.search(source):
            continue
        normalized = " ".join(source.replace(">", "").split())
        historical = all(
            phrase in normalized for phrase in (PUBLICATION_SENTENCE, SOURCE_AUTHORITY_SENTENCE, TAG_AUTHORITY_SENTENCE)
        )
        current = all(
            phrase in normalized
            for phrase in (CURRENT_PUBLICATION_SENTENCE, CURRENT_SOURCE_AUTHORITY, CURRENT_TAG_AUTHORITY)
        )
        if historical or current:
            continue
        if PUBLICATION_SENTENCE not in normalized and CURRENT_PUBLICATION_SENTENCE not in normalized:
            failures.append(f"missing publication lifecycle:{path.relative_to(docs_root)}")
        if SOURCE_AUTHORITY_SENTENCE not in normalized and CURRENT_SOURCE_AUTHORITY not in normalized:
            failures.append(f"missing pre-publication source authority:{path.relative_to(docs_root)}")
        if TAG_AUTHORITY_SENTENCE not in normalized and CURRENT_TAG_AUTHORITY not in normalized:
            failures.append(f"missing public-tag transition authority:{path.relative_to(docs_root)}")
        if all(
            any(phrase in normalized for phrase in pair)
            for pair in (
                (PUBLICATION_SENTENCE, CURRENT_PUBLICATION_SENTENCE),
                (SOURCE_AUTHORITY_SENTENCE, CURRENT_SOURCE_AUTHORITY),
                (TAG_AUTHORITY_SENTENCE, CURRENT_TAG_AUTHORITY),
            )
        ):
            failures.append(f"mixed release lifecycle:{path.relative_to(docs_root)}")
    return failures


def test_0_6_docs_are_self_contained_and_lifecycle_stable() -> None:
    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
    release = (PACKAGE_ROOT / "docs" / "releases" / "0.6.0.md").read_text(encoding="utf-8")
    migration = (PACKAGE_ROOT / "docs" / "onboarding" / "migrate-to-0.6.md").read_text(encoding="utf-8")
    choose_path = (PACKAGE_ROOT / "docs" / "onboarding" / "choose-your-path.md").read_text(encoding="utf-8")
    local = (PACKAGE_ROOT / "docs" / "onboarding" / "local-30-minutes.md").read_text(encoding="utf-8")
    changelog = (PACKAGE_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    for source in (release, migration):
        normalized = " ".join(source.replace(">", "").split())
        assert PUBLICATION_SENTENCE in normalized
        assert SOURCE_AUTHORITY_SENTENCE in normalized
        assert TAG_AUTHORITY_SENTENCE in normalized
    for source in (choose_path, local):
        normalized = " ".join(source.replace(">", "").split())
        assert CURRENT_PUBLICATION_SENTENCE in normalized
        assert CURRENT_SOURCE_AUTHORITY in normalized
        assert CURRENT_TAG_AUTHORITY in normalized
    # The public landing page stays concise; detailed install pages retain the
    # complete pre-publication lifecycle and qualification instructions.
    assert "docs/onboarding/choose-your-path.md" in readme
    assert "available before the PyPI upload completes" in " ".join(readme.split())
    assert (
        "git clone --branch spectra-sherpa-v0.6.3 " "https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.git"
    ) in readme
    assert "check the [published package]" in readme
    assert "Unreleased release candidate" not in release
    assert "Unreleased migration preview" not in migration
    headings = re.findall(r"^## \[0\.6\.0\] - (Unreleased|20\d{2}-\d{2}-\d{2})$", changelog, re.MULTILINE)
    assert len(headings) == 1

    # Historical 0.6.0 pages retain their exact lifecycle; current onboarding
    # binds published installs to the index and source builds to a reviewed
    # revision or corresponding public tag.
    assert 'pip install "spectra-sherpa==0.6.0"' in release
    for source in (readme, choose_path, local):
        assert "pip install spectra-sherpa" in source
    assert migration.index("only after PyPI reports 0.6.0") < migration.index(
        'pip install --upgrade "spectra-sherpa==0.6.0"'
    )

    candidate_sources = [readme]
    candidate_sources.extend(
        path.read_text(encoding="utf-8")
        for path in (PACKAGE_ROOT / "docs").rglob("*.md")
        if any(
            marker in path.read_text(encoding="utf-8")
            for marker in (PUBLICATION_SENTENCE, CURRENT_PUBLICATION_SENTENCE)
        )
    )
    unpinned_public_clone = "git clone https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.git"
    assert all(unpinned_public_clone not in source for source in candidate_sources)

    assert _current_install_guidance_failures(PACKAGE_ROOT / "docs") == []


def test_new_install_page_cannot_escape_publication_truth_gate(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "new-install-page.md").write_text(
        '# New page\n\n```bash\npip install "spectra-sherpa[scp]"\n```\n',
        encoding="utf-8",
    )
    failures = _current_install_guidance_failures(docs)
    assert any("new-install-page.md" in failure for failure in failures)
