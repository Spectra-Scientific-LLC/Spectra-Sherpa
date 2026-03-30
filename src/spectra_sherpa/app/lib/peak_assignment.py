"""
Rule-based vibrational peak assignment — textbook-level functional group identification.

This module provides conservative, "cannot be wrong" peak assignments based on
well-established characteristic absorption frequencies found in standard
spectroscopy reference tables (Silverstein, Socrates, Colthup).

Design principles:
- Only includes assignments that are universally accepted across textbooks
- Ranges are deliberately broad to avoid false negatives
- No technique-specific logic — works for IR, Raman, NIR without metadata
- Returns *possible* functional groups, not definitive identifications
- Intended as a local, zero-egress fallback for OSS users without LLM access

The assignments are organized by spectral region and represent the minimum
knowledge a spectroscopist would apply to any vibrational spectrum.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True, slots=True)
class FunctionalGroupRule:
    """A single frequency-to-functional-group mapping rule."""

    low: float  # Lower bound of characteristic range (cm⁻¹)
    high: float  # Upper bound of characteristic range (cm⁻¹)
    group: str  # Functional group label (e.g., "O-H stretch")
    description: str  # Brief textbook-level note
    region: str  # "functional_group" or "fingerprint"


@dataclass(frozen=True, slots=True)
class PeakAssignment:
    """Assignment result for a single observed peak."""

    position: float  # Observed peak position (original units)
    position_cm1: float  # Position converted to cm⁻¹ (for table lookup)
    matches: tuple[FunctionalGroupRule, ...] = field(default_factory=tuple)


# ============================================================================
# Characteristic frequency table — vibrational spectroscopy (cm⁻¹)
#
# Sources: Silverstein "Spectrometric Identification of Organic Compounds",
#          Socrates "Infrared and Raman Characteristic Group Frequencies",
#          Colthup "Introduction to Infrared and Raman Spectroscopy"
#
# Only entries that are unambiguous across IR *and* Raman are included.
# Ranges are intentionally broad.  Technique-specific refinement is left
# to the LLM conversational layer.
# ============================================================================

_RULES: tuple[FunctionalGroupRule, ...] = (
    # ── O-H stretching ──────────────────────────────────────────────
    FunctionalGroupRule(
        3200,
        3600,
        "O-H stretch",
        "Broad: alcohols, phenols, carboxylic acids; sharp: free O-H",
        "functional_group",
    ),
    # ── N-H stretching ──────────────────────────────────────────────
    FunctionalGroupRule(
        3250,
        3500,
        "N-H stretch",
        "Primary amines (two bands), secondary amines (one band), amides",
        "functional_group",
    ),
    # ── C-H stretching — sp3 ────────────────────────────────────────
    FunctionalGroupRule(
        2800,
        3000,
        "C-H stretch (sp3)",
        "Alkanes: methyl, methylene, methine",
        "functional_group",
    ),
    # ── C-H stretching — sp2 ────────────────────────────────────────
    FunctionalGroupRule(
        3000,
        3100,
        "C-H stretch (sp2)",
        "Alkenes, aromatics",
        "functional_group",
    ),
    # ── C-H stretching — sp (≡C-H) ─────────────────────────────────
    FunctionalGroupRule(
        3250,
        3340,
        "≡C-H stretch (sp)",
        "Terminal alkynes",
        "functional_group",
    ),
    # ── C≡N stretching ──────────────────────────────────────────────
    FunctionalGroupRule(
        2200,
        2260,
        "C≡N stretch",
        "Nitriles",
        "functional_group",
    ),
    # ── C≡C stretching ──────────────────────────────────────────────
    FunctionalGroupRule(
        2100,
        2260,
        "C≡C stretch",
        "Alkynes (may be weak or absent if symmetric)",
        "functional_group",
    ),
    # ── C=O stretching ──────────────────────────────────────────────
    FunctionalGroupRule(
        1650,
        1800,
        "C=O stretch",
        "Ketones, aldehydes, carboxylic acids, esters, amides, anhydrides",
        "functional_group",
    ),
    # ── C=C stretching ──────────────────────────────────────────────
    FunctionalGroupRule(
        1600,
        1680,
        "C=C stretch",
        "Alkenes, conjugated dienes",
        "functional_group",
    ),
    # ── Aromatic C=C stretching ─────────────────────────────────────
    FunctionalGroupRule(
        1400,
        1600,
        "Aromatic C=C stretch",
        "Aromatic ring vibrations (typically two bands near 1450 and 1600)",
        "fingerprint",
    ),
    # ── N-H bending ─────────────────────────────────────────────────
    FunctionalGroupRule(
        1550,
        1640,
        "N-H bend",
        "Primary amines, amide II band",
        "functional_group",
    ),
    # ── C-H bending — methyl/methylene ──────────────────────────────
    FunctionalGroupRule(
        1370,
        1470,
        "C-H bend (deformation)",
        "Methyl symmetric bend ~1375; methylene scissor ~1450",
        "fingerprint",
    ),
    # ── C-O stretching ──────────────────────────────────────────────
    FunctionalGroupRule(
        1000,
        1300,
        "C-O stretch",
        "Alcohols, ethers, esters, carboxylic acids",
        "fingerprint",
    ),
    # ── S=O stretching ──────────────────────────────────────────────
    FunctionalGroupRule(
        1000,
        1070,
        "S=O stretch (sulfoxide)",
        "Sulfoxides",
        "fingerprint",
    ),
    FunctionalGroupRule(
        1100,
        1370,
        "S=O stretch (sulfonyl)",
        "Sulfones, sulfonates, sulfonic acids",
        "fingerprint",
    ),
    # ── N=O stretching ──────────────────────────────────────────────
    FunctionalGroupRule(
        1500,
        1570,
        "N=O asymmetric stretch (nitro)",
        "Nitro compounds",
        "fingerprint",
    ),
    FunctionalGroupRule(
        1290,
        1370,
        "N=O symmetric stretch (nitro)",
        "Nitro compounds",
        "fingerprint",
    ),
    # ── C-F, C-Cl stretching ────────────────────────────────────────
    FunctionalGroupRule(
        1000,
        1400,
        "C-F stretch",
        "Fluoroalkanes (strong, broad)",
        "fingerprint",
    ),
    FunctionalGroupRule(
        550,
        850,
        "C-Cl stretch",
        "Chloroalkanes",
        "fingerprint",
    ),
    # ── P=O stretching ──────────────────────────────────────────────
    FunctionalGroupRule(
        1150,
        1300,
        "P=O stretch",
        "Phosphates, phosphonates",
        "fingerprint",
    ),
    # ── Si-O stretching ─────────────────────────────────────────────
    FunctionalGroupRule(
        1000,
        1100,
        "Si-O stretch",
        "Silicates, silicones, siloxanes",
        "fingerprint",
    ),
)


def assign_peaks(
    positions: Sequence[float],
    x_units: str = "cm-1",
) -> list[PeakAssignment]:
    """Assign functional groups to observed peak positions.

    Args:
        positions: Observed peak positions in the units given by *x_units*.
        x_units: Unit string for the positions.  Supported: "cm-1", "cm⁻¹",
            "1/cm" (wavenumber — used directly), "nm" (wavelength — converted),
            "um"/"µm" (wavelength — converted).  Unknown units are passed through
            with a warning.

    Returns:
        List of PeakAssignment objects, one per input position, each containing
        zero or more matching FunctionalGroupRule entries.
    """
    results: list[PeakAssignment] = []
    for pos in positions:
        pos_cm1 = _to_wavenumber(float(pos), x_units)
        matches = tuple(r for r in _RULES if r.low <= pos_cm1 <= r.high)
        results.append(PeakAssignment(position=float(pos), position_cm1=pos_cm1, matches=matches))
    return results


def format_assignments(assignments: list[PeakAssignment], x_units: str = "cm-1") -> str:
    """Format assignments as a human-readable text block for the chat window.

    Returns a plain-text summary suitable for display in the Sherpa chat or
    as a starting point for LLM-assisted refinement.
    """
    if not assignments:
        return "No peaks provided for assignment."

    unit_label = x_units if x_units else "cm⁻¹"
    lines: list[str] = []
    lines.append(f"Rule-based peak assignments ({len(assignments)} peaks):")
    lines.append("")

    for a in assignments:
        pos_str = f"{a.position:.1f} {unit_label}"
        if not a.matches:
            lines.append(f"  {pos_str} — no standard functional group match")
        else:
            for i, m in enumerate(a.matches):
                prefix = f"  {pos_str}" if i == 0 else " " * (len(pos_str) + 2)
                lines.append(f"{prefix} — {m.group}: {m.description}")
    return "\n".join(lines)


# ── Unit conversion helpers ─────────────────────────────────────────────────


def _to_wavenumber(value: float, units: str) -> float:
    """Convert a spectral position to wavenumber (cm⁻¹)."""
    u = units.strip().lower().replace("⁻¹", "-1")
    if u in ("cm-1", "1/cm", ""):
        return value
    if u == "nm":
        # λ(nm) → ν̃(cm⁻¹) = 1e7 / λ
        return 1e7 / value if value != 0 else 0.0
    if u in ("um", "µm", "micrometer"):
        # λ(µm) → ν̃(cm⁻¹) = 1e4 / λ
        return 1e4 / value if value != 0 else 0.0
    # Unknown units — assume wavenumber and let caller deal with it
    return value
