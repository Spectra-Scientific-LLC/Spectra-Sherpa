from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import FeatureAxis, SpectralAxis, canonicalize_feature_axis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.nodes.blend import MergeSpectraNode
from spectra_sherpa.core.axis_semantics import (
    AxisQuantity,
    AxisSemantics,
    axis_semantics,
    canonical_axis_unit,
    require_compatible_axis_semantics,
)


@pytest.mark.parametrize(
    "source",
    ["cm-1", "cm^-1", "cm⁻¹", "1/cm", "Wavenumber (cm-1)", "Raman shift (cm^-1)"],
)
def test_inverse_centimetre_aliases_share_one_canonical_unit(source: str) -> None:
    assert canonical_axis_unit(source) == "cm-1"


def test_quantity_not_inferred_from_ambiguous_inverse_centimetre_unit() -> None:
    assert axis_semantics(axis_class="SpectralAxis", title=None, units="cm-1").quantity is None


def test_raman_shift_and_wavenumber_remain_distinct() -> None:
    wavenumber = axis_semantics(axis_class="SpectralAxis", title="Wavenumber", units="cm^-1")
    raman = axis_semantics(axis_class="SpectralAxis", title="Raman shift", units="cm⁻¹")

    assert wavenumber == AxisSemantics(AxisQuantity.WAVENUMBER, "cm-1")
    assert raman == AxisSemantics(AxisQuantity.RAMAN_SHIFT, "cm-1")
    with pytest.raises(ValueError, match="cannot combine 'wavenumber' and 'raman_shift'"):
        require_compatible_axis_semantics(wavenumber, raman, context="test operation")


def test_quantity_can_be_recovered_from_combined_vendor_unit_label() -> None:
    semantics = axis_semantics(axis_class="SpectralAxis", title=None, units="Wavenumber (cm-1)")

    assert semantics == AxisSemantics(AxisQuantity.WAVENUMBER, "cm-1")


def test_reader_boundary_preserves_original_unit_spelling_for_display() -> None:
    axis = SpectralAxis(
        values=np.asarray([4000.0, 3999.0]),
        title="Wavenumber",
        units="cm⁻¹",
    )

    canonical = canonicalize_feature_axis(axis)

    assert canonical.units == "cm-1"
    assert canonical.display_units == "cm⁻¹"
    assert canonical.quantity is AxisQuantity.WAVENUMBER
    assert canonical.axis_type == "wavenumber"


def test_raman_axis_type_is_not_wavenumber_alias() -> None:
    axis = canonicalize_feature_axis(SpectralAxis(values=np.asarray([100.0, 200.0]), title="Raman shift", units="cm-1"))

    assert axis.quantity is AxisQuantity.RAMAN_SHIFT
    assert axis.axis_type == "raman_shift"


def test_compatible_aliases_admit_after_canonicalization() -> None:
    left = axis_semantics(axis_class="SpectralAxis", title="Wavenumber", units="1/cm")
    right = axis_semantics(axis_class="SpectralAxis", title="Wavenumber", units="cm⁻¹")

    require_compatible_axis_semantics(left, right, context="test operation")


def test_generic_feature_tables_may_share_an_undeclared_axis() -> None:
    undeclared = AxisSemantics(quantity=None, units=None)

    require_compatible_axis_semantics(
        undeclared,
        undeclared,
        context="generic table collection",
        require_quantity=False,
    )


def test_declared_channel_indexes_are_dimensionless() -> None:
    channel = axis_semantics(axis_class="SpectralAxis", title="Channel", units=None)

    assert channel == AxisSemantics(AxisQuantity.INDEX, None)
    require_compatible_axis_semantics(channel, channel, context="single-view channel collection")


def test_generic_feature_tables_still_refuse_asymmetric_semantics() -> None:
    with pytest.raises(ValueError, match="matching feature-axis quantity declarations"):
        require_compatible_axis_semantics(
            AxisSemantics(quantity=None, units=None),
            AxisSemantics(quantity=AxisQuantity.WAVELENGTH, units="nm"),
            context="generic table collection",
            require_quantity=False,
        )


def test_unit_compatible_node_admission_matches_collection_policy_for_generic_tables() -> None:
    left = SherpaDataset(
        X=np.asarray([[1.0, 2.0]]),
        feature_axis=FeatureAxis(values=np.asarray([0.0, 1.0]), title="Feature"),
        data_role="X_features",
    )
    right = SherpaDataset(
        X=np.asarray([[3.0, 4.0]]),
        feature_axis=FeatureAxis(values=np.asarray([0.0, 1.0]), title="Feature"),
        data_role="X_features",
    )
    node = MergeSpectraNode("merge", {})

    node._validate_axis_semantics((), {"default": [left, right]})


def test_unit_compatible_node_names_missing_axis_declarations() -> None:
    declared = SherpaDataset(
        X=np.asarray([[1.0, 2.0]]),
        feature_axis=SpectralAxis(
            values=np.asarray([1000.0, 1001.0]),
            title="Wavenumber",
            units="cm-1",
        ),
    )
    undeclared = SherpaDataset(
        X=np.asarray([[3.0, 4.0]]),
        feature_axis=FeatureAxis(values=np.asarray([0.0, 1.0]), title="Feature"),
        data_role="X_features",
    )
    node = MergeSpectraNode("merge", {})

    with pytest.raises(ValueError, match="declare the missing quantity and units"):
        node._validate_axis_semantics((), {"default": [declared, undeclared]})


def test_wavelength_units_are_unambiguous_but_not_interchangeable() -> None:
    nanometres = axis_semantics(axis_class="SpectralAxis", title=None, units="nanometers")
    micrometres = axis_semantics(axis_class="SpectralAxis", title=None, units="um")

    assert nanometres.quantity is AxisQuantity.WAVELENGTH
    assert micrometres.quantity is AxisQuantity.WAVELENGTH
    with pytest.raises(ValueError, match="matching canonical feature-axis units"):
        require_compatible_axis_semantics(nanometres, micrometres, context="test operation")
