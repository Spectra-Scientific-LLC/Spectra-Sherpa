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

  // --- Bare-bracket display math (DeepSeek pattern) ---

  it("converts bare-bracket display math to $$...$$ delimiters", () => {
    const source =
      "Weight vector:\n[\nw_h = X_{h-1}^T y_{h-1} / \\| X_{h-1}^T y_{h-1} \\|\n]\nThis is the direction.";

    const result = normalizeMathMarkdown(source);
    expect(result).toContain("$$w_h = X_{h-1}^T y_{h-1}");
    expect(result).toContain("$$");
    expect(result).not.toContain("\n[\n");
  });

  it("converts multiple bare-bracket blocks in one string", () => {
    const source =
      "X-scores:\n[\nt_h = X_{h-1} w_h\n]\nY-loadings:\n[\nc_h = \\frac{y_{h-1}^T t_h}{t_h^T t_h}\n]\n";

    const result = normalizeMathMarkdown(source);
    expect(result).toContain("$$t_h = X_{h-1} w_h$$");
    expect(result).toContain("$$c_h = \\frac{y_{h-1}^T t_h}{t_h^T t_h}$$");
  });

  it("leaves bare brackets alone when content is not LaTeX", () => {
    const source = "Some list:\n[\nitem one\nitem two\n]\nDone.";

    expect(normalizeMathMarkdown(source)).toBe(source);
  });

  it("handles multiline bare-bracket equations", () => {
    const source =
      "Deflation:\n[\nX_h = X_{h-1} - t_h p_h^T\n]\n[\ny_h = y_{h-1} - c_h t_h\n]\n";

    const result = normalizeMathMarkdown(source);
    expect(result).toContain("$$X_h = X_{h-1} - t_h p_h^T$$");
    expect(result).toContain("$$y_h = y_{h-1} - c_h t_h$$");
  });

  it("does not match inline brackets in prose", () => {
    const source = "Use [this link](http://example.com) and [another].";

    expect(normalizeMathMarkdown(source)).toBe(source);
  });
});
