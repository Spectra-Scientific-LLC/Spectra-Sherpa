import katex from "katex";

/**
 * Supplier-aware math markdown normalizer.
 *
 * The durable rule is:
 *   1. Detect candidate math emitted by a supplier.
 *   2. Apply a small set of targeted repairs.
 *   3. Only keep the repaired form when KaTeX can parse it.
 *
 * This avoids steadily expanding regex-only prose mutation.
 */

const TWO_ARG_COMMANDS = new Set([
  "frac",
  "dfrac",
  "tfrac",
  "cfrac",
  "binom",
  "dbinom",
  "tbinom",
  "overset",
  "underset",
  "stackrel",
  "xrightarrow",
  "xleftarrow",
]);

const SUBSCRIPTABLE_COMMANDS = new Set([
  "mathbf",
  "mathrm",
  "mathit",
  "mathsf",
  "mathtt",
  "boldsymbol",
  "hat",
  "tilde",
  "bar",
  "vec",
  "dot",
  "ddot",
  "check",
  "breve",
  "overline",
  "underline",
  "widehat",
  "widetilde",
  "text",
  "textbf",
  "textit",
  "textrm",
]);

const BIG_OPERATOR_PATTERN =
  "sum|prod|coprod|int|oint|iint|iiint|bigcup|bigcap|bigoplus|bigotimes|lim|limsup|liminf|max|min|sup|inf|arg\\\\s*min|arg\\\\s*max";

function canRenderMath(body: string, displayMode: boolean): boolean {
  try {
    katex.renderToString(body, {
      displayMode,
      throwOnError: true,
      strict: "ignore",
    });
    return true;
  } catch {
    return false;
  }
}

function looksLikeMathCandidate(body: string): boolean {
  return (
    /\\[A-Za-z]{2,}/.test(body) ||
    /[_^]/.test(body) ||
    /\{[^{}]*\}/.test(body) ||
    /=/.test(body) ||
    /\|{1,2}/.test(body)
  );
}

function hasRepairablePattern(body: string): boolean {
  return (
    /\\([A-Za-z]+)\{((?:[^{}]|\{[^{}]*\})+)\}\{((?:[^{}]|\\[A-Za-z]+\{[^{}]*\})+)\}/.test(
      body
    ) ||
    /\\([A-Za-z]+)\{([^{}]+)\}([A-Za-z0-9])(?=[\s=,\^_\\)}$]|$)/.test(body) ||
    new RegExp(String.raw`\\(${BIG_OPERATOR_PATTERN})\{([^{}]+)\}`).test(body) ||
    /(\|{1,2})([A-Za-z0-9])(\^)/.test(body)
  );
}

function normalizeLatexBody(body: string): string {
  let normalized = body;

  normalized = normalized.replace(
    /\\([A-Za-z]+)\{((?:[^{}]|\{[^{}]*\})+)\}\{((?:[^{}]|\\[A-Za-z]+\{[^{}]*\})+)\}/g,
    (match, command: string, base: string, suffix: string) => {
      if (TWO_ARG_COMMANDS.has(command)) return match;
      return `\\${command}{${base}}_{${suffix}}`;
    }
  );

  normalized = normalized.replace(
    /\\([A-Za-z]+)\{([^{}]+)\}([A-Za-z0-9])(?=[\s=,\^_\\)}$]|$)/g,
    (match, command: string, base: string, suffix: string) => {
      if (!SUBSCRIPTABLE_COMMANDS.has(command)) return match;
      return `\\${command}{${base}}_${suffix}`;
    }
  );

  normalized = normalized.replace(
    new RegExp(String.raw`\\(${BIG_OPERATOR_PATTERN})\{([^{}]+)\}`, "g"),
    (match, operator: string, limit: string, offset: number) => {
      if (offset > 0 && normalized[offset - 1] === "_") return match;
      return `\\${operator}_{${limit}}`;
    }
  );

  normalized = normalized.replace(
    /(\|{1,2})([A-Za-z0-9])(\^)/g,
    (match, pipes: string, indicator: string, caret: string, offset: number) => {
      if (offset > 0 && normalized[offset - 1] === "_") return match;
      return `${pipes}_${indicator}${caret}`;
    }
  );

  return normalized;
}

function repairMathBody(body: string, displayMode: boolean): string | null {
  const repaired = normalizeLatexBody(body);
  const originalValid = canRenderMath(body, displayMode);

  if (repaired === body) {
    return originalValid ? body : null;
  }

  if (hasRepairablePattern(body) && canRenderMath(repaired, displayMode)) {
    return repaired;
  }

  if (originalValid) {
    return body;
  }

  return canRenderMath(repaired, displayMode) ? repaired : null;
}

function normalizeDelimitedMath(source: string): string {
  let normalized = source;

  normalized = normalized.replace(/\$\$([\s\S]+?)\$\$/g, (_match, body: string) => {
    return `$$${repairMathBody(body, true) || body}$$`;
  });

  normalized = normalized.replace(/\\\[([\s\S]+?)\\\]/g, (_match, body: string) => {
    return `\\[${repairMathBody(body, true) || body}\\]`;
  });

  normalized = normalized.replace(/\\\(([\s\S]+?)\\\)/g, (_match, body: string) => {
    return `\\(${repairMathBody(body, false) || body}\\)`;
  });

  normalized = normalized.replace(/\$(?!\$)([^$\n]+?)\$(?!\$)/g, (_match, body: string) => {
    return `$${repairMathBody(body, false) || body}$`;
  });

  return normalized;
}

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
      const repaired =
        closed && body.length > 0 && looksLikeMathCandidate(body)
          ? repairMathBody(body, true)
          : null;

      if (closed && repaired) {
        out.push(`$$${repaired}$$`);
        i = j + 1;
        continue;
      }
    }

    out.push(lines[i]);
    i++;
  }

  return out.join("\n");
}

function wrapBareInlineExpressions(source: string): string {
  const mathPattern =
    /(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$[^$\n]+?\$)/g;
  const parts = source.split(mathPattern);

  const target = String.raw`(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}|\\[A-Za-z]+\{[^{}]*\}|[A-Za-z0-9+\-])`;
  const bareTokenRe = new RegExp(
    String.raw`(?<=\s|^|[,(])([A-Za-z](?:[_^]${target})+)(?=[\s.,;:)!?]|$)`,
    "g"
  );

  return parts
    .map((part) => {
      if (/^\$/.test(part) || /^\\\(/.test(part) || /^\\\[/.test(part)) {
        return part;
      }

      return part.replace(bareTokenRe, (match, token: string) => {
        if (!/[_^]/.test(token) || token.length > 40) {
          return match;
        }

        const repaired = repairMathBody(token, false);
        return repaired ? `$${repaired}$` : match;
      });
    })
    .join("");
}

function normalizeDeepSeekMath(source: string): string {
  return wrapBareInlineExpressions(convertBareBlockMath(source));
}

type SupplierNormalizer = (source: string) => string;

const SUPPLIER_NORMALIZERS: Record<string, SupplierNormalizer> = {
  deepseek: normalizeDeepSeekMath,
};

export function normalizeMathMarkdown(source: string, supplier?: string): string {
  let normalized = source;

  if (supplier) {
    const supplierNorm = SUPPLIER_NORMALIZERS[supplier];
    if (supplierNorm) {
      normalized = supplierNorm(normalized);
    }
  }

  return normalizeDelimitedMath(normalized);
}
