<script setup lang="ts">
import oofFixture from "./oof-fixture.json";
import { computed, ref } from "vue";
import QuickPlotModal from "@/views/workflow-builder/modals/QuickPlotModal.vue";
import DataTableModal from "@/views/workflow-builder/modals/DataTableModal.vue";
import DataQualityPanel from "@/views/data/DataQualityPanel.vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
import DataMatrixGrid from "@/views/data/DataMatrixGrid.vue";
import {
  buildCategoryCountsPlot,
  buildClassificationResponsesPlot,
  buildOutOfFoldEvidencePlot,
} from "@/utils/scientificPlots";
const selected = ref("classification");
const tableOpen = ref(false);
const choices = [
  ["classification", "GSC-04 categorical target quality"],
  ["noise", "GSC-05 generic renderer (provisional)"],
  ["missing", "GSC-08 malformed missing responses"],
  ["matrix", "GSC-10 missing matrix"],
  ["oof", "GSC-07 OOF fold scope"],
  ["class_authority", "GSC-06 malformed class authority"],
  ["png", "GSC-09 plot download"],
  ["traces", "GSC-01 multi-trace table"],
  ["rows", "GSC-02 table limits"],
  ["precision", "GSC-03 axis export"],
];
const classification = {
  data: [[1], [2], [3]],
  n_samples: 3,
  n_features: 1,
  target: ["A", "B", "C"],
  target_context: { target_type: "categorical", class_names: ["A", "B", "C"] },
  metadata: {},
};
const missing = {
  data: [[null, null]],
  presentation_value: [[null, null]],
  metadata: {
    scientific_presentation: {
      schema_version: "spectrasherpa-node-presentation/1",
      contract_digest: "a".repeat(64),
      presentation_id: "responses",
      source_port: "responses",
      source_ports: ["responses"],
      modes: ["plot", "table"],
      kind: "classification_responses",
    },
  },
};
const traces = {
  data: [
    { type: "scatter", name: "A", x: [500, 501], y: [1, 2] },
    { type: "scatter", name: "B", x: [500, 501], y: [31, 32] },
  ],
  metadata: {},
};
const rows = {
  data: Array.from({ length: 120 }, (_, i) => [i]),
  metadata: { sample_labels: Array.from({ length: 120 }, (_, i) => `S${i}`) },
};
const precision = { data: [[1, 2]], metadata: { wavenumbers: [500.001, 500.004] } };
const tableOutput = computed(() =>
  selected.value === "traces" ? traces : selected.value === "rows" ? rows : precision,
);
const plot = computed(() =>
  selected.value === "noise"
    ? buildCategoryCountsPlot([-1, -1, -1])
    : selected.value === "class_authority"
      ? buildClassificationResponsesPlot([[0.1, 0.9]], {})
      : buildOutOfFoldEvidencePlot(oofFixture),
);
const plotOutput = {
  data: traces.data,
  metadata: {},
  ports: { visualization: { value: { plot_type: "spectra", ...traces, layout: {} } } },
};
</script>
<template>
  <main>
    <h1>Scientific GUI contract — pinned main 12bd8961</h1>
    <p>
      Synthetic component harness. Production components and renderers, isolated from application
      data.
    </p>
    <nav>
      <button
        v-for="[key, label] in choices"
        :key="key"
        @click="
          selected = key;
          tableOpen = false;
        "
      >
        {{ label }}
      </button>
    </nav>
    <h2>{{ choices.find((c) => c[0] === selected)?.[1] }}</h2>
    <p v-if="selected === 'classification'">
      Fixture: three samples, one categorical target, classes A/B/C; expected three valid target
      values.
    </p>
    <DataQualityPanel v-if="selected === 'classification'" :dataset-dict="classification as any" />
    <QuickPlotModal
      v-else-if="selected === 'missing'"
      embedded
      :model-value="true"
      node-type="model.pls_da"
      node-label="All missing responses"
      :node-output="missing"
    />
    <DataMatrixGrid
      v-else-if="selected === 'matrix'"
      :matrix="
        {
          rows_shown: 1,
          cols_shown: 3,
          total_rows: 1,
          total_cols: 3,
          truncated: false,
          row_labels: ['A'],
          col_labels: ['x', 'y', 'z'],
          matrix: [[null, null, null]],
        } as any
      "
    />
    <QuickPlotModal
      v-else-if="selected === 'png'"
      embedded
      :model-value="true"
      node-type="output.plot"
      node-label="Synthetic two traces"
      :node-output="plotOutput"
    />
    <template v-else-if="['traces', 'rows', 'precision'].includes(selected)"
      ><p>
        {{
          selected === "traces"
            ? "Two spectra A=[1,2], B=[31,32]."
            : selected === "rows"
              ? "120 rows S0–S119. Initial row limit is 100."
              : "Distinct coordinates 500.001 and 500.004."
        }}
      </p>
      <button @click="tableOpen = true">Open production data table</button
      ><DataTableModal
        v-model="tableOpen"
        :node-output="tableOutput"
        node-type="output.plot"
        node-label="Synthetic audit"
    /></template>
    <PlotlyChart v-else :data="plot.data" :layout="plot.layout" style="height: 500px" />
  </main>
</template>
<style>
body {
  font-family: system-ui;
  margin: 24px;
  background: #f1f5f9;
  color: #162235;
}
main {
  max-width: 1200px;
  margin: auto;
}
nav {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
button {
  padding: 9px;
  cursor: pointer;
}
h1 {
  font-size: 23px;
}
</style>
