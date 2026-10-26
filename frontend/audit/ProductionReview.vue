<script setup lang="ts">
// Explicit browser fixture, not an application route or authenticated journey.
import { ref } from "vue";
import ValidationLedger from "@/components/ValidationLedger.vue";
import QuickPlotModal from "@/views/workflow-builder/modals/QuickPlotModal.vue";
import DataTableModal from "@/views/workflow-builder/modals/DataTableModal.vue";
import { useAuthStore } from "@/stores/auth";
import { useClipboardStore } from "@/stores/clipboard";
import { useNotificationStore } from "@/stores/notification";
import { createSherpaRequestId } from "@/lib/sherpaEvents";
const auth = useAuthStore();
const clipboard = useClipboardStore();
const notifications = useNotificationStore();
const large = ref(false);
const requestId = ref("");
const showScores = ref(false);
const showScoreTable = ref(false);
const appliedScores = {
  data: [[0.1, 0.2], [0.3, 0.4]], metadata: {},
  presentation_value: {
    y_axis: { labels: ["Specimen 135", "Specimen 142"] },
    x_axis: { labels: ["PC1", "PC2"], units: "dimensionless" },
  },
};
const rows = Array.from({ length: 30000 }, (_, index) => ({
  sample: index === 0 ? "specimen\rA" : `specimen-${index}`,
  target: "synthetic response", reference: 100, predicted: 100.00001,
  residual: 0.00001, role: "held_out_test",
}));
function seed() {
  auth.user = { id: 101, username: "Synthetic A" };
  clipboard.set({ nodes: [{ id: "pca", type: "model.pca", x: 0, y: 0, params: {} }], edges: [], sourceWorkflowId: 1 });
  notifications.add({ source: "system", severity: "info", title: "Synthetic A", message: "Private context" });
  requestId.value = createSherpaRequestId();
}
function insecureApi() {
  // Simulate the one missing API without touching the browser's security policy.
  Object.defineProperty(crypto, "randomUUID", { configurable: true, value: undefined });
  seed();
}
</script>
<template>
  <main style="max-width: 1000px; margin: 24px auto; font-family: sans-serif">
    <h1>Production review — synthetic fixtures</h1>
    <p>Real components and stores; no login, live provider or backend request.</p>
    <section aria-label="Session fixture">
      <button @click="seed">Seed account A context</button>
      <button @click="auth.user = { id: 101, username: 'Synthetic A refreshed' }">Same-account profile refresh</button>
      <button @click="auth.user = { id: 102, username: 'Synthetic B' }">Switch account identity</button>
      <button @click="auth.user = null">Clear account identity</button>
      <button @click="insecureApi">Test absent randomUUID</button>
      <p role="status">Clipboard: {{ clipboard.isEmpty() ? 'empty' : 'populated' }} · Notifications: {{ notifications.notifications.length }}</p>
      <p>Request ID: {{ requestId }}</p>
    </section>
    <section aria-label="Typed applied-score fixture">
      <button @click="showScores = !showScores">Toggle named applied-score preview</button>
      <button @click="showScoreTable = true">Open named applied-score Data View</button>
      <QuickPlotModal v-if="showScores" :model-value="true" embedded table-only
        node-type="model.load_apply" node-label="Synthetic applied PCA" :node-output="appliedScores" />
      <DataTableModal v-model="showScoreTable" node-type="model.load_apply"
        node-label="Synthetic applied PCA" :node-output="appliedScores" />
    </section>
    <button @click="large = !large">{{ large ? 'Show two observations' : 'Show 30,000 observations' }}</button>
    <ValidationLedger :rows="large ? rows : rows.slice(0, 2)" title="production-review-synthetic" />
  </main>
</template>
