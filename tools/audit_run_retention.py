"""Measure real fixed-fixture serialization, without claiming preview completeness."""

import argparse
import asyncio
import json
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.run_evidence_cases import executed_cases  # noqa: E402

from spectra_sherpa.app.api.v1.routes.workflows._helpers import (  # noqa: E402
    _compact_results_for_run_history,
    contains_run_history_truncation,
)
from spectra_sherpa.app.schemas.run_evidence import RunEvidence  # noqa: E402
from spectra_sherpa.app.services import run_output_retention as retention  # noqa: E402
from spectra_sherpa.app.services.serialization import serialize_result  # noqa: E402


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    records = {}
    for name, value in (await executed_cases()).items():
        started = time.perf_counter()
        wire = serialize_result(value)
        retained = serialize_result(
            {port: item for port, item in value.items() if not port.startswith("_")}, retain_full=True
        )
        compact = _compact_results_for_run_history(wire)
        payload = json.dumps(compact, separators=(",", ":"), default=str).encode()
        records[name] = {
            "api_bytes": len(json.dumps(wire, separators=(",", ":"), default=str).encode()),
            "history_bytes": len(payload),
            "retained_bytes": len(json.dumps(retained, separators=(",", ":"), default=str).encode()),
            "history_reduced": contains_run_history_truncation(compact),
            "serialization_ms": round(1000 * (time.perf_counter() - started), 3),
            "output_keys": sorted(wire),
        }
        with tempfile.TemporaryDirectory() as root:
            retention.settings = replace(retention.settings, data_dir=Path(root))
            started = time.perf_counter()
            evidence = RunEvidence.model_validate(retention.retain_run_outputs(1, {name: value}, {}))
            records[name]["publication_ms"] = round(1000 * (time.perf_counter() - started), 3)
            retrieval_ms = []
            for item in evidence.outputs[name].values():
                if item.storage is not None:
                    started = time.perf_counter()
                    retention.read_output(1, item)
                    retrieval_ms.append(1000 * (time.perf_counter() - started))
            records[name]["max_single_output_read_ms"] = round(max(retrieval_ms, default=0), 3)
            records[name]["metadata_bytes"] = len(evidence.model_dump_json().encode())
            records[name]["missing_outputs"] = [
                port
                for port, item in evidence.outputs[name].items()
                if item.state == "missing" and not port.startswith("_")
            ]
            records[name]["policy_excluded_outputs"] = [
                port
                for port, item in evidence.outputs[name].items()
                if item.state == "missing" and port.startswith("_")
            ]
    report = json.dumps({"schema": "run-retention-audit/v1", "cases": records}, indent=2)
    if args.output:
        args.output.write_text(report + "\n")
    else:
        print(report)


if __name__ == "__main__":
    asyncio.run(main())
