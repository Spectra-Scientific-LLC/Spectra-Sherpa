"""Real MCP SDK subprocess interoperability against the local HTTP bridge."""

import asyncio
import os
import socket
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

import uvicorn
from fastapi import FastAPI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from sqlalchemy.ext.asyncio import async_sessionmaker

from spectra_sherpa.app.api.v1.routes import inspection as routes
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.services.inspection_grants import issue_inspection_credential, revoke_inspection_credential


async def test_real_sdk_stdio_reads_and_revocation(test_session, test_engine, test_user, monkeypatch, tmp_path):
    # The real Workbench imports its workflow catalog before serving requests.
    # This router-only fixture must also finish scientific module registration
    # before timing a bounded inspection request (not during its first read).
    from spectra_sherpa.app.services.dag import node_registry

    assert node_registry.list_catalog_nodes()
    project = Project(name="MCP interoperability", user_id=test_user.id)
    test_session.add(project)
    await test_session.flush()
    from datetime import datetime, timezone

    import numpy as np

    from spectra_sherpa.app.core import security
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.models.data_egress import UserEgressDefaults
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.services.dataset_registry import dataset_registry

    monkeypatch.setattr(security, "is_egress_enabled", lambda: True)
    test_session.add(UserEgressDefaults(user_id=test_user.id, allow_llm_context=True, allow_llm_chat=True))
    workflow = Workflow(name="Saved facts", user_id=test_user.id, project_id=project.id)
    test_session.add(workflow)
    await test_session.flush()
    run = ExecutionRun(
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        name="Retained run",
        status="completed",
        run_kind="data",
        params_snapshot={},
        results_summary={},
        executed_at=datetime.now(timezone.utc),
    )
    test_session.add(run)
    await test_session.flush()
    handle = dataset_registry.register(
        SherpaDataset(X=np.zeros((3, 4))), owner_user_id=test_user.id, project_id=project.id
    )
    credential = await issue_inspection_credential(
        test_session, test_user, project.id, "MCP SDK 2.3.0", project_summaries=True, retained_results=True
    )
    await test_session.commit()
    sessions = async_sessionmaker(test_engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[routes.inspection_sessions] = lambda: sessions
    monkeypatch.setattr(routes, "is_local", lambda: True)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if serving.done():
                    await serving
                await asyncio.sleep(0.01)
        import httpx

        async with httpx.AsyncClient(trust_env=False) as probe:
            checked = await probe.post(
                f"http://127.0.0.1:{port}/api/v1/inspection/{project.id}/{credential.identity.client_id}/call",
                headers={"Authorization": f"Bearer {credential.token}"},
                json={"operation": "list_node_types", "arguments": {"limit": 1}},
            )
            assert checked.status_code == 200, checked.text
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-c",
                "from spectra_sherpa.cli import main; main()",
                "mcp",
                "--workbench-url",
                f"http://127.0.0.1:{port}",
                "--project-id",
                str(project.id),
                "--client-id",
                credential.identity.client_id,
            ],
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
                "DATA_DIR": str(tmp_path),
                "SPECTRA_INSPECTION_CREDENTIAL": credential.token,
            },
        )
        async with asyncio.timeout(30):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=10) as client:
                    initialized = await client.initialize()
                    assert initialized.capabilities.prompts is None
                    assert initialized.capabilities.resources is None
                    listing = await client.list_tools()
                    assert {tool.name for tool in listing.tools} == {
                        "list_node_types",
                        "describe_dataset",
                        "inspect_workflow",
                        "list_runs",
                        "get_run",
                        "get_results",
                        "get_diagnostics",
                        "compare_runs",
                    }
                    assert listing.tools[0].annotations.read_only_hint is True
                    result = await client.call_tool("list_node_types", {"limit": 1})
                    assert not result.is_error and len(result.structured_content["items"]) == 1
                    dataset = await client.call_tool("describe_dataset", {"dataset_id": handle})
                    assert not dataset.is_error and dataset.structured_content["structured"]["shape"] == [3, 4]
                    summary = await client.call_tool("inspect_workflow", {"workflow_id": workflow.id})
                    assert not summary.is_error and summary.structured_content["node_count"] == 0
                    page = await client.call_tool("list_runs", {"limit": 1})
                    assert not page.is_error and page.structured_content["runs"][0]["id"] == run.id
                    detail = await client.call_tool("get_run", {"run_id": run.id})
                    assert not detail.is_error and detail.structured_content["name"] == "Retained run"
                    metrics = await client.call_tool("get_results", {"run_id": run.id})
                    assert not metrics.is_error and metrics.structured_content["availability"] == "unavailable"
                    denied = await client.call_tool("run_workflow", {})
                    assert denied.is_error
                    async with sessions() as session:
                        await revoke_inspection_credential(session, test_user, credential.identity.client_id)
                        await session.commit()
                    refused = await client.call_tool("list_node_types", {})
                    assert refused.is_error
                    assert credential.token not in str(refused)
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, 5)
        sock.close()


def test_oversized_protocol_line_terminates_without_echoing_input(tmp_path):
    import subprocess

    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "DATA_DIR": str(tmp_path),
        "SPECTRA_INSPECTION_CREDENTIAL": "ssmcp_" + "A" * 43,
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from spectra_sherpa.cli import main; main()",
            "mcp",
            "--project-id",
            "1",
            "--client-id",
            "fb54eea9-177d-44fa-9e34-de62b1493d59",
        ],
        input="x" * 16385 + "\n",
        text=True,
        capture_output=True,
        env=env,
        timeout=15,
    )
    assert result.returncode != 0
    assert "MCP message exceeds limit" in result.stderr
    assert "ssmcp_" not in result.stderr and "x" * 100 not in result.stderr
