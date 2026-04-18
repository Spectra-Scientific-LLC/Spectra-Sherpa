/**
 * Supplier-aware math markdown normalizer.
 *
 * Different LLM engines emit math notation with different quirks.
 * This module provides a generic normalization pipeline plus
 * per-supplier pre-processing passes that convert engine-specific
 * patterns into standard delimited LaTeX before KaTeX rendering.
 *
 * To add support for a new engine:
 *   1. Write a `normalize<Engine>Math(source)` function.
 *   2. Register it in `SUPPLIER_NORMALIZERS`.
 *   3. Add tests in mathMarkdown.test.ts.
 */

// ── Shared helpers ──────────────────────────────────────────────────

/**
 * Commands that legitimately take two brace-group arguments.
 * Pattern A must NOT insert `_` between their arguments.
 */
const TWO_ARG_COMMANDS = new Set([
  "frac", "dfrac", "tfrac", "cfrac",
  "binom", "dbinom", "tbinom",
  "overset", "underset", "stackrel",
  "xrightarrow", "xleftarrow",
]);

/**
 * Font/decorator commands where a trailing bare character (Pattern B)
 * is almost certainly a dropped subscript.
 */
const SUBSCRIPTABLE_COMMANDS = new Set([
  "mathbf", "mathrm", "mathit", "mathsf", "mathtt", "boldsymbol",
  "hat", "tilde", "bar", "vec", "dot", "ddot", "check", "breve",
  "overline", "underline", "widehat", "widetilde",
  "text", "textbf", "textit", "textrm",
]);

/**
 * Detect whether a block of text looks like LaTeX math content.
 */
function looksLikeLatex(text: string): boolean {
  if (/\\[A-Za-z]{2,}/.test(text)) return true;
  if (/[_^]\{/.test(text)) return true;
  if (/[A-Za-z][_^][A-Za-z0-9]/.test(text)) return true;
  if (/[A-Za-z]\s*=\s*[A-Za-z]/.test(text) && /[_^{}\\]/.test(text)) return true;
  return false;
}

// ── Generic normalization (all suppliers) ────────────────────────────

/**
 * Fix malformed subscript patterns inside already-delimited LaTeX.
 *
 * Handles two DeepSeek-originated patterns that can appear from any engine:
 *   \mathbf{X}{a-1}  →  \mathbf{X}_{a-1}   (braced suffix)
 *   \mathbf{t}a      →  \mathbf{t}_a        (bare suffix)
 */
function normalizeLatexBody(body: string): string {
  let normalized = body;

  // Pattern A: \cmd{base}{suffix} — two consecutive brace groups.
  // Base may contain nested braces (e.g. \hat{\mathbf{x}}{new,k}).
  // Suffix may contain \text{...} commands (e.g. \mathbf{C}{\text{new}}).
  // We EXCLUDE known two-argument commands (\frac, \binom, etc.)
  // rather than maintaining a whitelist of subscriptable ones.
  normalized = normalized.replace(
    /\\([A-Za-z]+)\{((?:[^{}]|\{[^{}]*\})+)\}\{((?:[^{}]|\\[A-Za-z]+\{[^{}]*\})+)\}/g,
    (match, command: string, base: string, suffix: string) => {
      if (TWO_ARG_COMMANDS.has(command)) return match;
      return `\\${command}{${base}}_{${suffix}}`;
    },
  );

  // Pattern B: \cmd{base}X — bare character after brace group
  normalized = normalized.replace(
    /\\([A-Za-z]+)\{([^{}]+)\}([A-Za-z0-9])(?=[\s=,\^_\\)}$]|$)/g,
    (match, command: string, base: string, suffix: string) => {
      if (!SUBSCRIPTABLE_COMMANDS.has(command)) return match;
      return `\\${command}{${base}}_${suffix}`;
    },
  );

  // Pattern C: \operator{limit} — big operators missing _ before limit.
  // e.g. \sum{j=1} → \sum_{j=1}, \prod{i} → \prod_{i}
  // Only triggers for known limit operators, and only when no _ precedes {.
  normalized = normalized.replace(
    /\\(sum|prod|coprod|int|oint|iint|iiint|bigcup|bigcap|bigoplus|bigotimes|lim|limsup|liminf|max|min|sup|inf|arg\s*min|arg\s*max)\{([^{}]+)\}/g,
    (match, operator: string, limit: string, offset: number) => {
      // Check the character before the match — if it's already _, skip
      if (offset > 0 && normalized[offset - 1] === "_") return match;
      return `\\${operator}_{${limit}}`;
    },
  );

  return normalized;
}

/**
 * Normalize LaTeX bodies inside all standard math delimiters.
 * Runs after any supplier-specific pre-processing.
 */
function normalizeDelimitedMath(source: string): string {
  let normalized = source;

  normalized = normalized.replace(/\$\$([\s\S]+?)\$\$/g, (_match, body: string) => {
    return `$$${normalizeLatexBody(body)}$$`;
  });

  normalized = normalized.replace(/\\\[([\s\S]+?)\\\]/g, (_match, body: string) => {
    return `\\[${normalizeLatexBody(body)}\\]`;
  });

  normalized = normalized.replace(/\\\(([\s\S]+?)\\\)/g, (_match, body: string) => {
    return `\\(${normalizeLatexBody(body)}\\)`;
  });

  normalized = normalized.replace(/\$(?!\$)([^$\n]+?)\$(?!\$)/g, (_match, body: string) => {
    return `$${normalizeLatexBody(body)}$`;
  });

  return normalized;
}

// ── DeepSeek normalizer ─────────────────────────────────────────────
//
// DeepSeek quirks observed:
//   1. Display math uses bare [ / ] on own lines instead of $$ or \[
//   2. Drops `_` between font commands and subscripts (\mathbf{t}a)
//   3. Emits bare single-letter variables without $ delimiters in prose
//      (e.g. "applied to \nC\nC after calculation")
//
// Quirk 2 is handled generically by normalizeLatexBody (Pattern B).
// Quirks 1 and 3 are DeepSeek-specific pre-processing below.

/**
 * Convert bare-bracket display math blocks into `$$…$$`.
 *
 * Matches `[` on its own line, LaTeX body lines, `]` on its own line.
 */
function convertBareBlockMath(source: string): string {
  const lines = source.split("\n");
  const out: string[] = [];
  let i = 0;

  while (i < lines.length) {
    if (/^\s*\[\s*$/.test(lines[i])) {
      const bodyLines: string[] = [];
      let j = i + 1;
      let closed = false;
      while (j < lines.length) {
        if (/^\s*\]\s*$/.test(lines[j])) {
          closed = true;
          break;
        }
        bodyLines.push(lines[j]);
        j++;
      }
      const body = bodyLines.join("\n").trim();
      if (closed && body.length > 0 && looksLikeLatex(body)) {
        out.push(`$$${body}$$`);
        i = j + 1;
        continue;
      }
    }
    out.push(lines[i]);
    i++;
  }

  return out.join("\n");
}

/**
 * Wrap bare single-letter math variables that DeepSeek leaves undelimited.
 *
 * DeepSeek often emits a line like:
 *   "constraints are applied to \n$C$\nC after calculation"
 * where the first $C$ renders but the second bare C does not. It also
 * produces patterns where a variable stands alone on its own line
 * between prose lines.
 *
 * Strategy: find isolated single uppercase letters (or very short
 * LaTeX-like tokens) on their own line that sit between prose lines
 * and wrap them in $…$. This is intentionally conservative.
 */
function wrapBareInlineVars(source: string): string {
  const lines = source.split("\n");
  const out: string[] = [];

  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();

    // Single uppercase letter alone on a line (e.g. "C", "X", "Y")
    // between non-empty prose lines
    if (/^[A-Z]$/.test(trimmed)) {
      const prevLine = i > 0 ? lines[i - 1].trim() : "";
      const nextLine = i < lines.length - 1 ? lines[i + 1].trim() : "";
      const prevIsProse = prevLine.length > 0 && !/^\$/.test(prevLine) && !/^\[/.test(prevLine);
      const nextIsProse = nextLine.length > 0 && !/^\$/.test(nextLine) && !/^\]/.test(nextLine);

      if (prevIsProse || nextIsProse) {
        out.push(`$${trimmed}$`);
        continue;
      }
    }

    out.push(lines[i]);
  }

  return out.join("\n");
}

/**
 * Wrap bare inline math expressions that DeepSeek leaves undelimited.
 *
 * DeepSeek often drops `$` around short expressions containing `^`, `_`,
 * or LaTeX commands, e.g.:
 *   "hold S^T constant"        → "hold $S^T$ constant"
 *   "pseudoinverse ( )^+"      → left alone (too ambiguous)
 *   "E = D - C S^T"            → left alone (multi-token equation)
 *
 * Strategy: split the source on existing math delimiters so we only
 * process prose segments. In those segments, find tokens containing
 * `^` or `_` that look like single math identifiers and wrap in $…$.
 */
function wrapBareInlineExpressions(source: string): string {
  // Split on $$ … $$, \[ … \], \( … \), and $ … $ to isolate prose
  const mathPattern = /(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$[^$\n]+?\$)/g;
  const parts = source.split(mathPattern);

  // Superscript/subscript target: braced group, \cmd{...}, or single char
  const target = String.raw`(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}|\\[A-Za-z]+\{[^{}]*\}|[A-Za-z0-9+\-])`;
  // Full token: letter followed by one or more ^target or _target
  const bareTokenRe = new RegExp(
    String.raw`(?<=\s|^|[,(])([A-Za-z](?:[_^]${target})+)(?=[\s.,;:)!?]|$)`,
    "g",
  );

  return parts
    .map((part) => {
      // If this part is a math delimiter region, pass through unchanged
      if (/^\$/.test(part) || /^\\\(/.test(part) || /^\\\[/.test(part)) {
        return part;
      }
      // Prose segment: wrap bare math tokens
      return part.replace(bareTokenRe, (match, token: string) => {
        if (!/[_^]/.test(token)) return match;
        if (token.length > 40) return match;
        return `$${token}$`;
      });
    })
    .join("");
}

function normalizeDeepSeekMath(source: string): string {
  let normalized = source;
  normalized = convertBareBlockMath(normalized);
  normalized = wrapBareInlineVars(normalized);
  normalized = wrapBareInlineExpressions(normalized);
  return normalized;
}

// ── Supplier dispatch ───────────────────────────────────────────────

type SupplierNormalizer = (source: string) => string;

/**
 * Registry of supplier-specific normalizers.
 *
 * Keys are the `provider` values from LlmConfig (as returned by the
 * /config endpoint). To add a new engine, register its normalizer here.
 */
const SUPPLIER_NORMALIZERS: Record<string, SupplierNormalizer> = {
  deepseek: normalizeDeepSeekMath,
};

/**
 * Normalize math markdown for KaTeX rendering.
 *
 * @param source   Raw markdown from the LLM.
 * @param supplier LLM provider key (e.g. "deepseek", "openai").
 *                 When supplied, engine-specific pre-processing runs
 *                 before the generic delimiter normalization.
 */
export function normalizeMathMarkdown(source: string, supplier?: string): string {
  let normalized = source;

  // Phase 1: supplier-specific pre-processing
  if (supplier) {
    const supplierNorm = SUPPLIER_NORMALIZERS[supplier];
    if (supplierNorm) {
      normalized = supplierNorm(normalized);
    }
  }

  // Phase 2: generic delimiter normalization (all suppliers)
  normalized = normalizeDelimitedMath(normalized);

  return normalized;
}
