<template>
  <section class="dataset-curation" :class="{ embedded }" aria-label="Sample inclusion">
    <h4 v-if="!embedded">Exclude from My Dataset</h4>
    <p v-if="!embedded">
      Use this for defective acquisitions. Save a new definition, then explicitly choose which
      analyses use it. Original files, saved runs and optimization seeds are retained.
    </p>
    <button
      v-if="!controlsOnly || error"
      type="button"
      :disabled="busy || disabled"
      @click="load()"
    >
      {{ controlsOnly ? "Retry" : embedded ? "Select samples" : "Review dataset observations" }}
    </button>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <template v-if="context">
      <p v-if="!controlsOnly">
        {{ context.selection.included_count }} of {{ context.rows.length }} observations included in
        this definition.
      </p>
      <p v-if="!controlsOnly && context.selection.decision">
        Last decision: {{ context.selection.decision.action }} —
        {{ context.selection.decision.reason }}
      </p>
      <p v-if="context.selection.review_context?.post_review" role="status">
        Post-review dataset: this definition or an ancestor was selected after diagnostic
        inspection.
        <strong v-if="context.selection.review_context.heldout_inspected"
          >Held-out observations informed the correction; derived subsets are not independent
          validation.</strong
        >
      </p>
      <label v-if="!controlsOnly && (!embedded || !matrix || !fileName)"
        >Find observation <input v-model="query" type="search"
      /></label>
      <label v-if="!controlsOnly && (!embedded || !matrix || !fileName)"
        ><input v-model="selectedOnly" type="checkbox" /> Selected only</label
      >
      <table v-if="!controlsOnly && (!embedded || !matrix || !fileName)">
        <caption>
          Exact source observations —
          {{
            selected.length
          }}
          selected
        </caption>
        <thead>
          <tr>
            <th>Select</th>
            <th>Observation</th>
            <th>Source file</th>
            <th>Source row</th>
            <th>Inclusion</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in pageRows" :key="row.sample_id" :class="{ excluded: !row.included }">
            <td>
              <input
                type="checkbox"
                :aria-label="`Curate observation ${row.sample_id}`"
                :disabled="busy || !row.source_included"
                :checked="selected.includes(row.sample_id)"
                @change="toggle(row.sample_id)"
              />
            </td>
            <td>{{ row.sample_id }}</td>
            <td>{{ row.file_name }}</td>
            <td>{{ row.source_row + 1 }}</td>
            <td>
              {{
                row.status === "source_excluded"
                  ? "Original source exclusion"
                  : row.included
                    ? "Included"
                    : "× Excluded by curation"
              }}
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="!controlsOnly && (!embedded || !matrix || !fileName)" class="actions">
        <button type="button" :disabled="page === 0" @click="page--">Previous observations</button
        ><span>Page {{ page + 1 }} / {{ pages }}</span
        ><button type="button" :disabled="page + 1 >= pages" @click="page++">
          Next observations
        </button>
      </div>
      <label v-if="!embedded">New portfolio name <input v-model="name" maxlength="120" /></label>
      <label v-if="!embedded"
        >Reason for dataset correction <textarea v-model="reason" maxlength="2000" rows="2" />
      </label>
      <div v-if="!embedded" class="actions">
        <button type="button" :disabled="!canExclude" @click="save('exclude')">
          Save portfolio with exclusions
        </button>
        <button type="button" :disabled="!canRestore" @click="save('restore')">
          Save portfolio with restored samples
        </button>
      </div>
      <p v-else-if="selected.length" role="status">
        {{
          selectionAction === "exclude"
            ? "Selected samples will be excluded when you save the portfolio below."
            : selectionAction === "restore"
              ? "Selected samples will be restored when you save the portfolio below."
              : "Select only included or only previously curated samples per portfolio."
        }}
      </p>
      <p v-if="!embedded">
        Restoring creates another definition. Original source exclusions cannot be restored here.
      </p>
    </template>
    <p v-if="!controlsOnly && embedded && context && matrix && !matrixSelections" role="status">
      Exact sample rows cannot be matched to this source matrix. Select the source file again.
    </p>
    <DataMatrixGrid
      v-if="!controlsOnly && embedded && matrix"
      :matrix="matrix"
      :selection-rows="matrixSelections ?? undefined"
      :selection-disabled="busy || disabled"
      @toggle-sample="toggle"
    />
    <section v-if="saved" aria-label="Dependent workflow updates">
      <h4>Update dependent workflows deliberately</h4>
      <p>
        Saved “{{ saved.name }}”. Updating a workflow changes its future runs; run it again to
        calculate new results. Existing results remain unchanged.
      </p>
      <button type="button" :disabled="busy || disabled" @click="loadDependents">
        Refresh dependent workflows
      </button>
      <p v-if="dependentsLoaded && !dependents.length">
        No workflows remain bound to the parent definition. Other source bindings and campaign seeds
        are preserved.
      </p>
      <ul>
        <li v-for="item in dependents" :key="`${item.workflow_id}:${item.source_node_id}`">
          <strong>{{ item.workflow_name }}</strong> · {{ item.source_node_id }}
          <span v-if="item.blocked_reason"> — {{ item.blocked_reason }}</span>
          <button v-else type="button" :disabled="busy || disabled" @click="apply(item)">
            Update {{ item.workflow_name }} to {{ saved.name }}
          </button>
        </li>
      </ul>
    </section>
  </section>
</template>
<script setup lang="ts">
import { computed, ref, watch } from "vue";
import api from "@/api/client";
import type {
  CurationSource,
  CurationObservation,
  SampleInclusionState,
} from "@/utils/datasetCuration";
import type { DataMatrixResponse } from "@/stores/data";
import DataMatrixGrid from "@/views/data/DataMatrixGrid.vue";
interface MatrixSelectionRow {
  sampleId: string;
  checked: boolean;
  sourceIncluded: boolean;
}
const props = defineProps<{
  source: CurationSource;
  matrix?: DataMatrixResponse | null;
  fileName?: string | null;
  seedIds?: string[];
  disabled?: boolean;
  embedded?: boolean;
  prepareSource?: () => Promise<void>;
  controlsOnly?: boolean;
  autoLoad?: boolean;
}>();
const emit = defineEmits<{
  saved: [view: { id: number; name: string; selection_sha256: string }];
  applied: [workflowId: number];
  selectionChanged: [action: "exclude" | "restore" | "mixed" | null];
  inclusionChanged: [state: SampleInclusionState];
}>();
type Row = CurationObservation & { included: boolean; source_included: boolean; status: string };
type Context = {
  selection_sha256: string;
  observations_sha256: string;
  rows: Row[];
  selection: {
    included_count: number;
    decision?: { action: string; reason: string };
    review_context?: { post_review: boolean; heldout_inspected: boolean };
  };
};
type Dependent = {
  workflow_id: number;
  workflow_name: string;
  source_node_id: string;
  expected_revision: number | null;
  expected_graph_digest: string;
  blocked_reason: string | null;
};
const context = ref<Context | null>(null),
  saved = ref<{ id: number; name: string; selection_sha256: string } | null>(null);
const selected = ref<string[]>([]),
  query = ref(""),
  selectedOnly = ref(false),
  page = ref(0),
  name = ref(""),
  reason = ref("");
const busy = ref(false),
  error = ref(""),
  message = ref(""),
  dependents = ref<Dependent[]>([]),
  dependentsLoaded = ref(false);
let generation = 0;
let admittedSource: CurationSource | null = null;
let previousCohortKey: string | null = null;
function cohortKey(source: CurationSource): string {
  return JSON.stringify({
    experiment_id: source.experiment_id,
    parent_view_id: source.parent_view_id ?? null,
    parent_sha256: source.parent_sha256 ?? null,
    stage: source.stage,
    selected_file_ids: source.selected_file_ids,
    asset_id: source.asset_id,
  });
}
watch(
  () => JSON.stringify(props.source),
  () => {
    const nextCohortKey = cohortKey(props.source);
    const cohortChanged = previousCohortKey !== nextCohortKey;
    previousCohortKey = nextCohortKey;
    generation++;
    busy.value = false;
    saved.value = null;
    admittedSource = null;
    if (cohortChanged) {
      context.value = null;
      selected.value = [];
    }
    dependents.value = [];
    dependentsLoaded.value = false;
    message.value = "";
    error.value = "";
  },
  { immediate: true },
);
watch(
  () => [JSON.stringify(props.source), props.disabled, props.autoLoad] as const,
  () => {
    if (props.autoLoad && !props.disabled && !admittedSource && !busy.value && !saved.value)
      void load(false);
  },
  { immediate: true, flush: "post" },
);
watch(
  [context, selected, busy, () => props.disabled],
  () =>
    emit("inclusionChanged", {
      rows: (context.value?.rows ?? []).map((row) => ({
        sampleId: row.sample_id,
        included: selected.value.includes(row.sample_id) ? !row.included : row.included,
        editable: row.source_included && !busy.value && !props.disabled,
      })),
      loading: busy.value || Boolean(props.disabled),
    }),
  { immediate: true, deep: true },
);
watch(
  () => props.seedIds,
  (ids) => {
    if (context.value)
      selected.value = (ids || []).filter((id) =>
        context.value!.rows.some((r) => r.sample_id === id && r.source_included),
      );
  },
  { deep: true },
);
const filtered = computed(() =>
  (context.value?.rows || []).filter(
    (r) =>
      r.sample_id.toLowerCase().includes(query.value.toLowerCase()) &&
      (!selectedOnly.value || selected.value.includes(r.sample_id)),
  ),
);
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / 50)));
const pageRows = computed(() => filtered.value.slice(page.value * 50, (page.value + 1) * 50));
watch([query, selectedOnly, pages], () => {
  page.value = Math.min(page.value, pages.value - 1);
});
const chosen = computed(() =>
  (context.value?.rows || []).filter((r) => selected.value.includes(r.sample_id)),
);
const matrixSelections = computed<Array<MatrixSelectionRow | null> | null>(() => {
  if (!props.matrix || !props.fileName || !context.value) return null;
  const sourceRows = context.value.rows.filter((row) => row.file_name === props.fileName);
  if (sourceRows.length !== props.matrix.total_rows) return null;
  const byIndex = new Map<number, Row>();
  for (const row of sourceRows) {
    if (byIndex.has(row.source_row)) return null;
    byIndex.set(row.source_row, row);
  }
  const mapped: Array<MatrixSelectionRow | null> = [];
  for (let index = 0; index < props.matrix.matrix.length; index++) {
    const row = byIndex.get(props.matrix.row_start + index);
    if (!row) return null;
    mapped.push({
      sampleId: row.sample_id,
      checked: selected.value.includes(row.sample_id) ? !row.included : row.included,
      sourceIncluded: row.source_included,
    });
  }
  return mapped;
});
const canSave = computed(
  () =>
    !busy.value &&
    !props.disabled &&
    !!name.value.trim() &&
    !!reason.value.trim() &&
    chosen.value.length > 0 &&
    chosen.value.every((r) => r.source_included),
);
const canExclude = computed(() => canSave.value && chosen.value.every((r) => r.included));
const canRestore = computed(() => canSave.value && chosen.value.every((r) => !r.included));
const selectionAction = computed<"exclude" | "restore" | "mixed" | null>(() => {
  if (!selected.value.length || !context.value) return null;
  if (chosen.value.length !== selected.value.length || chosen.value.some((r) => !r.source_included))
    return "mixed";
  if (chosen.value.every((r) => r.included)) return "exclude";
  if (chosen.value.every((r) => !r.included)) return "restore";
  return "mixed";
});
watch(selectionAction, (action) => emit("selectionChanged", action), { immediate: true });
function toggle(id: string) {
  selected.value = selected.value.includes(id)
    ? selected.value.filter((i) => i !== id)
    : [...selected.value, id];
}
function detail(e: any): string {
  return typeof e?.response?.data?.detail === "string"
    ? e.response.data.detail
    : e?.message || "Dataset curation is unavailable. Reload and try again.";
}
function body(source: CurationSource) {
  const { experiment_id: _id, ...rest } = source;
  return rest;
}
async function load(refreshSource = true) {
  const requestedExperiment = props.source.experiment_id;
  const previousSelection = context.value ? [...selected.value] : (props.seedIds || []);
  let ticket = ++generation;
  busy.value = true;
  error.value = "";
  if (!context.value) selected.value = [];
  try {
    if (refreshSource && props.prepareSource) {
      await props.prepareSource();
      if (props.source.experiment_id !== requestedExperiment) return;
      ticket = ++generation;
      busy.value = true;
    }
    const source = JSON.parse(JSON.stringify(props.source)) as CurationSource;
    const result = await api.post<Context>(
      `/experiments/${source.experiment_id}/dataset-views/curation-context`,
      body(source),
    );
    if (ticket !== generation) return;
    if (!result.data?.selection || !Array.isArray(result.data.rows))
      throw new Error("Sample inclusion could not be loaded. Refresh the dataset and retry.");
    admittedSource = source;
    context.value = result.data;
    page.value = 0;
    selected.value = previousSelection.filter((id) =>
      result.data.rows.some((r) => r.sample_id === id && r.source_included),
    );
  } catch (e) {
    if (props.source.experiment_id === requestedExperiment) {
      ticket = generation;
      error.value = detail(e);
    }
  } finally {
    if (ticket === generation) busy.value = false;
  }
}
async function save(action: "exclude" | "restore") {
  if (
    !context.value ||
    !admittedSource ||
    !(action === "exclude" ? canExclude.value : canRestore.value)
  )
    return;
  const ticket = generation,
    source = admittedSource;
  busy.value = true;
  error.value = "";
  try {
    const result = await api.post(`/experiments/${source.experiment_id}/dataset-views/curations`, {
      ...body(source),
      name: name.value.trim(),
      reason: reason.value.trim(),
      action,
      sample_ids: [...selected.value],
      expected_selection_sha256: context.value.selection_sha256,
      expected_observations_sha256: context.value.observations_sha256,
    });
    if (ticket !== generation) return;
    saved.value = result.data;
    context.value = null;
    message.value =
      "New dataset definition saved. Choose workflow updates below; no workflow was changed automatically.";
    await loadDependents();
    if (ticket === generation) emit("saved", result.data);
  } catch (e) {
    if (ticket === generation) error.value = detail(e);
  } finally {
    if (ticket === generation) busy.value = false;
  }
}
async function saveWith(
  action: "exclude" | "restore",
  portfolioName: string,
  correctionReason: string,
) {
  name.value = portfolioName;
  reason.value = correctionReason;
  if (selectionAction.value !== action) return;
  await save(action);
}
function toggleSample(id: string): void {
  if (
    busy.value ||
    props.disabled ||
    !context.value?.rows.some((row) => row.sample_id === id && row.source_included)
  )
    return;
  toggle(id);
}
defineExpose({ saveWith, toggleSample });
async function loadDependents() {
  if (!saved.value || !admittedSource) return;
  const ticket = generation,
    viewId = saved.value.id;
  try {
    const result = await api.get<Dependent[]>(
      `/experiments/${admittedSource.experiment_id}/dataset-views/${viewId}/dependents`,
    );
    if (ticket === generation && saved.value?.id === viewId) {
      dependents.value = result.data;
      dependentsLoaded.value = true;
    }
  } catch (e) {
    if (ticket === generation) error.value = detail(e);
  }
}
async function apply(item: Dependent) {
  if (!saved.value || !admittedSource || busy.value || props.disabled || item.blocked_reason)
    return;
  const ticket = generation;
  busy.value = true;
  error.value = "";
  try {
    await api.post(
      `/experiments/${admittedSource.experiment_id}/dataset-views/${saved.value.id}/apply`,
      {
        workflow_id: item.workflow_id,
        source_node_id: item.source_node_id,
        expected_revision: item.expected_revision,
        expected_graph_digest: item.expected_graph_digest,
        idempotency_key: crypto.randomUUID(),
      },
    );
    if (ticket !== generation) return;
    message.value = `${item.workflow_name} updated. Rerun it to calculate results with this definition.`;
    await loadDependents();
    if (ticket === generation) emit("applied", item.workflow_id);
  } catch (e) {
    if (ticket === generation) error.value = detail(e);
  } finally {
    if (ticket === generation) busy.value = false;
  }
}
</script>
<style scoped>
.dataset-curation {
  border: 1px solid var(--surface-border, var(--ss-border-strong));
  padding: 1rem;
  margin: 1rem 0;
}
.dataset-curation.embedded {
  border: 0;
  padding: 0;
}
label {
  display: block;
  margin: 0.6rem 0;
}
input {
  margin-left: 0.5rem;
}
input[maxlength="120"] {
  width: min(24rem, 90%);
}
textarea {
  display: block;
  width: min(48rem, 95%);
  font: inherit;
  margin-top: 0.4rem;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  text-align: left;
  padding: 0.4rem;
}
.excluded {
  color: var(--text-color-secondary, var(--ss-text-muted));
  background: var(--surface-100, var(--ss-surface-subtle));
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.7rem;
  margin: 0.7rem 0;
}
li {
  margin: 0.7rem 0;
}
</style>
