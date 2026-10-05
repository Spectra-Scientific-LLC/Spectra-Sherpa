<script setup lang="ts">
defineOptions({name:"EncodingAcceptance"});
import { computed, ref } from "vue";
import QuickPlotModal from "@/views/workflow-builder/modals/QuickPlotModal.vue";
import DataTableModal from "@/views/workflow-builder/modals/DataTableModal.vue";
const selected = ref("anisotropic");
const table = ref(false);
const flipped = ref(false);
const choices = [
  ["anisotropic", "E1 Anisotropic scores"],
  ["signed", "E2 Signed micro matrix"],
  ["masked", "E3 Active cohort"],
  ["sign", "E4 Paired sign orientation"],
  ["degenerate", "E5 Singleton scores"],
];
function result(kind: string, data: number[][], extra: Record<string, unknown> = {}) {
  return {
    data,
    presentation_value: { data, ...extra },
    metadata: {
      explained_variance_ratio: [0.9999, 0.0001],
      x_title: "Wavenumber",
      x_units: "cm-1",
      scientific_presentation: {
        schema_version: "spectrasherpa-node-presentation/1",
        contract_digest: "a".repeat(64),
        presentation_id: "result",
        source_port: "result",
        source_ports: ["result"],
        kind,
        modes: ["plot", "table"],
      },
    },
  };
}
const output = computed(() => {
  if (selected.value === "signed")
    return result(
      "spectral_dataset",
      [
        [-1e-6, 0, 1e-6],
        [1e-6, 0, -1e-6],
      ],
      { feature_axis: { data: [1000.01, 1000.02, 1000.03] } },
    );
  if (selected.value === "masked")
    return result(
      "spectral_dataset",
      [
        [1, 2, 3],
        [999, 999, 999],
        [4, 5, 6],
      ],
      {
        sample_axis: { labels: ["A", "excluded", "C"], include_mask: [true, false, true] },
        feature_axis: { data: [1000.01, 1000.02, 1000.03], include_mask: [true, false, true] },
      },
    );
  if (selected.value === "degenerate") return result("pca_scores", [[2, 2]]);
  if (selected.value === "sign")
    return result("pca_scores", [
      [2, flipped.value ? -1 : 1],
      [-2, flipped.value ? 1 : -1],
    ]);
  return result("pca_scores", [
    [-100, -1],
    [0, 0],
    [100, 1],
  ]);
});
</script>
<template>
  <section>
    <h2>§8 visual acceptance — synthetic retained projections</h2>
    <nav>
      <button
        v-for="[key, label] in choices"
        :key="key"
        @click="
          selected = key;
          table = false;
        "
      >
        {{ label }}
      </button>
    </nav>
    <p>
      Expected: equal score units, balanced signed colors about zero, distinct nearby coordinates,
      identical active cohorts, finite singleton layout. Synthetic inputs; no private corpus.
    </p>
    <p v-if="selected === 'sign'">
      Two independently retained fits: switch both scores and loading orientation together. Original
      loading [3,4]; paired fit loading {{ flipped ? "[-3,-4]" : "[3,4]" }}. Reconstruction is
      unchanged; the renderer must preserve each fit's signs.
    </p>
    <button v-if="selected === 'sign'" @click="flipped = !flipped">Switch paired fit</button>
    <button v-if="selected === 'masked'" @click="table = true">Inspect active table</button>
    <QuickPlotModal
      :key="selected"
      embedded
      :model-value="true"
      node-type=""
      :node-label="selected"
      :node-output="output"
    />
    <DataTableModal v-model="table" node-type="" node-label="Active cohort" :node-output="output" />
  </section>
</template>
