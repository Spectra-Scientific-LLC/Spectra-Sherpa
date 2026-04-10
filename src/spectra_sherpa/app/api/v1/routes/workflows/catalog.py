"""
Catalog endpoints: SpectroChemPy examples, node library, type registry.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from spectra_sherpa.app.api.deps import get_current_user
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.workflows import (
    NodeLibraryResponse,
    NodeMetadataInfo,
    NodeParameterInfo,
    NodePortInfo,
)
from spectra_sherpa.app.services.dag import node_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows")


# IMPORTANT: This route must be defined BEFORE /{workflow_id} routes
# to avoid "spectrochempy-examples" being parsed as a workflow_id
@router.get("/spectrochempy-examples", response_model=dict[str, list[dict[str, str]]])
async def list_spectrochempy_examples(
    current_user: User = Depends(get_current_user),
) -> dict[str, list[dict[str, str]]]:
    """
    List available files in SpectroChemPy example datasets.

    Scans configured SpectroChemPy datadirs (``SCP_DATADIR``,
    ``scp.preferences.datadir``, and ``~/.spectrochempy/testdata``),
    deduplicates files, and returns metadata for each file.

    Returns a dictionary mapping dataset names (e.g., 'irdata', 'ramandata')
    to lists of available files with their labels, paths, and metadata.
    """
    from pathlib import Path

    from spectra_sherpa.app.lib.scp_catalog import build_scp_catalog
    from spectra_sherpa.app.lib.scp_compat import HAS_SCP, get_preferred_scp_datadir, scp

    if not HAS_SCP:
        raise HTTPException(
            status_code=501,
            detail=(
                "SpectroChemPy is not installed. "
                "Example datasets are unavailable. "
                "Install with: pip install spectra-sherpa[scp]"
            ),
        )

    try:
        preferred_datadir = get_preferred_scp_datadir()
        primary_datadir = scp.preferences.datadir
        primary_resolved = Path(primary_datadir).expanduser().resolve(strict=False)
        selected_resolved = preferred_datadir.expanduser().resolve(strict=False) if preferred_datadir else None
        source_kind = "primary" if selected_resolved == primary_resolved else "fallback"

        result: dict[str, list[dict[str, str]]] = {}
        for entry in build_scp_catalog(force=True):
            dataset_name = entry["category"]
            path = entry["file_path"].rstrip("/")
            format_name = "dir" if entry["entry_type"] == "group" else Path(path).suffix.lower()
            result.setdefault(dataset_name, []).append(
                {
                    "label": entry["label"],
                    "value": path,
                    "path": path,
                    "format": format_name,
                    "source": source_kind,
                }
            )

        for dataset_name, files in result.items():
            files.sort(key=lambda item: item["label"].lower())

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list SpectroChemPy examples: {str(e)}")


@router.get("/nodes/library", response_model=NodeLibraryResponse)
async def get_node_library(
    current_user: User = Depends(get_current_user),
) -> NodeLibraryResponse:
    """
    Get available node types from the registry.

    Includes backend version for client-side cache invalidation.
    """
    from spectra_sherpa.app.core.config import settings

    nodes = list(node_registry.list_nodes())

    # In demo mode, hide nodes associated with disabled capabilities.
    from spectra_sherpa.app.core.config import app_config

    if app_config.site_profile == "demo":
        from spectra_sherpa.app.contracts.demo_policy import get_demo_policy

        hidden_types = get_demo_policy().hidden_node_types
        if hidden_types:
            nodes = [n for n in nodes if n.node_type not in hidden_types]

    node_infos = []
    for node_meta in nodes:
        params = [
            NodeParameterInfo(
                name=p.name,
                label=p.label,
                param_type=p.param_type,
                default=p.default,
                min_value=p.min_value,
                max_value=p.max_value,
                step=p.step,
                options=p.options,
                description=p.description,
                required=p.required,
                category=p.category,
                visible_when=p.visible_when,
            )
            for p in node_meta.parameters
        ]

        # Serialize input ports
        input_ports = None
        if node_meta.input_ports:
            input_ports = [
                NodePortInfo(
                    name=port.name,
                    type_ref=port.type_ref,
                    required=port.required,
                    label=port.label,
                    description=port.description,
                )
                for port in node_meta.input_ports
            ]

        # Serialize output ports
        output_ports = None
        if node_meta.output_ports:
            output_ports = [
                NodePortInfo(
                    name=port.name,
                    type_ref=port.type_ref,
                    required=port.required,
                    label=port.label,
                    description=port.description,
                )
                for port in node_meta.output_ports
            ]

        node_infos.append(
            NodeMetadataInfo(
                node_type=node_meta.node_type,
                category=node_meta.category,
                label=node_meta.label,
                description=node_meta.description,
                parameters=params,
                input_types=node_meta.input_types,
                output_type=node_meta.output_type,
                input_ports=input_ports,
                output_ports=output_ports,
                diagnostics=node_meta.diagnostics,
                help_url=node_meta.help_url,
            )
        )

    return NodeLibraryResponse(
        nodes=node_infos, total=len(node_infos), version=settings.app_version  # For cache invalidation
    )


@router.get("/types/registry")
async def get_type_registry(
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Get the type registry for client-side type validation.

    Returns all type definitions, subtype relationships, and version info
    so the frontend can validate connections without per-edge API calls.
    """
    from spectra_sherpa.app.types import type_registry

    return type_registry.to_api_json()
