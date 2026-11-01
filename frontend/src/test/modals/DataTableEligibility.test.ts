import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import PrimeVue from "primevue/config";
import DataTableModal from "@/views/workflow-builder/modals/DataTableModal.vue";
import ObservationExclusionButton from "@/components/ObservationExclusionButton.vue";
import { buildNodeOutput } from "@/utils/nodeOutput";
import { projectScientificPresentation, resolveScientificPresentation } from "@/utils/scientificPresentation";
import { WORKFLOW_POPULATION_ACTIONS } from "@/utils/workflowPopulation";

const refs = [0, 1, 2, 3, 4].map(index => `load:${"a".repeat(64)}:${index}`);
describe("DataTable inspected cohort eligibility", () => {
  it.each(["qualified", "source-excluded", "other-cohort"])("keeps inspected columns and exact identities with %s display", async variant => {
    const dataset = { type: "SherpaDataset", data: [[10, 20], [30, 40]],
      sample_axis: { labels: ["Same", "Same"], workflow_observation_refs: refs.slice(1, 3) },
      feature_axis: { labels: ["Hidden feature", "Inspected feature"], include_mask: [false, true] } };
    const displayRefs = variant === "other-cohort" ? refs : refs.slice(0, 3);
    const raw = buildNodeOutput({ default: dataset });
    raw.presentation_contract = { schema_version: "spectrasherpa-node-presentation/1", digest: "test", payload: {
      default_presentation: "data", presentations: [{ presentation_id: "data", label: "Data", kind: "spectral_dataset",
        modes: ["table"], source_ports: ["default"], output_binding: ["default", "sample_axis"] }],
    } } as typeof raw.presentation_contract;
    raw.metadata.workflow_population = { outputs: { default: { ...dataset,
      data: displayRefs.map(() => [9999, 9999]), sample_axis: { labels: displayRefs.map(() => "Same"),
        workflow_observation_refs: displayRefs, include_mask: displayRefs.map(reference => reference !== refs[0] && reference !== refs[4]) } } } };
    const output = projectScientificPresentation(raw, resolveScientificPresentation(null, raw))!;
    const before = JSON.stringify(output);
    const change = vi.fn();
    const wrapper = mount(DataTableModal, { props: { modelValue: true, nodeOutput: output, nodeType: "data.file_load", nodeLabel: "Data" },
      global: { plugins: [PrimeVue], stubs: { Dialog: { template: "<div><slot /></div>" }, MethodHelp: true }, provide: {
        [WORKFLOW_POPULATION_ACTIONS]: { scope: () => "workflow:1", change,
          resolve: () => ({ excluded: true, restorable: true }), populations: () => [{
            schema_version: "spectrasherpa-workflow-population/1", source_node_id: "load", source_digest: "a".repeat(64), identity_basis: "typed_sample_id",
            source_count: 5, active_count: 3, workflow_excluded_count: 2, rows: refs.map((reference, index) => ({
              observation_ref: reference, source_row: index + 1, sample_id: `id-${index}`, sample_label: "Same",
              included: index !== 0 && index !== 4, source_included: variant !== "source-excluded" || index !== 0,
              workflow_excluded: index === 0 || index === 4, result_row: index || null,
            })),
          }],
        },
      } },
    });
    try {
      await flushPromises();
      const rows = wrapper.findAll("tbody tr");
      expect(rows).toHaveLength(variant === "qualified" ? 3 : 2);
      expect(rows.map(row => row.findAll("td").at(-1)!.text())).toEqual(variant === "qualified" ? ["-", "20", "40"] : ["20", "40"]);
      expect(wrapper.findAll("th").slice(0, 2).map(cell => cell.text())).toEqual(["", ""]);
      const controls = wrapper.findAllComponents(ObservationExclusionButton);
      expect(controls.map(control => control.props("observationRef"))).toEqual(variant === "qualified" ? refs.slice(0, 3) : refs.slice(1, 3));
      expect(wrapper.find("table").text()).not.toContain("9999");
      expect(JSON.stringify(output)).toBe(before);
    } finally { wrapper.unmount(); }
  });
});
