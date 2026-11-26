/** Inert display projection. Numeric lexemes stay exact; original JSON is retained separately. */
export const RETAINED_DISPLAY_CHAR_LIMIT = 64 * 1024;

export function retainedJsonForDisplay(source: string): unknown {
  if (source.length > RETAINED_DISPLAY_CHAR_LIMIT) throw new Error("Saved value exceeds display limits");
  const projected = source.replace(
    /"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g,
    token => token.startsWith('"') ? token : JSON.stringify(token),
  );
  return JSON.parse(projected) as unknown;
}
