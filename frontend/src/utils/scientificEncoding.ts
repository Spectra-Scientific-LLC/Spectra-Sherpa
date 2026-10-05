/** Shared quantitative display rules; these never change scientific values. */
export const SCIENTIFIC_HOVER_FORMAT = ".15g";
export type ScientificDisplayPrecision =
  | { significantDigits: number; decimalPlaces?: never }
  | { decimalPlaces: number; significantDigits?: never };

/**
 * A numeric payload does not encode measurement significant figures. Without an
 * explicit display policy, keep its round-trip representation. With a policy,
 * keep the formatted string (including trailing zeros); never coerce it back
 * through Number. Decimal displays use scientific notation below their unit of
 * resolution, with decimalPlaces + 1 significant digits in the mantissa.
 */
export function scientificNumber(value: number, precision?: ScientificDisplayPrecision): string {
  if (!Number.isFinite(value)) return "Unavailable";
  if (!precision) return String(value);
  if (precision.significantDigits !== undefined) {
    const digits = precision.significantDigits;
    if (!Number.isInteger(digits) || digits < 1 || digits > 100)
      throw new RangeError("Significant digits must be an integer from 1 to 100.");
    return value.toPrecision(digits);
  }
  const places = precision.decimalPlaces;
  if (!Number.isInteger(places) || places < 0 || places > 100)
    throw new RangeError("Decimal places must be an integer from 0 to 100.");
  const magnitude = Math.abs(value);
  if (magnitude > 0 && (magnitude < 10 ** -places || magnitude >= 1e21))
    return value.toExponential(places);
  return value.toFixed(places);
}
export const componentPercent = (value: number): string =>
  scientificNumber(value * 100, { decimalPlaces: 1 });
export const scoreGeometry = { scaleanchor: "x", scaleratio: 1, constrain: "range" };
export const componentOrientationNotice =
  "Component signs are fit-specific; compare paired scores/loadings from the same fit.";
export const scoreOrientationNotice = `Equal axis units. ${componentOrientationNotice}`;

/** Unknown physical semantics are disclosed; numerical zero is never called a physical baseline. */
export function matrixColorEncoding(matrix: unknown, semantics?: unknown) {
  const values = Array.isArray(matrix)
    ? matrix.flat().filter((x): x is number => typeof x === "number" && Number.isFinite(x))
    : [];
  let low = Infinity,
    high = -Infinity;
  for (const value of values) {
    low = Math.min(low, value);
    high = Math.max(high, value);
  }
  const signed = semantics === "signed_zero_centered" || low < 0;
  const span = Math.max(Math.abs(low), Math.abs(high));
  const magnitude = Number.isFinite(span) && span > 0 ? span : 1;
  const declared = semantics === "signed_zero_centered" || semantics === "nonnegative";
  const notice = signed
    ? `Symmetric color limits about numerical zero (±${scientificNumber(magnitude)}). ${declared ? "Declared value semantics." : "Physical baseline unspecified."}`
    : `Sequential color scale; limits follow this displayed matrix. ${declared ? "Declared nonnegative values." : "Physical baseline unspecified."}`;
  return {
    trace: signed
      ? { colorscale: "RdBu", zmid: 0, zmin: -magnitude, zmax: magnitude }
      : { colorscale: "Viridis" },
    notice,
    error: !values.length
      ? "No finite matrix values are available for color encoding."
      : semantics != null && !declared
        ? "Matrix value semantics are unsupported."
        : semantics === "nonnegative" && low < 0
          ? "Matrix contains negative values contrary to its declared nonnegative semantics."
          : null,
  };
}
export function encodingAnnotation(text: string) {
  return {
    text,
    x: 0,
    y: 1.14,
    xref: "paper",
    yref: "paper",
    xanchor: "left",
    yanchor: "bottom",
    showarrow: false,
    font: { size: 11, color: "#94a3b8" },
  };
}
