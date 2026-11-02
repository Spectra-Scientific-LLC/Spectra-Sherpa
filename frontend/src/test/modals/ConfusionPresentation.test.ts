import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import PrimeVue from "primevue/config";

import type { NodePresentationContract } from "@/types";
import type { NodeScientificValueDescriptors } from "@/stores/workflow-types";
import { buildNodeOutput } from "@/utils/nodeOutput";
import { projectScientificPresentation, resolveScientificPresentation } from "@/utils/scientificPresentation";
import { scientificMatrixColumns, scientificMatrixRowLabels } from "@/utils/scientificMatrixColumns";
import QuickPlotModal from "@/views/workflow-builder/modals/QuickPlotModal.vue";
import DataTableModal from "@/views/workflow-builder/modals/DataTableModal.vue";
import fixture from "@/test/fixtures/classification-evaluator.json";

/* eslint-disable @typescript-eslint/no-explicit-any */

const classes = ["setosa", "versicolor", "virginica"];
const matrix = [[11, 1, 0], [0, 6, 6], [0, 3, 10]];
const global = {
  plugins: [PrimeVue],
  stubs: {
    Dialog: { template: "<div><slot /></div>" },
    Dropdown: true, Button: true, PlotlyChart: true, Paginator: true,
  },
};

function evaluatorOutput(sampleCount = 37) {
  const output = buildNodeOutput(structuredClone(fixture.result), undefined, undefined,
    structuredClone(fixture.descriptors) as NodeScientificValueDescriptors,
    structuredClone(fixture.presentation_contract) as NodePresentationContract);
  // An adjacent sample result may have 37 rows, or coincidentally three. Its
  // names must never replace the visualization port's own class identities.
  output.primary_port = "default";
  output.metadata = { sample_labels: Array.from({ length: sampleCount }, (_, i) => `Sample ${i + 1}`),
    classes: ["wrong A", "wrong B", "wrong C"] };
  return output;
}

function project(output = evaluatorOutput()) {
  return projectScientificPresentation(output, resolveScientificPresentation(null, output, "confusion"))!;
}

afterEach(() => vi.restoreAllMocks());

describe("canonical evaluator confusion presentation", () => {
  it.each([37, 3])("binds generic visualization axes to its own classes, not %i sample labels", count => {
    const output = evaluatorOutput(count);
    const before = structuredClone(output);
    expect(output.ports!.visualization.descriptor!.dimensions.map(d => d.role)).toEqual(["axis_1", "axis_2"]);
    const projected = project(output);
    expect(projected.descriptor!.dimensions).toEqual([
      { role: "actual_class", size: 3, labels: classes },
      { role: "predicted_class", size: 3, labels: classes },
    ]);
    expect(projected.metadata.scientific_value).toEqual(projected.descriptor);
    expect(scientificMatrixRowLabels(projected, 3)).toEqual(classes);
    expect(projected.data).toEqual(matrix);
    expect(output).toEqual(before);
    expect(projected.presentation_contract).toEqual(fixture.presentation_contract);
  });

  it("renders actual reference class names and retained counts in QuickPlot's real table DOM", async () => {
    const wrapper = mount(QuickPlotModal, { props: {
      modelValue: true, embedded: true, tableOnly: true, nodeType: fixture.node_type,
      nodeLabel: "Test Evaluation", nodeOutput: project(),
    }, global });
    await nextTick();
    expect(wrapper.findAll("thead th").map(cell => cell.text())).toEqual(["#", "Actual class", ...classes]);
    expect(wrapper.findAll("tbody tr").map(row => row.findAll("td").map(cell => cell.text())))
      .toEqual(matrix.map((row, i) => [String(i + 1), classes[i], ...row.map(String)]));
    wrapper.unmount();
  });

  it("preserves explicit actual and predicted class axes instead of replacing them with a common domain", () => {
    const output = evaluatorOutput();
    const descriptor = output.ports!.visualization.descriptor!;
    descriptor.dimensions = [
      { role: "actual_class", size: 3, labels: ["A", "B", "C"] },
      { role: "predicted_class", size: 3, labels: ["C", "A", "B"] },
    ];
    const before = structuredClone(output);
    const projected = project(output);
    expect(projected.descriptor).toEqual(descriptor);
    expect(scientificMatrixRowLabels(projected, 3)).toEqual(["A", "B", "C"]);
    expect(scientificMatrixColumns(projected, 3)).toEqual(["C", "A", "B"]);
    expect(output).toEqual(before);
  });

  it("exports the same ordered reference and prediction classes and original counts to CSV", async () => {
    const wrapper = mount(DataTableModal, { props: {
      modelValue: true, nodeType: fixture.node_type, nodeLabel: "Test Evaluation", nodeOutput: project(),
    }, global });
    let blob: Blob | undefined;
    vi.spyOn(URL, "createObjectURL").mockImplementation(value => { blob = value as Blob; return "blob:csv"; });
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    (wrapper.vm as any).exportCSV();
    expect(blob).toBeDefined();
    expect(await blob!.text()).toBe("Index,Label,setosa,versicolor,virginica\n1,setosa,11,1,0\n2,versicolor,0,6,6\n3,virginica,0,3,10\n");
    expect((wrapper.vm as any).exportError).toBe("");
    wrapper.unmount();
  });

  it.each(["sample", "feature", "component"])("preserves contradictory %s axes and refuses CSV labels", role => {
    const output = evaluatorOutput(3);
    output.ports!.visualization.descriptor!.dimensions[0].role = role;
    const projected = project(output);
    expect(projected.descriptor!.dimensions[0].role).toBe(role);
    expect(scientificMatrixRowLabels(projected, 3)).toEqual([]);
    const wrapper = mount(DataTableModal, { props: {
      modelValue: true, nodeType: fixture.node_type, nodeLabel: "Test Evaluation", nodeOutput: projected,
    }, global });
    const download = vi.spyOn(URL, "createObjectURL");
    (wrapper.vm as any).exportCSV();
    expect(download).not.toHaveBeenCalled();
    expect((wrapper.vm as any).exportError).toContain("declared class row labels");
    wrapper.unmount();
  });

  it.each(["column_role", "shape_invalid", "shape_size", "dimension_size", "explicit_labels", "column_labels", "null_axis_labels", "missing_labels", "wrong_label_count", "empty_label", "duplicate_label", "string_collision", "not_confusion"])(
    "does not reinterpret an invalid or unrelated visualization: %s", change => {
      const output = evaluatorOutput(3);
      const port = output.ports!.visualization;
      if (change === "column_role") port.descriptor!.dimensions[1].role = "feature";
      if (change === "shape_invalid") port.descriptor!.shape_valid = false;
      if (change === "shape_size") port.descriptor!.shape = [37, 3];
      if (change === "dimension_size") port.descriptor!.dimensions[0].size = 37;
      if (change === "explicit_labels") port.descriptor!.dimensions[0].labels = ["Sample 1", "Sample 2", "Sample 3"];
      if (change === "column_labels") port.descriptor!.dimensions[1].labels = ["Variable A", "Variable B", "Variable C"];
      if (change === "null_axis_labels") port.descriptor!.dimensions[0].labels = null as unknown as string[];
      if (change === "missing_labels") delete port.metadata.labels;
      if (change === "wrong_label_count") port.metadata.labels = ["A", "B"];
      if (change === "empty_label") port.metadata.labels = ["A", "", "C"];
      if (change === "duplicate_label") port.metadata.labels = ["A", "A", "C"];
      if (change === "string_collision") port.metadata.labels = [1, "1", 2];
      const resolved = resolveScientificPresentation(null, output, "confusion")!;
      if (change === "not_confusion") resolved.presentation = { ...resolved.presentation, kind: "visualization" };
      const projected = projectScientificPresentation(output, resolved)!;
      expect(projected.descriptor).toEqual(port.descriptor);
      expect(scientificMatrixRowLabels(projected, 3)).toEqual([]);
    },
  );
});
