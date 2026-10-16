"""Application policy for the fingerprinted legacy saved-model admission checks."""

from __future__ import annotations

from typing import Any

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.legacy_model_application import (
    LEGACY_WARNING as LEGACY_WARNING,
)
from spectra_sherpa.app.services.dag.legacy_model_application import (
    LegacyAcknowledgementRequired as LegacyAcknowledgementRequired,
)
from spectra_sherpa.app.services.dag.legacy_model_application import (
    require_legacy_application_acknowledgement as _require_legacy_application_acknowledgement,
)


def require_legacy_application_acknowledgement(
    manifest: dict[str, Any], arrays: dict[str, Any], prepared: SherpaDataset, *, acknowledged: bool
) -> str | None:
    from spectra_sherpa.app.core.mode_policy import is_local

    return _require_legacy_application_acknowledgement(
        manifest, arrays, prepared, acknowledged=acknowledged, local_allowed=is_local()
    )
