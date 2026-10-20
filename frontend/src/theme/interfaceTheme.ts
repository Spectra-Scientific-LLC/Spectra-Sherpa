import tokensCss from "@/assets/tokens.css?raw";

/** Canvas/SVG/standalone documents need resolved colors, not CSS var strings.
 * Read the same bundled authority as CSS; no DOM, network, or second palette. */
const tokens = new Map([...tokensCss.matchAll(/(--ss-[\w-]+)\s*:\s*([^;{}]+);/g)]
  .map((match) => [match[1], match[2].trim()]));

export function themeToken(name: string): string {
  const resolve = (key: string, seen: Set<string>): string => {
    if (seen.has(key)) throw new Error(`Cyclic theme token: ${key}`);
    const value = tokens.get(key);
    if (!value) throw new Error(`Unknown theme token: ${key}`);
    return value.replace(/var\((--ss-[\w-]+)\)/g, (_, ref: string) =>
      resolve(ref, new Set([...seen, key])));
  };
  return resolve(name.startsWith("--ss-") ? name : `--ss-${name}`, new Set());
}

/** Embedded in downloaded HTML so reports retain their theme while offline. */
export const standaloneThemeCss = tokensCss;
