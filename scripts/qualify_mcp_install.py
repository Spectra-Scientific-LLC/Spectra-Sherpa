#!/usr/bin/env python3
"""Exercise an installed wheel through real Workbench HTTP and MCP stdio.

Run with the interpreter into which the exact wheel[mcp] was installed. This
probe creates an isolated local profile; it never uses a scientist's database.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import platform
import socket
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


async def qualify(root: Path) -> dict:
    import spectra_sherpa

    # Source tests are a separate gate and cannot stand in for installed proof.
    Path(spectra_sherpa.__file__).resolve().relative_to(Path(sysconfig.get_paths()["purelib"]).resolve())
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "APP_MODE": "local",
        "SITE_PROFILE": "local",
        "EGRESS_ENABLED": "false",
        "DATA_DIR": str(root / "data"),
        "DATABASE_URL": f"sqlite+aiosqlite:///{root / 'data' / 'sherpa.db'}",
        "MPLCONFIGDIR": str(root / "mpl"),
        "SCP_CONFIG_HOME": str(root / "scp"),
        "SCP_PROJECTS_HOME": str(root / "scp-projects"),
    }
    env.pop("PYTHONPATH", None)
    (root / "data").mkdir()
    log = (root / "workbench.log").open("w")
    process = None

    async def start() -> subprocess.Popen:
        candidate = subprocess.Popen(
            [sys.executable, "-c", "from spectra_sherpa.cli import main; main()", "--port", str(port), "--no-browser"],
            cwd=root,
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            async with asyncio.timeout(90), httpx.AsyncClient(trust_env=False, timeout=2) as http:
                while True:
                    if candidate.poll() is not None:
                        raise RuntimeError("Installed Workbench exited during startup")
                    try:
                        response = await http.get(f"{origin}/api/v1/health")
                        if response.status_code == 200:
                            return candidate
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.2)
        except BaseException:
            stop(candidate)
            raise

    try:
        process = await start()
        headers = {"X-Spectra-Workbench": "inspection", "Origin": origin}
        async with httpx.AsyncClient(base_url=f"{origin}/api/v1", trust_env=False, timeout=15) as http:
            project = await http.post("/projects", json={"name": "Installed MCP qualification"})
            project.raise_for_status()
            project_id = project.json()["id"]
            path = f"/projects/{project_id}/inspection-clients"
            workflow = await http.post("/workflows", json={"name": "Saved inspection facts", "project_id": project_id})
            workflow.raise_for_status()
            workflow_id = workflow.json()["id"]
            issued = await http.post(
                path,
                headers=headers,
                json={
                    "client_label": "MCP Python SDK qualification",
                    "confirm_external_provider": True,
                    "project_summaries": True,
                    "retained_results": True,
                },
            )
            issued.raise_for_status()
            connection = issued.json()
            params = StdioServerParameters(
                command=sys.executable,
                args=[
                    "-c",
                    "from spectra_sherpa.cli import main; main()",
                    "mcp",
                    "--workbench-url",
                    origin,
                    "--project-id",
                    str(project_id),
                    "--client-id",
                    connection["client_id"],
                ],
                cwd=root,
                env={**env, "SPECTRA_INSPECTION_CREDENTIAL": connection["credential"]},
            )
            async with asyncio.timeout(180), stdio_client(params) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=35) as client:
                    initialized = await client.initialize()
                    assert initialized.capabilities.prompts is None
                    assert initialized.capabilities.resources is None
                    catalog = await client.list_tools()
                    assert {tool.name for tool in catalog.tools} == {
                        "list_node_types",
                        "describe_dataset",
                        "inspect_workflow",
                        "list_runs",
                        "get_run",
                    }
                    assert catalog.tools[0].annotations.read_only_hint is True
                    first = await client.call_tool("list_node_types", {"limit": 1})
                    assert not first.is_error and len(first.structured_content["items"]) == 1
                    for operation in ("run_workflow", "save_workflow", "export_run", "apply_model"):
                        refused = await client.call_tool(operation, {})
                        assert refused.is_error
                    privacy_refused = await client.call_tool("inspect_workflow", {"workflow_id": workflow_id})
                    assert privacy_refused.is_error
                    stop(process)
                    env["EGRESS_ENABLED"] = "true"
                    process = await start()
                    workflow_summary = await client.call_tool("inspect_workflow", {"workflow_id": workflow_id})
                    assert not workflow_summary.is_error and workflow_summary.structured_content["node_count"] == 0
                    run_page = await client.call_tool("list_runs", {})
                    assert not run_page.is_error and run_page.structured_content == {"runs": [], "next_offset": None}
                    resumed = await client.call_tool("list_node_types", {"limit": 1})
                    assert resumed.structured_content == first.structured_content
                    revoked = await http.delete(f"{path}/{connection['client_id']}", headers=headers)
                    revoked.raise_for_status()
                    stop(process)
                    process = await start()
                    refused = await client.call_tool("list_node_types", {})
                    assert refused.is_error and connection["credential"] not in str(refused)
                    history = await http.get(f"/projects/{project_id}/inspection-calls", headers=headers)
                    history.raise_for_status()
                    assert len(history.json()) >= 3
                    assert connection["credential"] not in history.text
        return {
            "client": "MCP Python SDK",
            "client_version": importlib.metadata.version("mcp"),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "package_version": importlib.metadata.version("spectra-sherpa"),
            "checks": {
                name: True
                for name in (
                    "installed_workbench_startup",
                    "stdio_handshake",
                    "closed_tool_catalog",
                    "bounded_node_read",
                    "workflow_summary_read",
                    "empty_run_navigation_read",
                    "global_privacy_denial",
                    "no_prompts_or_resources",
                    "write_refusal",
                    "read_after_restart",
                    "revocation_after_restart",
                    "payload_free_local_history",
                )
            },
        }
    finally:
        if process is not None and process.poll() is None:
            stop(process)
        log.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    wheel_hash = hashlib.sha256(args.wheel.read_bytes()).hexdigest()
    direct = json.loads(importlib.metadata.distribution("spectra-sherpa").read_text("direct_url.json") or "{}")
    assert (
        direct.get("archive_info", {}).get("hashes", {}).get("sha256") == wheel_hash
    ), "Installed wheel identity mismatch"
    with tempfile.TemporaryDirectory(prefix="spectra-mcp-installed-") as temporary:
        result = asyncio.run(qualify(Path(temporary)))
    result.update(
        schema_version="spectra-mcp-install-qualification/1",
        source_revision=args.source_revision,
        wheel_sha256=wheel_hash,
        wheel=args.wheel.name,
        target_release="0.7.0",
    )
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
