import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import * as contract from "@/extension-contract/v1";
import { CONTEXTUAL_ACTIONS_VERSION } from "@/composables/useContextualActions";

describe("public frontend extension contract", () => {
  it("exports only the existing version handshake at runtime", () => {
    expect({ ...contract }).toEqual({
      EXTENSION_CONTRACT_VERSION: 1,
      CONTEXTUAL_ACTIONS_VERSION,
    });
  });

  it("depends only on type imports from public framework/client modules", () => {
    const path = resolve("src/extension-contract/v1.ts");
    const source = ts.createSourceFile(path, readFileSync(path, "utf8"), ts.ScriptTarget.Latest, true);
    const imports = source.statements.filter(ts.isImportDeclaration);
    expect(imports.length).toBeGreaterThan(0);
    for (const declaration of imports) {
      expect(declaration.importClause?.isTypeOnly).toBe(true);
      expect(["axios", "vue", "vue-router"]).toContain(
        (declaration.moduleSpecifier as ts.StringLiteral).text,
      );
    }
    expect(source.statements.filter(ts.isExportDeclaration)).toHaveLength(0);
  });

  it("typechecks host adapters and rejects invalid extension contributions", () => {
    const result = spawnSync(process.execPath, [
      resolve("node_modules/vue-tsc/bin/vue-tsc.js"),
      "--noEmit", "--project", "src/test/boot/tsconfig.extension-contract.json",
    ], { cwd: process.cwd(), encoding: "utf8", timeout: 60_000 });
    expect(result.status, `${result.error ?? ""}\n${result.stdout}\n${result.stderr}`).toBe(0);
  }, 60_000);
});
