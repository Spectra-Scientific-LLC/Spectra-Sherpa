/** Numeric drafts must never become a different number through formatting. */
export type ScientificNumberValue = number | string | null;

// Decimal notation only: Number() alone would also accept hex and whitespace.
const decimal = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;

function canonicalDecimal(text: string): string {
  const [mantissa, exponent = "0"] = text.toLowerCase().split("e");
  const negative = mantissa.startsWith("-");
  const unsigned = mantissa.replace(/^[+-]/, "");
  const [whole, fraction = ""] = unsigned.split(".");
  let digits = (whole + fraction).replace(/^0+/, "");
  if (!digits) return "0";
  let power = BigInt(exponent) - BigInt(fraction.length);
  const trailing = digits.match(/0+$/)?.[0].length ?? 0;
  if (trailing) {
    digits = digits.slice(0, -trailing);
    power += BigInt(trailing);
  }
  return `${negative ? "-" : ""}${digits}e${power}`;
}

export function parseScientificNumber(text: string): {
  value: ScientificNumberValue;
  error: string | null;
} {
  const trimmed = text.trim();
  if (!trimmed) return { value: null, error: null };
  if (!decimal.test(trimmed)) {
    return { value: text, error: "Enter a complete decimal number (for example 0.5 or 1e-6)." };
  }
  const value = Number(trimmed);
  if (!Number.isFinite(value)) {
    return { value: text, error: "This value is outside the supported finite numeric range." };
  }
  // Check the decimal round trip, not binary equality (which would reject 0.1).
  // Refuse lost digits and underflow rather than quietly saving another value.
  if (canonicalDecimal(trimmed) !== canonicalDecimal(String(value))) {
    return {
      value: text,
      error:
        "This value cannot be stored without rounding. Enter a representable value explicitly.",
    };
  }
  return { value, error: null };
}

export function numericRangeError(
  value: ScientificNumberValue,
  min?: number | null,
  max?: number | null,
): string | null {
  if (typeof value !== "number") return null;
  if (min != null && value < min)
    return `Must be ≥ ${min}. The entered value has not been changed.`;
  if (max != null && value > max)
    return `Must be ≤ ${max}. The entered value has not been changed.`;
  return null;
}
