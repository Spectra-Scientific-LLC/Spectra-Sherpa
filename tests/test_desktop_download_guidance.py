"""Public installer guidance must describe the real data and artifact contract."""

from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]


def test_download_guidance_requires_published_assets_and_preserves_actual_data_path():
    source = (PACKAGE / "docs/support/local_install.md").read_text()
    assert "desktop-manifest.json" in source and "SHA256SUMS" in source
    assert "has\nnot been published" in source
    assert "%USERPROFILE%\\.spectra_sherpa" in source and "~/.spectra_sherpa" in source
    assert "~/.local/share/SpectraSherpa" not in source
    for target in ("macos-arm64.dmg", "windows-x86_64.exe"):
        assert target in source
    assert "Silent\nuninstall retains data" in source
    assert "not a universal binary" in source

    assert "macos-x86_64.dmg" not in source
    assert "linux-x86_64.tar.gz" not in source
    assert "no automatic update feed" in source
