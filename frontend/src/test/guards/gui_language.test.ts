import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * GUI language guards. Developer vocabulary must not return to GUI prose, and
 * toasts must answer something the user did, never announce a page load.
 * Prompts sent to the assistant are not GUI text and are exempt.
 */
const root = resolve(__dirname, "../..");
function sources(folder: string): string[] {
  return readdirSync(folder, { withFileTypes: true }).flatMap((entry) => {
    const path = join(folder, entry.name);
    if (entry.isDirectory()) return ["test", "types", "api"].includes(entry.name) ? [] : sources(path);
    return /\.(vue|ts)$/.test(entry.name) ? [path] : [];
  });
}

describe("GUI language", () => {
  const files = sources(root).map((path) => ({ name: relative(root, path), text: readFileSync(path, "utf8") }));

  it("uses chemometric words, not developer vocabulary, in GUI prose", () => {
    expect(() => execFileSync("python3", [resolve(root, "../../scripts/check_user_copy.py")], {
      encoding: "utf8",
    })).not.toThrow();
  });

  it("never toasts a page or project load; the page itself shows what loaded", () => {
    const offenders = files.flatMap(({ name, text }) =>
      [...text.matchAll(/summary:\s*["'`]((?:Workbook|Project|Page|Data) Loaded)["'`]/g)].map((match) => `${name}: ${match[1]}`));
    expect(offenders).toEqual([]);
  });
});
