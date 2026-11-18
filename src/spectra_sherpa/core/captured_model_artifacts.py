"""Immutable, bounded model bytes for trusted execution admission.

This is a Python runtime capability, never a client payload. Caller admission
owns authorization and capture; canonical model consumers still own application
semantics. Decoding never accesses live model storage.
"""

from __future__ import annotations

import hashlib
import io
import math
import zipfile
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from spectra_sherpa.core.model_artifact import (
    ModelArtifactIntegrityError,
    parse_model_manifest_json,
    require_artifact_identity,
    require_model_artifact_authority,
)

MAX_CAPTURED_MODEL_BYTES = 64 * 1024 * 1024
MAX_MODEL_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_MODEL_ARRAY_BYTES = 32 * 1024 * 1024
MAX_DECODED_MODEL_BYTES = 64 * 1024 * 1024
MAX_CAPTURED_MODELS = 16
MAX_MODEL_ARRAYS = 256


def _check_arrays(payload: bytes) -> int:
    """Bound both ZIP expansion and NPY-declared allocation before NumPy loads."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if not 1 <= len(entries) <= MAX_MODEL_ARRAYS or len(names) != len(set(names)):
            raise ModelArtifactIntegrityError("Captured model array inventory is invalid")
        decoded_bytes = sum(entry.file_size for entry in entries)
        if decoded_bytes > MAX_DECODED_MODEL_BYTES:
            raise ModelArtifactIntegrityError("Captured model decoded bytes exceed the limit")
        for entry in entries:
            name = entry.filename
            if (
                not name.endswith(".npy")
                or not name[:-4]
                or "/" in name
                or "\\" in name
                or entry.flag_bits & 1
                or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
            ):
                raise ModelArtifactIntegrityError("Captured model array member is invalid")
            with archive.open(entry) as member:
                version = np.lib.format.read_magic(member)
                if version == (1, 0):
                    shape, _, dtype = np.lib.format.read_array_header_1_0(member)
                elif version == (2, 0):
                    shape, _, dtype = np.lib.format.read_array_header_2_0(member)
                else:
                    raise ModelArtifactIntegrityError("Captured model NPY version is unsupported")
                expected = math.prod(shape) * dtype.itemsize
                if dtype.hasobject or expected > MAX_DECODED_MODEL_BYTES or member.tell() + expected != entry.file_size:
                    raise ModelArtifactIntegrityError("Captured model array allocation is invalid")
        return decoded_bytes


@dataclass(frozen=True, slots=True)
class CapturedModelArtifact:
    artifact_uid: str
    manifest_bytes: bytes = field(repr=False)
    arrays_bytes: bytes = field(repr=False)
    decoded_bytes: int = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.artifact_uid) is not str
            or not self.artifact_uid
            or self.artifact_uid != self.artifact_uid.strip()
        ):
            raise ValueError("Captured model identity is invalid")
        if type(self.manifest_bytes) is not bytes or type(self.arrays_bytes) is not bytes:
            raise TypeError("Captured model contents must be immutable bytes")
        if not 0 < len(self.manifest_bytes) <= MAX_MODEL_MANIFEST_BYTES:
            raise ModelArtifactIntegrityError("Captured model manifest exceeds the limit")
        if not 0 < len(self.arrays_bytes) <= MAX_MODEL_ARRAY_BYTES:
            raise ModelArtifactIntegrityError("Captured model arrays exceed the limit")
        manifest = parse_model_manifest_json(self.manifest_bytes)
        require_model_artifact_authority(manifest)
        require_artifact_identity(manifest, expected_uid=self.artifact_uid)
        if manifest.get("integrity_hash") != hashlib.sha256(self.arrays_bytes).hexdigest():
            raise ModelArtifactIntegrityError("Captured model array integrity mismatch")
        object.__setattr__(self, "decoded_bytes", _check_arrays(self.arrays_bytes))


@dataclass(frozen=True, slots=True)
class CapturedModelArtifacts:
    artifacts: tuple[CapturedModelArtifact, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.artifacts) is not tuple or not 1 <= len(self.artifacts) <= MAX_CAPTURED_MODELS:
            raise ValueError("Captured models require a bounded immutable inventory")
        if any(type(item) is not CapturedModelArtifact for item in self.artifacts):
            raise TypeError("Captured model inventory contains an unsupported envelope")
        if len(self.artifact_uids) != len(set(self.artifact_uids)):
            raise ValueError("Captured model inventory repeats an identity")
        if sum(len(item.manifest_bytes) + len(item.arrays_bytes) for item in self.artifacts) > MAX_CAPTURED_MODEL_BYTES:
            raise ValueError("Captured model inventory exceeds the aggregate byte limit")
        if sum(item.decoded_bytes for item in self.artifacts) > MAX_DECODED_MODEL_BYTES:
            raise ValueError("Captured model inventory exceeds the aggregate decoded limit")

    @property
    def artifact_uids(self) -> tuple[str, ...]:
        return tuple(item.artifact_uid for item in self.artifacts)

    def require_exact_ids(self, admitted: tuple[str, ...] | None) -> None:
        if admitted is None or set(admitted) != set(self.artifact_uids):
            raise ValueError("Captured models do not match the admitted model identities")

    def load(self, artifact_uid: str, *, verify: bool = True) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
        # Captured envelopes always verify, including callers asking verify=False.
        del verify
        for item in self.artifacts:
            if item.artifact_uid == artifact_uid:
                manifest = parse_model_manifest_json(item.manifest_bytes)
                with np.load(io.BytesIO(item.arrays_bytes), allow_pickle=False) as archive:
                    arrays = {name: np.array(value, copy=True) for name, value in archive.items()}
                return manifest, arrays
        raise FileNotFoundError("Model is outside the admitted captured inventory")
