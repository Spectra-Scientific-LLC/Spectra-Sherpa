"""Bounded lossless storage of large two-dimensional run datasets.

Each compressed numeric partition uses the existing content-addressed store and
quotas. The manifest is published last. No pickle or executable codec is used.
"""

from __future__ import annotations

import base64
import zlib

import numpy as np

from spectra_sherpa.app.schemas.run_evidence import OutputEvidence

SCHEMA = "spectrasherpa-partitioned-run-output/1"
MAX_VALUES = 16_000_000
PARTITION_VALUES = 200_000
MAX_DECODED_BYTES = 8 * 1024 * 1024


def retain_dataset(user_id, dataset, *, role, byte_limit):
    from spectra_sherpa.app.services.run_output_retention import retain_output
    from spectra_sherpa.app.services.serialization import serialize_result

    if dataset.ndim != 2 or dataset.X.size > MAX_VALUES or dataset.n_features > PARTITION_VALUES:
        raise ValueError("Dataset exceeds partitioned retention dimensions")
    if dataset.X.dtype.kind != "f" or dataset.X.dtype.itemsize > 8:
        raise ValueError("Partitioned retention requires float32 or float64 spectra")
    if not np.isfinite(dataset.X).all():
        raise ValueError("Partitioned retention requires finite spectral values")
    # A one-feature projection retains complete sample identity without expanding
    # the large spectral matrix. A one-row projection supplies the feature axis.
    header = serialize_result(dataset[:, :1], owner_user_id=user_id, retain_full=True)
    feature = serialize_result(dataset[:1, :], owner_user_id=user_id, retain_full=True)
    header.pop("data", None)
    header.update(
        shape=list(dataset.shape), n_features=dataset.n_features, dataset_id=dataset.dataset_id, title=dataset.title
    )
    header["x_axis"] = feature.get("x_axis")
    header["scientific_projection"] = dataset.scientific_projection(include_data=False, include_sample_table=False)
    header["manifest"] = dataset.manifest.model_dump(mode="json")
    for key in ("wavenumbers", "feature_names"):
        header["metadata"].pop(key, None)
        if key in feature["metadata"]:
            header["metadata"][key] = feature["metadata"][key]
    partitions = []
    used = 0
    rows_per_partition = max(1, PARTITION_VALUES // dataset.n_features)
    for start in range(0, dataset.n_samples, rows_per_partition):
        rows = dataset.X[start : start + rows_per_partition]
        raw = np.ascontiguousarray(rows, dtype="<f8").view(np.uint8).reshape(-1, 8).T.copy().tobytes()
        if len(raw) > MAX_DECODED_BYTES:
            raise ValueError("Decoded retention partition exceeds byte limit")
        packed = {
            "codec": "zlib-shuffle-float64-le/1",
            "raw_bytes": len(raw),
            "data": base64.b64encode(zlib.compress(raw)).decode(),
        }
        item = retain_output(user_id, packed, role=role, byte_limit=byte_limit - used)
        used += item.byte_count
        partitions.append({"start": start, "rows": len(rows), "evidence": item.model_dump()})
    manifest = {"schema": SCHEMA, "header": header, "partitions": partitions, "partition_bytes": used}
    import json

    if len(json.dumps(manifest).encode()) > 900_000:
        raise ValueError("Retention manifest exceeds metadata limit")
    item = retain_output(user_id, manifest, role=role, byte_limit=byte_limit - used)
    return item.model_copy(update={"partition_bytes": used}), used + item.byte_count


def expand_dataset(user_id, manifest):
    from spectra_sherpa.app.services.run_output_retention import read_output

    header = manifest["header"]
    shape = header["shape"]
    if len(shape) != 2 or any(type(n) is not int or n < 1 for n in shape) or shape[0] * shape[1] > MAX_VALUES:
        raise ValueError("Invalid partitioned output shape")
    if not 1 <= len(manifest["partitions"]) <= 1024:
        raise ValueError("Invalid retention partition count")
    rows = []
    for partition in manifest["partitions"]:
        if partition["start"] != len(rows) or not 1 <= partition["rows"] <= shape[0] - len(rows):
            raise ValueError("Noncontiguous retention partitions")
        packed = read_output(user_id, OutputEvidence.model_validate(partition["evidence"]), expand_partitions=False)
        size = packed.get("raw_bytes")
        if (
            packed.get("codec") not in {"zlib-shuffle-float64-le/1", "zlib-float64-le/1"}
            or type(size) is not int
            or not 0 < size <= MAX_DECODED_BYTES
        ):
            raise ValueError("Invalid retained partition codec or size")
        decoder = zlib.decompressobj()
        raw = decoder.decompress(base64.b64decode(packed["data"], validate=True), size + 1)
        if len(raw) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError("Retained partition decompression bounds mismatch")
        if size != partition["rows"] * shape[1] * 8:
            raise ValueError("Retained partition byte shape mismatch")
        if packed["codec"] == "zlib-shuffle-float64-le/1":
            unshuffled = np.frombuffer(raw, dtype=np.uint8).reshape(8, -1).T.copy()
        else:
            unshuffled = np.frombuffer(raw, dtype=np.uint8).copy()
        chunk = unshuffled.view("<f8").reshape(partition["rows"], shape[1]).tolist()
        if len(chunk) != partition["rows"] or any(len(row) != shape[1] for row in chunk):
            raise ValueError("Retained partition shape mismatch")
        rows.extend(chunk)
    if len(rows) != shape[0]:
        raise ValueError("Incomplete retained dataset")
    return {**header, "data": rows}


def api_projection(value, user_id):
    """Project exact retained bytes through the normal bounded dataset API."""
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services.serialization import serialize_result

    wire = dict(value)
    wire["feature_axis"] = wire.pop("x_axis", None)
    wire["sample_axis"] = wire.pop("y_axis", None)
    wire.pop("manifest", None)
    wire.pop("scientific_projection", None)
    wire["metadata"] = dict(wire.get("metadata", {}))
    wire["metadata"]["data_type"] = wire.get("domain", {}).get("technique") or "generic"
    return serialize_result(SherpaDataset.from_dict(wire), owner_user_id=user_id)
