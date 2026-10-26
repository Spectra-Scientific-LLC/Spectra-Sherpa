"""Verify every local BOSCH wafer against independent raw dictionary lookups."""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import subprocess
import sys
import time
from pathlib import Path

import h5py
import numpy as np

import spectra_sherpa
from spectra_sherpa.io.bosch_netcdf import read_bosch_netcdf
from spectra_sherpa.io.types import ParserLimits

try:
    from .download_data import FILES, checksum
except ImportError:
    from download_data import FILES, checksum


def verify(directory: Path) -> dict:
    source_root = Path(spectra_sherpa.__file__).resolve().parents[1]
    package = Path(__file__).resolve().parents[2]
    if source_root != package / "src":
        raise RuntimeError(f"Wrong source tree: {source_root}, expected {package / 'src'}")
    files = {}
    for name, expected in FILES.items():
        path = directory / name
        if checksum(path) != expected:
            raise ValueError(f"{name} differs from the Zenodo record checksum")
        with path.open("rb") as stream:
            sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
        files[name] = {"size_bytes": path.stat().st_size, "md5": expected, "sha256": sha256}
    records = []
    for source_name, dictionary_name in [
        ("Day_2024_08_05.nc", "Dictionary_OES.nc"),
        ("Process_data.nc", "Dictionary_process.nc"),
    ]:
        with h5py.File(directory / dictionary_name, "r") as f:
            decoder = f["data"][:]
        with h5py.File(directory / source_name, "r") as f:
            groups = list(f)
        for name in groups:
            started = time.monotonic()
            dataset = read_bosch_netcdf(
                directory / source_name,
                dictionary_path=directory / dictionary_name,
                group=name,
                limits=ParserLimits(max_source_bytes=1024**3),
            )
            expected_hash = hashlib.sha256()
            with h5py.File(directory / source_name, "r") as f:
                group = f[name]
                assert dataset.shape == group["data"].shape
                np.testing.assert_array_equal(dataset.sample_axis.values, group["times"][:])
                if source_name.startswith("Day_"):
                    np.testing.assert_array_equal(dataset.feature_axis.values, group["wavelengths"][:])
                    assert dataset.feature_axis.units == "nm"
                else:
                    assert dataset.feature_axis.labels == [v.decode() for v in group["feature"][:]]
                    assert dataset.data_role == "X_features"
                for offset in range(0, dataset.n_samples, 128):
                    expected = np.asarray(decoder[group["data"][offset : offset + 128]], dtype=np.float64)
                    np.testing.assert_array_equal(dataset.X[offset : offset + 128], expected)
                    expected_hash.update(memoryview(np.ascontiguousarray(expected)))
            actual_hash = hashlib.sha256(memoryview(dataset.X)).hexdigest()
            assert actual_hash == expected_hash.hexdigest()
            authority = dataset.get_extra("ingestion.authority")
            assert [member["sha256"] for member in authority["source_members"]] == [
                files[source_name]["sha256"],
                files[dictionary_name]["sha256"],
            ]
            assert len(set(dataset.sample_axis.sample_table["sample_id"])) == dataset.n_samples
            records.append(
                {
                    "file": source_name,
                    "group": name,
                    "shape": list(dataset.shape),
                    "data_role": dataset.data_role,
                    "decoded_float64_sha256": actual_hash,
                    "all_values_exact": True,
                    "timestamps_exact": True,
                    "axis_exact": True,
                    "seconds": round(time.monotonic() - started, 3),
                }
            )
            print(f"PASS {source_name}/{name}: {dataset.shape}", flush=True)
            del dataset
            gc.collect()
    return {
        "public_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=package, text=True).strip(),
        "source_root": str(source_root),
        "interpreter": sys.executable,
        "python": sys.version,
        "versions": {
            name: importlib.metadata.version(name)
            for name in ["numpy", "scipy", "h5py", "netCDF4", "cftime", "scikit-learn"]
        },
        "files": files,
        "groups": records,
        "limitation": "One real OES day (six wafers), and all process groups; other OES days not downloaded.",
        "reader_sha256": hashlib.sha256((package / "src/spectra_sherpa/io/bosch_netcdf.py").read_bytes()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.directory)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Verified {len(result['groups'])} groups; report {args.report}")


if __name__ == "__main__":
    main()
