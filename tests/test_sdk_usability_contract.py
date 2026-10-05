"""Scientist-facing SDK failures name the exact remediation."""

from __future__ import annotations

import sys

import pytest

from spectra_sherpa.app.services import synthesis
from spectra_sherpa.core.execution_runtime import ExecutionCapabilityError, ExecutionRuntime


@pytest.mark.parametrize(
    ("method", "remediation"),
    (
        ("require_model_artifact_reader", "import/open the model in the Workbench"),
        ("require_model_artifact_writer", "provide ExecutionRuntime(model_artifact_writer=...)"),
        ("require_model_artifact_replay", "provide ExecutionRuntime(model_artifact_replay=...)"),
        ("require_canonical_artifact_reader", "load the canonical project"),
        ("require_dataset_source_resolver", "use deploy.input for SDK arrays"),
    ),
)
def test_missing_runtime_capabilities_name_an_action(method: str, remediation: str) -> None:
    runtime = ExecutionRuntime()

    with pytest.raises(ExecutionCapabilityError, match=r"capability is unavailable") as caught:
        getattr(runtime, method)()

    assert remediation in str(caught.value)


def test_missing_hitran_extra_names_the_exact_install_command(monkeypatch, tmp_path) -> None:
    monkeypatch.setitem(sys.modules, "hapi", None)
    monkeypatch.setitem(sys.modules, "hapi2", None)

    with pytest.raises(synthesis.SynthesisError) as hapi1:
        synthesis._import_hapi1_module()
    with pytest.raises(synthesis.SynthesisError) as hapi2:
        synthesis._import_hapi2_module(tmp_path / "hitran")

    command = "pip install 'spectra-sherpa[hitran]'"
    assert command in str(hapi1.value)
    assert command in str(hapi2.value)


def test_missing_nist_extra_names_the_exact_install_command(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "bs4", None)

    with pytest.raises(synthesis.SynthesisError) as caught:
        synthesis._extract_nist_jcamp_download_url("<html></html>")

    assert "pip install 'spectra-sherpa[nist]'" in str(caught.value)
