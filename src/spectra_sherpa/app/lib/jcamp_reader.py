"""
Standalone JCAMP-DX reader — no SpectroChemPy dependency.

Parses JCAMP-DX (.jdx, .dx) files into numpy arrays, returning
wavenumber (x) and absorbance/transmittance (y) data along with
header metadata.

Supports:
- ``##XYDATA= (X++(Y..Y))``  — NIST WebBook standard compressed format
- ``##XYPOINTS= (XY..XY)``   — explicit X,Y pair format
- ``##PEAK TABLE= (XY..XY)`` — peak table format

Reference:
    IUPAC JCAMP-DX Standard
    Pure Appl. Chem., Vol. 60, No. 9, pp. 1389-1403, 1988
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import numpy as np

_JCAMP_EXTENSIONS = {".jdx", ".dx", ".jcamp"}

logger = logging.getLogger(__name__)

# Label regex: ##KEY= value (case-insensitive keys)
_LDR_RE = re.compile(r"^##([^=]+)=\s*(.*)")
_ADJACENT_NUMBER_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?")

# JCAMP-DX SQZ (squeeze) digit encoding used in (X++(Y..Y)) format.
# Characters encode sign+digit: @=0, A-I=+1..+9, a-i=-1..-9,
# J-R → +0..+8 (DIF), j-r → -0..-8 (DIF), S-Z → +1..+8 (DUP), s → -1 (DUP)
# For NIST WebBook data, values are typically plain integers separated by spaces,
# so the SQZ decoding is rarely needed but supported for completeness.

_SQZ_MAP: dict[str, str] = {}
for _i, _c in enumerate("@ABCDEFGHI"):
    _SQZ_MAP[_c] = f"+{_i}"
for _i, _c in enumerate("@abcdefghi"):
    _SQZ_MAP[_c] = f"-{_i}"

_DIF_MAP: dict[str, str] = {"%": "+0"}
for _i, _c in enumerate("JKLMNOPQR"):
    _DIF_MAP[_c] = f"+{_i}"
for _i, _c in enumerate("jklmnopqr"):
    _DIF_MAP[_c] = f"-{_i}"

_DUP_MAP: dict[str, int] = {}
for _i, _c in enumerate("STUVWXYZ", start=1):
    _DUP_MAP[_c] = _i
for _i, _c in enumerate("stuvwxyz", start=1):
    _DUP_MAP[_c] = _i

_PACKED_PREFIXES = set(_SQZ_MAP) | set(_DIF_MAP) | set(_DUP_MAP)


def _tokenize_data_line(line: str) -> list[float]:
    """Parse a data line that may contain SQZ-encoded or plain numeric values."""
    # Fast path: most NIST data is plain space/comma-separated numbers
    parts = line.replace(",", " ").split()
    values: list[float] = []
    for part in _expand_packed_parts(parts):
        try:
            values.append(float(part))
        except ValueError:
            kind, decoded = _decode_packed_token(part)
            if kind == "absolute":
                values.append(decoded)
            elif kind in {"diff", "dup"}:
                raise ValueError(
                    "DIF/DUP JCAMP tokens require stateful XYDATA decoding; "
                    f"token {part!r} cannot be parsed as an independent value"
                )
            else:
                raise ValueError(f"Unparseable JCAMP token: {part!r}")
    return values


def _decode_sqz_token(token: str) -> float | None:
    """Decode a single SQZ-encoded token. Returns None if not decodable."""
    if not token:
        return None
    first = token[0]
    if first in _SQZ_MAP:
        rest = token[1:]
        sign_digit = _SQZ_MAP[first]
        try:
            return float(sign_digit + rest)
        except ValueError:
            return None
    return None


def _expand_packed_parts(parts: list[str]) -> list[str]:
    """Split adjacent packed JCAMP tokens while leaving plain numbers intact."""
    expanded: list[str] = []
    for part in parts:
        try:
            float(part)
            expanded.append(part)
            continue
        except ValueError:
            pass
        adjacent_numbers = _split_adjacent_numeric_tokens(part)
        if adjacent_numbers is not None:
            expanded.extend(adjacent_numbers)
            continue
        starts = [i for i, char in enumerate(part) if char in _PACKED_PREFIXES]
        if not starts or starts[0] != 0:
            expanded.append(part)
            continue
        starts.append(len(part))
        expanded.extend(part[starts[i] : starts[i + 1]] for i in range(len(starts) - 1))
    return expanded


def _split_adjacent_numeric_tokens(part: str) -> list[str] | None:
    """Split compact signed numeric runs such as ``6556-17677-43270``."""
    matches = list(_ADJACENT_NUMBER_RE.finditer(part))
    if len(matches) < 2:
        return None
    tokens: list[str] = []
    pos = 0
    for match in matches:
        if match.start() != pos:
            return None
        tokens.append(match.group())
        pos = match.end()
    if pos != len(part):
        return None
    return tokens


def _decode_packed_token(token: str) -> tuple[str, float]:
    """Decode one JCAMP packed token into (absolute|diff|dup, value)."""
    if not token:
        raise ValueError("Empty JCAMP token")
    try:
        return "absolute", float(token)
    except ValueError:
        pass
    first = token[0]
    rest = token[1:]
    if first in _SQZ_MAP:
        return "absolute", float(_SQZ_MAP[first] + rest)
    if first in _DIF_MAP:
        return "diff", float(_DIF_MAP[first] + rest)
    if first in _DUP_MAP:
        if rest:
            raise ValueError(f"Malformed JCAMP DUP token: {token!r}")
        return "dup", float(_DUP_MAP[first])
    raise ValueError(f"Unparseable JCAMP token: {token!r}")


class JCAMPData:
    """Parsed JCAMP-DX file contents."""

    __slots__ = ("x", "y", "headers", "title", "xunits", "yunits", "data_type")

    def __init__(
        self,
        x: np.ndarray,
        y: np.ndarray,
        headers: dict[str, str],
        title: str,
        xunits: str,
        yunits: str,
        data_type: str,
    ) -> None:
        self.x = x
        self.y = y
        self.headers = headers
        self.title = title
        self.xunits = xunits
        self.yunits = yunits
        self.data_type = data_type


def read_jcamp(filepath: str | Path) -> JCAMPData:
    """
    Read a JCAMP-DX file and return parsed spectral data.

    Parameters
    ----------
    filepath : str or Path
        Path to the .jdx / .dx file.

    Returns
    -------
    JCAMPData
        Parsed x (wavenumber), y (intensity), header dict, and axis labels.

    Raises
    ------
    ValueError
        If the file cannot be parsed or contains no data block.
    """
    try:
        filepath = Path(filepath).expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"JCAMP-DX file does not exist: {filepath}") from exc
    if not filepath.is_file():
        raise ValueError(f"JCAMP-DX path is not a file: {filepath}")
    if filepath.suffix.lower() not in _JCAMP_EXTENSIONS:
        raise ValueError(f"Unsupported JCAMP-DX extension: {filepath.suffix or '<none>'}")
    text = filepath.read_text(encoding="utf-8", errors="replace")
    return parse_jcamp(text)


def parse_jcamp(text: str) -> JCAMPData:
    """
    Parse JCAMP-DX content from a string.

    Parameters
    ----------
    text : str
        Full JCAMP-DX file content.

    Returns
    -------
    JCAMPData
        Parsed spectral data with headers and axis information.
    """
    headers: dict[str, str] = {}
    data_lines: list[str] = []
    data_format: str | None = None
    in_data_block = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Check for labeled data record
        m = _LDR_RE.match(line)
        if m:
            key = m.group(1).strip().upper()
            value = m.group(2).strip()

            # Detect data block start
            if key in ("XYDATA", "XYPOINTS", "PEAK TABLE"):
                data_format = key
                in_data_block = True
                continue
            elif key == "END":
                in_data_block = False
                continue

            # If we hit a new ## record while in data block, data block ended
            if in_data_block:
                in_data_block = False

            headers[key] = value
            continue

        # Accumulate data lines
        if in_data_block:
            data_lines.append(line)

    if not data_format or not data_lines:
        raise ValueError("No XYDATA, XYPOINTS, or PEAK TABLE block found in JCAMP-DX file")

    # Parse scaling factors
    xfactor = _safe_float(headers.get("XFACTOR", "1.0"), 1.0)
    yfactor = _safe_float(headers.get("YFACTOR", "1.0"), 1.0)

    if data_format == "XYDATA":
        x, y = _parse_xydata(data_lines, headers, xfactor or 1.0, yfactor or 1.0)
    elif data_format in ("XYPOINTS", "PEAK TABLE"):
        x, y = _parse_xypoints(data_lines, xfactor or 1.0, yfactor or 1.0)
    else:
        raise ValueError(f"Unsupported JCAMP-DX data format: {data_format}")

    title = headers.get("TITLE", "")
    xunits = headers.get("XUNITS", "1/CM")
    yunits = headers.get("YUNITS", "ABSORBANCE")
    data_type = headers.get("DATA TYPE", "INFRARED SPECTRUM")

    return JCAMPData(
        x=x,
        y=y,
        headers=headers,
        title=title,
        xunits=xunits,
        yunits=yunits,
        data_type=data_type,
    )


def _parse_xydata(
    lines: list[str],
    headers: dict[str, str],
    xfactor: float,
    yfactor: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Parse ``(X++(Y..Y))`` compressed format.

    Each line: first value is X, remaining values are consecutive Y values
    at X, X+DELTAX, X+2*DELTAX, ...
    """
    firstx = _safe_float(headers.get("FIRSTX"), None)
    lastx = _safe_float(headers.get("LASTX"), None)
    npoints = _safe_int(headers.get("NPOINTS"), None)
    deltax = _safe_float(headers.get("DELTAX"), None)

    # Collect all Y values. DIF tokens encode deltas from the previous Y value
    # and DUP tokens repeat the last delta, so decoding must carry state across
    # the whole XYDATA block. X values are derived from each line checkpoint
    # rather than only FIRSTX/DELTAX; NIST WebBook JCAMP files occasionally
    # include checkpoint spacing/rounding that does not agree exactly with a
    # single global FIRSTX + n*DELTAX sequence.
    all_x: list[float] = []
    all_y: list[float] = []
    previous_y: float | None = None
    last_diff: float | None = None
    checkpoint_mismatch_count = 0

    for line in lines:
        parts = _expand_packed_parts(line.replace(",", " ").split())
        if len(parts) < 2:
            continue
        kind, line_x = _decode_packed_token(parts[0])
        if kind != "absolute":
            raise ValueError(f"JCAMP XYDATA line checkpoint must be absolute, got {parts[0]!r}")
        expected_x = firstx + len(all_y) * deltax if firstx is not None and deltax is not None else None
        if expected_x is not None and not np.isclose(line_x, expected_x, rtol=1e-5, atol=1e-8):
            checkpoint_mismatch_count += 1
            logger.debug(
                "JCAMP XYDATA checkpoint mismatch: expected %g, got %g; using explicit line checkpoint",
                expected_x,
                line_x,
            )

        line_y: list[float] = []
        for part in parts[1:]:
            token_kind, token_value = _decode_packed_token(part)
            if token_kind == "absolute":
                current_y = token_value
                if previous_y is not None:
                    last_diff = current_y - previous_y
                previous_y = current_y
                line_y.append(current_y * yfactor)
            elif token_kind == "diff":
                if previous_y is None:
                    raise ValueError("JCAMP DIF token encountered before any absolute Y value")
                current_y = previous_y + token_value
                last_diff = token_value
                previous_y = current_y
                line_y.append(current_y * yfactor)
            elif token_kind == "dup":
                if previous_y is None or last_diff is None:
                    raise ValueError("JCAMP DUP token encountered before a repeatable Y increment")
                for _ in range(int(token_value)):
                    current_y = previous_y + last_diff
                    previous_y = current_y
                    line_y.append(current_y * yfactor)
        all_y.extend(line_y)
        if deltax is not None:
            all_x.extend((line_x + i * deltax) * xfactor for i in range(len(line_y)))

    if checkpoint_mismatch_count:
        logger.info(
            "JCAMP XYDATA used explicit line checkpoints for %d line(s) because header FIRSTX/DELTAX "
            "does not match the data line checkpoints.",
            checkpoint_mismatch_count,
        )

    if npoints is not None and len(all_y) != npoints:
        raise ValueError(
            f"JCAMP XYDATA point-count mismatch: header NPOINTS={npoints}, decoded {len(all_y)}. "
            "Refusing to return a truncated or shifted spectrum."
        )

    n = len(all_y)
    if n == 0:
        raise ValueError("No data points parsed from XYDATA block")

    # Build X axis
    if len(all_x) == n:
        x = np.array(all_x, dtype=np.float64)
    elif firstx is not None and deltax is not None:
        x = np.array([firstx * xfactor + i * deltax * xfactor for i in range(n)])
    elif firstx is not None and lastx is not None and n > 1:
        x = np.linspace(firstx * xfactor, lastx * xfactor, n)
    else:
        x = np.arange(n, dtype=np.float64)

    y = np.array(all_y, dtype=np.float64)
    return x, y


def _parse_xypoints(
    lines: list[str],
    xfactor: float,
    yfactor: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Parse ``(XY..XY)`` explicit pair format."""
    xs: list[float] = []
    ys: list[float] = []

    for line in lines:
        values = _tokenize_data_line(line)
        # Pairs: x1 y1 x2 y2 ...
        for i in range(0, len(values) - 1, 2):
            xs.append(values[i] * xfactor)
            ys.append(values[i + 1] * yfactor)

    if not xs:
        raise ValueError("No data points parsed from XYPOINTS block")

    return np.array(xs, dtype=np.float64), np.array(ys, dtype=np.float64)


def _safe_float(val: Any, default: float | None) -> float | None:
    """Safely convert to float."""
    if val is None:
        return default
    try:
        return float(str(val).split()[0])
    except (ValueError, TypeError, IndexError):
        return default


def _safe_int(val: Any, default: int | None) -> int | None:
    """Safely convert to int."""
    if val is None:
        return default
    try:
        return int(float(str(val).split()[0]))
    except (ValueError, TypeError, IndexError):
        return default
