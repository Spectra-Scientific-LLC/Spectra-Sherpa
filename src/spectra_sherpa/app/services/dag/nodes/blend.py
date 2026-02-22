"""
Blend nodes for creating synthetic spectral mixtures.

These nodes combine multiple species with concentration profiles to generate
synthetic mixture spectra for training and validation purposes.

Ground Truth Metadata:
    When blending, the output dataset includes complete ground truth in meta["spectra"]:
    - concentration_matrix: C matrix (n_timepoints x n_species)
    - pure_spectra_matrix: S matrix (n_wavenumbers x n_species)
    - species: List of species information
    - concentrations: Concentration profiles with curve parameters

    This enables downstream MCR-ALS validation by comparing recovered vs. true values.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)
from spectra_sherpa.app.lib.sherpa_dataset import AxisInfo
from spectra_sherpa.app.models.spectra_meta import (
    ConcentrationProfile,
    ConcentrationUnit,
    DataProvenance,
    ExperimentalConditions,
    PhysicalState,
    SourceType,
    SpeciesInfo,
    SpectraMeta,
)
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

from ..io_contracts import build_dataset_like, coerce_to_sherpa, to_numpy_2d
from ..node_base import Node, NodeMetadata, NodeParameter, register_node


def generate_concentration_curve(
    curve_type: str,
    n_points: int,
    max_concentration: float = 1.0,
    center: float = 0.5,
    width: float = 0.1,
) -> np.ndarray:
    """
    Generate a concentration profile curve.

    Args:
        curve_type: Type of curve (sigmoid, gaussian, linear, step, constant)
        n_points: Number of time points
        max_concentration: Maximum concentration value
        center: Center position for sigmoid/gaussian (0-1)
        width: Width parameter for sigmoid/gaussian

    Returns:
        1D numpy array of concentration values
    """
    t = np.linspace(0, 1, n_points)

    if curve_type == "sigmoid":
        return max_concentration / (1 + np.exp(-(t - center) / width))
    elif curve_type == "gaussian":
        return max_concentration * np.exp(-((t - center) ** 2) / (2 * width**2))
    elif curve_type == "linear":
        return max_concentration * t
    elif curve_type == "exponential":
        return max_concentration * (1 - np.exp(-t / width))
    elif curve_type == "step":
        return np.where(t >= center, max_concentration, 0.0)
    else:  # constant
        return np.ones(n_points) * max_concentration


@register_node
class BlendNode(Node):
    """
    Blend node for creating synthetic mixture spectra.

    Combines multiple input spectra with concentration profiles to generate
    time-resolved mixture spectra following Beer-Lambert or saturation models.
    """

    metadata = NodeMetadata(
        node_type="synthesis.blend",
        category="synthesis",
        label="Blend",
        description="Create synthetic mixtures from multiple spectra with concentration curves",
        parameters=[
            NodeParameter(
                name="n_timepoints",
                label="Number of Time Points",
                param_type="number",
                default=100,
                min_value=10,
                max_value=1000,
                step=10,
                description="Number of time points in the output mixture",
                required=True,
            ),
            NodeParameter(
                name="model_type",
                label="Model Type",
                param_type="select",
                default="linear",
                options=["linear", "saturation"],
                description="Mixing model: linear (Beer-Lambert) or saturation",
                required=True,
            ),
            NodeParameter(
                name="pathlength",
                label="Pathlength (m)",
                param_type="number",
                default=0.01,
                min_value=0.001,
                max_value=1.0,
                step=0.001,
                description="Optical pathlength in meters",
                required=True,
            ),
            NodeParameter(
                name="noise_level",
                label="Noise Level",
                param_type="number",
                default=0.01,
                min_value=0.0,
                max_value=0.5,
                step=0.001,
                description="Gaussian noise level (fraction of signal)",
                required=False,
            ),
            NodeParameter(
                name="species_config",
                label="Species Configuration",
                param_type="json",
                default=[],
                description="JSON array of species configurations with curve parameters",
                required=False,
            ),
        ],
        input_types=["NDDataset"],  # Multiple inputs (one per species)
        output_type="NDDataset",
    )

    async def execute(self, *input_data: Any) -> Any:
        """
        Execute blending of multiple spectra.

        Args:
            *input_data: Variable number of dataset inputs (one per species)

        Returns:
            Dataset containing the blended mixture spectra
        """
        n_timepoints = int(self.parameters.get("n_timepoints", 100))
        model_type = self.parameters.get("model_type", "linear")
        pathlength = self.parameters.get("pathlength", 0.01)
        noise_level = self.parameters.get("noise_level", 0.01)
        species_config = self.parameters.get("species_config", [])

        if len(input_data) == 0:
            raise ValueError("At least one input spectrum is required")

        # Normalize all inputs and collect units.
        spectra = [
            coerce_to_sherpa(
                inp,
                input_name=f"input_data[{i}]",
                dataset_error_message="Input must be dataset object",
            )
            for i, inp in enumerate(input_data)
        ]
        input_units = []
        for inp in spectra:
            if hasattr(inp, "units") and inp.units:
                input_units.append(str(inp.units))

        # Determine output units from input spectra
        # Inherit from first spectrum, or use "absorbance" as default
        if input_units:
            # Warn if units are inconsistent
            unique_units = list(set(input_units))
            if len(unique_units) > 1:
                logger.warning(
                    f"[BlendNode] Input spectra have different units: {unique_units}. Using first spectrum's units."
                )
            output_units = input_units[0]
        else:
            output_units = "absorbance"  # Default for typical FTIR blending

        # Get wavenumber axis from first spectrum
        # Assume all spectra are aligned to the same wavenumber grid
        first_spectrum = spectra[0]
        first_x_coord = first_spectrum.spectral_axis
        first_matrix = to_numpy_2d(first_spectrum, name="input_data[0]")
        wavenumbers = first_x_coord.data if first_x_coord is not None else np.arange(first_matrix.shape[-1])

        n_wavenumbers = len(wavenumbers)

        # Build species matrix (each column is a pure spectrum)
        S = np.zeros((n_wavenumbers, len(spectra)))
        for i, spec in enumerate(spectra):
            spec_matrix = to_numpy_2d(spec, name=f"input_data[{i}]")
            S[:, i] = np.mean(spec_matrix, axis=0)

        # Generate concentration profiles
        C = np.zeros((n_timepoints, len(spectra)))

        if species_config and len(species_config) == len(spectra):
            # Use provided configuration
            for i, config in enumerate(species_config):
                curve_type = config.get("curve", {}).get("type", "sigmoid")
                max_conc = config.get("curve", {}).get("maxConcentration", 1.0)
                center = config.get("curve", {}).get("center", 0.5)
                width = config.get("curve", {}).get("width", 0.1)
                C[:, i] = generate_concentration_curve(curve_type, n_timepoints, max_conc, center, width)
        else:
            # Default: generate diverse curves for each species
            for i in range(len(spectra)):
                curve_type = ["sigmoid", "gaussian", "linear"][i % 3]
                center = 0.3 + 0.4 * (i / max(1, len(spectra) - 1))
                C[:, i] = generate_concentration_curve(
                    curve_type, n_timepoints, max_concentration=1.0, center=center, width=0.1
                )

        # Compute mixture spectra
        if model_type == "linear":
            # Beer-Lambert law: A = C * S^T * pathlength
            D = np.dot(C, S.T) * pathlength
        else:
            # Saturation model: A = Amax * (1 - exp(-C * S^T * pathlength))
            Amax = 2.0  # Maximum absorbance
            D = Amax * (1 - np.exp(-np.dot(C, S.T) * pathlength))

        # Add noise
        if noise_level > 0:
            noise = np.random.randn(*D.shape) * noise_level * np.abs(D).mean()
            D += noise

        # Create output dataset (explicitly reset inherited meta/target for synthesis output)
        dataset = build_dataset_like(
            D,
            first_spectrum,
            units=output_units,
            title="Synthetic Mixture",
            backend="numpy",
            copy_history=False,
        )
        dataset.target = None
        dataset.meta = {"processing_history": dataset.provenance}
        dataset.set_coordset(
            y=AxisInfo(values=np.arange(n_timepoints), title="Time", units="s"),
            x=AxisInfo(values=wavenumbers, title="Wavenumber", units="cm^-1"),
        )

        # ---------------------------------------------------------------------
        # Attach Ground Truth Metadata (Critical for MCR-ALS validation)
        # ---------------------------------------------------------------------

        # Build species info from input datasets
        species_list = []
        for i, spec in enumerate(spectra):
            species_name = spec.title if spec.title and spec.title != "<untitled>" else f"Species_{i+1}"
            species_info = SpeciesInfo(
                name=species_name,
                state=PhysicalState.UNKNOWN,
            )
            # Try to extract metadata from input if available
            if hasattr(spec, "meta") and spec.meta:
                input_meta = spec.meta.get("spectra", {})
                if isinstance(input_meta, dict):
                    if "species" in input_meta and input_meta["species"]:
                        # Copy from first species in input
                        src = input_meta["species"][0]
                        if isinstance(src, dict):
                            species_info = SpeciesInfo(
                                name=src.get("name", species_name),
                                cas_number=src.get("cas_number"),
                                molecular_formula=src.get("molecular_formula"),
                                molecular_weight=src.get("molecular_weight"),
                                molar_absorptivity=src.get("molar_absorptivity"),
                                state=src.get("state", PhysicalState.UNKNOWN),
                            )
            species_list.append(species_info)

        # Build concentration profiles
        concentration_profiles = []
        for i in range(len(spectra)):
            if species_config and i < len(species_config):
                config = species_config[i]
                curve_cfg = config.get("curve", {})
                profile = ConcentrationProfile(
                    species_index=i,
                    species_name=species_list[i].name,
                    curve_type=curve_cfg.get("type", "sigmoid"),
                    values=C[:, i].tolist(),
                    max_concentration=curve_cfg.get("maxConcentration", 1.0),
                    center=curve_cfg.get("center", 0.5),
                    width=curve_cfg.get("width", 0.1),
                    unit=ConcentrationUnit.MOL_L,
                )
            else:
                # Default curve
                curve_type = ["sigmoid", "gaussian", "linear"][i % 3]
                profile = ConcentrationProfile(
                    species_index=i,
                    species_name=species_list[i].name,
                    curve_type=curve_type,
                    values=C[:, i].tolist(),
                    max_concentration=1.0,
                    center=0.3 + 0.4 * (i / max(1, len(spectra) - 1)),
                    width=0.1,
                    unit=ConcentrationUnit.MOL_L,
                )
            concentration_profiles.append(profile)

        # Create comprehensive metadata
        meta = SpectraMeta(
            species=species_list,
            concentrations=concentration_profiles,
            # Ground truth matrices (for MCR-ALS validation)
            concentration_matrix=C.tolist(),  # n_timepoints x n_species
            pure_spectra_matrix=S.T.tolist(),  # n_species x n_wavenumbers (transposed for storage)
            # Experimental conditions
            conditions=ExperimentalConditions(
                temperature_c=25.0,  # Default assumption
            ),
            # Provenance
            provenance=DataProvenance(
                source_type=SourceType.BLEND,
                created_datetime=datetime.utcnow().isoformat(),
            ),
            # This IS ground truth (we know the true C and S)
            is_ground_truth=True,
            # Processing info
            processing_steps=["blend"],
            # Custom fields for blend parameters
            custom={
                "blend_params": {
                    "n_timepoints": n_timepoints,
                    "model_type": model_type,
                    "pathlength_m": pathlength,
                    "noise_level": noise_level,
                }
            },
        )

        # Store in dataset meta
        dataset.meta["spectra"] = meta.model_dump(exclude_none=True)

        # Record processing step
        add_processing_step(
            dataset,
            "synthesis.blend",
            {
                "n_timepoints": n_timepoints,
                "model_type": model_type,
                "pathlength_m": pathlength,
                "noise_level": noise_level,
                "n_species": len(spectra),
            },
            node_id=self.node_id,
        )
        return dataset


@register_node
class SpeciesSelectorNode(Node):
    """
    Species Selector node for marking a spectrum as a blend component.

    This is a pass-through node that labels a spectrum for use in blending.
    """

    metadata = NodeMetadata(
        node_type="synthesis.species",
        category="synthesis",
        label="Species",
        description="Mark a spectrum as a species for blending",
        parameters=[
            NodeParameter(
                name="species_name",
                label="Species Name",
                param_type="text",
                default="Species",
                description="Name identifier for this species",
                required=True,
            ),
            NodeParameter(
                name="molar_absorptivity",
                label="Molar Absorptivity",
                param_type="number",
                default=1.0,
                min_value=0.0,
                max_value=1000000.0,
                description="Molar absorptivity coefficient (L/mol/cm)",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    async def execute(self, input_data: Any) -> Any:
        """
        Pass through the spectrum with species metadata.

        Args:
            input_data: Input dataset

        Returns:
            Dataset with species metadata attached
        """
        input_ds = coerce_to_sherpa(
            input_data,
            input_name="input_data",
            dataset_error_message="Input must be an dataset object object",
        )

        species_name = self.parameters.get("species_name", "Species")
        molar_abs = self.parameters.get("molar_absorptivity", 1.0)

        result = input_ds.copy()
        result.title = species_name

        # Create structured metadata
        species_info = SpeciesInfo(
            name=species_name,
            molar_absorptivity=molar_abs if molar_abs != 1.0 else None,
            state=PhysicalState.UNKNOWN,
        )

        # Check if input already has metadata
        existing_meta = None
        if hasattr(input_ds, "meta") and input_ds.meta:
            existing_dict = input_ds.meta.get("spectra", {})
            if isinstance(existing_dict, dict) and existing_dict:
                try:
                    existing_meta = SpectraMeta.model_validate(existing_dict)
                except Exception:
                    pass

        if existing_meta:
            # Update existing metadata
            existing_meta.species = [species_info]
            meta = existing_meta
        else:
            # Create new metadata
            meta = SpectraMeta(
                species=[species_info],
                provenance=DataProvenance(
                    source_type=SourceType.EXPERIMENT,
                    created_datetime=datetime.utcnow().isoformat(),
                ),
            )

        # Store in dataset meta
        result.meta["spectra"] = meta.model_dump(exclude_none=True)

        # Also keep legacy fields for backwards compatibility
        result.meta["species_name"] = species_name
        result.meta["molar_absorptivity"] = molar_abs

        # Record processing step
        add_processing_step(
            result,
            "synthesis.species",
            {
                "species_name": species_name,
                "molar_absorptivity": molar_abs,
            },
            node_id=self.node_id,
        )
        return result


@register_node
class MergeSpectraNode(Node):
    """
    Merge Spectra node for combining multiple spectra into a single dataset.

    Takes multiple input spectra and stacks them into a 2D dataset.
    """

    metadata = NodeMetadata(
        node_type="synthesis.merge",
        category="synthesis",
        label="Merge Spectra",
        description="Combine multiple spectra into a single stacked dataset",
        parameters=[
            NodeParameter(
                name="align_wavenumbers",
                label="Align Wavenumbers",
                param_type="boolean",
                default=True,
                description="Interpolate spectra to a common wavenumber grid",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    async def execute(self, *input_data: Any) -> Any:
        """
        Merge multiple spectra into a single dataset.

        Args:
            *input_data: Variable number of dataset inputs

        Returns:
            Dataset containing all spectra stacked
        """
        if len(input_data) == 0:
            raise ValueError("At least one input spectrum is required")

        datasets = [
            coerce_to_sherpa(
                inp,
                input_name=f"input_data[{idx}]",
                dataset_error_message="Input must be dataset object",
            )
            for idx, inp in enumerate(input_data)
        ]
        spectra = []
        wavenumbers_list = []
        input_units = []

        for inp in datasets:
            # Collect units from each input
            if hasattr(inp, "units") and inp.units:
                input_units.append(str(inp.units))

            inp_x_coord = inp.spectral_axis
            inp_matrix = to_numpy_2d(inp, name="input_data")
            for row in inp_matrix:
                spectra.append(row)
            wavenumbers_list.append(inp_x_coord.data if inp_x_coord is not None else np.arange(inp_matrix.shape[-1]))

        # Use the first wavenumber axis as reference
        ref_wn = wavenumbers_list[0]

        # Stack all spectra
        stacked = np.vstack([s.reshape(1, -1) for s in spectra])

        # Determine output units from input spectra
        if input_units:
            unique_units = list(set(input_units))
            if len(unique_units) > 1:
                logger.warning(
                    f"[MergeSpectraNode] Input spectra have different units: {unique_units}. Using first input's units."
                )
            output_units = input_units[0]
        else:
            output_units = "absorbance"  # Default fallback

        dataset = build_dataset_like(
            stacked,
            datasets[0],
            units=output_units,
            title="Merged Spectra",
            backend="numpy",
            copy_history=False,
        )
        dataset.target = None
        dataset.meta = {"processing_history": dataset.provenance}
        dataset.set_coordset(
            y=AxisInfo(values=np.arange(len(spectra)), title="Sample"),
            x=AxisInfo(values=ref_wn, title="Wavenumber", units="cm^-1"),
        )

        # Record processing step
        add_processing_step(
            dataset,
            "synthesis.merge",
            {
                "n_inputs": len(input_data),
                "n_spectra_merged": len(spectra),
                "align_wavenumbers": self.parameters.get("align_wavenumbers", True),
            },
            node_id=self.node_id,
        )
        return dataset
