"""Canonical, conservative BOSCH gas-state segmentation and clock alignment.

Gas channel numbers are source identities, not declared chemical identities.
The 4.5/1.5 second recipe supports etch/passivation candidate labels only.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from spectra_sherpa.app.lib.axes import SampleAxis
from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

PHASE_LABELS = {
    "etch": "Production · Gas5 / tentative SF₆ etch",
    "passivation": "Production · Gas4 / tentative C₄F₈ passivation",
    "gas1_plasma": "Gas1-only plasma · gas identity unconfirmed",
    "mixed_plasma": "Mixed gas plasma · unassigned step",
    "stabilization": "Gas stabilization · RF off",
    "break": "Break / no active plasma",
    "transition": "Gas transition / unassigned plasma",
    "unmapped": "Outside process coverage / acquisition gap",
}


def _runs(values: np.ndarray) -> list[tuple[int, int]]:
    edges = np.flatnonzero(np.r_[True, values[1:] != values[:-1], True])
    return list(zip(edges[:-1].tolist(), edges[1:].tolist()))


def phase_projection(times, signal, process, *, minimum_correlation=0.8, retain_cycle_membership=False):
    """Return exact source-row labels plus explicit alignment diagnostics.

    Clock offset is estimated, not declared as a shared Unix clock. A broad
    search rejects cycle aliases; a narrow refinement estimates the best lag.
    Rows within one DAQ interval of a gas boundary remain transition rows.
    Gaps in the process clock are never interpolated into phase assignments.
    """
    ot = np.asarray(times, dtype=float)
    y = np.asarray(signal, dtype=float)
    pt = np.asarray(process.sample_axis.values, dtype=float)
    if (
        ot.ndim != 1
        or y.shape != ot.shape
        or len(ot) < 20
        or len(pt) < 20
        or not np.isfinite(ot).all()
        or not np.isfinite(y).all()
        or not np.isfinite(pt).all()
        or np.any(np.diff(ot) <= 0)
        or np.any(np.diff(pt) <= 0)
    ):
        raise ValueError("Phase alignment requires finite increasing clocks and at least 20 observations")
    names = list(process.feature_axis.labels or [])

    def channel(suffix):
        name = f"Stat3_Etch_MV_{suffix}"
        if name not in names:
            raise ValueError(f"Missing required process channel: {name}")
        values = np.asarray(process.X[:, names.index(name)], dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(f"Non-finite process values: {name}")
        return values

    gas = np.column_stack([channel(f"Gas{i}Flow") for i in (1, 4, 5)])
    rf = channel("SourceRFLoadPower")
    maxima = gas.max(axis=0)
    if maxima[1] <= 1 or maxima[2] <= 1 or np.ptp(rf) <= 1:
        raise ValueError("No alternating production gas/RF signal is present")
    active = gas > np.maximum(maxima * 0.5, 1.0)
    # Native file times are relative despite their epoch attribute. Estimate
    # their offset against real OES observations instead of trusting that origin.
    indexes = np.unique(np.linspace(0, len(ot) - 1, min(len(ot), 4000)).astype(int))
    relative = ot[indexes] - ot[0]
    observed = y[indexes]
    low, high = np.quantile(observed, [0.05, 0.95])
    if high - low <= 1e-12:
        raise ValueError("OES alignment channel has no usable variation")
    observed = np.clip((observed - low) / (high - low), 0, 1)

    def score(offset):
        positions = relative + offset
        idx = np.searchsorted(pt, positions, side="right") - 1
        valid = (idx >= 0) & (idx < len(pt) - 1)
        safe = np.clip(idx, 0, len(pt) - 2)
        valid &= pt[safe + 1] - pt[safe] <= 0.6
        if valid.sum() < 0.9 * len(relative):
            return -1.0
        expected = gas[safe[valid], 2]
        if np.ptp(expected) <= 1e-12:
            return -1.0
        return float(np.corrcoef(observed[valid], expected)[0, 1])

    # Cover every offset with potentially >=90% optical observation overlap.
    # The optical recording may start well after the process recording, for
    # example when a variable-duration precursor precedes the production run.
    lower = float(pt[0] - np.quantile(relative, 0.1))
    upper = float(pt[-1] - np.quantile(relative, 0.9))
    if upper <= lower:
        raise ValueError("Insufficient overlapping process/OES recording coverage")
    spacing = max(0.2, (upper - lower) / 4096)
    candidates = [(score(offset), float(offset)) for offset in np.arange(lower, upper + spacing / 2, spacing)]
    best_score, best = max(candidates)
    competitor = max(value for value, offset in candidates if abs(offset - best) > 2)
    fine = [(score(offset), float(offset)) for offset in best + np.arange(-spacing, spacing + 0.01, 0.02)]
    best_score, best = max(fine)
    if not np.isfinite(best_score) or best_score < minimum_correlation or best_score - competitor < 0.025:
        raise ValueError(
            f"Ambiguous process/OES alignment (correlation {best_score:.3f}, "
            f"alias margin {best_score - competitor:.3f})"
        )
    rf_on = rf > max(1, float(rf.max()) * 0.05)
    production_runs = [(a, b) for a, b in _runs(rf_on) if rf_on[a] and pt[b - 1] - pt[a] > 60]
    if len(production_runs) != 1:
        raise ValueError("Expected one identifiable production RF interval in the wafer group")
    a, b = production_runs[0]
    labels = np.full(len(pt), "transition", dtype=object)
    labels[~rf_on & ~active.any(axis=1)] = "break"
    labels[~rf_on & active.any(axis=1)] = "stabilization"
    labels[rf_on & active[:, 0] & ~active[:, 1] & ~active[:, 2]] = "gas1_plasma"
    labels[rf_on & (active.sum(axis=1) > 1)] = "mixed_plasma"
    production = (np.arange(len(pt)) >= a) & (np.arange(len(pt)) < b) & ~active[:, 0]
    labels[production & active[:, 2] & ~active[:, 1]] = "etch"
    labels[production & active[:, 1] & ~active[:, 2]] = "passivation"
    mapped_times = ot - ot[0] + best
    idx = np.searchsorted(pt, mapped_times, side="right") - 1
    safe = np.clip(idx, 0, len(pt) - 1)
    mapped = labels[safe].copy()
    cadence = float(np.median(np.diff(pt)))
    valid = (idx >= 0) & (idx < len(pt) - 1)
    valid &= mapped_times - pt[safe] <= 3 * cadence
    mapped[~valid] = "unmapped"
    # Preserve uncertain DAQ-resolution transition edges rather than claiming
    # sub-sample precision from the much faster optical acquisition clock.
    boundary = pt[np.flatnonzero(labels[1:] != labels[:-1]) + 1]
    if not retain_cycle_membership:
        for edge in boundary:
            mapped[np.abs(mapped_times - edge) <= cadence] = "transition"
    # Cycle identity comes from process etch onsets, never optical recording gaps.
    onsets = (labels == "etch") & np.r_[True, labels[:-1] != "etch"]
    cycles = np.cumsum(onsets)[safe]
    production_membership = valid & (safe >= a) & (safe < b)
    cycles[~production_membership] = 0
    return mapped, {
        **(
            {"cycle_indices": cycles.tolist(), "production_membership": production_membership.tolist()}
            if retain_cycle_membership
            else {}
        ),
        "method": "gas5 / strongest OES channel correlation",
        "correlation": best_score,
        "alias_margin": best_score - competitor,
        "process_time_at_first_oes_s": best,
        "boundary_uncertainty_s": cadence,
        "process_coverage_s": [float(pt[0]), float(pt[-1])],
        "gas_thresholds": np.maximum(maxima * 0.5, 1.0).tolist(),
        "rf_threshold": max(1, float(rf.max()) * 0.05),
        "chemical_mapping_confirmed": False,
        "chemical_mapping_source": "User-suggested, pending OES validation: Gas1=O2; Gas4=C4F8; Gas5=SF6",
    }


@register_node
class BoschPhaseLabelsNode(Node):
    metadata = NodeMetadata(
        node_type="preprocess.bosch_phase_labels",
        category="preprocessing",
        label="BOSCH Gas Phase Labels",
        description=(
            "Label wafer acquisitions from a matching process gas record; reject ambiguous clock alignment. "
            "Gas1=O2, Gas4=C4F8, Gas5=SF6 remains tentative pending spectroscopic validation."
        ),
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Wafer spectra",
                accepted_data_roles=["X_spectra"],
            ),
            PortMetadata(
                name="process",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Matching process wafer",
                accepted_data_roles=["X_features"],
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Spectra with gas phase labels",
                accepted_data_roles=["X_spectra"],
            )
        ],
        policy=NodePolicy(),
    )

    async def execute(self, default=None, process=None, **kwargs):
        source = coerce_to_sherpa(default, input_name="default")
        companion = coerce_to_sherpa(process, input_name="process")
        if source.meta.get("supervision_binding") is not None:
            raise ValueError("Apply BOSCH phase labels before binding sample-table supervision")
        wafer = source.source_identity.object_name
        process_group = companion.source_identity.object_name
        if source.sample_axis is None or source.sample_axis.values is None or not wafer:
            raise ValueError("Select one native OES wafer with its original acquisition clock and identity")
        date = datetime.fromtimestamp(float(source.sample_axis.values[0]), timezone.utc).strftime("%Y_%m_%d")
        if process_group != f"Day_{date}_{wafer}":
            raise ValueError("Process group does not match this OES acquisition date and wafer identity")
        probes = np.unique(np.linspace(0, source.shape[0] - 1, min(source.shape[0], 256)).astype(int))
        channel = int(np.argmax(np.mean(source.X[probes], axis=0)))
        labels, diagnostics = phase_projection(source.sample_axis.values, source.X[:, channel], companion)
        result = apply_phase_labels(source, labels, diagnostics, node_id=self.node_id)
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)


def apply_phase_labels(source, labels, diagnostics, *, node_id):
    """Project canonical phase keys onto the typed sample table, preserving identities."""
    labels = np.asarray(labels, dtype=object)
    if labels.shape != (source.n_samples,) or any(label not in PHASE_LABELS for label in labels):
        raise ValueError("Processing labels must match the exact acquisition population")
    result = source.copy()
    axis = source.sample_axis.model_dump()
    table = dict(axis.get("sample_table") or {})
    table["processing_step"] = labels.tolist()
    axis["sample_table"] = table
    result.sample_axis = SampleAxis(**axis)
    add_processing_step(result, "preprocess.bosch_phase_labels", {}, node_id=node_id, input_shape=source.shape)
    result.set_extra("bosch.phase_alignment", diagnostics)
    return result


bind_stable_execution_contract(
    BoschPhaseLabelsNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.preprocess.bosch_phase_labels",
    implementation_version="0.1.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 60, "cpu_seconds": 60, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=("Zenodo 17122442; gas-channel mapping is tentative, endpoint control is unverified",),
)
