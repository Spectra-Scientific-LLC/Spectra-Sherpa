/** Draw only retained, explicitly scoped points. No inference, filtering or pooling. */
export interface ValidationFigure {
  state: string;
  reason?: string;
  node_id: string;
  source_port: string;
  repeat_id: number | null;
  total_rows: number;
  visible_rows?: number;
  units?: string;
  scope?: string;
  observed?: number[];
  predicted?: number[];
  residual?: number[];
}
const escape = (s: unknown) =>
  String(s).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!,
  );

export function validationFigureSvg(figure: ValidationFigure): string {
  const x = figure.observed,
    predicted = figure.predicted,
    residual = figure.residual;
  if (
    figure.state !== "available" ||
    !x ||
    !predicted ||
    !residual ||
    x.length === 0 ||
    x.length > 5000 ||
    x.length !== predicted.length ||
    x.length !== residual.length ||
    x.length !== figure.total_rows ||
    figure.visible_rows !== figure.total_rows ||
    ![...x, ...predicted, ...residual].every(Number.isFinite)
  )
    return "";
  const panel = (y: number[], offset: number, label: string) => {
    const xmin = Math.min(...x),
      xmax = Math.max(...x),
      ymin = Math.min(...y),
      ymax = Math.max(...y);
    const scale = (v: number, low: number, high: number) => {
      if (high === low) return 0.5;
      const magnitude = Math.max(Math.abs(low), Math.abs(high), Number.MIN_VALUE);
      return (v / magnitude - low / magnitude) / (high / magnitude - low / magnitude);
    };
    const circles = x
      .map(
        (v, i) =>
          `<circle cx="${offset + 45 + scale(v, xmin, xmax) * 285}" cy="${220 - scale(y[i], ymin, ymax) * 175}" r="2" fill="#2563eb" opacity="0.65"/>`,
      )
      .join("");
    return (
      `<path d="M${offset + 45},40 V220 H${offset + 330}" fill="none" stroke="#444"/>${circles}` +
      `<text x="${offset + 45}" y="25">${label}</text><text x="${offset + 45}" y="245">Reference (${escape(xmin)} to ${escape(xmax)})</text>` +
      `<text x="${offset + 45}" y="265">Y range: ${escape(ymin)} to ${escape(ymax)}</text>`
    );
  };
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 305" role="img" aria-label="Retained CV predictions and residuals">` +
    `<rect width="760" height="305" fill="white"/><g font-size="11" fill="#222">` +
    panel(predicted, 0, "Predicted versus reference") +
    panel(residual, 380, "Residual (prediction minus reference)") +
    `<text x="45" y="290">${escape(figure.units ?? "Units not recorded")}</text></g></svg>`
  );
}

export function validationFigureCaption(figure: ValidationFigure): string {
  if (figure.state === "available" && !validationFigureSvg(figure)) {
    return `${figure.node_id}/${figure.source_port}: Figure unavailable because retained rows are nonfinite, inconsistent, or exceed the display limit. No rows were silently dropped.`;
  }
  return (
    `${figure.node_id}/${figure.source_port}; repeat ${figure.repeat_id ?? "single"}; ` +
    `${figure.visible_rows ?? 0}/${figure.total_rows} rows shown; ${figure.scope ?? figure.reason ?? "scope unavailable"}`
  );
}
