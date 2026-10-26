"""Public HTTP refusals must preserve meaning without publishing internals."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from spectra_sherpa.app.services.batch_verification import application_refusal_reason
from spectra_sherpa.app.services.dag.fitted_input_identity import FittedInputMismatch
from spectra_sherpa.core.scientific_refusal import ScientificInputRefusal


def test_application_refusals_keep_closed_scientific_advice_only():
    secret = "/private/operator/data/key.txt: nested parser failure"
    assert secret not in application_refusal_reason(ValueError(secret))
    mismatch = FittedInputMismatch(("axis", "signal_units"))
    mismatch.args = (secret,)
    reason = application_refusal_reason(mismatch)
    assert "axis, signal_units" in reason
    assert "refit" in reason
    assert secret not in reason
    assert "reference targets" in application_refusal_reason(
        ScientificInputRefusal("reference_targets_required", detail=secret)
    )


def test_stateless_compatibility_is_exact_directional_and_operation_scoped():
    from spectra_sherpa.core.node_identity import node_contract_digest_is_compatible

    old = "4d405cdbf887713619a462b33e9c941a62abcd281176f590415c46bf606507b6"
    new = "da86321ad34a334b778e3e3632e542fbfb6374f9283bd92c34657f1e79f1b490"
    assert node_contract_digest_is_compatible("preprocess.smooth", old, new)
    assert not node_contract_digest_is_compatible("preprocess.smooth", new, old)
    assert not node_contract_digest_is_compatible("preprocess.scale", old, new)
    assert not node_contract_digest_is_compatible("preprocess.smooth", "0" * 64, new)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [ValueError("/private/secret/file"), HTTPException(409, "/private/secret/file")])
async def test_batch_execute_masks_nested_admission_errors_before_any_write(monkeypatch, failure):
    from spectra_sherpa.app.api.v1.routes import runs

    async def refuse(*args, **kwargs):
        raise failure

    monkeypatch.setattr(runs, "_prepare_verification_pair", refuse)
    # No session is needed: admission must refuse before reservation/persistence.
    with pytest.raises(HTTPException) as caught:
        await runs.execute_verification_batch(
            SimpleNamespace(pairs=[object()]), _dg=None, session=None, current_user=SimpleNamespace(id=7)
        )
    assert caught.value.status_code in {409, 422}
    assert "/private" not in caught.value.detail
    assert any(word in caught.value.detail for word in ("Reload", "Review"))
