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

    // Bare inline expressions with ^ or _

    it("wraps bare S^T in prose", () => {
      const source = "hold the spectral profiles S^T constant and solve";

      const result = normalizeMathMarkdown(source, ds);
      expect(result).toContain("$S^T$");
      expect(result).not.toContain(" S^T ");
    });

    it("wraps bare S^\\text{T} in prose", () => {
      const source = "if S^\\text{T} is known";

      const result = normalizeMathMarkdown(source, ds);
      expect(result).toContain("$S^\\text{T}$");
    });

    it("wraps bare p_h^T in prose", () => {
      const source = "the loading vector p_h^T is orthogonal";

      const result = normalizeMathMarkdown(source, ds);
      expect(result).toContain("$p_h^T$");
    });

    it("does not double-wrap tokens already inside $$", () => {
      const source = "$$X_h = X_{h-1} - t_h p_h^T$$";

      const result = normalizeMathMarkdown(source, ds);
      // Should NOT produce $$...$t_h$...$$
      expect(result).not.toMatch(/\$\$[^$]*\$[^$]+\$[^$]*\$\$/);
    });

    it("does not double-wrap tokens already inside $", () => {
      const source = "the matrix $S^T$ is transposed";

      expect(normalizeMathMarkdown(source, ds)).toBe(source);
    });

    // Dropped underscore with \text{...} suffix

    it("repairs \\mathbf{C}{\\text{new}} inside display math", () => {
      const source =
        "$$\\mathbf{C}{\\text{new}} = \\mathbf{C}{\\text{constrained}}$$";

      const result = normalizeMathMarkdown(source, ds);
      expect(result).toContain("\\mathbf{C}_{\\text{new}}");
      expect(result).toContain("\\mathbf{C}_{\\text{constrained}}");
    });

    // Nested braces in base (decorator + font command)

    it("repairs \\hat{\\mathbf{x}}{new,k} with nested braces in base", () => {
      const source =
        "$$\\hat{\\mathbf{x}}{new,k} = \\mathbf{t}{new,k} \\mathbf{P}_k^T$$";

      const result = normalizeMathMarkdown(source, ds);
      expect(result).toContain("\\hat{\\mathbf{x}}_{new,k}");
      expect(result).toContain("\\mathbf{t}_{new,k}");
    });

    it("does not insert _ in \\frac{a}{b}", () => {
      const source = "$$\\frac{a}{b} + \\binom{n}{k}$$";

      const result = normalizeMathMarkdown(source, ds);
      expect(result).toContain("\\frac{a}{b}");
      expect(result).toContain("\\binom{n}{k}");
    });

    // Inline subscript expressions in prose

    it("wraps bare A_k in prose", () => {
      const source = "retaining a small number A_k of principal components";

      const result = normalizeMathMarkdown(source, ds);
      expect(result).toContain("$A_k$");
    });

    it("wraps bare s_{new,k}^2 in prose", () => {
      const source = "We compare s_{new,k}^2 to the pooled variance";

      const result = normalizeMathMarkdown(source, ds);
      expect(result).toContain("$s_{new,k}^2$");
    });

    // Full bare-bracket block from SIMCA output

    it("handles SIMCA-style bare-bracket equation with nested commands", () => {
      const source =
        "The residual:\n[\n\\mathbf{e}{new,k} = \\mathbf{x}{new} - \\hat{\\mathbf{x}}{new,k}\n]\n";

      const result = normalizeMathMarkdown(source, ds);
      expect(result).toContain("$$");
      expect(result).toContain("\\mathbf{e}_{new,k}");
      expect(result).toContain("\\mathbf{x}_{new}");
      expect(result).toContain("\\hat{\\mathbf{x}}_{new,k}");
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
