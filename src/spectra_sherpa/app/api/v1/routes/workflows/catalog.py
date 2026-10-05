"""Canonical node-library and type-registry endpoints."""

from __future__ import annotations

from itertools import product

from fastapi import APIRouter, Depends

from spectra_sherpa.app.api.deps import get_current_user
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.workflows import (
    NodeCatalogClassificationInfo,
    NodeDependencyReadinessInfo,
    NodeExecutionContractInfo,
    NodeLibraryResponse,
    NodeManagedOptimizationProfileInfo,
    NodeMetadataInfo,
    NodeParameterInfo,
    NodePortInfo,
    NodePresentationContractInfo,
)
from spectra_sherpa.app.services.dag import node_registry
from spectra_sherpa.app.services.dag.node_base import NodeMetadata, NodeParameter
from spectra_sherpa.app.services.dag.node_catalog_contract import (
    NODE_LIBRARY_SCHEMA_VERSION,
    build_node_contract_census,
    census_digest,
    dependency_readiness,
    node_library_cache_identity,
)

router = APIRouter(prefix="/workflows")


def _parameter_options(metadata: NodeMetadata, parameter: NodeParameter, *, managed: bool):
    """Project selectable defaults through the same node-owned admission rule.

    This does not alter saved values or replace validation of the complete
    effective parameter record at execution. Standalone retains all options.
    """
    if not managed or parameter.param_type != "select" or metadata.managed_parameter_validator is None:
        return parameter.options
    conditions = parameter.visible_when or {}
    contexts = [dict(zip(conditions, values)) for values in product(*conditions.values())]
    options = []
    for option in parameter.options or []:
        value = option.get("value") if isinstance(option, dict) else option
        for context in contexts:
            try:
                metadata.canonicalize_managed_parameters({**context, parameter.name: value})
            except ValueError:
                continue
            options.append(option)
            break
    return options


@router.get("/nodes/library", response_model=NodeLibraryResponse)
async def get_node_library(
    current_user: User = Depends(get_current_user),
) -> NodeLibraryResponse:
    """
    Get available node types from the registry.

    Includes backend version for client-side cache invalidation.
    """
    from spectra_sherpa.app.core.config import settings

    nodes = list(node_registry.list_catalog_nodes())
    from spectra_sherpa.app.contracts.project_access import uses_managed_project_access
    from spectra_sherpa.app.contracts.scientific_access import QUALIFIED_SCIENTIFIC_NODES

    managed = uses_managed_project_access()
    if managed:
        nodes = [node for node in nodes if node.node_type in QUALIFIED_SCIENTIFIC_NODES]

    # In demo mode, hide nodes associated with disabled capabilities.
    from spectra_sherpa.app.core.config import app_config

    if app_config.site_profile == "demo":
        from spectra_sherpa.app.contracts.demo_policy import get_demo_policy

        hidden_types = get_demo_policy().hidden_node_types
        if hidden_types:
            nodes = [n for n in nodes if n.node_type not in hidden_types]

    census = build_node_contract_census(nodes)
    census_by_node_type = {row["node_type"]: row for row in census["nodes"]}
    node_infos = []
    for node_meta in nodes:
        census_row = census_by_node_type[node_meta.node_type]
        params = [
            NodeParameterInfo(
                name=p.name,
                label=p.label,
                param_type=p.param_type,
                default=p.default,
                min_value=p.min_value,
                max_value=p.max_value,
                max_value_reason=p.max_value_reason,
                step=p.step,
                options=_parameter_options(node_meta, p, managed=managed),
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
                    variadic=port.variadic,
                    accepted_data_roles=port.accepted_data_roles,
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
                    variadic=port.variadic,
                    accepted_data_roles=port.accepted_data_roles,
                )
                for port in node_meta.output_ports
            ]

        contract = node_meta.resolved_execution_contract()
        presentation = node_meta.resolved_presentation_contract()
        readiness = dependency_readiness(node_meta).as_dict()
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
                execution_contract=(
                    NodeExecutionContractInfo(digest=contract.digest, payload=contract.as_dict())
                    if contract is not None
                    else None
                ),
                presentation_contract=(
                    NodePresentationContractInfo(digest=presentation.digest, payload=presentation.as_dict())
                    if presentation is not None
                    else None
                ),
                dependency_readiness=NodeDependencyReadinessInfo(**readiness),
                requires_scp=bool(census_row["requires_scp"]),
                catalog_classification=NodeCatalogClassificationInfo(**census_row["catalog_classification"]),
                managed_optimization_profile=NodeManagedOptimizationProfileInfo(
                    **census_row["managed_optimization_profile"]
                ),
            )
        )

    registry_digest = census_digest(census)
    return NodeLibraryResponse(
        nodes=node_infos,
        total=len(node_infos),
        # ``version`` remains the application version for older clients. New
        # clients consume the digest-based identity because app releases do not
        # cover contract drift.
        version=settings.app_version,
        contract_schema_version=NODE_LIBRARY_SCHEMA_VERSION,
        registry_digest=registry_digest,
        cache_identity=node_library_cache_identity(nodes),
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
