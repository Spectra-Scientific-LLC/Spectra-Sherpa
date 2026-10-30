/** Shared refusal vocabulary for projections, renderers, exports and advisor prose. */
export function scientificPlotRefusal(layout: unknown): string | null {
  if (!layout || typeof layout !== "object") return null;
  const meta = (layout as Record<string, unknown>).meta;
  if (!meta || typeof meta !== "object") return null;
  const reason = (meta as Record<string, unknown>).refusal_reason;
  return typeof reason === "string" && reason.trim() ? reason : null;
}

export function refusedScientificPlot(reason: string, layout: Record<string, unknown> = {}) {
  return {
    data: [],
    layout: {
      ...layout,
      meta: { ...(layout.meta as Record<string, unknown> | undefined), refusal_reason: reason },
    },
  };
}

/** Retained scientific limitations stay visible on both result surfaces. */
export function spectralTruthLimitation(nodeType: string, metadata: unknown): string | null {
  if (nodeType !== "model.mcr_als" || !metadata || typeof metadata !== "object") return null;
  const reason = (metadata as Record<string, unknown>).spectra_recovery_unavailable;
  return typeof reason === "string" && reason.trim() ? reason : null;
}
