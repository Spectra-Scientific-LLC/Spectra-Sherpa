"""Scientific refusal projections are closed and independent of exception text."""

import pytest

from spectra_sherpa.app.services.dag.fitted_input_identity import FittedInputMismatch, fitted_input_refusal_reason
from spectra_sherpa.core.scientific_refusal import ScientificInputRefusal, scientific_refusal_reason


@pytest.mark.parametrize("field", ["features", "axis", "signal_units", "signal_quantity", "measurement_mode"])
def test_fitted_input_fields_are_literal_public_labels(field):
    refusal = FittedInputMismatch((field,))
    refusal.args = ("private internal detail",)
    assert str(refusal) == "private internal detail"
    assert fitted_input_refusal_reason(refusal.fields) == (
        f"application input differs from fitted input authority: {field}; "
        "use an explicit conversion or refit with the correct metadata"
    )


@pytest.mark.parametrize("fields", [(), ("axis", "axis"), ("axis",) * 6])
def test_malformed_field_selection_is_refused(fields):
    with pytest.raises(ValueError):
        FittedInputMismatch(fields)


def test_unknown_codes_and_labels_are_never_projected():
    with pytest.raises(KeyError):
        ScientificInputRefusal("Traceback: /private/server.py")
    with pytest.raises(ValueError):
        FittedInputMismatch(("Traceback: /private/server.py",))


def test_refusal_detail_is_not_public_target_context():
    refusal = ScientificInputRefusal("target_mismatch", detail="Oil Traceback /private/server.py")
    assert "Oil" not in scientific_refusal_reason(refusal.code)
    assert scientific_refusal_reason(refusal.code, target_name="Oil") == (
        "Saved model target 'Oil' could not be matched. Bind the matching target before application."
    )
