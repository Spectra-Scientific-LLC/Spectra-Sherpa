<template>
  <section class="bosch-step-comparison" aria-label="BOSCH processing step comparison">
    <h3>Scientific result · processing steps across days</h3>
    <div class="companion-selection">
      <label>Required process companion
        <select v-model.number="processFileId" aria-label="Process companion">
          <option :value="null">Select Process_data.nc</option>
          <option v-for="file in processFiles" :key="file.id" :value="file.id">{{ basename(file.file_path) }}</option>
        </select>
      </label>
      <label class="companion-upload">Add Process_data.nc
        <input type="file" accept=".nc" aria-label="Add Process_data.nc" :disabled="uploading" @change="addCompanion" />
      </label>
    </div>
    <p v-if="!processFileId" role="status">Upload Process_data.nc to this dataset before comparing daily OES steps. Its gas records define phase boundaries.</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="inventoryLoading" role="status">Matching process records and checking acquisition clocks…</p>
    <template v-if="catalogs.length">
      <div class="step-controls">
        <label>Processing steps to compare
          <select v-model="selectedSteps" multiple size="6" aria-label="Processing steps to compare">
            <option v-for="step in availableSteps" :key="step.step_id" :value="step.step_id">{{ step.label }}</option>
          </select>
        </label>
        <div>
          <button type="button" @click="selectAll(true)">Select all days and wafers</button>
          <button type="button" @click="selectAll(false)">Clear wafers</button>
          <button type="button" :disabled="!selectedPairCount || plotting" @click="compare">Compare selected steps ({{ selectedPairCount }} groups)</button>
          <small>Steps apply to every checked wafer. Previews use four original acquisitions per group, with no averaging. At most 50 wafer/step groups.</small>
        </div>
      </div>
      <details v-for="entry in catalogs" :key="entry.file.id" class="day-group" open>
        <summary>
          <input type="checkbox" :aria-label="`Select all wafers in ${basename(entry.file.file_path)}`"
            :checked="entry.catalog.wafers.filter(w => !w.refusal).every(w => selectedWafers.includes(key(entry.file.id, w.asset_id)))"
            @click.stop @change="selectFile(entry, ($event.target as HTMLInputElement).checked)" />
          {{ basename(entry.file.file_path) }} · {{ entry.catalog.date }}
          <span v-if="entry.catalog.lot"> · {{ entry.catalog.lot.conditioning_surface }} · {{ entry.catalog.lot.conditioning_repetitions }} conditioning repetitions</span>
        </summary>
        <details v-for="wafer in entry.catalog.wafers" :key="wafer.asset_id" class="wafer-group">
          <summary>
            <input v-model="selectedWafers" type="checkbox" :value="key(entry.file.id, wafer.asset_id)" :disabled="Boolean(wafer.refusal)"
              :aria-label="`Compare ${basename(entry.file.file_path)} ${wafer.asset_id}`" @click.stop />
            {{ wafer.asset_id }}
            <small v-if="wafer.alignment"> · clock fit {{ Number(wafer.alignment.correlation).toFixed(3) }} · edge uncertainty ±{{ Number(wafer.alignment.boundary_uncertainty_s).toFixed(2) }} s</small>
          </summary>
          <button type="button" @click="emit('inspect', entry.file, wafer.asset_id)">Inspect all acquisitions and experiment metadata</button>
          <p v-if="wafer.refusal" role="alert">{{ wafer.refusal }}</p>
          <table v-else :aria-label="`Processing steps ${basename(entry.file.file_path)} ${wafer.asset_id}`">
            <thead><tr><th>Processing step</th><th>Start / end (UTC)</th><th>Acquisition ranges (1-based)</th><th>Observations</th></tr></thead>
            <tbody><tr v-for="step in wafer.steps" :key="step.step_id" :class="{ chosen: selectedSteps.includes(step.step_id) }">
              <td>{{ step.label }}</td>
              <td>{{ time(step.intervals[0].start_time) }}<br />{{ time(step.intervals[step.intervals.length - 1].end_time) }}</td>
              <td><details><summary>{{ step.intervals.length }} separate interval{{ step.intervals.length === 1 ? '' : 's' }}</summary>
                <div v-for="(interval, index) in step.intervals" :key="index">
                  {{ interval.first_acquisition }}–{{ interval.last_acquisition }} · {{ time(interval.start_time) }} → {{ time(interval.end_time) }}
                </div>
              </details></td>
              <td>{{ step.acquisition_count.toLocaleString() }}</td>
            </tr></tbody>
          </table>
        </details>
        <details class="protocol-coverage"><summary>Protocol stages outside these recordings</summary>
          <p v-for="step in entry.catalog.unrecorded_protocol_steps" :key="step">{{ step }} — no source interval identified.</p>
        </details>
      </details>
      <details><summary>Gas mapping and alignment evidence</summary>
        <p>Gas4 → C₄F₈ and Gas5 → SF₆ are tentative assignments checked against C₂ and fluorine emission. Gas1 → O₂ is unconfirmed; its optical spectrum must be reviewed before labeling it as an oxygen clean. EPD control is not inferred from duration.</p>
        <p v-for="warning in catalogs[0].catalog.warnings" :key="warning">{{ warning }}</p>
      </details>
    </template>
    <SelectedSpectraPlotPanel :plot-datasets="sources" :plot-dataset-count="sources.length ? 1 : 0"
      :plot-file-count="sources[0]?.selectedFileCount ?? 0" :plot-datasets-loading="plotting" :plot-datasets-error="plotError"
      :minimum-trace-count="sources.reduce((total, source) => total + source.members.length, 0)" />
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import api from "@/api/client";
import type { components } from "@/types/api/v1";
import type { DatasetPlotSource, ExperimentFile, SherpaDatasetDict } from "@/types";
import { useScopedRequest } from "@/composables/useScopedRequest";
import { useDataStore } from "@/stores/data";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";
import { getErrorMessage } from "@/utils/errors";
import SelectedSpectraPlotPanel from "./SelectedSpectraPlotPanel.vue";

type Catalog = components["schemas"]["BoschStepsOut"];
type CatalogEntry = { file: ExperimentFile; catalog: Catalog };
const props = defineProps<{ experimentId: number; files: ExperimentFile[] }>();
const emit = defineEmits<{ inspect: [file: ExperimentFile, assetId: string] }>();
const dataStore = useDataStore();
const auth = useAuthStore();
const project = useProjectStore();
const processFileId = ref<number | null>(null);
const catalogs = ref<CatalogEntry[]>([]);
const selectedSteps = ref<string[]>(["etch"]);
const selectedWafers = ref<string[]>([]);
const inventoryLoading = ref(false);
const uploading = ref(false);
const plotting = ref(false);
const error = ref<string | null>(null);
const plotError = ref<string | null>(null);
const sources = ref<DatasetPlotSource[]>([]);
const basename = (name: string) => name.split("/").pop() ?? name;
const time = (value: number) => new Date(value * 1000).toISOString().replace("T", " ").replace("Z", " UTC");
const key = (fileId: number, assetId: string) => `${fileId}:${assetId}`;
const processFiles = computed(() => props.files.filter(file => /(?:^|\/)Process_data[^/]*\.nc$/i.test(file.file_path)));
const dailyFiles = computed(() => props.files.filter(file => /day_\d{4}_\d{2}_\d{2}.*\.nc$/i.test(file.file_path)));
const scope = () => [auth.user?.id, project.currentProjectId, props.experimentId,
  JSON.stringify(props.files.map(file => [file.id, file.file_path, file.file_size_bytes])), processFileId.value];
const inventoryRequests = useScopedRequest(scope, () => { catalogs.value = []; sources.value = []; inventoryLoading.value = false; });
const plotRequests = useScopedRequest(() => [...scope(), JSON.stringify(selectedSteps.value), JSON.stringify(selectedWafers.value)],
  () => { sources.value = []; plotting.value = false; plotError.value = null; });
const availableSteps = computed(() => [...new Map(catalogs.value.flatMap(entry => entry.catalog.wafers.flatMap(wafer => wafer.steps))
  .map(step => [step.step_id, step])).values()]);
const selectedPairCount = computed(() => catalogs.value.reduce((sum, entry) => sum + entry.catalog.wafers.reduce((count, wafer) =>
  count + (selectedWafers.value.includes(key(entry.file.id, wafer.asset_id)) ? wafer.steps.filter(step => selectedSteps.value.includes(step.step_id)).length : 0), 0), 0));
watch(processFiles, files => {
  if (!files.some(file => file.id === processFileId.value)) processFileId.value = files[0]?.id ?? null;
}, { immediate: true });
watch(scope, async () => {
  selectedWafers.value = [];
  if (!processFileId.value || !dailyFiles.value.length) return;
  const ticket = inventoryRequests.begin();
  inventoryLoading.value = true;
  error.value = null;
  const entries: CatalogEntry[] = [];
  try {
    for (const file of dailyFiles.value) {
      const response = await api.get<Catalog>(`/experiments/${props.experimentId}/files/${file.id}/bosch-steps`,
        { params: { process_file_id: processFileId.value }, signal: ticket.signal });
      if (!ticket.isCurrent()) return;
      entries.push({ file, catalog: response.data });
    }
    if (ticket.isCurrent()) catalogs.value = entries;
  } catch (reason) { if (ticket.isCurrent()) error.value = getErrorMessage(reason, "Could not align process records"); }
  finally { if (ticket.isCurrent()) inventoryLoading.value = false; }
}, { immediate: true });
function selectFile(entry: CatalogEntry, checked: boolean) {
  const ids = entry.catalog.wafers.filter(wafer => !wafer.refusal).map(wafer => key(entry.file.id, wafer.asset_id));
  selectedWafers.value = checked ? [...new Set([...selectedWafers.value, ...ids])] : selectedWafers.value.filter(id => !ids.includes(id));
}
function selectAll(checked: boolean) {
  selectedWafers.value = checked ? catalogs.value.flatMap(entry => entry.catalog.wafers.filter(wafer => !wafer.refusal).map(wafer => key(entry.file.id, wafer.asset_id))) : [];
}
async function addCompanion(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  uploading.value = true;
  try { await dataStore.uploadFile(props.experimentId, file, "raw"); }
  catch (reason) { error.value = getErrorMessage(reason, "Process companion upload failed"); }
  finally { uploading.value = false; input.value = ""; }
}
async function compare() {
  if (selectedPairCount.value > 50) { plotError.value = "Select at most 50 wafer/step groups so every group has a visible trace."; return; }
  const ticket = plotRequests.begin();
  plotting.value = true;
  plotError.value = null;
  sources.value = [];
  const loaded: DatasetPlotSource[] = [];
  try {
    for (const entry of catalogs.value) {
      const members: DatasetPlotSource["members"] = [];
      for (const wafer of entry.catalog.wafers) {
        if (!selectedWafers.value.includes(key(entry.file.id, wafer.asset_id))) continue;
        for (const step of wafer.steps.filter(candidate => selectedSteps.value.includes(candidate.step_id))) {
          const response = await api.post<components["schemas"]["BoschStepPreviewOut"]>(
            `/experiments/${props.experimentId}/files/${entry.file.id}/bosch-step-preview`,
            { process_file_id: processFileId.value, asset_id: wafer.asset_id, step_id: step.step_id,
              source_sha256: entry.catalog.source_sha256, process_sha256: entry.catalog.process_sha256, max_rows: 4 },
            { signal: ticket.signal });
          if (!ticket.isCurrent()) return;
          members.push({ curveGroupLabel: `${entry.catalog.date} · ${wafer.asset_id} · ${step.label.replace("Production · ", "")}`, fileId: entry.file.id, fileName: `${basename(entry.file.file_path)} · ${wafer.asset_id} · ${step.label}`,
            dataset: response.data.dataset as unknown as SherpaDatasetDict });
        }
      }
      if (members.length) loaded.push({ experimentId: props.experimentId, name: `${entry.catalog.date} · selected processing steps`,
        members, selectedFileCount: 1, totalFileCount: 1 });
    }
    if (ticket.isCurrent() && loaded.length) sources.value = [{
      experimentId: props.experimentId, name: "Selected processing steps across days",
      members: loaded.flatMap(source => source.members),
      selectedFileCount: loaded.length, totalFileCount: loaded.length,
    }];
  } catch (reason) { if (ticket.isCurrent()) plotError.value = getErrorMessage(reason, "Selected steps could not be plotted"); }
  finally { if (ticket.isCurrent()) plotting.value = false; }
}
</script>

<style scoped>
.bosch-step-comparison { display: grid; gap: 1rem; }
.companion-selection, .step-controls { display: flex; gap: 1rem; flex-wrap: wrap; }
label { display: grid; gap: .4rem; }
select, button, input { font: inherit; }
select { min-width: 20rem; max-width: 100%; }
button { margin: .2rem; padding: .45rem .7rem; }
small { display: block; }
.day-group, .wafer-group { padding: .6rem; border: 1px solid var(--surface-border); border-radius: .4rem; }
.wafer-group { margin-top: .5rem; }
summary { cursor: pointer; }
table { width: 100%; border-collapse: collapse; margin-top: .6rem; }
th, td { text-align: left; vertical-align: top; padding: .5rem; border-bottom: 1px solid var(--surface-border); }
.chosen { background: var(--highlight-bg); }
.protocol-coverage { margin-top: .7rem; }
</style>
