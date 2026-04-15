import { describe, it, expect } from "vitest";
import { useNodeSections } from "@/views/workflow-builder/node-detail/composables/useNodeSections";

describe("useNodeSections", () => {
  it("top-level sections default to collapsed (false)", () => {
    const { sections } = useNodeSections();
    expect(sections.value).toEqual({
      input: false,
      settings: false,
      output: false,
      plots: false,
      log: false,
    });
  });

  it("toggleSection flips the matching entry only", () => {
    const { sections, toggleSection } = useNodeSections();
    toggleSection("settings");
    expect(sections.value.settings).toBe(true);
    expect(sections.value.input).toBe(false);
    toggleSection("settings");
    expect(sections.value.settings).toBe(false);
  });

  it("toggleOutputSubsection flips the matching subsection only", () => {
    const { outputSubsections, toggleOutputSubsection } = useNodeSections();
    toggleOutputSubsection("metadata");
    expect(outputSubsections.value.metadata).toBe(true);
    expect(outputSubsections.value.quality).toBe(false);
  });

  it("plotSections preserves opt-in defaults (evaluationResults, clusterScatter, outlierChart = true)", () => {
    const { plotSections } = useNodeSections();
    expect(plotSections.value.evaluationResults).toBe(true);
    expect(plotSections.value.clusterScatter).toBe(true);
    expect(plotSections.value.outlierChart).toBe(true);
    expect(plotSections.value.pcaScores).toBe(false);
  });

  it("togglePlot flips the requested plot key", () => {
    const { plotSections, togglePlot } = useNodeSections();
    togglePlot("pcaScores");
    expect(plotSections.value.pcaScores).toBe(true);
    togglePlot("pcaScores");
    expect(plotSections.value.pcaScores).toBe(false);
  });

  it("each invocation produces independent state", () => {
    const a = useNodeSections();
    const b = useNodeSections();
    a.toggleSection("input");
    expect(a.sections.value.input).toBe(true);
    expect(b.sections.value.input).toBe(false);
  });
});
