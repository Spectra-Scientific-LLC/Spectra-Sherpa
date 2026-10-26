"""Spectroscopic transition matching and identification engine for plasma OES peaks."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Prototype reference candidates; not a verified NIST database query.
# Wavelength proximity alone does not establish a chemical identification.
NIST_TRANSITIONS: Dict[str, List[Dict[str, Any]]] = {
    "F": [
        {
            "wavelength_nm": 685.60,
            "species": "F I",
            "lower_conf": "2s² 2p⁴(³P) 3s",
            "lower_term": "⁴P",
            "lower_J": "5/2",
            "upper_conf": "2s² 2p⁴(³P) 3p",
            "upper_term": "⁴D°",
            "upper_J": "7/2",
            "A_ki": 3.6e7,
            "role": "Active Silicon etchant radical; primary indicator of F radical density and etch rate.",
        },
        {
            "wavelength_nm": 703.75,
            "species": "F I",
            "lower_conf": "2s² 2p⁴(³P) 3s",
            "lower_term": "²P",
            "lower_J": "3/2",
            "upper_conf": "2s² 2p⁴(³P) 3p",
            "upper_term": "²P°",
            "upper_J": "3/2",
            "A_ki": 3.8e7,
            "role": "Strongest atomic fluorine emission line in SF6 plasma; standard actinometry line (I_F/I_Ar).",
        },
        {
            "wavelength_nm": 712.79,
            "species": "F I",
            "lower_conf": "2s² 2p⁴(³P) 3s",
            "lower_term": "²P",
            "lower_J": "1/2",
            "upper_conf": "2s² 2p⁴(³P) 3p",
            "upper_term": "²P°",
            "upper_J": "1/2",
            "A_ki": 2.5e7,
            "role": "Multiplet partner of 703.7 nm; verifies atomic fluorine concentration without optical saturation.",
        },
        {
            "wavelength_nm": 720.24,
            "species": "F I",
            "lower_conf": "2s² 2p⁴(³P) 3s",
            "lower_term": "⁴P",
            "lower_J": "3/2",
            "upper_conf": "2s² 2p⁴(³P) 3p",
            "upper_term": "⁴S°",
            "upper_J": "3/2",
            "A_ki": 1.7e7,
            "role": "High-lying quartet transition; sensitive to hot electron tail in ICP discharge.",
        },
        {
            "wavelength_nm": 739.87,
            "species": "F I",
            "lower_conf": "2s² 2p⁴(³P) 3s",
            "lower_term": "⁴P",
            "lower_J": "5/2",
            "upper_conf": "2s² 2p⁴(³P) 3p",
            "upper_term": "⁴P°",
            "upper_J": "5/2",
            "A_ki": 1.1e7,
            "role": "Prominent fluorine 3s-3p quartet transition in halogen etch plasmas.",
        },
        {
            "wavelength_nm": 755.22,
            "species": "F I",
            "lower_conf": "2s² 2p⁴(¹D) 3s",
            "lower_term": "²D",
            "lower_J": "5/2",
            "upper_conf": "2s² 2p⁴(¹D) 3p",
            "upper_term": "²F°",
            "upper_J": "7/2",
            "A_ki": 4.1e7,
            "role": "Singlet core F I transition; monitors fluorine dissociation dynamics.",
        },
        {
            "wavelength_nm": 775.47,
            "species": "F I",
            "lower_conf": "2s² 2p⁴(¹D) 3s",
            "lower_term": "²D",
            "lower_J": "3/2",
            "upper_conf": "2s² 2p⁴(¹D) 3p",
            "upper_term": "²D°",
            "upper_J": "5/2",
            "A_ki": 3.3e7,
            "role": "Diagnostic fluorine emission line in the near-infrared region.",
        },
        {
            "wavelength_nm": 623.97,
            "species": "F I",
            "lower_conf": "2s² 2p⁴(³P) 3s",
            "lower_term": "⁴P",
            "lower_J": "5/2",
            "upper_conf": "2s² 2p⁴(³P) 3p",
            "upper_term": "⁴D°",
            "upper_J": "5/2",
            "A_ki": 6.8e6,
            "role": "Visible red atomic fluorine line.",
        },
    ],
    "Si": [
        {
            "wavelength_nm": 251.61,
            "species": "Si I",
            "lower_conf": "3s² 3p²",
            "lower_term": "³P",
            "lower_J": "2",
            "upper_conf": "3s² 3p 4s",
            "upper_term": "³P°",
            "upper_J": "2",
            "A_ki": 1.7e8,
            "role": "Resonance emission of sputtered/etched Silicon; primary direct measure of Si wafer etch rate.",
        },
        {
            "wavelength_nm": 288.16,
            "species": "Si I",
            "lower_conf": "3s² 3p²",
            "lower_term": "¹D",
            "lower_J": "2",
            "upper_conf": "3s² 3p 4s",
            "upper_term": "¹P°",
            "upper_J": "1",
            "A_ki": 2.2e8,
            "role": "Strong singlet resonance line of atomic silicon; endpoint detection benchmark for Si clearance.",
        },
        {
            "wavelength_nm": 390.55,
            "species": "Si I",
            "lower_conf": "3s² 3p²",
            "lower_term": "¹S",
            "lower_J": "0",
            "upper_conf": "3s² 3p 4s",
            "upper_term": "¹P°",
            "upper_J": "1",
            "A_ki": 1.3e7,
            "role": "Near-UV Si I transition from metastable 1S state.",
        },
        {
            "wavelength_nm": 504.10,
            "species": "Si I / Si II",
            "lower_conf": "3s² 3p 4s",
            "lower_term": "³P°",
            "lower_J": "1",
            "upper_conf": "3s² 3p 4p",
            "upper_term": "³D",
            "upper_J": "2",
            "A_ki": 1.9e7,
            "role": "Visible silicon emission line in high-density inductively coupled plasma.",
        },
    ],
    "O": [
        {
            "wavelength_nm": 777.19,
            "species": "O I",
            "lower_conf": "2s² 2p³(⁴S°) 3s",
            "lower_term": "⁵S°",
            "lower_J": "2",
            "upper_conf": "2s² 2p³(⁴S°) 3p",
            "upper_term": "⁵P",
            "upper_J": "3,2,1",
            "A_ki": 3.7e7,
            "role": (
                "Atomic oxygen triplet; key metric for chamber conditioning, O2 cleaning, and SiO2 etch selectivity."
            ),
        },
        {
            "wavelength_nm": 844.64,
            "species": "O I",
            "lower_conf": "2s² 2p³(⁴S°) 3s",
            "lower_term": "³S°",
            "lower_J": "1",
            "upper_conf": "2s² 2p³(⁴S°) 3p",
            "upper_term": "³P",
            "upper_J": "2,1,0",
            "A_ki": 3.2e7,
            "role": "Ground-connected triplet atomic oxygen line; direct indicator of oxygen radical concentration.",
        },
    ],
    "CF2": [
        {
            "wavelength_nm": 251.90,
            "species": "CF₂ (Ã¹B₁ → X̃¹A₁)",
            "lower_conf": "Ground state X̃¹A₁",
            "lower_term": "(0,0,0)",
            "lower_J": "vibronic",
            "upper_conf": "Excited state Ã¹B₁",
            "upper_term": "(0,v₂',0)",
            "upper_J": "vibronic",
            "A_ki": 1.0e7,
            "role": (
                "Fluorocarbon passivation polymer precursor; diagnostic for C4F8 sidewall protection film deposition."
            ),
        },
        {
            "wavelength_nm": 271.10,
            "species": "CF₂ (Ã¹B₁ → X̃¹A₁)",
            "lower_conf": "Ground state X̃¹A₁",
            "lower_term": "vibrational",
            "lower_J": "vibronic",
            "upper_conf": "Excited state Ã¹B₁",
            "upper_term": "vibrational",
            "upper_J": "vibronic",
            "A_ki": 8.0e6,
            "role": "CF2 radical emission band in fluorocarbon plasma.",
        },
    ],
    "SiF": [
        {
            "wavelength_nm": 440.05,
            "species": "SiF (A²Σ⁺ → X²Π)",
            "lower_conf": "Ground state X²Π",
            "lower_term": "v''=0",
            "lower_J": "rotational",
            "upper_conf": "Excited state A²Σ⁺",
            "upper_term": "v'=0",
            "upper_J": "rotational",
            "A_ki": 1.2e7,
            "role": "Primary volatile intermediate in Si etching by fluorine radicals (Si + 4F -> SiF4).",
        },
        {
            "wavelength_nm": 777.00,
            "species": "SiF",
            "lower_conf": "Molecular band",
            "lower_term": "vibronic",
            "lower_J": "-",
            "upper_conf": "Molecular band",
            "upper_term": "vibronic",
            "upper_J": "-",
            "A_ki": 5.0e6,
            "role": "SiF molecular band emission in the red/NIR.",
        },
    ],
    "Ar": [
        {
            "wavelength_nm": 750.39,
            "species": "Ar I",
            "lower_conf": "3s² 3p⁵(²P°₁/₂) 4s",
            "lower_term": "²[1/2]°",
            "lower_J": "1",
            "upper_conf": "3s² 3p⁵(²P°₁/₂) 4p",
            "upper_term": "²[1/2]",
            "upper_J": "0",
            "A_ki": 4.5e7,
            "role": (
                "Inert carrier actinometry line (2p1 -> 1s2); "
                "excitation cross-section matches F I 703.7 nm for actinometry."
            ),
        },
        {
            "wavelength_nm": 811.53,
            "species": "Ar I",
            "lower_conf": "3s² 3p⁵(²P°₃/₂) 4s",
            "lower_term": "²[3/2]°",
            "lower_J": "2",
            "upper_conf": "3s² 3p⁵(²P°₃/₂) 4p",
            "upper_term": "²[5/2]",
            "upper_J": "3",
            "A_ki": 3.3e7,
            "role": "Standard argon reference line in plasma diagnostic OES.",
        },
    ],
}


class TransitionAnalyzer:
    """Return wavelength candidates from local, unverified reference tables."""

    def __init__(self, ref_csv_path: str | Path):
        self.ref_csv_path = Path(ref_csv_path)
        self.ref_lines: List[Tuple[float, str]] = []
        self._load_ref_lines()

    def _load_ref_lines(self) -> None:
        if not self.ref_csv_path.exists():
            raise FileNotFoundError(f"Reference CSV not found: {self.ref_csv_path}")
        with open(self.ref_csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    wl = float(row["wavelength"])
                    sp = row["species"].strip()
                    self.ref_lines.append((wl, sp))
                except (ValueError, KeyError):
                    continue
        self.ref_lines.sort(key=lambda x: x[0])

    def identify_peak(self, peak_wl: float, tolerance: float = 0.6) -> Dict[str, Any]:
        """Associate a candidate only with transitions of that same species.

        This heuristic is not a validated species identification or a live NIST query.
        """
        matches = []
        for ref_wl, species in self.ref_lines:
            diff = abs(peak_wl - ref_wl)
            if diff <= tolerance:
                matches.append({"ref_wavelength": ref_wl, "species": species, "delta_nm": diff})

        matches.sort(key=lambda m: m["delta_nm"])

        # Check NIST transitions
        best_nist = None
        best_nist_delta = 999.0
        for sp_group, trans_list in NIST_TRANSITIONS.items():
            if matches and sp_group != matches[0]["species"]:
                continue
            for trans in trans_list:
                d = abs(peak_wl - trans["wavelength_nm"])
                if d <= tolerance and d < best_nist_delta:
                    best_nist_delta = d
                    best_nist = trans

        primary_species = matches[0]["species"] if matches else (best_nist["species"] if best_nist else "Unassigned")
        ref_wl = matches[0]["ref_wavelength"] if matches else (best_nist["wavelength_nm"] if best_nist else None)

        return {
            "observed_wavelength_nm": round(peak_wl, 2),
            "reference_wavelength_nm": ref_wl,
            "species": primary_species,
            "delta_nm": (
                round(matches[0]["delta_nm"], 3) if matches else (round(best_nist_delta, 3) if best_nist else None)
            ),
            "all_matches": matches,
            "nist_transition": best_nist,
        }
