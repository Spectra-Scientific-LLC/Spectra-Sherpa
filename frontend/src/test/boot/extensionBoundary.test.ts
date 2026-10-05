import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";

function productionSources(root: string): string[] {
  return readdirSync(root, { withFileTypes: true }).flatMap(entry => {
    const path = resolve(root, entry.name);
    if (entry.isDirectory()) {
      return entry.name === "test" ? [] : productionSources(path);
    }
    return /\.(ts|vue)$/.test(entry.name) ? [path] : [];
  });
}

describe("OSS extension boundary", () => {
  it("contains no commercial campaign routes, module URLs or API requests in production source", () => {
    const source = productionSources(resolve(process.cwd(), "src"))
      .map(path => readFileSync(path, "utf8"))
      .join("\n");
    for (const privateSurface of ["/hybrid/", "/config/activate-hybrid", "/config/deactivate-hybrid", "/config/spectrasherpa", "spectra-hybrid-advisor-context/1"]) {
      expect(source).not.toContain(privateSurface);
    }
    expect(source).not.toContain("/campaigns");
    expect(source).not.toContain("/ui/campaign.js");
    expect(source).not.toContain("/harness/canonical-campaigns");
  });
});
