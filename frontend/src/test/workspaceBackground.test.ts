// Node-only source contract test; keep it in the host's test-only tree.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("workbench canvas background", () => {
  it("shares one token between the host workspace tabs", () => {
    const css = readFileSync(resolve("src/assets/main.css"), "utf8");
    expect(css).toContain("--workspace-background: #e4e0fa;");
    for (const view of ["data/DataContent", "models/ModelsContent", "workflow-builder/WorkflowBuilderContent"]) {
      const source = readFileSync(resolve(`src/views/${view}.vue`), "utf8");
      expect(source).toContain("background: var(--workspace-background);");
    }
  });
});
