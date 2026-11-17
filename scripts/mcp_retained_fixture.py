#!/usr/bin/env python3
"""Seed a synthetic retained-reader fixture in the qualification profile only.

This is fixture preparation, not workflow execution or MCP mutation. Canonical
statistics and retention come from the installed wheel being qualified.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from pathlib import Path


async def seed(project_id: int, workflow_id: int) -> int:
    from spectra_sherpa.app.core.config import settings
    from spectra_sherpa.app.db.session import async_session, engine
    from spectra_sherpa.app.models import ExecutionRun, Workflow
    from spectra_sherpa.app.services.dag.regression_comparison import build_regression_comparison
    from spectra_sherpa.app.services.pca_review_evidence import SCHEMA
    from spectra_sherpa.app.services.run_output_retention import retain_run_outputs

    # Refuse a scientist's real profile, even if this helper is invoked directly.
    profile = Path(settings.data_dir).resolve()
    if not profile.parent.name.startswith("spectra-mcp-installed-") or profile.name != "data":
        raise ValueError("Retained fixture requires the isolated qualification profile")
    async with async_session() as session:
        workflow = await session.get(Workflow, workflow_id)
        if workflow is None or workflow.project_id != project_id:
            raise ValueError("Qualification workflow is unavailable")
        graph = "b" * 64
        receipt = {
            "schema_version": SCHEMA,
            "model_kind": "pca",
            "graph_digest": graph,
            "n_components": 2,
            "calibration_t2_limit": 2.0,
            "application_t2_limit": 5.0,
            "q_limit": 4.0,
            "rows": [
                {"id": f"fixture-private-{i}", "role": "calibration", "t2": float(i), "q": float(2 * i)}
                for i in range(4)
            ],
        }
        comparison = build_regression_comparison(
            [1, 2, 3, 4],
            [2, 2, 3, 5],
            role="held_out_test",
            target_names=["concentration"],
            sample_labels=[f"fixture-private-{i}" for i in range(4)],
        )
        evidence = retain_run_outputs(
            workflow.user_id,
            {
                "model": {"comparison": comparison},
                "__workflow__": {
                    "definition": {"schema_version": 1, "nodes": [], "edges": []},
                    "pca_review": {"model": receipt},
                },
            },
            {},
        )
        run = ExecutionRun(
            user_id=workflow.user_id,
            project_id=project_id,
            workflow_id=workflow_id,
            name="Synthetic retained-reader fixture",
            status="completed",
            run_kind="training",
            integrity_hash=graph,
            evidence_completeness=evidence,
            params_snapshot={},
            source_metadata={},
        )
        session.add(run)
        await session.commit()
        identity = run.id
    await engine.dispose()
    return identity


if __name__ == "__main__":
    with contextlib.redirect_stdout(sys.stderr):
        identity = asyncio.run(seed(int(sys.argv[1]), int(sys.argv[2])))
    print(json.dumps({"run_id": identity}))
