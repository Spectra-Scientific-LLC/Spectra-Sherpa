const SUBSCRIPTABLE_COMMANDS = new Set([
  "mathbf",
  "mathrm",
  "mathit",
  "mathsf",
  "mathtt",
  "boldsymbol",
]);

function normalizeLatexBody(body: string): string {
  let normalized = body;

  normalized = normalized.replace(
    /\\([A-Za-z]+)\{([^{}]+)\}\{([^{}\\]+)\}/g,
    (match, command: string, base: string, suffix: string) => {
      if (!SUBSCRIPTABLE_COMMANDS.has(command)) {
        return match;
      }
      return `\\${command}{${base}}_{${suffix}}`;
    },
  );

  normalized = normalized.replace(
    /\\([A-Za-z]+)\{([^{}]+)\}([A-Za-z0-9])(?=[\s=,\^_\\)}$]|$)/g,
    (match, command: string, base: string, suffix: string) => {
      if (!SUBSCRIPTABLE_COMMANDS.has(command)) {
        return match;
      }
      return `\\${command}{${base}}_${suffix}`;
    },
  );

  return normalized;
}

/**
 * Detect whether a block of text looks like LaTeX math content.
 *
 * Checks for common LaTeX commands (`\frac`, `\mathbf`, …), operators
 * (`^`, `_`), and structural tokens (`{`, `}`) that wouldn't appear in
 * normal prose.
 */
function looksLikeLatex(text: string): boolean {
  // Backslash commands (\frac, \mathbf, \hat, …)
  if (/\\[A-Za-z]{2,}/.test(text)) return true;
  // Braced sub/superscripts: _{...} or ^{...}
  if (/[_^]\{/.test(text)) return true;
  // Bare sub/superscript with single token: x_h, t^T
  if (/[A-Za-z][_^][A-Za-z0-9]/.test(text)) return true;
  // Equals with surrounding identifiers (equation-like): X = T P^T
  if (/[A-Za-z]\s*=\s*[A-Za-z]/.test(text) && /[_^{}\\]/.test(text)) return true;
  return false;
}

/**
 * Convert bare-bracket display math blocks emitted by some LLM engines
 * (notably DeepSeek) into proper `$$…$$` delimiters that KaTeX can render.
 *
 * Matches a `[` on its own line, one or more lines of LaTeX-like content,
 * and a closing `]` on its own line.
 */
function normalizeBareBlockMath(source: string): string {
  // Split into lines so we can walk them and handle consecutive blocks.
  const lines = source.split("\n");
  const out: string[] = [];
  let i = 0;

  while (i < lines.length) {
    // Look for a line that is just `[` (with optional whitespace)
    if (/^\s*\[\s*$/.test(lines[i])) {
      // Collect body lines until we hit a closing `]` on its own line
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

export function normalizeMathMarkdown(source: string): string {
  let normalized = source;

  // --- Phase 1: recover bare-bracket display math ---
  normalized = normalizeBareBlockMath(normalized);

  // --- Phase 2: normalize LaTeX bodies inside known delimiters ---
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
