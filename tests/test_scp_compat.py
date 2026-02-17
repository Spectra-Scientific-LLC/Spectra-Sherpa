"""
Tests for the SCP compatibility layer (Phase 0).

Covers:
- Re-exports from scp_compat
- HAS_SCP flag
- CI enforcement: no direct spectrochempy imports outside scp_compat.py

Run:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_scp_compat.py -v --no-cov
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from spectra_sherpa.app.lib.scp_compat import HAS_SCP


APP_ROOT = Path(__file__).resolve().parent.parent / "src" / "spectra_sherpa" / "app"
SCP_COMPAT = APP_ROOT / "lib" / "scp_compat.py"


class TestScpCompatExports:
    """Verify the scp_compat module exports the expected symbols."""

    def test_has_scp_is_bool(self):
        assert isinstance(HAS_SCP, bool)

    def test_exports_all_expected_symbols(self):
        from spectra_sherpa.app.lib import scp_compat
        assert hasattr(scp_compat, "scp")
        assert hasattr(scp_compat, "NDDataset")
        assert hasattr(scp_compat, "Coord")
        assert hasattr(scp_compat, "HAS_SCP")
        assert hasattr(scp_compat, "require_scp")
        assert hasattr(scp_compat, "get_scp_datadirs")
        assert hasattr(scp_compat, "resolve_scp_path")
        assert hasattr(scp_compat, "download_testdata")

    @pytest.mark.skipif(not HAS_SCP, reason="spectrochempy not installed")
    def test_require_scp_passes_when_available(self):
        from spectra_sherpa.app.lib.scp_compat import require_scp
        require_scp("test")  # Should not raise

    @pytest.mark.skipif(not HAS_SCP, reason="spectrochempy not installed")
    def test_scp_is_module_when_available(self):
        from spectra_sherpa.app.lib.scp_compat import scp
        import types
        assert isinstance(scp, types.ModuleType)

    @pytest.mark.skipif(not HAS_SCP, reason="spectrochempy not installed")
    def test_nddataset_is_class_when_available(self):
        from spectra_sherpa.app.lib.scp_compat import NDDataset
        assert isinstance(NDDataset, type)

    def test_nddataset_is_always_a_type(self):
        """NDDataset must always be a type (real or stub) so isinstance() never crashes."""
        from spectra_sherpa.app.lib.scp_compat import NDDataset, Coord
        assert isinstance(NDDataset, type)
        assert isinstance(Coord, type)

    def test_isinstance_safe_without_scp(self):
        """isinstance(x, NDDataset) must never raise TypeError, even without SCP."""
        from spectra_sherpa.app.lib.scp_compat import NDDataset, Coord
        # These must evaluate to False for arbitrary objects, never raise
        assert not isinstance("hello", NDDataset)
        assert not isinstance(42, NDDataset)
        assert not isinstance({}, Coord)

    def test_require_scp_raises_when_absent(self, monkeypatch):
        import spectra_sherpa.app.lib.scp_compat as scp_mod
        monkeypatch.setattr(scp_mod, "HAS_SCP", False)
        with pytest.raises(ImportError, match="requires SpectroChemPy"):
            scp_mod.require_scp("Test feature")

    def test_get_scp_datadirs_prioritizes_env_override(self, monkeypatch: pytest.MonkeyPatch):
        from spectra_sherpa.app.lib import scp_compat

        monkeypatch.setenv("SCP_DATADIR", "/tmp/custom-scp-datadir")
        dirs = scp_compat.get_scp_datadirs()
        assert dirs
        assert str(dirs[0]) == "/tmp/custom-scp-datadir"

    def test_get_scp_datadirs_includes_testdata_fallback(self, monkeypatch: pytest.MonkeyPatch):
        from spectra_sherpa.app.lib import scp_compat

        monkeypatch.delenv("SCP_DATADIR", raising=False)
        dirs = scp_compat.get_scp_datadirs()
        assert any(str(path).endswith(".spectrochempy/testdata") for path in dirs)

    def test_resolve_scp_path_uses_discovered_dirs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        from spectra_sherpa.app.lib import scp_compat

        target = tmp_path / "irdata" / "sample.spg"
        target.parent.mkdir(parents=True)
        target.write_text("placeholder")

        monkeypatch.setenv("SCP_DATADIR", str(tmp_path))
        resolved = scp_compat.resolve_scp_path("irdata/sample.spg")
        assert resolved == target


class TestNoDirectScpImports:
    """CI enforcement: no file except scp_compat.py directly imports spectrochempy."""

    def _collect_python_files(self) -> list[Path]:
        """Get all .py files under app/, excluding scp_compat.py itself."""
        return [
            p for p in APP_ROOT.rglob("*.py")
            if p != SCP_COMPAT
            and "__pycache__" not in str(p)
        ]

    def test_no_import_spectrochempy_statements(self):
        """Scan AST of every .py file for `import spectrochempy` or `from spectrochempy`."""
        violations: list[str] = []

        for py_file in self._collect_python_files():
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "spectrochempy" or alias.name.startswith("spectrochempy."):
                            violations.append(
                                f"{py_file.relative_to(APP_ROOT.parent.parent.parent)}:{node.lineno}: "
                                f"import {alias.name}"
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.module and (
                        node.module == "spectrochempy" or node.module.startswith("spectrochempy.")
                    ):
                        violations.append(
                            f"{py_file.relative_to(APP_ROOT.parent.parent.parent)}:{node.lineno}: "
                            f"from {node.module} import ..."
                        )

        if violations:
            msg = (
                "Direct spectrochempy imports found outside scp_compat.py:\n"
                + "\n".join(f"  {v}" for v in violations)
            )
            pytest.fail(msg)
