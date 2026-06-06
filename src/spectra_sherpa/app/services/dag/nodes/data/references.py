"""NISTLibraryNode -- load reference spectra from the local NIST library.

Registered as ``data.nist_library``.
"""

from __future__ import annotations

import logging
from typing import Any

from spectra_sherpa.app.lib.sherpa_dataset import (
    DomainContext,
    SampleAxis,
    SherpaDataset,
    SpectralAxis,
)
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

from ...node_base import Node, NodeMetadata, NodeParameter, register_node

logger = logging.getLogger(__name__)


@register_node
class NISTLibraryNode(Node):
    """
    NIST Library node for loading reference spectra.

    Loads spectra from the local NIST library database.
    """

    metadata = NodeMetadata(
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
            NodeParameter(
                name="compound_name",
                label="Compound Name",
                param_type="text",
                default="",
                description="Name of the compound (for display)",
                required=False,
            ),
        ],
        input_types=[],
        input_ports=[],
        output_type="SherpaDataset",
    )

    async def execute(self, *args) -> Any:
        """Load spectrum from NIST library using standalone JCAMP-DX reader."""
        from sqlalchemy import select

        from spectra_sherpa.app.core.config import settings
        from spectra_sherpa.app.db.session import async_session
        from spectra_sherpa.app.lib.jcamp_reader import read_jcamp
        from spectra_sherpa.app.models.nist_library import NistLibrary

        library_id = self.parameters.get("library_id")

        if not library_id:
            raise ValueError("library_id is required")

        try:
            async with async_session() as session:
                query = select(NistLibrary).where(NistLibrary.id == library_id)
                result = await session.execute(query)
                entry = result.scalar_one_or_none()

                if not entry:
                    raise ValueError(f"Library entry {library_id} not found")

                # Build path to library file (file_path already includes "nist_library/" prefix)
                file_path = settings.data_dir / entry.file_path

                # Parse JCAMP-DX with our standalone reader (no SCP dependency)
                jcamp = read_jcamp(str(file_path))

                # Determine domain from JCAMP data type
                technique = "IR"
                data_type_lower = jcamp.data_type.lower()
                if "raman" in data_type_lower:
                    technique = "Raman"
                elif "uv" in data_type_lower or "vis" in data_type_lower:
                    technique = "UV-Vis"
                elif "nir" in data_type_lower or "near" in data_type_lower:
                    technique = "NIR"

                # Map JCAMP yunits to data_quantity
                yunits_lower = jcamp.yunits.lower()
                if "transmit" in yunits_lower:
                    data_quantity = "Transmittance"
                elif "absorb" in yunits_lower:
                    data_quantity = "Absorbance"
                else:
                    data_quantity = jcamp.yunits

                xunits = jcamp.xunits or None
                xunits_lower = (xunits or "").lower()
                if technique == "Raman":
                    axis_title = "Raman Shift"
                elif "nm" in xunits_lower or "micrometer" in xunits_lower or "um" in xunits_lower:
                    axis_title = "Wavelength"
                else:
                    axis_title = "Wavenumber"

                # Build SherpaDataset directly
                dataset = SherpaDataset(
                    jcamp.y.reshape(1, -1),
                    feature_axis=SpectralAxis(values=jcamp.x, units=xunits, title=axis_title),
                    sample_axis=SampleAxis(labels=[entry.compound_name]),
                    domain=DomainContext(
                        technique=technique,
                        data_quantity=data_quantity,
                        expected_units=xunits,
                    ),
                    title=entry.compound_name,
                    units=data_quantity,
                )

                # Store NIST/JCAMP metadata in extra namespace
                dataset.set_extra("nist.cas_number", entry.cas_number)
                dataset.set_extra("nist.compound_name", entry.compound_name)
                dataset.set_extra("nist.file_path", str(entry.file_path))
                nist_id = getattr(entry, "nist_id", None)
                if nist_id:
                    dataset.set_extra("nist.nist_id", nist_id)
                mol_formula = getattr(entry, "molecular_formula", None)
                if mol_formula:
                    dataset.set_extra("nist.molecular_formula", mol_formula)

                # Record provenance
                add_processing_step(
                    dataset,
                    "data.nist_library",
                    {
                        "library_id": library_id,
                        "compound_name": entry.compound_name,
                        "nist_id": nist_id,
                    },
                    node_id=self.node_id,
                )
                return dataset
        except Exception as e:
            raise ValueError(f"Error loading NIST library entry: {e}")
