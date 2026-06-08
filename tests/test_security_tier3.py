"""Regression tests for Tier-3 CodeQL hardening (path injection + error info)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from spectra_sherpa.app.services import prepared_data
from spectra_sherpa.app.services.prepared_data import (
    _safe_sidecar_segment,
    sidecar_path,
)


class TestSafeSidecarSegment:
    """``_safe_sidecar_segment`` defangs user-supplied filename segments."""

    @pytest.mark.parametrize(
        "raw,sanitised",
        [
            ("dataset1", "dataset1"),
            ("nist_lib", "nist_lib"),
            ("Sample-A.csv", "Sample-A.csv"),
            ("foo/bar", "foo_bar"),
            # Leading dots get stripped, runs of ``/`` collapse into a single
            # ``_``; the resulting label is safe (no traversal possible).
            ("../etc/passwd", "_etc_passwd"),
            ("name with spaces", "name_with_spaces"),
            ("héllo", "h_llo"),
            ("/abs/path", "_abs_path"),
            ("///", "_"),  # collapses to single underscore — no traversal
        ],
    )
    def test_sanitises_user_input(self, raw, sanitised):
        assert _safe_sidecar_segment(raw) == sanitised

    def test_rejects_empty_after_sanitisation(self):
        with pytest.raises(ValueError):
            _safe_sidecar_segment("...")
        with pytest.raises(ValueError):
            _safe_sidecar_segment("")


class TestSidecarPathContainment:
    """``sidecar_path`` must never produce a path outside ``_OVERRIDES_DIR``."""

    def test_source_name_traversal_defanged(self):
        path = sidecar_path(file_path=None, source="../../etc", name="passwd")
        overrides_root = prepared_data._OVERRIDES_DIR.resolve()
        assert path.resolve().is_relative_to(overrides_root)
        # Sanitised filename remains a single path component — no separators
        # survived, so ``..`` cannot act as a traversal segment.
        assert "/" not in path.name
        assert "\\" not in path.name
        assert "../" not in path.name
        assert "..\\" not in path.name

    def test_file_path_absolute_traversal_defanged(self):
        path = sidecar_path(file_path="/etc/passwd", source=None, name=None)
        overrides_root = prepared_data._OVERRIDES_DIR.resolve()
        assert path.resolve().is_relative_to(overrides_root)

    def test_round_trip_for_legitimate_input(self):
        path = sidecar_path(file_path=None, source="nist_lib", name="Sample-A")
        assert path.name == "ref__nist_lib__Sample-A.json"

    def test_requires_at_least_one_of_file_path_or_source_name(self):
        with pytest.raises(ValueError):
            sidecar_path(file_path=None, source=None, name=None)


class TestUserPathContainment:
    """User-facing file readers must stay under DATA_DIR in multi-user mode."""

    def test_csv_reader_rejects_outside_data_dir_in_multi_user_mode(self, tmp_path):
        from spectra_sherpa.app.lib.io import load_csv_as_sherpa

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        outside = tmp_path / "outside.csv"
        outside.write_text("wavenumber,absorbance\n1000,0.1\n", encoding="utf-8")

        with (
            patch("spectra_sherpa.app.core.mode_policy.is_multi_user", return_value=True),
            patch("spectra_sherpa.app.core.config.settings") as mock_settings,
        ):
            mock_settings.data_dir = data_dir
            with pytest.raises(ValueError, match="must be under the data directory"):
                load_csv_as_sherpa(outside)

    def test_jcamp_reader_rejects_outside_data_dir_in_multi_user_mode(self, tmp_path):
        from spectra_sherpa.app.lib.jcamp_reader import read_jcamp

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        outside = tmp_path / "outside.jdx"
        outside.write_text("##TITLE=outside\n##XYPOINTS=(XY..XY)\n1000 1\n##END=", encoding="utf-8")

        with (
            patch("spectra_sherpa.app.core.mode_policy.is_multi_user", return_value=True),
            patch("spectra_sherpa.app.core.config.settings") as mock_settings,
        ):
            mock_settings.data_dir = data_dir
            with pytest.raises(ValueError, match="must be under the data directory"):
                read_jcamp(outside)

    def test_synthetic_npz_metadata_rejects_outside_data_dir_in_multi_user_mode(self, tmp_path):
        from spectra_sherpa.app.services.synthesis import _resolve_synthetic_npz_path

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        outside = tmp_path / "outside.npz"
        outside.write_bytes(b"not a real npz, but enough to test path containment")

        with (
            patch("spectra_sherpa.app.core.mode_policy.is_multi_user", return_value=True),
            patch("spectra_sherpa.app.core.config.settings") as mock_settings,
        ):
            mock_settings.data_dir = data_dir
            with pytest.raises(ValueError, match="must be under the data directory"):
                _resolve_synthetic_npz_path(outside)

    def test_restricted_user_file_reader_still_allows_local_paths_in_local_mode(self, tmp_path):
        from spectra_sherpa.app.core.path_security import resolve_existing_file_path

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        outside = tmp_path / "local.csv"
        outside.write_text("x,y\n1,2\n", encoding="utf-8")

        with (
            patch("spectra_sherpa.app.core.mode_policy.is_multi_user", return_value=False),
            patch("spectra_sherpa.app.core.config.settings") as mock_settings,
        ):
            mock_settings.data_dir = data_dir
            resolved = resolve_existing_file_path(
                outside,
                label="CSV",
                suffixes={".csv"},
                restrict_to_data_dir_in_multi_user=True,
            )

        assert resolved == outside.resolve()

    def test_restricted_user_file_reader_allows_file_under_data_dir_in_multi_user_mode(self, tmp_path):
        from spectra_sherpa.app.core.path_security import resolve_existing_file_path

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        inside = data_dir / "local.csv"
        inside.write_text("x,y\n1,2\n", encoding="utf-8")

        with (
            patch("spectra_sherpa.app.core.mode_policy.is_multi_user", return_value=True),
            patch("spectra_sherpa.app.core.config.settings") as mock_settings,
        ):
            mock_settings.data_dir = data_dir
            resolved = resolve_existing_file_path(
                inside,
                label="CSV",
                suffixes={".csv"},
                restrict_to_data_dir_in_multi_user=True,
            )

        assert resolved == inside.resolve()

    def test_trusted_local_file_reader_allows_unrestricted_path_with_default_flag(self, tmp_path):
        from spectra_sherpa.app.core.path_security import resolve_existing_file_path

        outside = tmp_path / "local.csv"
        outside.write_text("x,y\n1,2\n", encoding="utf-8")

        resolved = resolve_existing_file_path(outside, label="CSV", suffixes={".csv"})

        assert resolved == outside.resolve()
