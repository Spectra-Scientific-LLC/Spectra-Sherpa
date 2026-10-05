/** Presentation fallback for retained replies from older servers/models. */
export function splitFollowUps(source: string): { text: string; suggestions: string[] } {
  const block = /(?:^|\n)\s*<follow_ups?>\s*([\s\S]*?)(?:<\/follow_ups?>\s*)?$/i.exec(source);
  if (!block) return { text: source, suggestions: [] };
  return {
    text: source.slice(0, block.index).trimEnd(),
    suggestions: block[1].split("\n").map((s) => s.replace(/^\s*(?:[-*]|\d+[.)])\s*/, "").trim())
      .filter(Boolean).slice(0, 3),
  };
}
