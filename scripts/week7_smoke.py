#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from typing import Any

import httpx


def build_csv(scale: float) -> bytes:
    lines = []
    for wn in range(400, 1400, 10):
        absorbance = scale * (0.05 + (wn % 100) / 2000)
        lines.append(f"{wn},{absorbance:.6f}")
    return ("\n".join(lines) + "\n").encode("ascii")


def ensure_ok(response: httpx.Response, label: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"{label} failed: {exc.response.text}") from exc
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Week 7 smoke test for backend APIs.")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000/api/v1",
        help="API base URL (default: http://127.0.0.1:8000/api/v1)",
    )
    parser.add_argument(
        "--api-key",
        default="default-local-key",
        help="API key (default: default-local-key)",
    )
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--poll-seconds", type=float, default=1.5)
    parser.add_argument("--poll-max", type=int, default=40)
    args = parser.parse_args()

    headers = {"X-API-Key": args.api_key}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    with httpx.Client(base_url=args.base_url, headers=headers, timeout=args.timeout) as client:
        health = client.get("/health")
        if health.status_code != 200:
            raise RuntimeError("Backend is not responding on /health")

        experiment_payload = {
            "name": f"Week7 Smoke {timestamp}",
            "description": "Automated smoke test experiment",
            "metadata": {
                "hardware": {"instrument": "Smoke-FTIR", "detector": "Demo"},
                "doe": {"design": "screening", "objective": "smoke test"},
                "mixtures": [{"component": "CH4", "fraction": 25}],
            },
        }
        experiment = ensure_ok(
            client.post("/experiments", json=experiment_payload), "create experiment"
        )
        exp_id = experiment["id"]
        exp_prefix = f"exp_{exp_id:03d}"

        upload_data = build_csv(1.0)
        files = {"file": ("sample.csv", upload_data, "text/csv")}
        upload_resp = ensure_ok(
            client.post(
                f"/experiments/{exp_id}/files",
                data={"stage": "raw"},
                files=files,
            ),
            "upload experiment file",
        )
        file_path = upload_resp["file_path"]

        _ = ensure_ok(client.get(f"/experiments/{exp_id}/files"), "list files")

        version_resp = ensure_ok(
            client.post(
                f"/experiments/{exp_id}/versions",
                json={
                    "version_name": "v1",
                    "description": "Smoke snapshot",
                    "stages": ["raw"],
                },
            ),
            "create version",
        )
        version_name = version_resp["version_name"]

        ensure_ok(
            client.post(
                f"/experiments/{exp_id}/versions/{version_name}/restore",
                params={"overwrite": "true"},
            ),
            "restore version",
        )

        preprocess_payload = {
            "spectra": [
                {
                    "label": "Sample",
                    "file_path": f"experiments/{exp_prefix}/{file_path}",
                    "source": "csv",
                }
            ],
            "settings": {},
        }
        preprocess_resp = ensure_ok(
            client.post("/builder/preprocess", json=preprocess_payload),
            "builder preprocess",
        )
        if preprocess_resp.get("status") != "ok":
            raise RuntimeError("builder preprocess returned non-ok status")

        processed = preprocess_resp["data"]
        blend_payload = {
            "species": processed,
            "concentration_timeseries": {"Sample": [0, 0.25, 0.5, 0.75, 1.0]},
            "settings": {},
        }
        blend_resp = ensure_ok(
            client.post("/builder/blend", json=blend_payload),
            "builder blend",
        )
        if blend_resp.get("status") != "ok":
            raise RuntimeError("builder blend returned non-ok status")

        calibration_payload = {
            "compound_name": "SmokeCompound",
            "concentration_mode": "product",
            "x_unit": "ppm*m",
            "metadata": {"source": "smoke"},
        }
        calibration = ensure_ok(
            client.post("/calibrations", json=calibration_payload), "create calibration"
        )
        cal_id = calibration["id"]

        for idx, scale in enumerate([0.8, 1.0, 1.2, 1.4], start=1):
            measurement_file = build_csv(scale)
            meas_files = {"file": (f"measurement_{idx}.csv", measurement_file, "text/csv")}
            ensure_ok(
                client.post(
                    f"/calibrations/{cal_id}/measurements",
                    data={"concentration": str(idx * 10)},
                    files=meas_files,
                ),
                f"upload measurement {idx}",
            )

        fit_resp = ensure_ok(
            client.post(
                f"/calibrations/{cal_id}/fit",
                json={"model_type": "linear", "settings": {}, "version_name": "v_smoke"},
            ),
            "fit calibration",
        )
        job_id = fit_resp["job_id"]

        status = None
        last_job = None
        for _ in range(args.poll_max):
            job_resp = ensure_ok(client.get(f"/jobs/{job_id}"), "job status")
            last_job = job_resp
            status = job_resp["status"]
            if status in {"completed", "failed"}:
                break
            time.sleep(args.poll_seconds)

        if status != "completed":
            error_message = None
            if isinstance(last_job, dict):
                error_message = last_job.get("error_message") or last_job.get("progress_message")
            detail = f": {error_message}" if error_message else ""
            raise RuntimeError(
                f"Calibration fit job {job_id} did not complete: {status}{detail}"
            )

        _ = ensure_ok(client.get(f"/calibrations/{cal_id}/models"), "list models")

        print(json.dumps({"status": "ok", "experiment_id": exp_id, "calibration_id": cal_id}))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
