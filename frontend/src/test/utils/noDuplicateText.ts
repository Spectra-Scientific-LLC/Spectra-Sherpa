import type { VueWrapper, DOMWrapper } from "@vue/test-utils";

/**
 * Sentences and labels that appear more than once on a mounted page. A page says
 * each fact once; repeated per-row values belong in a column header or summary.
 * Short tokens and numeric data values are ignored; so is text inside <details>
 * that is collapsed, which is a disclosure rather than a second statement.
 */
export function repeatedText(wrapper: VueWrapper | DOMWrapper<Element>, minLength = 12): string[] {
  const root = wrapper.element as Element;
  const seen = new Map<string, number>();
  const walker = root.ownerDocument.createTreeWalker(root, 4 /* NodeFilter.SHOW_TEXT */);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = (node.textContent ?? "").replace(/\s+/g, " ").trim();
    // Data values legitimately repeat; only words count.
    if (text.length < minLength || /^[-+−<>=±\d.,\s%eE]+$/.test(text)) continue;
    const closedDetails = node.parentElement?.closest("details:not([open])");
    if (closedDetails && !node.parentElement?.closest("summary")) continue;
    seen.set(text, (seen.get(text) ?? 0) + 1);
  }
  return [...seen].filter(([, count]) => count > 1).map(([text]) => text);
}
