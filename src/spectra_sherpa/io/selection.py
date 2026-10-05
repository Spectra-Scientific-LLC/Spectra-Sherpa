"""Single explicit projection from a typed multi-asset ingestion result."""

from __future__ import annotations

from spectra_sherpa.io.types import IngestionResult, SpectralAsset


def select_asset(result: IngestionResult, *, asset_id: str | None = None) -> SpectralAsset:
    """Return one exact asset; never infer among several scientific results."""
    if asset_id is None:
        if len(result.assets) == 1:
            return result.assets[0]
        available = ", ".join(asset.asset_id for asset in result.assets)
        raise ValueError(
            f"Source contains {len(result.assets)} scientific assets ({available}); select one exact asset_id"
        )
    if not isinstance(asset_id, str) or not asset_id.strip() or asset_id != asset_id.strip():
        raise ValueError("asset_id must be one non-empty exact asset identity")
    matches = [asset for asset in result.assets if asset.asset_id == asset_id]
    if len(matches) != 1:
        available = ", ".join(asset.asset_id for asset in result.assets)
        raise ValueError(f"Asset {asset_id!r} is unavailable. Available assets: {available}.")
    return matches[0]


__all__ = ["select_asset"]
