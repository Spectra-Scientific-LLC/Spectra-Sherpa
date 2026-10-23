"""Scientific refusal projections are closed and independent of exception text."""

import multiprocessing
import pickle
from concurrent.futures import ProcessPoolExecutor

import pytest

from spectra_sherpa.app.services.dag.fitted_input_identity import FittedInputMismatch, fitted_input_refusal_reason
from spectra_sherpa.app.services.dag.legacy_model_application import LegacyInputRefusal, legacy_refusal_reason
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


def _raise_classified_refusal(kind):
    if kind == "fitted":
        raise FittedInputMismatch(("signal_units",))
    if kind == "legacy":
        raise LegacyInputRefusal("units_mismatch")
    raise ScientificInputRefusal("target_mismatch", detail="private operator detail")


@pytest.mark.parametrize(
    "kind,exception",
    [("fitted", FittedInputMismatch), ("legacy", LegacyInputRefusal), ("target", ScientificInputRefusal)],
)
def test_classification_and_private_detail_survive_pickling(kind, exception):
    with pytest.raises(exception) as caught:
        _raise_classified_refusal(kind)
    restored = pickle.loads(pickle.dumps(caught.value))
    assert type(restored) is exception
    assert restored.args == caught.value.args
    assert restored.__dict__ == caught.value.__dict__


def test_real_spawned_worker_preserves_classified_refusals_and_stays_usable():
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as pool:
        for kind, exception in [
            ("fitted", FittedInputMismatch),
            ("legacy", LegacyInputRefusal),
            ("target", ScientificInputRefusal),
        ]:
            with pytest.raises(exception) as caught:
                pool.submit(_raise_classified_refusal, kind).result(timeout=60)
            if kind == "fitted":
                assert caught.value.fields == ("signal_units",)
                assert "signal_units" in fitted_input_refusal_reason(caught.value.fields)
            elif kind == "legacy":
                assert caught.value.code == "units_mismatch"
                assert legacy_refusal_reason(caught.value.code) == (
                    "Application feature-axis units differ from the legacy model"
                )
            else:
                assert caught.value.code == "target_mismatch"
                assert str(caught.value) == "private operator detail"
                assert "private" not in scientific_refusal_reason(caught.value.code)
