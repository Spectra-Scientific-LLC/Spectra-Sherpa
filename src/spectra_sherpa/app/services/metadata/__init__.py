"""
Metadata extraction and normalization service.

This module provides a unified interface for extracting instrument metadata
from various spectral file formats (OPUS, SPA, JCAMP-DX, SPC) and normalizing
them to our SpectraMeta schema.

Usage:
    from app.services.metadata import MetadataExtractor

    # Extract metadata from any supported format
    metadata = MetadataExtractor.extract(dataset, file_path)

    # The returned dict matches our SpectraMeta schema fields
"""

import logging
import warnings

from .extractor_base import BaseMetadataExtractor, ExtractorRegistry
from .normalizer import MetadataNormalizer

logger = logging.getLogger(__name__)

# Initialize the extractor registry singleton
_registry = ExtractorRegistry()


def get_extractor(file_path: str):
    """Get the appropriate extractor for a file based on extension."""
    return _registry.get_extractor(file_path)


def extract_metadata(dataset, file_path: str, debug: bool = False) -> dict:
    """
    Extract and normalize metadata from a loaded NDDataset.

    This is the main entry point for metadata extraction.

    Args:
        dataset: Loaded NDDataset with potential raw metadata
        file_path: Original file path (for format detection)
        debug: If True, print extraction debug info

    Returns:
        Dict with normalized metadata ready for SpectraMeta integration.
        Includes '_extraction_info' dict with extractor used and any warnings.
    """
    import os

    extractor = _registry.get_extractor(file_path)
    extractor_name = type(extractor).__name__ if extractor else "None"
    extraction_info = {"extractor": extractor_name, "warnings": []}

    ext = os.path.splitext(file_path)[1]
    filename = os.path.basename(file_path)

    if extractor is None:
        # No specific extractor - use generic fallback with WARNING
        from .extractors.generic import GenericExtractor
        extractor = GenericExtractor()
        extractor_name = "GenericExtractor (fallback)"
        extraction_info["extractor"] = extractor_name
        extraction_info["is_fallback"] = True

        # Log warning about unsupported format
        warning_msg = (
            f"No specific metadata extractor for '{ext}' files. "
            f"Using generic fallback - metadata may be incomplete."
        )
        extraction_info["warnings"].append(warning_msg)
        logger.warning(f"[METADATA] {filename}: {warning_msg}")
        warnings.warn(warning_msg, category=UserWarning, stacklevel=2)

    if debug:
        logger.debug(f"[METADATA] File: {filename}, Extension: {ext}")
        logger.debug(f"[METADATA] Using extractor: {extractor_name}")

    # Extract raw metadata using format-specific extractor
    try:
        raw_metadata = extractor.extract(dataset, file_path)
    except Exception as e:
        # Log extraction error but don't fail completely
        error_msg = f"Metadata extraction failed: {str(e)}"
        extraction_info["warnings"].append(error_msg)
        logger.error(f"[METADATA] {filename}: {error_msg}")
        raw_metadata = {
            "instrument": {},
            "acquisition": {},
            "conditions": {},
            "sample": {},
            "provenance": {},
            "extra": {},
        }

    if debug:
        # Show what raw metadata was found
        raw_count = sum(len(v) if isinstance(v, dict) else 0 for v in raw_metadata.values())
        logger.debug(f"[METADATA] Raw metadata fields extracted: {raw_count}")
        for section, data in raw_metadata.items():
            if isinstance(data, dict) and data:
                logger.debug(f"[METADATA]   {section}: {list(data.keys())}")

    # Check if extraction yielded any metadata
    total_fields = sum(
        len(v) if isinstance(v, dict) else 0
        for k, v in raw_metadata.items() if k != "extra"
    )
    if total_fields == 0:
        warning_msg = "No metadata fields extracted from file"
        extraction_info["warnings"].append(warning_msg)
        logger.warning(f"[METADATA] {filename}: {warning_msg}")

    # Normalize to SpectraMeta schema
    normalizer = MetadataNormalizer()
    normalized = normalizer.normalize(raw_metadata, file_path)

    if debug:
        norm_count = sum(len(v) if isinstance(v, dict) else 0 for v in normalized.values())
        logger.debug(f"[METADATA] Normalized metadata fields: {norm_count}")

    # Include extraction info for debugging (excluded from API by to_api_json)
    normalized["_extraction_info"] = extraction_info

    return normalized


__all__ = [
    "BaseMetadataExtractor",
    "ExtractorRegistry",
    "MetadataNormalizer",
    "get_extractor",
    "extract_metadata",
]
