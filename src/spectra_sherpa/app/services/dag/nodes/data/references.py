"""NISTLibraryNode -- load reference spectra from the local NIST library.

Registered as ``data.nist_library``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag import meta_helpers as dag_meta_helpers
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)
from spectra_sherpa.io import registry as ingestion_registry_contract

from ...node_base import Node, NodeMetadata, NodeParameter, NodePolicy, PortMetadata, register_node
from . import source_contracts

logger = logging.getLogger(__name__)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _canonical_nist_parameters(parameters: dict[str, object]) -> dict[str, object]:
    library_id = parameters.get("library_id")
    if isinstance(library_id, bool) or not isinstance(library_id, int) or library_id < 1:
        raise ValueError("library_id must be an exact positive integer")
    return {"library_id": library_id}


def _validated_jcamp_dataset(dataset: SherpaDataset) -> tuple[np.ndarray, np.ndarray]:
    axis = dataset.feature_axis
    x = np.asarray(None if axis is None else axis.values, dtype=np.float64).reshape(-1)
    values = np.asarray(dataset.X, dtype=np.float64)
    y = values.reshape(-1) if values.ndim == 2 and values.shape[0] == 1 else np.asarray([], dtype=np.float64)
    if x.size < 2 or y.size != x.size:
        raise ValueError("JCAMP spectrum must contain matching x/y vectors with at least two points")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError("JCAMP spectrum contains non-finite values")
    differences = np.diff(x)
    if not (np.all(differences > 0.0) or np.all(differences < 0.0)):
        raise ValueError("JCAMP x-axis must be strictly monotonic")
    xunits = _optional_text(None if axis is None else axis.units)
    yunits = _optional_text(dataset.units)
    if xunits is None or yunits is None:
        raise ValueError("JCAMP x-axis and signal units are required")
    if dataset.domain.technique not in {"IR", "NIR", "Raman", "UV-Vis"}:
        raise ValueError("JCAMP data type is not an admitted spectroscopy technique")
    if _optional_text(axis.title) not in {"Wavenumber", "Raman Shift", "Wavelength"}:
        raise ValueError("JCAMP x-axis units are not admitted")
    return x, y


@register_node
class NISTLibraryNode(Node):
    """
    NIST Library node for loading reference spectra.

    Loads spectra from the local NIST library database.
    """

    metadata = NodeMetadata(
        policy=NodePolicy(
            safe_for_auto_apply=False,
            requires_human_review=True,
            data_egress_risk="none",
            offload_to_pool=False,
        ),
        node_type="data.nist_library",
        category="data",
        label="NIST Library",
        description="Load reference spectra from NIST library",
        parameters=[
            NodeParameter(
                name="library_id",
                label="Library Entry ID",
                param_type="number",
                default=None,
                description="ID of the NIST library entry",
                required=True,
            ),
        ],
        input_types=[],
        input_ports=[],
        output_type="SherpaDataset",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Reference Spectrum",
                description="Exact content-digested local NIST JCAMP spectrum",
            )
        ],
        canonical_parameter_validator=_canonical_nist_parameters,
    )

    async def execute(self, *args) -> Any:
        """Load spectrum from NIST library through the frozen ingestion registry."""
        del args
        library_id = int(self.metadata.canonicalize_parameters(self.parameters)["library_id"])

        try:
            entry = (
                await self.require_execution_runtime()
                .require_dataset_source_resolver()
                .resolve_nist_library_entry(library_id=library_id)
            )
            file_path = Path(entry.path)
            from spectra_sherpa.io import ingest

            result = ingest(file_path)
            if len(result.assets) != 1:
                raise ValueError("NIST JCAMP entry must contain exactly one spectrum")
            dataset = result.assets[0].dataset
            _validated_jcamp_dataset(dataset)
            content_sha256 = result.source_members[0].sha256
            dataset.title = entry.compound_name
            if dataset.sample_axis is not None:
                dataset.sample_axis.labels = [entry.compound_name]
            dataset.set_extra("nist.cas_number", entry.cas_number)
            dataset.set_extra("nist.compound_name", entry.compound_name)
            dataset.set_extra("nist.file_path", entry.relative_path)
            dataset.set_extra("nist.content_sha256", content_sha256)
            dataset.set_extra("nist.resolution", entry.resolution)
            if entry.nist_id:
                dataset.set_extra("nist.nist_id", entry.nist_id)
            if entry.molecular_formula:
                dataset.set_extra("nist.molecular_formula", entry.molecular_formula)
            add_processing_step(
                dataset,
                "data.nist_library",
                {
                    "library_id": library_id,
                    "compound_name": entry.compound_name,
                    "cas_number": entry.cas_number,
                    "resolution": entry.resolution,
                    "content_sha256": content_sha256,
                    "nist_id": entry.nist_id,
                },
                node_id=self.node_id,
            )
            return dataset
        except Exception as e:
            raise ValueError(f"Error loading NIST library entry: {e}") from e


bind_stable_execution_contract(
    NISTLibraryNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.DATA_SOURCE,
    implementation_id="spectrasherpa.data.nist_library",
    implementation_version="2.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="generates_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 15, "memory_bytes": 536_870_912},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(
        source_contracts,
        dag_meta_helpers,
        ingestion_registry_contract,
        *ingestion_registry_contract.jcamp_implementation_modules(),
    ),
    implementation_distributions=("numpy", "pandas", "scipy"),
    runtime_requirements=(("numpy", "1.26.4"), ("pandas", "2.3.3"), ("scipy", "1.17.1")),
)
