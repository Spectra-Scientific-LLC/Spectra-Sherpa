"""
Serialization helpers for workflow results.

Moved from api/v1/routes/workflows.py so that service-layer code
(batch_predict, folder_watch_service) can import without depending on
the API route layer.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.lib.scp_compat import HAS_SCP, NDDataset
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.serialize import serialize_for_api

HAS_NDDATASET = HAS_SCP


def _is_model_object(obj: Any) -> bool:
    """Check if an object is a non-serializable model (sklearn, spectrochempy)."""
    if not hasattr(obj, "__module__") or obj.__module__ is None:
        return False
    module_name = obj.__module__
    if module_name.startswith("sklearn."):
        return True
    if module_name.startswith("spectrochempy."):
        type_name = type(obj).__name__
        # SpectroChemPy model objects (PCA, PLS, MCR-ALS, EFA, etc.)
        if type_name in ("PCA", "PLS", "PLSRegression", "IRIS", "MCRALS", "MCR_ALS", "EFA"):
            return True
        if hasattr(obj, "fit") or hasattr(obj, "transform") or hasattr(obj, "predict"):
            return True
    return False


def serialize_result(obj: Any, *, owner_user_id: int | None = None) -> Any:
    """
    Convert workflow results to JSON-serializable format.

    Note: Full data is sent without truncation. The frontend handles display limits
    separately (e.g., DataTableModal has a row limit dropdown).

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
    # 1a. SherpaDataset — primary path for no-SCP spectral data
    if isinstance(obj, SherpaDataset):
        return serialize_for_api(obj, sanitize_paths=settings.sanitize_paths, owner_user_id=owner_user_id)

    # 1b. NDDataset — convert to SherpaDataset first, then serialize
    if HAS_NDDATASET and isinstance(obj, NDDataset):
        import logging

        logging.getLogger(__name__).warning("NDDataset reached serialize_result — converting to SherpaDataset")
        from spectra_sherpa.app.lib.adapters.scp_adapter import from_nddataset

        obj = from_nddataset(obj)
        return serialize_for_api(obj, sanitize_paths=settings.sanitize_paths, owner_user_id=owner_user_id)

    # 2. Non-serializable model objects (sklearn, spectrochempy)
    if _is_model_object(obj):
        return {
            "__model_placeholder__": type(obj).__name__,
            "__module__": obj.__module__,
        }

    # 3. numpy arrays — must check BEFORE duck-typed objects
    if isinstance(obj, np.ndarray):
        return obj.tolist()

    # 5. Dicts — recursive serialization (handles multi-output node results)
    if isinstance(obj, dict):
        result_dict = {}
        for k, v in obj.items():
            if k.startswith("_"):
                continue  # Skip _internal, _model_artifact, and other private keys
            # Dataset MUST be serialized via serialize_for_api, never as a model placeholder.
            # Check dataset types before _is_model_object because NDDataset is a spectrochempy
            # object that may have .transform/.fit attributes, which would incorrectly
            # trigger the model placeholder path.
            if isinstance(v, SherpaDataset) or (HAS_NDDATASET and isinstance(v, NDDataset)):
                if HAS_NDDATASET and isinstance(v, NDDataset):
                    from spectra_sherpa.app.lib.adapters.scp_adapter import from_nddataset

                    v = from_nddataset(v)
                result_dict[k] = serialize_for_api(
                    v, sanitize_paths=settings.sanitize_paths, owner_user_id=owner_user_id
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
                    if isinstance(model_val, SherpaDataset) or (HAS_NDDATASET and isinstance(model_val, NDDataset)):
                        if HAS_NDDATASET and isinstance(model_val, NDDataset):
                            from spectra_sherpa.app.lib.adapters.scp_adapter import from_nddataset

                            model_val = from_nddataset(model_val)
                        serialized_models[model_key] = serialize_for_api(
                            model_val, sanitize_paths=settings.sanitize_paths, owner_user_id=owner_user_id
                        )
                    elif _is_model_object(model_val):
                        serialized_models[model_key] = {"__model_placeholder__": type(model_val).__name__}
                    else:
                        serialized_models[model_key] = serialize_result(model_val, owner_user_id=owner_user_id)
                result_dict[k] = serialized_models
                continue
            result_dict[k] = serialize_result(v, owner_user_id=owner_user_id)
        return result_dict

    # 6. Lists — recursive serialization
    if isinstance(obj, list):
        return [serialize_result(item, owner_user_id=owner_user_id) for item in obj]

    # 7. numpy scalar types
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()

    # 8. Sets / frozensets — convert to sorted lists for JSON
    if isinstance(obj, (frozenset, set)):
        return sorted(serialize_result(v, owner_user_id=owner_user_id) for v in obj)

    # 9. Pass through (str, int, float, bool, None)
    return obj
