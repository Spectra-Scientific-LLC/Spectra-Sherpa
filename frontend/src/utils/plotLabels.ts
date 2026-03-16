/**
 * Shared utilities for plot axis labeling in chemometric applications.
 *
 * Design principles:
 * - Never use "a.u." (arbitrary units) - use actual units or ML terms
 * - Use backend metadata when available
 * - Fall back to appropriate ML terminology ("Feature", "Response", "Target")
 * - Respect dimensionless/normalized data by not showing units
 */

export interface AxisMetadata {
  title?: string;
  units?: string;
}

export interface PlotMetadata {
  x_title?: string;
  x_units?: string;
  y_title?: string;
  y_units?: string;
  value_units?: string;
  value_units_label?: string;
  loadings_axis_labels?: unknown[];
  loadings_axis_units?: string;
  wavenumbers?: number[];
  feature_names?: string[];
}

/**
 * Build a properly formatted axis label from title and units.
 * Never returns "a.u." - uses generic terms instead.
 *
 * @param title - Axis title (e.g., "Wavenumber", "Absorbance")
 * @param units - Units (e.g., "cm^-1", "absorbance")
 * @param fallback - Default title if none provided (e.g., "Feature", "Response")
 */
export function buildAxisLabel(
  title?: string | null,
  units?: string | null,
  fallback: string = "Value"
): string {
  // Filter out meaningless units
  const meaningfulUnits = units &&
    units !== "dimensionless" &&
    units !== "normalized" &&
    units !== "a.u." &&
    units !== "arbitrary";

  if (meaningfulUnits) {
    return title ? `${title} (${units})` : units;
  }

  return title || fallback;
}

/**
 * Get Y-axis label from plot metadata.
 * Priority: y_units with y_title > y_title alone > "Response" (ML default)
 */
export function getYAxisLabel(metadata?: PlotMetadata | null): string {
  if (!metadata) return "Response";
  const fallbackUnits = metadata.value_units_label || metadata.value_units;
  return buildAxisLabel(metadata.y_title, metadata.y_units || fallbackUnits, "Response");
}

/**
 * Get X-axis label from plot metadata.
 * Priority: x_units with x_title > x_title alone > "Feature" (ML default)
 */
export function getXAxisLabel(metadata?: PlotMetadata | null): string {
  if (!metadata) return "Feature";
  return buildAxisLabel(metadata.x_title, metadata.x_units, "Feature");
}

/**
 * Get loadings plot X-axis label.
 * Uses wavenumbers/feature names context for appropriate labeling.
 */
export function getLoadingsXAxisLabel(metadata?: PlotMetadata | null): string {
  if (!metadata) return "Feature Index";

  // If we have explicit loadings axis info
  if (metadata.loadings_axis_units) {
    return buildAxisLabel(metadata.x_title, metadata.loadings_axis_units, "Feature");
  }

  // If we have wavenumbers, use axis metadata (could be wavenumber OR wavelength etc.)
  if (metadata.wavenumbers && metadata.wavenumbers.length > 0) {
    return buildAxisLabel(metadata.x_title, metadata.x_units, "Feature");
  }

  // If we have feature names, it's tabular data
  if (metadata.feature_names && metadata.feature_names.length > 0) {
    return "Feature";
  }

  return "Feature Index";
}

/**
 * Detect if data is spectral based on metadata.
 * Note: This does NOT determine reversal — only wavenumber data should be reversed.
 */
export function isSpectralData(metadata?: PlotMetadata | null): boolean {
  if (!metadata) return false;

  const xTitle = (metadata.x_title || "").toLowerCase();
  const spectralKeywords = [
    'wavenumber', 'wavelength', 'raman', 'cm-1', 'cm⁻¹',
    'nm', 'shift', 'frequency', 'cm^-1'
  ];

  return spectralKeywords.some(kw => xTitle.includes(kw)) ||
         !!(metadata.wavenumbers && metadata.wavenumbers.length > 0);
}

/**
 * Default label for scores plot axes (PCA, PLS).
 * These already have variance explained, so just return "Scores".
 */
export function getScoresAxisLabel(
  pcLabel?: string,
  varianceRatio?: number
): string {
  if (pcLabel) return pcLabel;
  if (varianceRatio !== undefined) {
    return `PC (${(varianceRatio * 100).toFixed(1)}%)`;
  }
  return "Component Score";
}
