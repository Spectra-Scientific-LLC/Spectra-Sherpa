import { describe, expect, it, vi, beforeEach } from "vitest";
import { captureReportPlots } from "@/utils/captureReportPlots";
import { reportNodePlotsHtml, reportNodePlotsMarkdown } from "@/utils/reportNodePlots";
import { generateProvenanceReport, type ReportData } from "@/utils/reportGenerator";
import { generateMarkdownReport } from "@/utils/reportMarkdownGenerator";
import type { RunReportData } from "@/stores/report";
import api from "@/api/client";
vi.mock("@/api/client", () => ({ default: { get: vi.fn() } }));

function run(): RunReportData {
  return { id: 7, name: "Saved run", status: "completed", executed_at: null,
    results_summary: {}, diagnostics: {}, params_snapshot: {}, node_statuses: {}, integrity_hash: null, labels: [],
    saved_definition: { nodes: [{ node_id: "source", node_type: "data.file_load", label: "Input spectra", parameters: {}, position_x: 0, position_y: 0 }], edges: [] } };
}
beforeEach(() => vi.resetAllMocks());

describe("retained node report plots", () => {
  it("enumerates saved canonical presentations and names missing presentations", async () => {
    const saved = run();
    saved.saved_definition!.nodes[0].node_type = "model.fitted_pls";
    const contract = { contract_digest: "a".repeat(64), contract: {
      schema_version: "spectrasherpa-node-presentation/1", default_presentation: "variance",
      presentations: [
        { presentation_id: "variance", label: "Explained variance", kind: "pls_explained_variance", source_ports: ["explained_variance"], modes: ["plot"], description: "" },
        { presentation_id: "scores", label: "Scores", kind: "component_scores", source_ports: ["x_scores"], modes: ["plot"], description: "" },
      ],
    } };
    const evidence = { state: "exact", storage: "file", byte_count: 100 };
    vi.mocked(api.get).mockImplementation(async url => ({ data: String(url).endsWith("/evidence")
      ? { evidence: { outputs: { source: { explained_variance: evidence }, __diagnostics__: { _scientific_presentations: evidence } } } }
      : { value: String(url).endsWith("/_scientific_presentations") ? { source: contract } : [[0.6, 0.7], [0.2, 0.15]] },
    }));
    const render = vi.fn().mockResolvedValue("data:image/png;base64,AA==");
    const sections = await captureReportPlots(saved, 1, () => true, render);
    expect(render).toHaveBeenCalledTimes(1);
    expect(sections[0].plots[0].title).toContain("Explained variance");
    expect(sections[0].notices).toContain("Scores: required retained output is unavailable.");
  });
  it("captures multiple available plot types from exact saved outputs", async () => {
    vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).endsWith("/evidence")
      ? { evidence: { outputs: { source: { default: { state: "exact", storage: "file", byte_count: 100 } } } } }
      : { value: { type: "SherpaDataset", data: [[1, 2, 3], [3, 2, 1]], shape: [2, 3],
        x_axis: { data: [100, 200, 300], units: "nm", title: "Wavelength" }, metadata: { is_spectra: true } } },
    }));
    const render = vi.fn().mockResolvedValue("data:image/png;base64,AA==");
    const sections = await captureReportPlots(run(), 1, () => true, render);
    expect(sections[0].label).toBe("Input spectra");
    expect(render.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(sections[0].plots.some(plot => /heatmap/i.test(plot.title))).toBe(true);
    expect(api.get).toHaveBeenCalledWith("/runs/7/outputs/source/default", { params: { project_id: 1 } });
  });
  it("refuses missing or reduced evidence instead of using previews", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { evidence: { outputs: { source: { default: { state: "reduced", storage: "file", byte_count: 100 } } } } } });
    const render = vi.fn();
    const sections = await captureReportPlots(run(), 1, () => true, render);
    expect(render).not.toHaveBeenCalled();
    expect(sections[0].notices.join(" ")).toContain("exact retained output unavailable");
    expect(api.get).toHaveBeenCalledTimes(1);
  });
  it("does not consult the current canvas when a definition is missing", async () => {
    const saved = run(); saved.saved_definition = null;
    expect((await captureReportPlots(saved, 1, () => true))[0].notices[0]).toContain("current canvas plots were not substituted");
    expect(api.get).not.toHaveBeenCalled();
  });
  it.each(["summary", "detailed"] as const)("renders node sections and retained validation figures in %s exports", reportMode => {
    const saved = run();
    saved.node_plots = [{ node_id: "source", label: "Input spectra", node_type: "data.file_load", notices: [],
      plots: [{ title: "Data overlay", image: "data:image/png;base64,AA==" }, { title: "Heatmap", notice: "Missing axis" }] }];
    saved.validation_summary = { schema_version: "spectrasherpa-readable-validation/1", run_id: 7, rows: [], figures: [{
      state: "available", node_id: "cv", source_port: "oof_evidence", repeat_id: null,
      total_rows: 2, visible_rows: 2, observed: [1, 2], predicted: [1.1, 2.1], residual: [0.1, 0.1],
    }] };
    const data: ReportData = { reportMode, workflowName: "Test", workflowDescription: null, integrityHash: null,
      generatedAt: "today", nodes: [], edges: [], terminalMetrics: {}, plotImages: new Map(), runs: [saved] };
    for (const text of [generateProvenanceReport(data), generateMarkdownReport(data)]) {
      expect(text).toContain("Plots by node"); expect(text).toContain("Input spectra");
      expect(text).toContain("Data overlay"); expect(text).toContain("data:image/png;base64,AA==");
      expect(text).toContain("Missing axis"); expect(text).toContain("<svg");
    }
  });
  it("escapes captions and rejects external image URLs", () => {
    const saved = run();
    saved.node_plots = [{ node_id: "source", label: "<script>", node_type: "data.file_load", notices: [],
      plots: [{ title: "<script>", image: "https://example.com/tracker.png" }] }];
    expect(reportNodePlotsHtml(saved)).not.toContain("<script>");
    expect(reportNodePlotsHtml(saved)).not.toContain("tracker.png");
    expect(reportNodePlotsMarkdown(saved)).not.toContain("tracker.png");
  });
});
