#!/usr/bin/env python3
"""Return a previously qualified node inventory to its four-star baseline.

Any change under the qualified product paths invalidates the retained paired
platform result.  This tool makes that state explicit without changing the
human-reviewed scientific assessment: it removes only the prior pair sentence
and pair reference, marks every active node with the qualification-only gap,
and leaves all substantive evidence and confidence judgements intact.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_PAIR_REFERENCE = "docs/evidence/canonical-node-paired-qualification.json"
_PAIR_SENTENCE_PREFIX = "Exact-tree paired Darwin/Linux qualification retained "


def prepare(repository_root: Path) -> None:
    assessment_path = repository_root / "docs/evidence/canonical-node-readiness-assessments.json"
    source = json.loads(assessment_path.read_text(encoding="utf-8"))
    rows = source.get("nodes")
    if not isinstance(rows, list) or not rows:
        raise ValueError("readiness assessment has no active node inventory")
    retired = set(source.get("retired_node_types") or [])
    for row in rows:
        if isinstance(row, dict) and row.get("node_type") in retired:
            continue
        if not isinstance(row, dict) or row.get("stars") != 5 or row.get("fault_patterns") != []:
            raise ValueError(f"{row.get('node_type') if isinstance(row, dict) else 'unknown'} is not five-star clean")
        summary = str(row.get("summary") or "")
        sentence_start = summary.rfind(_PAIR_SENTENCE_PREFIX)
        if sentence_start < 0:
            raise ValueError(f"{row.get('node_type')} has no retained pair summary")
        row.update(
            {
                "stars": 4,
                "summary": summary[:sentence_start].rstrip(),
                "fault_patterns": ["evidence_qualification_gap"],
                "next_star_blocker": "Retain exact node evidence in paired-platform qualification.",
                "evidence_refs": [ref for ref in row.get("evidence_refs", []) if ref != _PAIR_REFERENCE],
            }
        )
    source.pop("paired_qualification", None)
    source["schema_version"] = "spectra-canonical-node-readiness-assessments/3"
    assessment_path.write_text(json.dumps(source, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[3])
    arguments = parser.parse_args()
    prepare(arguments.repository_root.resolve())


if __name__ == "__main__":
    main()
