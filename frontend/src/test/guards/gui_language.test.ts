import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * GUI language guards. Developer vocabulary must not return to GUI prose, and
 * toasts must answer something the user did, never announce a page load.
 * Prompts sent to the assistant are not GUI text and are exempt.
 */
const root = resolve(__dirname, "../..");
const EXEMPT = new Set(["stores/sherpa.ts", "utils/localDataStory.ts"]);
const BANNED = /\b(retained|Retained|portfolio|Portfolio|owner-scoped|navigation receipt|node contract)\b/;

function sources(folder: string): string[] {
  return readdirSync(folder, { withFileTypes: true }).flatMap((entry) => {
    const path = join(folder, entry.name);
    if (entry.isDirectory()) return ["test", "types", "api"].includes(entry.name) ? [] : sources(path);
    return /\.(vue|ts)$/.test(entry.name) ? [path] : [];
  });
}

/** Prose: quoted text with at least two spaces, and template text between tags. */
function prose(file: string, text: string): string[] {
  const found: string[] = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (/^(\/\/|\*|\/\*|<!--)/.test(trimmed)) continue;
    for (const match of line.matchAll(/(['"`])([^'"`\n]*?)\1/g)) {
      const body = match[2].replace(/\$\{[^}]*\}/g, "");
      if (body.split(" ").length > 2 && !/===|!==|=>|\?\s/.test(body)) found.push(body);
    }
    if (file.endsWith(".vue")) {
      for (const match of line.matchAll(/>([^<>{}]+)</g)) found.push(match[1]);
    }
  }
  return found;
}

describe("GUI language", () => {
  const files = sources(root).map((path) => ({ name: relative(root, path), text: readFileSync(path, "utf8") }));

  it("uses chemometric words, not developer vocabulary, in GUI prose", () => {
    const offenders = files
      .filter(({ name }) => !EXEMPT.has(name))
      .flatMap(({ name, text }) => prose(name, text).filter((line) => BANNED.test(line)).map((line) => `${name}: ${line.trim()}`));
    expect(offenders).toEqual([]);
  });

  it("never toasts a page or project load; the page itself shows what loaded", () => {
    const offenders = files.flatMap(({ name, text }) =>
      [...text.matchAll(/summary:\s*["'`]((?:Workbook|Project|Page|Data) Loaded)["'`]/g)].map((match) => `${name}: ${match[1]}`));
    expect(offenders).toEqual([]);
  });
});
