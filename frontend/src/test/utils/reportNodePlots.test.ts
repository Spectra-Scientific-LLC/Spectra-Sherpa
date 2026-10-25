import { describe, expect, it, vi, beforeEach } from "vitest";
import { captureReportPlots, reportGroupKey, reportPopulationCaption, reportComparisonCaptions } from "@/utils/captureReportPlots";
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
  it("preserves panel refusal and population evidence without row identities", () => {
    expect(reportComparisonCaptions({ comparison_populations: {
      original: null, preprocessed: { shown: 3, total: 150, sample_labels: ["not a caption"] },
    }, comparison_refusals: ["Original input unavailable."] })).toEqual([
      "preprocessed: Subset: 3 of 150 active rows.", "Original input unavailable.",
    ]);
  });
  it("summarizes population counts without dumping retained row identities", () => {
    expect(reportPopulationCaption({ shown: 50, total: 150, excluded: 1, row_ids: ["private-identity"], indices: [1, 2] }))
      .toBe("Subset: 50 of 150 active rows; 1 row excluded.");
    expect(reportPopulationCaption({ shown: 151, total: 150 })).toBe("Display population unavailable.");
    expect(reportPopulationCaption({ shown: 150, total: 150 })).toBe("150 of 150 active rows.");
  });
  it('retains feature exclusions and one shared color qualifier without verbose notices or identities', () => {
    const population = { shown: 50, total: 150, excluded: 2, excluded_features: 7, source_row_indices: [12345], sample_labels: ['private-row-id'] };
    const color = 'Sequential color scale; limits follow this displayed matrix. Physical baseline unspecified.';
    const captions = reportComparisonCaptions({ comparison_populations: { original: population, preprocessed: population },
      comparison_color_notices: { original: color, preprocessed: color },
      comparison_notices: ['Verbose obsolete notice with private-row-id'] });
    expect(captions).toEqual(['Both panels: Subset: 50 of 150 active rows; 2 rows, 7 features excluded.', `Both panels: ${color}`]);
    expect(captions.join(' ')).not.toMatch(/private-row-id|12345|Verbose/);
    expect(reportPopulationCaption({ shown: 5, total: 5, excluded_features: 1 })).toBe('5 of 5 active rows; 1 feature excluded.');
    expect(reportPopulationCaption({ shown: 5, total: 5, excluded_features: -2 })).toBe('5 of 5 active rows.');
  });
  it('keeps distinct panel populations, color meanings and refusals scoped to their own panel', () => {
    const captions = reportComparisonCaptions({ comparison_populations: {
      original: { shown: 5, total: 10, excluded_features: 2 }, preprocessed: { shown: 5, total: 5, excluded_features: 1 },
    }, comparison_color_notices: { original: 'Physical baseline unspecified.', preprocessed: 'Symmetric limits about numerical zero.' },
    comparison_refusals: ['A third view is unavailable.'] });
    expect(captions).toEqual(['original: Subset: 5 of 10 active rows; 2 features excluded.', 'preprocessed: 5 of 5 active rows; 1 feature excluded.',
      'Original: Physical baseline unspecified. Preprocessed: Symmetric limits about numerical zero.', 'A third view is unavailable.']);
  });
  it("keeps a compact class-to-color key in static report captions without wide plot legends", () => {
    const groups = ["Oil", "Water"].map((name, index) => ({
      type: "scatter", mode: "markers", name, marker: { color: index ? "#0072B2" : "#D55E00" },
    }));
    expect(reportGroupKey(groups, { showlegend: true })).toBe(
      "Group color key: Oil (#D55E00); Water (#0072B2).",
    );
    expect(reportGroupKey(groups, { showlegend: false })).toBe("");
  });
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
    expect(render.mock.calls[0][1]).toMatchObject({ showlegend: false });
    expect(render.mock.calls[0][1].legend).toBeUndefined();
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
    const heatmap = sections[0].plots.find(plot => /heatmap/i.test(plot.title));
    expect(heatmap?.notice).toContain("Physical baseline unspecified.");
  });
  it.each(["summary", "detailed"] as const)("carries real comparison projection qualifiers into %s HTML and Markdown", async reportMode => {
    const saved = run();
    saved.saved_definition!.nodes.push({ node_id: "snv", node_type: "preprocess.normalize", label: "SNV", parameters: {}, position_x: 1, position_y: 0 });
    saved.saved_definition!.edges.push({ from_node_id: "source", from_output: "default", to_node_id: "snv", to_input: "default" });
    const value = { type: "SherpaDataset", data: [[1, 2, 3], [999, 999, 999], [4, 5, 6]], shape: [3, 3],
      sample_axis: { labels: ["private-A", "private-excluded", "private-C"], include_mask: [true, false, true] },
      feature_axis: { data: [100, 200, 300], include_mask: [true, false, true], units: "nm", title: "Wavelength" },
      metadata: { is_spectra: true } };
    const before = JSON.stringify(value);
    const evidence = { default: { state: "exact", storage: "file", byte_count: 100 } };
    vi.mocked(api.get).mockImplementation(async url => ({ data: String(url).endsWith("/evidence")
      ? { evidence: { outputs: { source: evidence, snv: evidence } } } : { value } }));
    const render = vi.fn().mockResolvedValue("data:image/png;base64,AA==");
    saved.node_plots = await captureReportPlots(saved, 1, () => true, render);
    const heatmap = saved.node_plots.find(section => section.node_id === "snv")!.plots.find(plot => /heatmap/i.test(plot.title))!;
    expect(heatmap.image).toBeTruthy();
    expect(heatmap.notice).toContain("Both panels: 2 of 2 active rows; 1 row, 1 feature excluded.");
    expect(heatmap.notice).toContain("Both panels: Sequential color scale;");
    expect(heatmap.notice).toContain("Physical baseline unspecified.");
    expect(heatmap.notice).toContain("independent axes and color scales");
    expect(heatmap.notice?.match(/Physical baseline unspecified/g)).toHaveLength(1);
    expect(heatmap.notice).not.toMatch(/private-|source_row_indices|sample_labels/);
    const data: ReportData = { reportMode, workflowName: "Test", workflowDescription: null, integrityHash: null,
      generatedAt: "today", nodes: [], edges: [], terminalMetrics: {}, plotImages: new Map(), runs: [saved] };
    for (const text of [generateProvenanceReport(data), generateMarkdownReport(data)]) {
      expect(text).toContain("1 row, 1 feature excluded.");
      expect(text).toContain("Physical baseline unspecified.");
      expect(text).toContain("independent axes and color scales");
      expect(text).not.toMatch(/private-|source_row_indices|sample_labels/);
    }
    expect(JSON.stringify(value)).toBe(before);
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
