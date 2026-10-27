"""Application-only interpretation authority; the qualified scientific runtime stays unchanged."""

from dataclasses import dataclass
from typing import Any, Protocol

from spectra_sherpa.core.execution_runtime import ExecutionRuntime


class SpectralInterpretationUnavailable(RuntimeError):
    """Safe reason an authorized application interpreter cannot serve a request."""


class SpectralPeakInterpreter(Protocol):
    async def interpret(self, request: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ApplicationExecutionRuntime(ExecutionRuntime):
    """Explicit per-execution app capability; absent in ordinary SDK execution.

    This public app adapter adds no model, artifact, or worker authority.
    Scientific nodes continue consuming the unchanged core runtime contract.
    """

    spectral_peak_interpreter: SpectralPeakInterpreter | None = None
