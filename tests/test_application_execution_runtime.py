"""App interpretation authority must not alter the qualified core runtime."""

from dataclasses import FrozenInstanceError

import pytest

from spectra_sherpa.app.contracts.application_execution_runtime import ApplicationExecutionRuntime
from spectra_sherpa.core.execution_runtime import ExecutionRuntime


def test_optional_app_interpreter_is_not_sdk_runtime_authority():
    interpreter = object()
    runtime = ApplicationExecutionRuntime(spectral_peak_interpreter=interpreter)
    assert isinstance(runtime, ExecutionRuntime)
    assert runtime.spectral_peak_interpreter is interpreter
    assert not hasattr(ExecutionRuntime(), "spectral_peak_interpreter")
    assert runtime.model_artifact_reader is None
    assert runtime.model_artifact_writer is None
    with pytest.raises(FrozenInstanceError):
        runtime.spectral_peak_interpreter = None
