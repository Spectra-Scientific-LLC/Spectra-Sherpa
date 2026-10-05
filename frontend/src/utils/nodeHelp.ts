const DOCS_BASE_URL = "https://docs.spectrascientific.ai/";
const NODE_HELP_REFERENCE = /^docs\/nodes\/(?:[a-z0-9][a-z0-9-]*\/)*[a-z0-9][a-z0-9-]*\.md$/;

/**
 * Project a qualified node contract's repository help path onto public docs.
 *
 * The execution contract remains the sole authority. External URLs, traversal,
 * mixed-case aliases, query strings, fragments, and non-node docs fail closed.
 */
export const resolveNodeHelpUrl = (reference: unknown): string | null => {
  if (typeof reference !== "string" || !NODE_HELP_REFERENCE.test(reference)) return null;
  const docsPath = reference.slice("docs/".length, -".md".length);
  return `${DOCS_BASE_URL}${docsPath}/`;
};
