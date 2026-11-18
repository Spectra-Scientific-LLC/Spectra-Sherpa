"""Fresh spawned workers reproduce explicit trusted-host pack composition."""

import os
import subprocess
import sys
import textwrap

from tests.test_pack_bootstrap import NODE_SOURCE


def test_spawned_pack_worker_matches_host_and_refuses_missing_composition(tmp_path):
    pack_root = tmp_path / "installed"
    pack_root.mkdir()
    (pack_root / "qualification_worker.py").write_text(NODE_SOURCE + textwrap.dedent("""
            import asyncio
            import hashlib
            import os
            from pathlib import Path
            from spectra_sherpa.app.services.dag.node_base import Node, NodeMetadata, NodePolicy, node_registry
            from spectra_sherpa.app.services.dag.bootstrap import InstalledPack, bootstrap
            from spectra_sherpa.core.pack_build import PackFile, build_sha256
            from spectra_sherpa.core.pack_manifest import PackManifest

            def initialize():
                source = Path(__file__)
                files = (PackFile(path=source.name, sha256=hashlib.sha256(source.read_bytes()).hexdigest()),)
                manifest = PackManifest(pack_id="reference", version="1.0.0", build_sha256=build_sha256(files),
                    core_min="0.6.4", core_max_exclusive="0.8.0", contract_versions=("4.0",),
                    entitlement_id="pack.reference", license_id="LicenseRef-Qualification-Fixture",
                    nodes=("pro.reference.record",), tools=())
                bootstrap(extensions=(InstalledPack(manifest, source.parent, files, (Record,)),))

            def missing_initialize():
                pass

            def mismatched_initialize():
                payload = Record.metadata.execution_contract.as_dict()
                payload["implementation_version"] = "999.0"
                Record.metadata.execution_contract = NodeExecutionContract.from_dict(payload)
                initialize()

            def resolve_and_execute():
                from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
                import numpy as np
                node = node_registry.create_node("pro.reference.record", "worker-test", {"floor": 0.0})
                result = asyncio.run(node.run(SherpaDataset(X=np.array([[-1.0, 2.0]]))))
                return os.getpid(), result.outputs["default"].X.tolist()
            """))
    script = tmp_path / "host.py"
    script.write_text(textwrap.dedent("""
            import asyncio
            import os
            from qualification_worker import initialize, missing_initialize, mismatched_initialize, resolve_and_execute
            from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

            async def main():
                initialize()
                try:
                    IsolatedWorkerPool(1)
                except ValueError as exc:
                    assert "initializer" in str(exc)
                else:
                    raise AssertionError("Pack host accepted an unconfigured worker pool")
                pool = IsolatedWorkerPool(1, initializer=initialize)
                assert pool._context.get_start_method() == "spawn"
                try:
                    async with pool.workflow():
                        first = await pool.run(resolve_and_execute, timeout=30)
                        second = await pool.run(resolve_and_execute, timeout=30)
                    assert first == second and first[0] != os.getpid() and first[1] == [[0.0, 2.0]]
                    fresh = await pool.run(resolve_and_execute, timeout=30)
                    assert fresh[0] != first[0] and fresh[1] == [[0.0, 2.0]]
                finally:
                    pool.shutdown()
                for initialize_bad in (missing_initialize, mismatched_initialize):
                    missing = IsolatedWorkerPool(1, initializer=initialize_bad)
                    try:
                        try:
                            await missing.run(resolve_and_execute, timeout=30)
                        except RuntimeError as exc:
                            assert "without a result" in str(exc)
                        else:
                            raise AssertionError("Mismatched worker executed a pack node")
                        assert missing._slots._value == 1
                    finally:
                        missing.shutdown()

            if __name__ == "__main__":
                asyncio.run(main())
            """))
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(pack_root), *sys.path))
    result = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=100)
    assert result.returncode == 0, result.stdout + result.stderr
