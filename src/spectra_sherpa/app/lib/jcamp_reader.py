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

import io
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np

from spectra_sherpa.app.core.path_security import resolve_existing_file_path
from spectra_sherpa.ingestion_errors import ParserLimitError

_JCAMP_EXTENSIONS = {".jdx", ".dx", ".jcamp"}
_MAX_JCAMP_DATA_LINE_CHARACTERS = 64 * 1024
LEGACY_NIST_QUANT_IR_AXIS_POLICY = "nist-quant-ir-fixed-grid-v1"
NIST_QUANT_IR_AXIS_POLICY = "nist-quant-ir-fixed-grid-v2"
_NIST_AXIS_POLICIES = {LEGACY_NIST_QUANT_IR_AXIS_POLICY, NIST_QUANT_IR_AXIS_POLICY}

logger = logging.getLogger(__name__)


def _bounded_jcamp_lines(text: str):
    """Iterate text while rejecting pathological packed lines before token expansion."""
    for raw_line in io.StringIO(text):
        if len(raw_line) > _MAX_JCAMP_DATA_LINE_CHARACTERS:
            raise ParserLimitError(
                f"JCAMP data line has {len(raw_line)} characters; limit is {_MAX_JCAMP_DATA_LINE_CHARACTERS}"
            )
        yield raw_line


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

    __slots__ = ("x", "y", "headers", "title", "xunits", "yunits", "data_type", "axis_reconciliation")

    def __init__(
        self,
        x: np.ndarray,
        y: np.ndarray,
        headers: dict[str, str],
        title: str,
        xunits: str,
        yunits: str,
        data_type: str,
        axis_reconciliation: dict[str, Any] | None = None,
    ) -> None:
        self.x = x
        self.y = y
        self.headers = headers
        self.title = title
        self.xunits = xunits
        self.yunits = yunits
        self.data_type = data_type
        self.axis_reconciliation = axis_reconciliation


def count_declared_jcamp_points(text: str) -> int:
    """Count the exact decoded point cardinality without allocating numeric arrays."""
    headers: dict[str, str] = {}
    data_format: str | None = None
    in_data_block = False
    count = 0
    found_data = False
    for raw_line in _bounded_jcamp_lines(text):
        line = raw_line.strip()
        if not line:
            continue
        match = _LDR_RE.match(line)
        if match:
            key = match.group(1).strip().upper()
            value = match.group(2).strip()
            if key in ("XYDATA", "XYPOINTS", "PEAK TABLE"):
                data_format = key
                in_data_block = True
                continue
            if key == "END":
                in_data_block = False
                continue
            if in_data_block:
                in_data_block = False
            headers[key] = value
            continue
        if in_data_block:
            found_data = True
            if data_format == "XYDATA":
                parts = _expand_packed_parts(line.replace(",", " ").split())
                for token in parts[1:]:
                    kind, value = _decode_packed_token(token)
                    count += int(value) if kind == "dup" else 1
            else:
                count += len(_tokenize_data_line(line)) // 2
    if data_format is None or not found_data:
        raise ValueError("No JCAMP data block is available to count")
    if data_format == "XYDATA":
        npoints = _safe_int(headers.get("NPOINTS"), None)
        if npoints is not None and count != npoints:
            raise ValueError(f"JCAMP point-count mismatch: header NPOINTS={npoints}, encoded {count}")
        return count
    return count


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
    filepath = resolve_existing_file_path(
        filepath,
        label="JCAMP-DX",
        suffixes=_JCAMP_EXTENSIONS,
        restrict_to_data_dir_in_multi_user=True,
    )
    text = filepath.read_text(encoding="utf-8", errors="replace")
    return parse_jcamp(text)


def parse_jcamp(text: str, *, axis_policy: str = "strict") -> JCAMPData:
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
    if axis_policy not in {"strict", *_NIST_AXIS_POLICIES}:
        raise ValueError("Unknown JCAMP axis policy")
    reconciliation: dict[str, Any] = {}
    headers: dict[str, str] = {}
    data_lines: list[str] = []
    data_format: str | None = None
    in_data_block = False

    for raw_line in _bounded_jcamp_lines(text):
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
    if axis_policy in _NIST_AXIS_POLICIES:
        for key in ("XFACTOR", "YFACTOR"):
            factor = float(headers.get(key, "1"))
            if not np.isfinite(factor) or factor <= 0 or (key == "XFACTOR" and factor != 1):
                raise ValueError("NIST reconciliation requires unscaled wavenumbers and positive finite YFACTOR")
    xfactor = _safe_float(headers.get("XFACTOR", "1.0"), 1.0)
    yfactor = _safe_float(headers.get("YFACTOR", "1.0"), 1.0)

    if data_format == "XYDATA":
        x, y = _parse_xydata(
            data_lines,
            headers,
            xfactor or 1.0,
            yfactor or 1.0,
            axis_policy=axis_policy,
            reconciliation=reconciliation,
        )
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
        axis_reconciliation=reconciliation or None,
    )


def _parse_xydata(
    lines: list[str],
    headers: dict[str, str],
    xfactor: float,
    yfactor: float,
    *,
    axis_policy: str = "strict",
    reconciliation: dict[str, Any] | None = None,
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
    nist_policy = axis_policy in _NIST_AXIS_POLICIES
    if nist_policy:
        if (
            firstx is None
            or lastx is None
            or npoints is None
            or npoints < 2
            or deltax is None
            or not np.isfinite([firstx, lastx, deltax, xfactor, yfactor]).all()
            or xfactor != 1.0
            or yfactor <= 0
            or not re.fullmatch(r"[0-9]+", headers.get("NPOINTS", ""))
            or headers.get("XUNITS", "").upper() not in {"CM-1", "CM^-1", "1/CM"}
        ):
            raise ValueError("NIST axis reconciliation requires complete finite wavenumber-grid declarations")

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
    checkpoints: list[tuple[int, float]] = []
    checkpoint_precision: list[float] = []

    for line in lines:
        parts = _expand_packed_parts(line.replace(",", " ").split())
        if len(parts) < 2:
            continue
        kind, line_x = _decode_packed_token(parts[0])
        if kind != "absolute":
            raise ValueError(f"JCAMP XYDATA line checkpoint must be absolute, got {parts[0]!r}")
        checkpoints.append((len(all_y), line_x))
        checkpoint_precision.append(_numeric_text_resolution(parts[0]))
        expected_x = firstx + len(all_y) * deltax if firstx is not None and deltax is not None else None
        if expected_x is not None and not np.isclose(line_x, expected_x, rtol=1e-5, atol=1e-8):
            checkpoint_mismatch_count += 1
            logger.debug(
                "JCAMP XYDATA checkpoint mismatch: expected %g, got %g; validating declared grid",
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
            "JCAMP XYDATA has %d line checkpoints inconsistent with header FIRSTX/DELTAX; "
            "fixed-grid validation follows.",
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

    x = _xydata_axis(
        headers,
        xfactor,
        checkpoints,
        all_x,
        n,
        axis_policy=axis_policy,
        reconciliation=reconciliation,
        checkpoint_precision=checkpoint_precision,
    )
    y = np.array(all_y, dtype=np.float64)
    if nist_policy and not np.isfinite(y).all():
        raise ValueError("NIST spectrum contains non-finite intensity values")
    return x, y


def _xydata_axis(
    headers: dict[str, str],
    xfactor: float,
    checkpoints: list[tuple[int, float]],
    all_x: list[float],
    n: int,
    *,
    axis_policy: str,
    reconciliation: dict[str, Any] | None,
    checkpoint_precision: list[float],
) -> np.ndarray:
    """Resolve the declared axis once; provider exceptions remain explicit."""
    firstx = _safe_float(headers.get("FIRSTX"), None)
    lastx = _safe_float(headers.get("LASTX"), None)
    npoints = _safe_int(headers.get("NPOINTS"), None)
    deltax = _safe_float(headers.get("DELTAX"), None)
    nist_policy = axis_policy in _NIST_AXIS_POLICIES
    # A complete fixed-grid declaration is the strongest axis authority for
    # X++(Y..Y): it carries both endpoints and exact cardinality. Supplier
    # writers commonly round DELTAX and line checkpoints independently, so
    # repeatedly expanding those rounded values can create avoidable drift.
    # Accept the global grid only when DELTAX and every checkpoint remain
    # consistent with it; materially contradictory files refuse.
    complete_grid = firstx is not None and lastx is not None and npoints is not None
    if complete_grid and npoints != n:
        raise ValueError("JCAMP fixed-grid cardinality does not match decoded XYDATA")
    if complete_grid and n > 1:
        assert firstx is not None and lastx is not None
        global_step = (lastx - firstx) / (n - 1)
        if not np.isfinite(global_step) or global_step == 0:
            raise ValueError("JCAMP fixed-grid endpoints do not define a finite monotonic axis")
        # Explicit provider exception, never inferred from file headers. The
        # tested NIST writer shifts checkpoints by one sample and rounds DELTAX
        # inconsistently. Permit at most one interval plus 1% for text rounding;
        # larger shifts, reversed checkpoints and malformed grids still refuse.
        provider_bound = abs(global_step) * 1.01
        delta_drift = 0.0 if deltax is None else abs(deltax - global_step) * (n - 1)
        precision_policy = axis_policy == NIST_QUANT_IR_AXIS_POLICY
        if precision_policy:
            provider_bound, checkpoint_offset = _validate_nist_checkpoints(
                headers, checkpoints, checkpoint_precision, n, global_step
            )
        if deltax is not None:
            declared_tolerance = max(
                _numeric_text_resolution(headers.get("DELTAX")),
                abs(global_step) * 1e-12,
            )
            if nist_policy and not precision_policy and (deltax * global_step <= 0 or delta_drift > provider_bound):
                raise ValueError("NIST DELTAX drift exceeds the one-interval reconciliation bound")
            if not nist_policy and abs(deltax - global_step) > declared_tolerance:
                raise ValueError("JCAMP DELTAX contradicts FIRSTX/LASTX/NPOINTS fixed grid")
        checkpoint_tolerance = abs(global_step) * 0.05
        max_checkpoint_error = 0.0
        previous_checkpoint = None
        for point_index, checkpoint in checkpoints:
            expected = firstx + point_index * global_step
            error = abs(checkpoint - expected)
            bound = provider_bound if nist_policy else checkpoint_tolerance
            if not np.isfinite(checkpoint) or (not precision_policy and error > bound):
                raise ValueError("JCAMP XYDATA line checkpoint contradicts the declared fixed grid")
            if (
                nist_policy
                and not precision_policy
                and (
                    (point_index == 0 and error > abs(global_step) * 0.01)
                    or (previous_checkpoint is not None and (checkpoint - previous_checkpoint) * global_step <= 0)
                )
            ):
                raise ValueError("NIST line checkpoints do not preserve the declared origin and direction")
            max_checkpoint_error = max(max_checkpoint_error, error)
            previous_checkpoint = checkpoint
        x = np.linspace(firstx * xfactor, lastx * xfactor, n, dtype=np.float64)
        if nist_policy and reconciliation is not None:
            reconciliation.update(
                {
                    "policy": axis_policy,
                    "axis_authority": "FIRSTX/LASTX/NPOINTS",
                    "original_declarations": {
                        key: headers[key] for key in ("FIRSTX", "LASTX", "NPOINTS", "DELTAX", "XUNITS")
                    },
                    "resolved_step": global_step,
                    "max_checkpoint_error": max_checkpoint_error,
                    "declared_step_endpoint_drift": delta_drift,
                    "maximum_allowed_error": provider_bound,
                    "checkpoint_count": len(checkpoints),
                    "values_reordered_or_interpolated": False,
                }
            )
            if precision_policy:
                reconciliation.update(
                    {
                        "checkpoint_offset_samples": checkpoint_offset,
                        "step_validation": "declared-step-rounding-or-adjacent-checkpoint-precision",
                    }
                )
    elif complete_grid and n == 1:
        assert firstx is not None and lastx is not None
        if not np.isclose(firstx, lastx, rtol=0.0, atol=_numeric_text_resolution(headers.get("LASTX"))):
            raise ValueError("JCAMP one-point fixed grid has contradictory endpoints")
        x = np.asarray([firstx * xfactor], dtype=np.float64)
    elif len(all_x) == n:
        x = np.array(all_x, dtype=np.float64)
    elif firstx is not None and deltax is not None:
        x = np.array([firstx * xfactor + i * deltax * xfactor for i in range(n)])
    elif firstx is not None and lastx is not None and n > 1:
        x = np.linspace(firstx * xfactor, lastx * xfactor, n)
    else:
        x = np.arange(n, dtype=np.float64)

    return x


def _validate_nist_checkpoints(
    headers: dict[str, str],
    checkpoints: list[tuple[int, float]],
    precision: list[float],
    n: int,
    step: float,
) -> tuple[float, int]:
    """Validate redundant provider declarations without accumulating rounded DELTAX.

    NIST Quant IR's writer uses either aligned checkpoints or a consistent
    one-sample lag after the initial row. Decimal rounding is bounded by the
    actual tokens, not a percentage of the step. FIRSTX/LASTX/NPOINTS remain
    the axis authority; no regression fit, reordering or interpolation is used.
    """
    first = float(headers["FIRSTX"])
    delta = float(headers["DELTAX"])
    first_precision = _numeric_text_resolution(headers["FIRSTX"])
    last_precision = _numeric_text_resolution(headers["LASTX"])
    delta_precision = _numeric_text_resolution(headers["DELTAX"])
    epsilon = max(abs(first), abs(float(headers["LASTX"])), 1.0) * 1e-12
    if delta * step <= 0 or len(checkpoints) < 3:
        raise ValueError("NIST reconciliation requires same-direction DELTAX and at least three checkpoints")
    # Coarse declarations cannot prove which sample a checkpoint describes.
    if max(*precision, first_precision, last_precision, delta_precision) >= abs(step) / 2:
        raise ValueError("NIST checkpoint precision cannot distinguish adjacent samples")
    # A correctly rounded DELTAX is directly corroborated by the authoritative
    # endpoints. Otherwise (the observed NIST writer defect), require every
    # adjacent checkpoint interval to corroborate it independently; a coarse
    # DELTAX token must not widen that fallback's checkpoint tolerance.
    rounded_delta_agrees = (
        abs(delta - step) <= delta_precision + (first_precision + last_precision) / (n - 1) + epsilon
        and abs(delta - step) * (n - 1) <= abs(step) * 1.01
    )
    offsets = {0, 1}
    maximum_error = 0.0
    for row, (index, value) in enumerate(checkpoints):
        fraction = index / (n - 1)
        rounding = precision[row] + (1 - fraction) * first_precision + fraction * last_precision + epsilon
        if not np.isfinite(value):
            raise ValueError("NIST checkpoint must be finite")
        if row == 0:
            if index != 0 or abs(value - first) > rounding:
                raise ValueError("NIST line checkpoints do not preserve the declared origin")
        else:
            previous_index, previous = checkpoints[row - 1]
            if index <= previous_index or (value - previous) * step <= 0:
                raise ValueError("NIST checkpoints do not preserve direction and sample order")
            offsets &= {offset for offset in (0, 1) if abs(value - (first + (index - offset) * step)) <= rounding}
            if not offsets:
                raise ValueError("NIST checkpoints contradict the fixed grid or change their sample offset")
            # The first interval can include the writer's one-sample lag. All
            # later intervals must agree with DELTAX at their text precision.
            if row > 1 and not rounded_delta_agrees:
                span = index - previous_index
                tolerance = precision[row] + precision[row - 1] + epsilon
                if abs(value - previous - span * delta) > tolerance:
                    raise ValueError("NIST DELTAX contradicts adjacent checkpoint spacing")
        maximum_error = max(maximum_error, abs(step) + rounding)
    if len(offsets) != 1:
        raise ValueError("NIST checkpoint precision leaves the sample offset ambiguous")
    return maximum_error, offsets.pop()


def _numeric_text_resolution(value: object) -> float:
    """Return half one declared least-significant decimal unit."""

    token = str(value or "").strip().split()[0] if str(value or "").strip() else ""
    match = re.fullmatch(r"[+-]?(?:\d+(?:\.(\d*))?|\.([0-9]+))(?:[Ee]([+-]?\d+))?", token)
    if match is None:
        return 0.0
    decimals = len(match.group(1) if match.group(1) is not None else (match.group(2) or ""))
    exponent = int(match.group(3) or 0)
    return 0.5 * (10.0 ** (exponent - decimals))


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
