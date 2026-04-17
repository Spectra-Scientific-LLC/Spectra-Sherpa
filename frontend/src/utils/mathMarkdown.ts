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
    /\\([A-Za-z]+)\{([^{}]+)\}([A-Za-z0-9])(?=[\^_])/g,
    (match, command: string, base: string, suffix: string) => {
      if (!SUBSCRIPTABLE_COMMANDS.has(command)) {
        return match;
      }
      return `\\${command}{${base}}_${suffix}`;
    },
  );

  return normalized;
}

export function normalizeMathMarkdown(source: string): string {
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
