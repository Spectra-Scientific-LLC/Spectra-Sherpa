/** Visible selection context; never a substitute for a server-admitted binding. */
export function portfolioFieldLabel(value: unknown): string {
  return typeof value === "string"
    ? value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
    : "";
}

export function portfolioDetail(
  count: number | null,
  target: unknown,
  group: unknown,
): string {
  const files =
    count == null ? "All source files" : `${count} selected file${count === 1 ? "" : "s"}`;
  return [
    files,
    target ? `Target: ${portfolioFieldLabel(target)}` : "No target selected",
    group ? `Group: ${portfolioFieldLabel(group)}` : "No grouping",
  ].join(" · ");
}

/** Preserve both source and distinguishing revision suffix in a narrow tab. */
export function sheetTabLabel(name: string): string {
  const chars = Array.from(name);
  return chars.length > 32 ? `${chars.slice(0, 11).join("")}…${chars.slice(-20).join("")}` : name;
}
