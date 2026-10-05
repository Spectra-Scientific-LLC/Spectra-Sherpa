#!/usr/bin/env python3
"""Prove an installed public wheel has no private product or implicit activation."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import importlib.util
import json
from pathlib import Path

from workbench_runtime_smoke import _NETWORK_ATTEMPTS, _execute_once, _install_network_guard


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scp", choices=("absent", "available"), required=True)
    args = parser.parse_args()
    import spectra_sherpa

    installed = importlib.metadata.distribution("spectra-sherpa")
    assert (
        Path(installed.locate_file("spectra_sherpa/__init__.py")).resolve() == Path(spectra_sherpa.__file__).resolve()
    )
    for name in ("spectra_hybrid", "spectra_hybrid_contracts", "spectrasherpa_server"):
        assert importlib.util.find_spec(name) is None, name
    assert (importlib.util.find_spec("spectrochempy") is not None) == (args.scp == "available")

    _install_network_guard()
    from fastapi.testclient import TestClient

    from spectra_sherpa.app.core.config import AppConfig
    from spectra_sherpa.app.main import create_app

    try:
        AppConfig(mode="hybrid")
    except ValueError:
        pass
    else:
        raise AssertionError("OSS accepted private runtime")
    app = create_app(include_frontend=False)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        assert client.get("/api/health").status_code == 200
        config = client.get("/api/v1/config").json()
        assert config["mode"] == "local"
        assert not config.get("uiExtensions")
        assert not config.get("advisorContextPolicy")
        assert not any("/hybrid" in p or "/config/spectrasherpa" in p for p in app.openapi()["paths"])
    digest = asyncio.run(_execute_once())
    assert digest == asyncio.run(_execute_once())
    assert _NETWORK_ATTEMPTS == []
    print(
        json.dumps(
            {
                "status": "passed",
                "scientific_result_sha256": digest,
                "private_modules": False,
                "outbound_attempts": 0,
                "scp": args.scp,
            }
        )
    )


if __name__ == "__main__":
    main()
