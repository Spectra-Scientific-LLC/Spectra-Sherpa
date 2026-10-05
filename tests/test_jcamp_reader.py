from __future__ import annotations

import numpy as np
import pytest


def test_read_jcamp_rejects_unexpected_extension(tmp_path):
    from spectra_sherpa.app.lib.jcamp_reader import read_jcamp

    path = tmp_path / "not_jcamp.txt"
    path.write_text("##TITLE=Nope\n##END=", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported JCAMP-DX extension"):
        read_jcamp(path)


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


def test_jcamp_complete_fixed_grid_uses_endpoints_instead_of_accumulating_checkpoint_rounding():
    from spectra_sherpa.app.lib.jcamp_reader import parse_jcamp

    text = "\n".join(
        [
            "##TITLE=Nicolet-style rounded checkpoints",
            "##FIRSTX=399.212341",
            "##LASTX=406.926590",
            "##DELTAX=1.928562",
            "##NPOINTS=5",
            "##XYDATA=(X++(Y..Y))",
            "399.212 1 2",
            "403.069 3 4",
            "406.851 5",
            "##END=",
        ]
    )

    parsed = parse_jcamp(text)

    np.testing.assert_allclose(parsed.x, np.linspace(399.212341, 406.926590, 5), rtol=0.0, atol=0.0)
    np.testing.assert_allclose(parsed.y, np.array([1, 2, 3, 4, 5], dtype=np.float64))


def test_jcamp_complete_fixed_grid_rejects_declared_delta_contradiction():
    from spectra_sherpa.app.lib.jcamp_reader import parse_jcamp

    text = "\n".join(
        [
            "##TITLE=Contradictory delta",
            "##FIRSTX=100",
            "##LASTX=103",
            "##DELTAX=2",
            "##NPOINTS=4",
            "##XYDATA=(X++(Y..Y))",
            "100 1 2 3 4",
            "##END=",
        ]
    )

    with pytest.raises(ValueError, match="DELTAX contradicts"):
        parse_jcamp(text)


def test_jcamp_complete_fixed_grid_rejects_materially_shifted_checkpoint():
    from spectra_sherpa.app.lib.jcamp_reader import parse_jcamp

    text = "\n".join(
        [
            "##TITLE=Contradictory checkpoint",
            "##FIRSTX=100",
            "##LASTX=103",
            "##DELTAX=1",
            "##NPOINTS=4",
            "##XYDATA=(X++(Y..Y))",
            "100 1 2",
            "102.6 3 4",
            "##END=",
        ]
    )

    with pytest.raises(ValueError, match="checkpoint contradicts"):
        parse_jcamp(text)


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
