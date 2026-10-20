import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { execFileSync, spawnSync } from "node:child_process";
import ts from "typescript";
import baseline from "@/api/adapters/legacy-boundaries.json";
import boundaryFiles from "@/api/adapters/boundary-files.json";

const root = process.cwd();

function containsObjectLiteral(node: ts.Node): boolean {
  return ts.isTypeLiteralNode(node) || Boolean(ts.forEachChild(node, containsObjectLiteral));
}

function declarationCounts(text: string): number[] {
  const source = ts.createSourceFile("boundary.ts", text, ts.ScriptTarget.Latest, true);
  const counts = [0, 0, 0];
  function visit(node: ts.Node): void {
    if (ts.isInterfaceDeclaration(node)) counts[0]++;
    if (ts.isTypeAliasDeclaration(node) && containsObjectLiteral(node.type)) counts[1]++;
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)
      && node.expression.expression.getText(source) === "api"
      && node.typeArguments?.some(containsObjectLiteral)) counts[2]++;
    ts.forEachChild(node, visit);
  }
  visit(source);
  return counts;
}

function sourceFiles(directory: string): string[] {
  return fs.readdirSync(path.join(root, directory), { withFileTypes: true }).flatMap((entry) => {
    const relative = `${directory}/${entry.name}`;
    if (entry.isDirectory()) return sourceFiles(relative);
    return relative.endsWith(".ts") ? [relative] : [];
  });
}

describe("public transport migration ratchet", () => {
  it("requires review for new boundary files and object aliases, not only named interfaces", () => {
    const files = ["src/api", "src/stores", "src/types", "src/extension-contract"].flatMap(sourceFiles)
      .filter((file) => !boundaryFiles.generated.includes(file));
    const reviewed: Record<string, number[]> = boundaryFiles.files;
    expect(files.filter((file) => !(file in reviewed)), "New boundary files require an explicit view-model/transport review.").toEqual([]);
    for (const file of files) {
      const actual = declarationCounts(fs.readFileSync(path.join(root, file), "utf8"));
      actual.forEach((count, index) => {
        expect(count, `${file}: ${boundaryFiles.counts_order[index]} grew; derive transport fields or review the view-model allowance.`)
          .toBeLessThanOrEqual(reviewed[file][index]);
      });
    }
  });

  it("counts alias and inline-generic evasions as handwritten boundaries", () => {
    expect(declarationCounts("interface A { name: string }; type B = { id: number }; api.get<{ data: string }>('x')"))
      .toEqual([1, 1, 1]);
    expect(declarationCounts('type B = components["schemas"]["RunPage"]; api.get<components["schemas"]["RunPage"]>("x")'))
      .toEqual([0, 0, 0]);
  });

  for (const [file, admitted] of Object.entries(baseline.files)) {
    it(`does not grow handwritten interface declarations in ${file}`, () => {
      const source = ts.createSourceFile(file, fs.readFileSync(path.join(root, file), "utf8"), ts.ScriptTarget.Latest, true);
      const names = source.statements.filter(ts.isInterfaceDeclaration).map((node) => node.name.text);
      expect(names.filter((name) => !admitted.includes(name)), "Derive API fields from generated components; review true view models explicitly.").toEqual([]);
      expect(names.length).toBeLessThanOrEqual(admitted.length);
    });
  }

  it("keeps generated boundaries on the four consumer stores", () => {
    const required = {
      "src/stores/workflow.ts": ["WorkflowDetail", "WorkflowSummary", "WorkflowValidationResponse", "workflowListItem", "workflowCreate"],
      "src/stores/data.ts": ["ExperimentSummary", "ExperimentFileOut", "ExperimentFileAssetsOut", "experimentFileAssets"],
      "src/stores/runs.ts": ["ExecutionRunList", "ExecutionRunOut", "RunPage", "SaveRunRequest", "BatchPredictionList", "runSummary"],
      "src/stores/deploy.ts": ["FolderWatchCreate", "FolderWatchUpdate", "FolderWatchOut", "ExecutionRunList", "folderWatch"],
    };
    for (const [file, names] of Object.entries(required)) {
      const source = fs.readFileSync(path.join(root, file), "utf8");
      expect(source).toContain('from "@/types/api/v1"');
      for (const name of names) expect(source).toContain(name);
    }
  });

  it("checks both projections without rewriting either file", () => {
    const outputs = ["src/types/api-generated.ts", "src/types/api/v1.ts"];
    const before = outputs.map((file) => ({
      text: fs.readFileSync(path.join(root, file), "utf8"),
      modified: fs.statSync(path.join(root, file)).mtimeMs,
    }));
    execFileSync(process.execPath, ["scripts/generate-api-types.mjs", "--check"], { cwd: root });
    outputs.forEach((file, index) => {
      expect(fs.readFileSync(path.join(root, file), "utf8")).toBe(before[index].text);
      expect(fs.statSync(path.join(root, file)).mtimeMs).toBe(before[index].modified);
    });
  });

  it("fails for a stale projection and leaves both outputs untouched", () => {
    // A disposable sibling keeps normal Node dependency resolution on Windows too.
    const fixtureRoot = fs.mkdtempSync(path.join(root, ".api-transport-check-"));
    try {
      fs.mkdirSync(path.join(fixtureRoot, "scripts"));
      fs.mkdirSync(path.join(fixtureRoot, "contracts"));
      fs.copyFileSync(path.join(root, "scripts/generate-api-types.mjs"), path.join(fixtureRoot, "scripts/generate-api-types.mjs"));
      const schema = {
        openapi: "3.1.0", info: { title: "Transport check fixture", version: "1" }, paths: {},
        components: { schemas: { State: { type: "string", enum: ["ready", "unavailable"] } } },
      };
      for (const file of ["openapi-v1.json", "openapi-llm-v1.json"]) {
        fs.writeFileSync(path.join(fixtureRoot, "contracts", file), JSON.stringify(schema));
      }
      execFileSync(process.execPath, ["scripts/generate-api-types.mjs"], { cwd: fixtureRoot });
      const stale = path.join(fixtureRoot, "src/types/api/v1.ts");
      fs.appendFileSync(stale, "\n// stale\n");
      const files = [stale, path.join(fixtureRoot, "src/types/api-generated.ts")];
      const before = files.map((file) => ({ text: fs.readFileSync(file, "utf8"), mtime: fs.statSync(file).mtimeMs }));
      const result = spawnSync(process.execPath, ["scripts/generate-api-types.mjs", "--check"], { cwd: fixtureRoot, encoding: "utf8" });
      expect(result.status).toBe(1);
      expect(result.stderr).toContain("npm run generate:types");
      files.forEach((file, index) => {
        expect(fs.readFileSync(file, "utf8")).toBe(before[index].text);
        expect(fs.statSync(file).mtimeMs).toBe(before[index].mtime);
      });
    } finally {
      fs.rmSync(fixtureRoot, { recursive: true, force: true });
    }
  });

  it("type-checks representative adapter fixtures against the generated schema", () => {
    const config = ts.readConfigFile(path.join(root, "tsconfig.json"), ts.sys.readFile);
    const parsed = ts.parseJsonConfigFileContent({
      ...config.config,
      include: ["src/test/api_transport_adapters.test.ts"],
      exclude: [],
      compilerOptions: { ...config.config.compilerOptions, noEmit: true },
    }, ts.sys, root);
    const program = ts.createProgram(parsed.fileNames, parsed.options);
    const diagnostics = ts.getPreEmitDiagnostics(program);
    expect(diagnostics.map((error) => ts.flattenDiagnosticMessageText(error.messageText, "\n"))).toEqual([]);
  }, 20000);
});
