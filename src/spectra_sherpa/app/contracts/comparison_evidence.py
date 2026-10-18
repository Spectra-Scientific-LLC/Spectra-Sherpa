"""Trusted registration seam for independently owned scientific evidence.

Only server startup code registers providers. A client reference selects an
already registered reader, never a URL, module, or executable. Providers must
enforce actor/project authorization before returning any data. The OSS
comparison service, not the provider, makes compatibility decisions.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.schemas.scientific_comparison import EvaluationRole, EvidenceReference, PopulationSummary


@dataclass(frozen=True)
class EvaluationEvidence:
    role: EvaluationRole
    sample_ids: tuple[str, ...]
    observations: tuple[float, ...]
    predictions: tuple[float, ...]
    # The receipt identifies exact features/population; response identity
    # identifies the target meaning, independently of its display name.
    feature_receipt: str
    response_identity: str
    units: str | None = None
    response: str | None = None
    fitted_sample_ids: tuple[str, ...] | None = None
    split_plan: dict[str, Any] | None = None
    population: PopulationSummary = field(default_factory=PopulationSummary)
    limitation: str | None = None
    aggregate_metrics: dict[str, float] = field(default_factory=dict)
    # Server-verified identity of an aggregate evaluation: exact development
    # examination, target/metric definition and ordered paired partitions.
    # Does not authorize sample plots or imply row-level retention.
    aggregate_protocol: str | None = None


@dataclass(frozen=True)
class ResolvedComparisonEvidence:
    reference: EvidenceReference
    label: str
    evaluations: tuple[EvaluationEvidence, ...] = ()
    population: PopulationSummary = field(default_factory=PopulationSummary)
    unavailable_reason: str | None = None
    dataset_use: dict[str, Any] | None = None


ComparisonEvidenceProvider = Callable[
    [EvidenceReference, AsyncSession, int, int], Awaitable[ResolvedComparisonEvidence]
]
_providers: dict[str, ComparisonEvidenceProvider] = {}


def register_comparison_evidence_provider(name: str, provider: ComparisonEvidenceProvider) -> None:
    import re

    if name == "runs" or not re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", name):
        raise ValueError("Evidence provider name is invalid or reserved.")
    if name in _providers and _providers[name] is not provider:
        raise ValueError(f"Evidence provider {name!r} is already registered.")
    _providers[name] = provider


def get_comparison_evidence_provider(name: str) -> ComparisonEvidenceProvider:
    try:
        return _providers[name]
    except KeyError as exc:
        raise ValueError("The evidence provider is unavailable in this installation.") from exc
