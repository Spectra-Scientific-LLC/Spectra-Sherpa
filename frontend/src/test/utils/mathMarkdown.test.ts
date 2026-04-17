import { describe, expect, it } from "vitest";

import { normalizeMathMarkdown } from "@/utils/mathMarkdown";

describe("normalizeMathMarkdown", () => {
  it("repairs missing underscore before braced subscripts inside display math", () => {
    const source =
      "Prediction: $$\\hat{\\mathbf{y}} = \\mathbf{x}{new} \\mathbf{B}{PLS}$$";

    expect(normalizeMathMarkdown(source)).toContain(
      "$$\\hat{\\mathbf{y}} = \\mathbf{x}_{new} \\mathbf{B}_{PLS}$$",
    );
  });

  it("repairs missing underscore before single-symbol subscripts inside display math", () => {
    const source =
      "Deflation: $$\\mathbf{X}_{a+1} = \\mathbf{X}_a - \\mathbf{t}_a \\mathbf{p}a^\\top$$";

    expect(normalizeMathMarkdown(source)).toContain(
      "$$\\mathbf{X}_{a+1} = \\mathbf{X}_a - \\mathbf{t}_a \\mathbf{p}_a^\\top$$",
    );
  });

  it("leaves non-math markdown untouched", () => {
    const source = "1. Setup\n\nX — an n × p data matrix";

    expect(normalizeMathMarkdown(source)).toBe(source);
  });
});
