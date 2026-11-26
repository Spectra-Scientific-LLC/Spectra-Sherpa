<template>
  <section class="retained-results" aria-label="Archived results">
    <h3>Saved results</h3>
    <p v-if="loading" role="status">Reading archived results…</p>
    <p v-if="error" role="status">{{ error }}</p>
    <template v-if="inventory">
      <p v-if="!inventory.runs.length">No runs were included in this archive.</p>
      <label v-if="inventory.runs.length">Run
        <select v-model="selectedRun" aria-label="Archived run">
          <option v-for="entry in inventory.runs" :key="entry.source_run_id" :value="entry.source_run_id">
            Run {{ entry.source_run_id }}
          </option>
        </select>
      </label>
      <template v-if="run">
        <details>
          <summary>Run details</summary>
          <SavedValue v-if="!recordTooLarge" :value="record" />
          <p v-else>Run details exceed the display limit.</p>
          <Button label="Download run details" text @click="downloadJson(run.record_json, 'retained-run.json')" />
        </details>
        <div class="retained-results__table">
        <table>
          <thead><tr><th>Node</th><th>Output</th><th>Evidence</th><th>Role</th><th>Inspect</th></tr></thead>
          <tbody>
            <tr v-for="entry in outputs" :key="JSON.stringify([entry.node, entry.port])">
              <td>{{ entry.node }}</td><td>{{ entry.port }}</td>
              <td>{{ entry.evidence.state }}<span v-if="entry.evidence.reason"> · {{ entry.evidence.reason }}</span></td>
              <td>{{ entry.evidence.role ?? 'Not recorded' }}</td>
              <td><Button label="View" text :disabled="outputLoading || entry.evidence.storage !== 'file'" @click="loadOutput(entry.node, entry.port)" /></td>
            </tr>
          </tbody>
        </table>
        </div>
        <p v-if="!outputs.length">No results were saved for this run.</p>
      </template>
      <p v-if="outputLoading" role="status">Reading selected output…</p>
      <p v-if="outputError" role="alert">{{ outputError }}</p>
      <template v-if="outputText">
        <h4>{{ outputLabel }}</h4>
        <SavedValue v-if="!outputTooLarge" :value="outputValue" />
        <p v-else>This result is too large to display. Download it to view all values.</p>
        <Button label="Download result (JSON)" text icon="pi pi-download" @click="downloadJson(outputText, 'retained-output.json')" />
      </template>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import Button from "primevue/button";
import SavedValue from "@/views/models/SavedValue.vue";
import { api } from "@/api";
import { useScopedRequest } from "@/composables/useScopedRequest";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";
import { retainedJsonForDisplay, RETAINED_DISPLAY_CHAR_LIMIT } from "@/utils/retainedJson";
import type { components } from "@/types/api/v1";

type Inventory = components["schemas"]["ArchivedResults"];
const props = defineProps<{ file: File }>();
const auth = useAuthStore();
const project = useProjectStore();
const fileRevision = ref(0);
const identity = () => [auth.user?.id, auth.sessionRevision, project.currentProjectId, fileRevision.value];
const requests = useScopedRequest(identity);
const selectedRun = ref<number | null>(null);
const outputRequests = useScopedRequest(() => [...identity(), selectedRun.value]);
const inventory = ref<Inventory | null>(null);
const loading = ref(false);
const error = ref("");
const outputText = ref("");
const outputLabel = ref("");
const outputLoading = ref(false);
const outputError = ref("");
const run = computed(() => inventory.value?.runs.find(item => item.source_run_id === selectedRun.value));
const recordTooLarge = computed(() => (run.value?.record_json.length ?? 0) > RETAINED_DISPLAY_CHAR_LIMIT);
const outputTooLarge = computed(() => outputText.value.length > RETAINED_DISPLAY_CHAR_LIMIT);
const record = computed(() => run.value && !recordTooLarge.value ? retainedJsonForDisplay(run.value.record_json) : null);
const outputs = computed(() => Object.entries(run.value?.evidence.outputs ?? {}).flatMap(([node, ports]) =>
  Object.entries(ports).map(([port, evidence]) => ({ node, port, evidence })),
));
const outputValue = computed(() => {
  if (!outputText.value || outputTooLarge.value) return null;
  const envelope = retainedJsonForDisplay(outputText.value) as { value?: unknown };
  return envelope.value;
});
function clearOutput(): void {
  outputRequests.invalidate();
  outputText.value = "";
  outputLabel.value = "";
  outputLoading.value = false;
  outputError.value = "";
}
watch(selectedRun, clearOutput);
watch(() => [auth.user?.id, auth.sessionRevision, project.currentProjectId], () => {
  requests.invalidate();
  inventory.value = null;
  selectedRun.value = null;
  loading.value = false;
  error.value = "";
  clearOutput();
});
watch(() => props.file, async () => {
  fileRevision.value += 1;
  clearOutput();
  inventory.value = null;
  selectedRun.value = null;
  error.value = "";
  const request = requests.begin();
  const form = new FormData();
  form.append("file", props.file);
  loading.value = true;
  try {
    const { data } = await api.post<Inventory>("/projects/objects/inspect-results", form, { signal: request.signal });
    if (request.isCurrent()) {
      inventory.value = data;
      selectedRun.value = data.runs[0]?.source_run_id ?? null;
    }
  } catch {
    if (request.isCurrent()) error.value = "This archive has no readable saved-result inventory.";
  } finally {
    if (request.isCurrent()) loading.value = false;
  }
}, { immediate: true });

async function loadOutput(node: string, port: string): Promise<void> {
  if (!run.value) return;
  clearOutput();
  const request = outputRequests.begin();
  const form = new FormData();
  form.append("file", props.file);
  outputLoading.value = true;
  try {
    const { data } = await api.post<string>("/projects/objects/inspect-output", form, {
      params: { run_id: run.value.source_run_id, node_id: node, port },
      signal: request.signal, responseType: "text", transformResponse: [value => value],
    });
    if (data.length <= RETAINED_DISPLAY_CHAR_LIMIT) retainedJsonForDisplay(data);
    if (request.isCurrent()) {
      outputText.value = data;
      outputLabel.value = `${node} · ${port}`;
    }
  } catch {
    if (request.isCurrent()) outputError.value = "This selected output is unavailable or failed its integrity check.";
  } finally {
    if (request.isCurrent()) outputLoading.value = false;
  }
}
function downloadJson(text: string, filename: string): void {
  if (!text) return;
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
</script>

<style scoped>
.retained-results { min-width: 0; }
.retained-results__table { max-width: 100%; overflow: auto; }
table { width: 100%; min-width: 34rem; }
th, td { text-align: left; padding: 0.4rem; overflow-wrap: anywhere; }
select { max-width: 100%; }
</style>
