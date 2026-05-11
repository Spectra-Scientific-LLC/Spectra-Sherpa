"""Regression tests for Tier-3 CodeQL hardening (path injection + error info)."""

from __future__ import annotations

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
