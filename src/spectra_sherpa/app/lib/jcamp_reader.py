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

logger = logging.getLogger(__name__)

# Label regex: ##KEY= value (case-insensitive keys)
_LDR_RE = re.compile(r"^##([^=]+)=\s*(.*)")

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


def _tokenize_data_line(line: str) -> list[float]:
    """Parse a data line that may contain SQZ-encoded or plain numeric values."""
    # Fast path: most NIST data is plain space/comma-separated numbers
    parts = line.replace(",", " ").split()
    values: list[float] = []
    for part in parts:
        try:
            values.append(float(part))
        except ValueError:
            # Attempt SQZ decode for packed formats
            decoded = _decode_sqz_token(part)
            if decoded is not None:
                values.append(decoded)
            else:
                logger.debug("Skipping unparseable JCAMP token: %s", part)
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
    filepath = Path(filepath)
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

    # Collect all Y values; rebuild X from FIRSTX/DELTAX
    all_y: list[float] = []

    for line in lines:
        values = _tokenize_data_line(line)
        if len(values) < 2:
            continue
        # First value is X checkpoint (for verification), rest are Y values
        y_vals = values[1:]
        for yv in y_vals:
            all_y.append(yv * yfactor)

    # Trim to NPOINTS if specified
    if npoints is not None and len(all_y) > npoints:
        all_y = all_y[:npoints]

    n = len(all_y)
    if n == 0:
        raise ValueError("No data points parsed from XYDATA block")

    # Build X axis
    if firstx is not None and deltax is not None:
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
