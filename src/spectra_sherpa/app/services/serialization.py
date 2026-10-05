"""
Serialization helpers for workflow results.

Moved from api/v1/routes/workflows.py so that service-layer code
(batch_predict, folder_watch_service) can import without depending on
the API route layer.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import numpy as np
from pydantic import BaseModel

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.serialize import serialize_for_api
from spectra_sherpa.app.services.dag.transport import reject_spectrochempy_transport


def _register_application_dataset(
    dataset: SherpaDataset, owner_user_id: int | None, *, project_id: int | None = None
) -> object | None:
    from spectra_sherpa.app.services.dataset_registry import (
        DatasetRegistryCapacityError,
        dataset_registry,
    )

    try:
        return dataset_registry.register(dataset, owner_user_id=owner_user_id, project_id=project_id)
    except DatasetRegistryCapacityError:
        return None


def _serialize_dataset(
    dataset: SherpaDataset, *, owner_user_id: int | None, retain_full: bool = False, project_id: int | None = None
) -> Any:
    return serialize_for_api(
        dataset,
        sanitize_paths=settings.sanitize_paths,
        owner_user_id=owner_user_id,
        dataset_register=lambda value, owner: _register_application_dataset(value, owner, project_id=project_id),
        retain_full=retain_full,
    )


def _is_model_object(obj: Any) -> bool:
    """Check if an object is a non-serializable sklearn model."""
    if not hasattr(obj, "__module__") or obj.__module__ is None:
        return False
    module_name = obj.__module__
    if module_name.startswith("sklearn."):
        return True
    return False


def serialize_result(
    obj: Any, *, owner_user_id: int | None = None, retain_full: bool = False, project_id: int | None = None
) -> Any:
    """
    Convert workflow results to JSON-serializable format.

    Scientific datasets are registered as full typed values. Results within the
    declared API ceiling are sent directly; larger values are represented by a
    deterministic, shape-preserving preview plus the registered dataset handle.

    ARCHITECTURE: SherpaDataset is the SINGLE canonical data type. Serialization
    happens at API boundary only via serialize_for_api().

    Serialization priority:
    1. SherpaDataset → serialize_for_api() (primary path for all spectral data)
    2. Model objects → placeholder dict
    3. numpy arrays → .tolist()
    4. dict → recursive serialization (handles multi-output node results)
    5. list → recursive serialization
    6. numpy scalars → Python native
    7. Everything else → pass through
    """
    reject_spectrochempy_transport(obj, boundary="workflow API serialization")

    # 1. SherpaDataset — the only spectral-data transport
    if isinstance(obj, SherpaDataset):
        return _serialize_dataset(obj, owner_user_id=owner_user_id, retain_full=retain_full, project_id=project_id)

    # 2. Non-serializable sklearn model objects. SpectroChemPy objects are
    # rejected recursively at the transport boundary above and can never be
    # represented as API placeholders.
    if _is_model_object(obj):
        return {
            "__model_placeholder__": type(obj).__name__,
            "__module__": obj.__module__,
        }

    # 3. numpy arrays — must check BEFORE duck-typed objects
    if isinstance(obj, np.ndarray):
        return obj.tolist()

    # 4. Pydantic models — dump to plain JSON-safe dict/list first, then recurse
    if isinstance(obj, BaseModel):
        return serialize_result(
            obj.model_dump(mode="json"), owner_user_id=owner_user_id, retain_full=retain_full, project_id=project_id
        )

    # 5. Dicts — recursive serialization (handles multi-output node results)
    if isinstance(obj, dict):
        result_dict = {}
        for k, v in obj.items():
            if not retain_full and k.startswith("_"):
                continue  # Skip _internal, _model_artifact, and other private keys
            # Dataset MUST be serialized via serialize_for_api, never as a model placeholder.
            if isinstance(v, SherpaDataset):
                result_dict[k] = _serialize_dataset(
                    v, owner_user_id=owner_user_id, retain_full=retain_full, project_id=project_id
                )
                continue
            # Model objects in dicts get placeholder treatment
            if _is_model_object(v):
                result_dict[k] = {"__model_placeholder__": type(v).__name__}
                continue
            # Nested dicts of models (e.g., {"models": {"class_a": model, "class_b": model}})
            if k == "models" and isinstance(v, dict):
                serialized_models = {}
                for model_key, model_val in v.items():
                    if isinstance(model_val, SherpaDataset):
                        serialized_models[model_key] = _serialize_dataset(
                            model_val, owner_user_id=owner_user_id, retain_full=retain_full, project_id=project_id
                        )
                    elif _is_model_object(model_val):
                        serialized_models[model_key] = {"__model_placeholder__": type(model_val).__name__}
                    else:
                        serialized_models[model_key] = serialize_result(
                            model_val, owner_user_id=owner_user_id, retain_full=retain_full, project_id=project_id
                        )
                result_dict[k] = serialized_models
                continue
            result_dict[k] = serialize_result(
                v, owner_user_id=owner_user_id, retain_full=retain_full, project_id=project_id
            )
        return result_dict

    # 6. Lists — recursive serialization
    if isinstance(obj, (list, tuple)):
        return [
            serialize_result(item, owner_user_id=owner_user_id, retain_full=retain_full, project_id=project_id)
            for item in obj
        ]

    # 7. numpy scalar types
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()

    # 8. Sets / frozensets — convert to sorted lists for JSON
    if isinstance(obj, (frozenset, set)):
        return sorted(
            serialize_result(v, owner_user_id=owner_user_id, retain_full=retain_full, project_id=project_id)
            for v in obj
        )

    # 9. datetime/date — normalize to ISO strings for JSON storage
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()

    # 10. Pass through (str, int, float, bool, None)
    return obj
