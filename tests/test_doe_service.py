"""Tests for the DOE service layer (services/doe.py)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.doe import (
    ExperimentNotFoundError,
    extract_filename_number,
    generate_scan_path,
    verify_experiment_ownership,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_experiment(session: AsyncSession, user: User) -> Experiment:
    exp = Experiment(name="test-exp", user_id=user.id, metadata_path="/tmp/test-meta.json")
    session.add(exp)
    await session.commit()
    await session.refresh(exp)
    return exp


# ---------------------------------------------------------------------------
# Pure function tests: generate_scan_path
# ---------------------------------------------------------------------------


class TestGenerateScanPath:
    def test_row_from_a1(self):
        cells = generate_scan_path("A1", 14, "row")
        assert cells[:12] == [f"A{i}" for i in range(1, 13)]
        assert cells[12:14] == ["B1", "B2"]

    def test_column_from_a1(self):
        cells = generate_scan_path("A1", 10, "column")
        expected = [f"{r}1" for r in "ABCDEFGH"] + ["A2", "B2"]
        assert cells == expected

    def test_serpentine_reverses_on_second_row(self):
        cells = generate_scan_path("A1", 24, "serpentine")
        # First row: A1..A12  (forward)
        assert cells[0] == "A1"
        assert cells[11] == "A12"
        # Second row: B12..B1  (backward)
        assert cells[12] == "B12"
        assert cells[23] == "B1"

    def test_serpentine_column(self):
        cells = generate_scan_path("A1", 16, "serpentine_column")
        # First col: A1..H1  (forward)
        assert cells[:8] == [f"{r}1" for r in "ABCDEFGH"]
        # Second col: H2..A2  (backward)
        assert cells[8:16] == [f"{r}2" for r in "HGFEDCBA"]

    def test_wraps_around(self):
        # More cells than 96-well plate — should wrap
        cells = generate_scan_path("A1", 97, "row")
        assert len(cells) == 97
        assert cells[96] == "A1"  # wraps back

    def test_start_from_non_a1(self):
        cells = generate_scan_path("C5", 3, "row")
        assert cells == ["C5", "C6", "C7"]


# ---------------------------------------------------------------------------
# Pure function tests: extract_filename_number
# ---------------------------------------------------------------------------


class TestExtractFilenameNumber:
    def test_underscore_digits_dot(self):
        assert extract_filename_number("Spectrum_0002.csv") == 2

    def test_underscore_digits_end(self):
        assert extract_filename_number("scan_045") == 45

    def test_leading_digits_underscore(self):
        assert extract_filename_number("0045_data.txt") == 45

    def test_any_digits(self):
        assert extract_filename_number("file123data") == 123

    def test_no_digits(self):
        assert extract_filename_number("nodigits") is None


# ---------------------------------------------------------------------------
# DB tests: verify_experiment_ownership
# ---------------------------------------------------------------------------


class TestVerifyExperimentOwnership:
    @pytest.mark.asyncio
    async def test_success(self, test_session: AsyncSession, test_user: User):
        exp = await _make_experiment(test_session, test_user)
        result = await verify_experiment_ownership(test_session, exp.id, test_user.id)
        assert result.id == exp.id

    @pytest.mark.asyncio
    async def test_wrong_user(self, test_session: AsyncSession, test_user: User):
        exp = await _make_experiment(test_session, test_user)
        with pytest.raises(ExperimentNotFoundError):
            await verify_experiment_ownership(test_session, exp.id, test_user.id + 999)

    @pytest.mark.asyncio
    async def test_missing_experiment(self, test_session: AsyncSession, test_user: User):
        with pytest.raises(ExperimentNotFoundError):
            await verify_experiment_ownership(test_session, 99999, test_user.id)
