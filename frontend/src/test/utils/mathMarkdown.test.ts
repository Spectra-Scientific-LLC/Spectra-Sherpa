import { describe, expect, it } from "vitest";

import { normalizeMathMarkdown } from "@/utils/mathMarkdown";

describe("normalizeMathMarkdown", () => {
  // ── Generic (all suppliers) ─────────────────────────────────────

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

  it("generic mode does not convert bare brackets", () => {
    const source = "Equation:\n[\nw_h = X_{h-1}^T y\n]\nDone.";

    // Without supplier, bare brackets are left alone
    expect(normalizeMathMarkdown(source)).toBe(source);
  });

  // ── DeepSeek supplier ───────────────────────────────────────────

  describe("supplier: deepseek", () => {
    const ds = "deepseek";

    // Bare-bracket display math

    it("converts bare-bracket display math to $$...$$ delimiters", () => {
      const source =
        "Weight vector:\n[\nw_h = X_{h-1}^T y_{h-1} / \\| X_{h-1}^T y_{h-1} \\|\n]\nThis is the direction.";

      const result = normalizeMathMarkdown(source, ds);
      expect(result).toContain("$$w_h = X_{h-1}^T y_{h-1}");
      expect(result).not.toContain("\n[\n");
    });

    it("converts multiple bare-bracket blocks in one string", () => {
      const source =
        "X-scores:\n[\nt_h = X_{h-1} w_h\n]\nY-loadings:\n[\nc_h = \\frac{y_{h-1}^T t_h}{t_h^T t_h}\n]\n";

      const result = normalizeMathMarkdown(source, ds);
      expect(result).toContain("$$t_h = X_{h-1} w_h$$");
      expect(result).toContain("$$c_h = \\frac{y_{h-1}^T t_h}{t_h^T t_h}$$");
    });

    it("leaves bare brackets alone when content is not LaTeX", () => {
      const source = "Some list:\n[\nitem one\nitem two\n]\nDone.";

      expect(normalizeMathMarkdown(source, ds)).toBe(source);
    });

    it("handles consecutive bare-bracket equations", () => {
      const source =
        "Deflation:\n[\nX_h = X_{h-1} - t_h p_h^T\n]\n[\ny_h = y_{h-1} - c_h t_h\n]\n";

      const result = normalizeMathMarkdown(source, ds);
      expect(result).toContain("$$X_h = X_{h-1} - t_h p_h^T$$");
      expect(result).toContain("$$y_h = y_{h-1} - c_h t_h$$");
    });

    it("does not match inline brackets in prose", () => {
      const source = "Use [this link](http://example.com) and [another].";

      expect(normalizeMathMarkdown(source, ds)).toBe(source);
    });

    // Dropped underscore repair

    it("repairs missing underscore before bare subscript followed by space", () => {
      const source =
        "$$\\mathbf{t}a = \\mathbf{X}{a-1} \\mathbf{w}_a$$";

      expect(normalizeMathMarkdown(source, ds)).toContain(
        "$$\\mathbf{t}_a = \\mathbf{X}_{a-1} \\mathbf{w}_a$$",
      );
    });

    it("repairs missing underscore in bare-bracket block after conversion", () => {
      const source =
        "Scores:\n[\n\\mathbf{t}a = \\mathbf{X}{a-1} \\mathbf{w}_a\n]\n";

      const result = normalizeMathMarkdown(source, ds);
      expect(result).toContain("$$\\mathbf{t}_a = \\mathbf{X}_{a-1} \\mathbf{w}_a$$");
    });

    // Bare inline variables

    it("wraps bare single uppercase letter on its own line in $...$", () => {
      const source =
        "But constraints are applied to\nC\nC after calculation (see below).";

      const result = normalizeMathMarkdown(source, ds);
      expect(result).toContain("$C$");
    });

    it("wraps multiple bare variables on separate lines", () => {
      const source = "We have:\nX\n(predictors) and\nY\n(responses).";

      const result = normalizeMathMarkdown(source, ds);
      expect(result).toContain("$X$");
      expect(result).toContain("$Y$");
    });

    it("does not wrap lowercase words or multi-char tokens", () => {
      const source = "The\ncat\nsat\non\nthe\nmat.";

      expect(normalizeMathMarkdown(source, ds)).toBe(source);
    });

    it("does not wrap single letter at start of document without context", () => {
      const source = "A";

      // Single letter with no surrounding prose — leave alone
      expect(normalizeMathMarkdown(source, ds)).toBe(source);
    });
  });

  // ── Unknown supplier (no-op pre-processing) ────────────────────

  describe("supplier: unknown", () => {
    it("applies only generic normalization", () => {
      const source =
        "$$\\mathbf{x}{new}$$ and [\nw_h = 1\n]";

      const result = normalizeMathMarkdown(source, "some-future-engine");
      // Generic fix applies to $$
      expect(result).toContain("$$\\mathbf{x}_{new}$$");
      // Bare brackets left alone (no supplier normalizer registered)
      expect(result).toContain("[\nw_h = 1\n]");
    });
  });
});
