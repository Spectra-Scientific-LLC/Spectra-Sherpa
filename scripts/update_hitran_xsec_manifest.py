#!/usr/bin/env python3
"""Build the packaged HITRAN absorption cross-section manifest.

The manifest is intentionally generated from HITRANonline's public x-section
catalog rather than a hand-curated summary page. It records the molecule id
used by HITRANonline/HAPI2 plus the selectable measurement rows shown on the
site, then the runtime loader still downloads spectra through HAPI2 with the
user's own HITRAN key.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

CATALOG_URL = "https://hitran.org/xsc/"
META_URL = "https://hitran.org/xsc/get-meta"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "src/spectra_sherpa/data/synthesis/hitran_xsec_manifest.json"


@dataclass
class MoleculeRow:
    hitran_molecule_id: int
    name: str
    formula: str
    category: str | None = None
    modalities: list[str] = field(default_factory=list)


class MoleculeListParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.category: str | None = None
        self.rows: list[MoleculeRow] = []
        self._in_h3 = False
        self._h3_parts: list[str] = []
        self._in_row = False
        self._row_id: int | None = None
        self._in_td = False
        self._td_index = -1
        self._td_parts: list[str] = []
        self._td_classes: list[str] = []
        self._row_cells: list[str] = []
        self._row_modalities: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        if tag == "h3":
            self._in_h3 = True
            self._h3_parts = []
        if tag == "tr":
            classes = attr_map.get("class", "")
            match = re.search(r"\bmolec-(\d+)\b", classes)
            if match:
                self._in_row = True
                self._row_id = int(match.group(1))
                self._td_index = -1
                self._row_cells = []
                self._row_modalities = []
        if self._in_row and tag == "td":
            self._in_td = True
            self._td_index += 1
            self._td_parts = []
            self._td_classes = (attr_map.get("class") or "").split()
        if self._in_row and self._in_td and tag == "span":
            classes = attr_map.get("class", "")
            if "fa-circle-check" in classes:
                if self._td_index == 0:
                    self._row_modalities.append("IR")
                elif self._td_index == 1:
                    self._row_modalities.append("UV/Vis")

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3" and self._in_h3:
            text = _clean_text("".join(self._h3_parts))
            self.category = re.sub(r"\s+", " ", text).strip() or self.category
            self._in_h3 = False
        if tag == "td" and self._in_td:
            self._row_cells.append(_clean_text("".join(self._td_parts)))
            self._in_td = False
        if tag == "tr" and self._in_row:
            if self._row_id is not None and len(self._row_cells) >= 4:
                name = self._row_cells[2]
                formula = _normalize_formula(self._row_cells[3])
                if name and formula:
                    self.rows.append(
                        MoleculeRow(
                            hitran_molecule_id=self._row_id,
                            name=name,
                            formula=formula,
                            category=self.category,
                            modalities=sorted(set(self._row_modalities)),
                        )
                    )
            self._in_row = False
            self._row_id = None

    def handle_data(self, data: str) -> None:
        if self._in_h3:
            self._h3_parts.append(data)
        if self._in_td:
            self._td_parts.append(data)


class MetaTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.variants: list[dict[str, Any]] = []
        self._section = ""
        self._in_header = False
        self._header_parts: list[str] = []
        self._in_row = False
        self._xsec_id: int | None = None
        self._in_td = False
        self._td_parts: list[str] = []
        self._row_cells: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        if tag == "tr" and attr_map.get("id") == "xsec-meta-table-molecule-header":
            self._in_header = True
            self._header_parts = []
            return
        if tag == "tr":
            match = re.search(r"\bxsec-(\d+)\b", attr_map.get("class", ""))
            if match:
                self._in_row = True
                self._xsec_id = int(match.group(1))
                self._row_cells = []
        if self._in_row and tag == "td":
            self._in_td = True
            self._td_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self._in_header:
            self._section = _clean_text("".join(self._header_parts))
            self._in_header = False
        if tag == "td" and self._in_td:
            self._row_cells.append(_clean_text("".join(self._td_parts)))
            self._in_td = False
        if tag == "tr" and self._in_row:
            parsed = _parse_meta_row(self._row_cells, self._xsec_id, self._section)
            if parsed:
                self.variants.append(parsed)
            self._in_row = False
            self._xsec_id = None

    def handle_data(self, data: str) -> None:
        if self._in_header:
            self._header_parts.append(data)
        if self._in_td:
            self._td_parts.append(data)


def _fetch_text(url: str, *, params: dict[str, Any] | None = None, timeout: float = 30.0) -> str:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "SpectraSherpa/manifest-builder"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def _clean_text(value: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", value.replace("\xa0", " "))).strip()


def _normalize_formula(value: str) -> str:
    value = _clean_text(value)
    value = value.replace("−", "-").replace("–", "-")
    return value


def _parse_range(value: str) -> list[float] | None:
    numbers = re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", value)
    if len(numbers) < 2:
        return None
    low = float(numbers[0])
    high = float(numbers[1])
    return [min(low, high), max(low, high)]


def _parse_float(value: str) -> float | None:
    match = re.search(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", value)
    return float(match.group(0)) if match else None


def _parse_int(value: str) -> int | None:
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def _parse_meta_row(cells: list[str], xsec_id: int | None, section: str) -> dict[str, Any] | None:
    if len(cells) < 7:
        return None
    x_range = _parse_range(cells[1])
    temperature = _parse_float(cells[2])
    pressure = _parse_float(cells[3])
    if x_range is None or temperature is None or pressure is None:
        return None
    broadener = cells[6] or None
    return {
        "xsec_id": xsec_id,
        "modality": "UV/Vis" if "UV" in section.upper() else "IR",
        "wavenumber_cm1": x_range,
        "temperature_k": temperature,
        "pressure_torr": pressure,
        "resolution_cm1": _parse_float(cells[4]),
        "npts": _parse_int(cells[5]),
        "broadener": broadener,
        "sets": 1,
        "source": "HITRANonline xsc/get-meta",
    }


def load_catalog() -> list[MoleculeRow]:
    parser = MoleculeListParser()
    parser.feed(_fetch_text(CATALOG_URL))
    rows = sorted(parser.rows, key=lambda item: (item.name.lower(), item.formula.lower(), item.hitran_molecule_id))
    seen: set[int] = set()
    unique_rows: list[MoleculeRow] = []
    for row in rows:
        if row.hitran_molecule_id in seen:
            continue
        seen.add(row.hitran_molecule_id)
        unique_rows.append(row)
    return unique_rows


def load_variants(molecule_id: int) -> list[dict[str, Any]]:
    try:
        raw = _fetch_text(META_URL, params={"molecule_id": molecule_id})
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            print(f"warning: metadata unavailable for molecule {molecule_id} (HTTP 404)", file=sys.stderr)
            return []
        raise
    payload = json.loads(raw)
    parser = MetaTableParser()
    parser.feed(str(payload.get("html", "")))
    return parser.variants


def build_manifest(delay_s: float) -> dict[str, Any]:
    rows = load_catalog()
    components: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if index > 1 and delay_s > 0:
            time.sleep(delay_s)
        variants = load_variants(row.hitran_molecule_id)
        components.append(
            {
                "id": f"hitran_xsec:{row.hitran_molecule_id}",
                "hitran_molecule_id": row.hitran_molecule_id,
                "name": row.name,
                "formula": row.formula,
                "cas": None,
                "category": row.category,
                "modalities": row.modalities,
                "variants": variants,
            }
        )
        print(
            f"{index:03d}/{len(rows):03d} {row.hitran_molecule_id}: {row.name} ({len(variants)} measurements)",
            file=sys.stderr,
        )
    return {
        "source": "HITRANonline absorption cross-section catalog",
        "source_url": CATALOG_URL,
        "metadata_url": META_URL,
        "edition": "HITRAN2024",
        "notes": (
            "Generated from HITRANonline xsc molecule and measurement metadata. "
            "Spectra are downloaded through HAPI2 at runtime with the user's HITRAN key."
        ),
        "component_count": len(components),
        "components": components,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--delay", type=float, default=0.02, help="Delay between metadata requests.")
    args = parser.parse_args()
    manifest = build_manifest(args.delay)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n")
    print(f"Wrote {args.output} with {manifest['component_count']} components")


if __name__ == "__main__":
    main()
