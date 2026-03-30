"""Tests for rule-based peak assignment module."""

from __future__ import annotations

import pytest

from spectra_sherpa.app.lib.peak_assignment import (
    _to_wavenumber,
    assign_peaks,
    format_assignments,
)

# ============================================================================
# Unit conversion
# ============================================================================


class TestToWavenumber:
    def test_cm1_passthrough(self):
        assert _to_wavenumber(1720.0, "cm-1") == 1720.0

    def test_cm1_unicode(self):
        assert _to_wavenumber(1720.0, "cm⁻¹") == 1720.0

    def test_nm_conversion(self):
        # 1000 nm → 10000 cm⁻¹
        assert _to_wavenumber(1000.0, "nm") == pytest.approx(10000.0)

    def test_um_conversion(self):
        # 10 µm → 1000 cm⁻¹
        assert _to_wavenumber(10.0, "µm") == pytest.approx(1000.0)

    def test_empty_units_treated_as_cm1(self):
        assert _to_wavenumber(2950.0, "") == 2950.0

    def test_unknown_units_passthrough(self):
        assert _to_wavenumber(42.0, "ppm") == 42.0


# ============================================================================
# Core assignment logic
# ============================================================================


class TestAssignPeaks:
    def test_carbonyl_peak(self):
        """1720 cm⁻¹ must match C=O stretch — textbook certainty."""
        results = assign_peaks([1720.0])
        assert len(results) == 1
        groups = [m.group for m in results[0].matches]
        assert "C=O stretch" in groups

    def test_oh_stretch(self):
        """3400 cm⁻¹ must match O-H stretch."""
        results = assign_peaks([3400.0])
        groups = [m.group for m in results[0].matches]
        assert "O-H stretch" in groups

    def test_ch_sp3_stretch(self):
        """2950 cm⁻¹ must match C-H stretch (sp3)."""
        results = assign_peaks([2950.0])
        groups = [m.group for m in results[0].matches]
        assert "C-H stretch (sp3)" in groups

    def test_nitrile(self):
        """2230 cm⁻¹ must match C≡N stretch."""
        results = assign_peaks([2230.0])
        groups = [m.group for m in results[0].matches]
        assert "C≡N stretch" in groups

    def test_no_match_in_silent_region(self):
        """2000 cm⁻¹ (silent region) should have no matches."""
        results = assign_peaks([2000.0])
        assert len(results[0].matches) == 0

    def test_multiple_peaks(self):
        """Multiple positions return one assignment per peak."""
        results = assign_peaks([1720.0, 2950.0, 3400.0])
        assert len(results) == 3

    def test_nm_units(self):
        """Wavelength in nm is converted: 5882 nm ≈ 1700 cm⁻¹ (C=O region)."""
        results = assign_peaks([5882.0], x_units="nm")
        groups = [m.group for m in results[0].matches]
        assert "C=O stretch" in groups

    def test_overlapping_rules(self):
        """3300 cm⁻¹ should match multiple groups (O-H, N-H, ≡C-H)."""
        results = assign_peaks([3300.0])
        groups = [m.group for m in results[0].matches]
        assert len(groups) >= 2  # At least O-H and N-H overlap here

    def test_empty_input(self):
        assert assign_peaks([]) == []

    def test_position_preserved(self):
        """Original position and converted position are both stored."""
        results = assign_peaks([5882.0], x_units="nm")
        assert results[0].position == 5882.0
        assert results[0].position_cm1 == pytest.approx(1700.7, abs=1.0)


# ============================================================================
# Formatting
# ============================================================================


class TestFormatAssignments:
    def test_empty(self):
        assert "No peaks" in format_assignments([])

    def test_single_peak_formatted(self):
        results = assign_peaks([1720.0])
        text = format_assignments(results)
        assert "C=O stretch" in text
        assert "1720.0" in text

    def test_no_match_formatted(self):
        results = assign_peaks([2000.0])
        text = format_assignments(results)
        assert "no standard functional group match" in text


# ============================================================================
# Rule integrity
# ============================================================================


class TestRuleIntegrity:
    def test_all_rules_have_valid_ranges(self):
        """Every rule must have low < high."""
        from spectra_sherpa.app.lib.peak_assignment import _RULES

        for rule in _RULES:
            assert rule.low < rule.high, f"{rule.group}: low={rule.low} >= high={rule.high}"

    def test_all_rules_have_region(self):
        from spectra_sherpa.app.lib.peak_assignment import _RULES

        valid_regions = {"functional_group", "fingerprint"}
        for rule in _RULES:
            assert rule.region in valid_regions, f"{rule.group}: invalid region '{rule.region}'"

    def test_no_duplicate_rules(self):
        """No two rules should have identical range + group."""
        from spectra_sherpa.app.lib.peak_assignment import _RULES

        seen = set()
        for rule in _RULES:
            key = (rule.low, rule.high, rule.group)
            assert key not in seen, f"Duplicate rule: {rule.group} [{rule.low}-{rule.high}]"
            seen.add(key)
