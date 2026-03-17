"""
DatasetSummarizer — LLM-facing summary generation for SherpaDataset.

Separates data model from LLM policy:
- Prompt formatting and natural language synthesis
- Tiered information disclosure
- Token budgeting and truncation
- Distribution statistics instead of raw arrays

Usage::

    from spectra_sherpa.app.lib.dataset_summarizer import DatasetSummarizer

    summarizer = DatasetSummarizer()
    context = summarizer.summarize(dataset, tier=1, max_tokens=2000)
"""

from __future__ import annotations

from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset


class DatasetSummarizer:
    """Generates LLM-facing summaries from SherpaDataset.

    Tiers:
        0: Domain + shape (goal understanding)
        1: + state + axis summary (strategy selection)
        2: + full provenance + parameters (algorithm config)
        3: + quality metrics + sample statistics (quality assessment)
    """

    def summarize(
        self,
        dataset: SherpaDataset,
        tier: int = 1,
        max_tokens: int | None = None,
        max_samples_detail: int = 20,
    ) -> str:
        """Generate tiered natural-language summary."""
        parts: list[str] = []

        # Tier 0: Domain + shape (always included)
        parts.append(self._tier0_identity(dataset))

        if tier >= 1:
            parts.append(self._tier1_state(dataset))

        if tier >= 2:
            parts.append(self._tier2_provenance(dataset))

        if tier >= 3:
            parts.append(self._tier3_quality(dataset, max_samples_detail))

        text = "\n\n".join(p for p in parts if p)

        if max_tokens is not None:
            text = self._truncate(text, max_tokens)

        return text

    def to_structured(self, dataset: SherpaDataset, tier: int = 1) -> dict[str, Any]:
        """Return structured dict for LLM tool consumption (not prose)."""
        result: dict[str, Any] = {
            "dataset_id": dataset.dataset_id,
            "shape": list(dataset.shape),
            "n_samples": dataset.shape[0],
            "n_features": dataset.shape[-1],
            "title": dataset.title,
            "backend": dataset.backend,
        }

        # Domain
        domain = dataset.domain
        result["domain"] = {
            "technique": domain.technique,
            "sample_type": domain.sample_type,
            "measurement_mode": domain.measurement_mode,
        }
        if domain.inferred:
            result["domain"]["inferred"] = {
                "technique": domain.inferred.technique,
                "confidence": domain.inferred.confidence,
                "source": domain.inferred.source,
            }

        if tier >= 1:
            state = dataset.state
            result["state"] = {
                "processing_stage": state.processing_stage,
                "effects": sorted(state.effects),
                "n_steps": state.n_steps,
            }
            result["units"] = dataset.units
            if dataset.feature_axis:
                result["feature_axis"] = {
                    "type": dataset.feature_axis.axis_type,
                    "range": dataset.feature_axis.range,
                    "units": dataset.feature_axis.units,
                    "n_points": dataset.feature_axis.length,
                }
            if dataset.target is not None:
                tc = dataset.target_context
                result["target"] = {
                    "type": tc.target_type,
                    "name": tc.target_name,
                    "units": tc.target_units,
                    "n_classes": tc.n_classes,
                    "n_values": len(dataset.target),
                }

        if tier >= 2:
            result["provenance"] = dataset.provenance.to_list()

        if tier >= 3:
            q = dataset.quality
            result["quality"] = {
                "snr": q.snr,
                "n_evaluations": len(q.evaluations),
            }
            if q.latest:
                latest = q.latest.model_dump(exclude_none=True)
                result["quality"]["latest"] = latest

            # Data statistics
            result["data_statistics"] = self._compute_statistics(dataset)

        return result

    def to_mcp_resource(self, dataset: SherpaDataset) -> dict[str, Any]:
        """MCP resource representation: manifest + preview + provenance."""
        manifest = dataset.manifest.model_dump(mode="json")
        preview = self._preview(dataset, n_rows=5)
        return {
            "manifest": manifest,
            "preview": preview,
            "provenance": dataset.provenance.to_list(),
            "state": dataset.state.model_dump(mode="json"),
        }

    # ── Tier Builders ─────────────────────────────────────────────

    def _tier0_identity(self, ds: SherpaDataset) -> str:
        """Tier 0: Domain + shape."""
        lines = []
        title = ds.title or "Untitled dataset"
        lines.append(f"Dataset: {title}")
        lines.append(f"Shape: {ds.shape[0]} samples x {ds.shape[-1]} features")
        lines.append(f"Backend: {ds.backend}")

        domain = ds.domain
        if domain.technique:
            lines.append(f"Technique: {domain.technique}")
        if domain.sample_type:
            lines.append(f"Sample type: {domain.sample_type}")
        if domain.measurement_mode:
            lines.append(f"Measurement mode: {domain.measurement_mode}")
        if domain.inferred and not domain.technique:
            inf = domain.inferred
            lines.append(
                f"Inferred technique: {inf.technique} " f"(confidence={inf.confidence:.0%}, source={inf.source})"
            )

        return "\n".join(lines)

    def _tier1_state(self, ds: SherpaDataset) -> str:
        """Tier 1: + state + axis summary."""
        lines = []
        state = ds.state
        lines.append(f"Processing stage: {state.processing_stage}")
        if state.effects:
            lines.append(f"Applied effects: {', '.join(sorted(state.effects))}")
        lines.append(f"Processing steps: {state.n_steps}")

        if ds.units:
            lines.append(f"Data units: {ds.units}")

        sa = ds.feature_axis
        if sa:
            axis_desc = f"Spectral axis: {sa.length} points"
            if sa.units:
                axis_desc += f" ({sa.units})"
            if sa.range:
                axis_desc += f", range [{sa.range[0]:.1f}, {sa.range[1]:.1f}]"
            if sa.axis_type:
                axis_desc += f", type={sa.axis_type}"
            lines.append(axis_desc)

        sam = ds.sample_axis
        if sam:
            sam_desc = f"Sample axis: {sam.length} samples"
            if sam.include_mask is not None:
                sam_desc += f", {sam.n_included} included"
            if sam.labels:
                preview = sam.labels[:5]
                if len(sam.labels) > 5:
                    preview_str = ", ".join(preview) + f"... (+{len(sam.labels) - 5} more)"
                else:
                    preview_str = ", ".join(preview)
                sam_desc += f", labels: [{preview_str}]"
            lines.append(sam_desc)

        if ds.target is not None:
            tc = ds.target_context
            target_desc = f"Target: {len(ds.target)} values"
            if tc.target_type:
                target_desc += f", type={tc.target_type}"
            if tc.target_name:
                target_desc += f", name={tc.target_name}"
            if tc.target_units:
                target_desc += f" ({tc.target_units})"
            if tc.n_classes:
                target_desc += f", {tc.n_classes} classes"
            lines.append(target_desc)

        return "\n".join(lines)

    def _tier2_provenance(self, ds: SherpaDataset) -> str:
        """Tier 2: + full provenance + parameters."""
        if not ds.provenance:
            return "Provenance: No processing steps recorded."

        lines = [f"Provenance ({len(ds.provenance)} steps):"]
        for i, entry in enumerate(ds.provenance):
            step = f"  {i + 1}. {entry.op_id}"
            if entry.op_version != "1.0":
                step += f" (v{entry.op_version})"
            if entry.state_effects:
                step += f" [{', '.join(entry.state_effects)}]"
            lines.append(step)
            if entry.parameters:
                params_str = ", ".join(f"{k}={v!r}" for k, v in entry.parameters.items())
                lines.append(f"     params: {params_str}")
            if entry.input_shape and entry.output_shape:
                lines.append(f"     shape: {entry.input_shape} -> {entry.output_shape}")

        return "\n".join(lines)

    def _tier3_quality(self, ds: SherpaDataset, max_samples: int = 20) -> str:
        """Tier 3: + quality metrics + sample statistics."""
        lines = []

        # Quality metrics
        q = ds.quality
        if q.snr is not None:
            lines.append(f"SNR: {q.snr:.2f}")

        if q.evaluations:
            lines.append(f"Evaluations ({len(q.evaluations)}):")
            for ev in q.evaluations[-3:]:  # Show last 3
                ev_desc = f"  - {ev.model_type or 'unknown'}"
                if ev.fold is not None:
                    ev_desc += f" (fold {ev.fold})"
                metrics = []
                if ev.r2 is not None:
                    metrics.append(f"R2={ev.r2:.4f}")
                if ev.rmse is not None:
                    metrics.append(f"RMSE={ev.rmse:.4f}")
                if ev.accuracy is not None:
                    metrics.append(f"accuracy={ev.accuracy:.4f}")
                if metrics:
                    ev_desc += f": {', '.join(metrics)}"
                lines.append(ev_desc)

        # Data statistics
        stats = self._compute_statistics(ds)
        if stats:
            lines.append("Data statistics:")
            for k, v in stats.items():
                if isinstance(v, float):
                    lines.append(f"  {k}: {v:.4g}")
                else:
                    lines.append(f"  {k}: {v}")

        return "\n".join(lines) if lines else ""

    # ── Helpers ────────────────────────────────────────────────────

    def _compute_statistics(self, ds: SherpaDataset) -> dict[str, Any]:
        """Compute distribution statistics on the data matrix."""
        X = ds.X
        finite_mask = np.isfinite(X)
        if not np.any(finite_mask):
            return {"all_nan": True}

        finite_data = X[finite_mask]
        return {
            "mean": float(np.mean(finite_data)),
            "std": float(np.std(finite_data)),
            "min": float(np.min(finite_data)),
            "max": float(np.max(finite_data)),
            "nan_fraction": float(1.0 - np.mean(finite_mask)),
            "n_total_values": int(X.size),
        }

    def _preview(self, ds: SherpaDataset, n_rows: int = 5) -> dict[str, Any]:
        """First N rows preview for MCP."""
        n = min(n_rows, ds.shape[0])
        preview_data = ds.X[:n].tolist()
        result: dict[str, Any] = {
            "n_rows": n,
            "data": preview_data,
        }
        if ds.feature_axis and ds.feature_axis.values is not None:
            # First/last few axis values
            vals = ds.feature_axis.values
            result["feature_axis_preview"] = {
                "first_5": vals[:5].tolist(),
                "last_5": vals[-5:].tolist(),
                "units": ds.feature_axis.units,
            }
        if ds.sample_axis and ds.sample_axis.labels:
            result["sample_labels"] = ds.sample_axis.labels[:n]
        return result

    def _truncate(self, text: str, max_tokens: int) -> str:
        """Rough token budget: ~4 chars per token."""
        max_chars = max_tokens * 4
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n... (truncated)"
