from __future__ import annotations

import numpy as np
import pytest


def test_jcamp_xydata_decodes_sqz_dif_and_dup_tokens():
    from spectra_sherpa.app.lib.jcamp_reader import parse_jcamp

    text = "\n".join(
        [
            "##TITLE=Packed spectrum",
            "##XUNITS=1/CM",
            "##YUNITS=ABSORBANCE",
            "##FIRSTX=100",
            "##LASTX=104",
            "##DELTAX=1",
            "##NPOINTS=5",
            "##XYDATA=(X++(Y..Y))",
            "100 A0 J2 K0 T",
            "##END=",
        ]
    )

    parsed = parse_jcamp(text)

    np.testing.assert_allclose(parsed.x, np.array([100, 101, 102, 103, 104], dtype=np.float64))
    np.testing.assert_allclose(parsed.y, np.array([10, 12, 22, 32, 42], dtype=np.float64))


def test_jcamp_xydata_splits_adjacent_plain_numeric_tokens():
    from spectra_sherpa.app.lib.jcamp_reader import parse_jcamp

    text = "\n".join(
        [
            "##TITLE=NIST-style compact numbers",
            "##FIRSTX=100",
            "##DELTAX=1",
            "##NPOINTS=4",
            "##XYDATA=(X++(Y..Y))",
            "100 6556-17677-43270-76589",
            "##END=",
        ]
    )

    parsed = parse_jcamp(text)

    np.testing.assert_allclose(parsed.x, np.array([100, 101, 102, 103], dtype=np.float64))
    np.testing.assert_allclose(parsed.y, np.array([6556, -17677, -43270, -76589], dtype=np.float64))


def test_jcamp_xydata_uses_line_checkpoints_when_header_grid_drifts():
    from spectra_sherpa.app.lib.jcamp_reader import parse_jcamp

    text = "\n".join(
        [
            "##TITLE=NIST checkpoint drift",
            "##FIRSTX=100",
            "##DELTAX=1",
            "##NPOINTS=4",
            "##XYDATA=(X++(Y..Y))",
            "100 1 2",
            "102.1 3 4",
            "##END=",
        ]
    )

    parsed = parse_jcamp(text)

    np.testing.assert_allclose(parsed.x, np.array([100, 101, 102.1, 103.1], dtype=np.float64))
    np.testing.assert_allclose(parsed.y, np.array([1, 2, 3, 4], dtype=np.float64))


def test_jcamp_xydata_splits_adjacent_signed_numeric_runs():
    from spectra_sherpa.app.lib.jcamp_reader import parse_jcamp

    text = "\n".join(
        [
            "##TITLE=Adjacent signed values",
            "##FIRSTX=100",
            "##DELTAX=1",
            "##NPOINTS=4",
            "##XYDATA=(X++(Y..Y))",
            "100 6556-17677-43270-76589",
            "##END=",
        ]
    )

    parsed = parse_jcamp(text)

    np.testing.assert_allclose(parsed.x, np.array([100, 101, 102, 103], dtype=np.float64))
    np.testing.assert_allclose(parsed.y, np.array([6556, -17677, -43270, -76589], dtype=np.float64))


def test_jcamp_xydata_rejects_point_count_mismatch():
    from spectra_sherpa.app.lib.jcamp_reader import parse_jcamp

    text = "\n".join(
        [
            "##TITLE=Truncated spectrum",
            "##FIRSTX=100",
            "##DELTAX=1",
            "##NPOINTS=3",
            "##XYDATA=(X++(Y..Y))",
            "100 1 2",
            "##END=",
        ]
    )

    with pytest.raises(ValueError, match="point-count mismatch"):
        parse_jcamp(text)


def test_jcamp_xydata_rejects_overlong_point_count():
    from spectra_sherpa.app.lib.jcamp_reader import parse_jcamp

    text = "\n".join(
        [
            "##TITLE=Overlong spectrum",
            "##FIRSTX=100",
            "##DELTAX=1",
            "##NPOINTS=2",
            "##XYDATA=(X++(Y..Y))",
            "100 1 2 3",
            "##END=",
        ]
    )

    with pytest.raises(ValueError, match="point-count mismatch"):
        parse_jcamp(text)
