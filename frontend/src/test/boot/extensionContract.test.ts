import { spawnSync } from "node:child_process";
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import * as contract from "@/extension-contract/v1";
import * as requests from "@/extension-contract/requests-v1";
import { useScopedRequest } from "@/composables/useScopedRequest";
import { CONTEXTUAL_ACTIONS_VERSION } from "@/composables/useContextualActions";

describe("public frontend extension contract", () => {
  it("exports only the existing version handshake at runtime", () => {
    expect({ ...contract }).toEqual({
      EXTENSION_CONTRACT_VERSION: 1,
      CONTEXTUAL_ACTIONS_VERSION,
    });
  });

  it("shares the exact request primitive, not a host-specific implementation", () => {
    expect({ ...requests }).toEqual({ REQUEST_SCOPE_CONTRACT_VERSION: 1, useScopedRequest });
  });

  it("keeps type contracts type-only and the pure request contract Vue-only", () => {
    const root = resolve("src/extension-contract");
    const files = readdirSync(root).filter(file => file.endsWith(".ts"));
    expect(files).toContain("v1.ts");
    for (const file of files) {
      const source = ts.createSourceFile(file, readFileSync(resolve(root, file), "utf8"), ts.ScriptTarget.Latest, true);
      for (const declaration of source.statements.filter(ts.isImportDeclaration)) {
        const module = (declaration.moduleSpecifier as ts.StringLiteral).text;
        if (file === "requests-v1.ts") {
          expect(module).toBe("vue");
          continue;
        }
        expect(declaration.importClause?.isTypeOnly).toBe(true);
        // Shared type modules stay inside the versioned contract; they cannot
        // reach host stores/configuration or create an implementation dependency.
        expect(["axios", "vue", "vue-router", ...files.map(name => `./${name.slice(0, -3)}`)]).toContain(module);
      }
      expect(source.statements.filter(ts.isExportDeclaration)).toHaveLength(0);
    }
  });

  it("typechecks host adapters and rejects invalid extension contributions", () => {
    const result = spawnSync(process.execPath, [
      resolve("node_modules/vue-tsc/bin/vue-tsc.js"),
      "--noEmit", "--project", "src/test/boot/tsconfig.extension-contract.json",
    ], { cwd: process.cwd(), encoding: "utf8", timeout: 60_000 });
    expect(result.status, `${result.error ?? ""}\n${result.stdout}\n${result.stderr}`).toBe(0);
  }, 60_000);
});
