<template>
  <section aria-label="Saved PLS-DA diagnostics" class="plsda-diagnostics">
    <h3>PLS-DA sample diagnostics</h3>
    <p>
      Calibration scores, T²/Q influence and selected-sample variable terms from this fitted
      classifier. A screening flag asks for inspection; it does not establish a bad measurement or
      validate class predictions.
    </p>
    <p v-if="loading" role="status">Loading saved classifier evidence…</p>
    <p v-else-if="error" role="status">{{ error }}</p>
    <template v-else-if="receipt">
      <p>
        {{ receipt.reference_count }} calibration observations · {{ receipt.components }} latent
        variables · {{ receipt.space }}. Component loadings describe model patterns; the bars below
        are the selected sample's additive Q and signed T² terms.
      </p>
      <p>
        Fitted global screen: {{ receipt.screening_method }}; Q limit method
        {{ receipt.q_limit_method }}; score covariance rank {{ receipt.score_covariance_rank }} /
        {{ receipt.components }}. This is a calibration cohort view, not independent test evidence.
      </p>
      <div class="plsda-diagnostics__controls">
        <label
          >Score X
          <select v-model.number="scoreX">
            <option v-for="i in receipt.components" :key="i" :value="i - 1">LV {{ i }}</option>
          </select></label
        >
        <label v-if="receipt.components > 1"
          >Score Y
          <select v-model.number="scoreY">
            <option v-for="i in receipt.components" :key="i" :value="i - 1">LV {{ i }}</option>
          </select></label
        >
        <button type="button" @click="selected = []">Clear selection</button>
      </div>
      <div class="plsda-diagnostics__plots">
        <PlotlyChart
          :data="scoreTraces"
          :layout="scoreLayout"
          :config="config"
          :selected-point-ids="selected"
          @selected="selectPoints"
          @deselect="selected = []"
        />
        <PlotlyChart
          :data="influenceTraces"
          :layout="influenceLayout"
          :config="config"
          :selected-point-ids="selected"
          @selected="selectPoints"
          @deselect="selected = []"
        />
      </div>
      <p v-if="receipt.t2_unavailable_reason || receipt.q_unavailable_reason" role="note">
        {{ receipt.t2_unavailable_reason || receipt.q_unavailable_reason }}. An unavailable
        statistic is not a pass.
      </p>
      <p>
        {{ selected.length }} observations selected. Select points by lasso or use the checkboxes
        below.
      </p>
      <label>Find observation <input v-model="query" type="search" /></label>
      <table>
        <caption>
          Linked calibration observations
        </caption>
        <thead>
          <tr>
            <th>Select</th>
            <th>Observation</th>
            <th>Class</th>
            <th>T²</th>
            <th>Q</th>
            <th>Screening</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in pageRows"
            :key="row.id"
            :class="{ 'is-selected': selectedSet.has(row.id) }"
          >
            <td>
              <input
                type="checkbox"
                :aria-label="`Select sample ${row.id}`"
                :checked="selectedSet.has(row.id)"
                @change="toggle(row.id)"
              />
            </td>
            <td>{{ row.id }}</td>
            <td>{{ row.class }}</td>
            <td>{{ number(row.t2) }}</td>
            <td>{{ number(row.q) }}</td>
            <td>
              {{
                row.outside_t2 || row.outside_q
                  ? "Outside global screen"
                  : row.outside_t2 == null || row.outside_q == null
                    ? "Unavailable"
                    : "Within global screen"
              }}
            </td>
          </tr>
        </tbody>
      </table>
      <div class="plsda-diagnostics__controls">
        <button type="button" :disabled="page === 0" @click="page--">Previous</button>
        <span>Page {{ page + 1 }} / {{ pages }}</span>
        <button type="button" :disabled="page + 1 >= pages" @click="page++">Next</button>
      </div>
      <template v-if="focused">
        <h4>Why {{ focused.id }} has this T²/Q</h4>
        <p>
          Q = {{ number(focused.q) }} {{ receipt.q_units }}; T² = {{ number(focused.t2) }}
          {{ receipt.t2_units }}. Reference: {{ receipt.reference_population }} (n={{
            receipt.reference_count
          }}).
        </p>
        <div class="plsda-diagnostics__plots">
          <PlotlyChart :data="qTermTraces" :layout="qTermLayout" :config="config" />
          <PlotlyChart
            v-if="focused.t2 != null"
            :data="t2TermTraces"
            :layout="t2TermLayout"
            :config="config"
          />
        </div>
        <p>
          Unshown Q contribution: {{ number(focused.terms.omitted_q) }}; unshown signed T²
          contribution: {{ number(focused.terms.omitted_t2) }} (absolute mass
          {{ number(focused.terms.omitted_t2_absolute) }}). Signed T² terms can be negative and
          should be interpreted together.
        </p>
      </template>
      <section aria-label="Ask Sherpa about saved PLS-DA diagnostics">
        <h4>Ask Sherpa</h4>
        <p v-if="!advisorAvailable">Diagnostic interpretation requires hosted Sherpa Advisor.</p>
        <template v-else>
          <button type="button" :disabled="advisorDisabled" @click="askAdvisor('samples')">
            Explain selected samples
          </button>
          <button
            type="button"
            :disabled="advisorDisabled || !focused"
            @click="askAdvisor('terms')"
          >
            Explain this sample's Q and T² contributions
          </button>
          <button type="button" :disabled="advisorDisabled" @click="askAdvisor('next')">
            What should I inspect next?
          </button>
          <p v-if="advisorError" role="alert">{{ advisorError }}</p>
        </template>
      </section>
      <button v-if="workflowId && selected.length" type="button" @click="emit('open-workflow')">
        Open source workflow
      </button>
      <p>
        This saved PLS-DA diagnostic view is read-only. It does not carry a selection into workflow
        exclusion; review the source dataset and create a new fit deliberately. Saved fitted
        evidence remains unchanged after a later decision.
      </p>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import api from "@/api/client";
import PlotlyChart from "@/components/PlotlyChart.vue";
import { useAppConfig } from "@/composables/useAppConfig";
import { requestAdvisorPrompt } from "@/lib/advisorPromptActions";
import { useSherpaStore } from "@/stores/sherpa";
import { selectedSampleIds } from "@/utils/sampleReview";

type Terms = {
  variables: [number, number, number | null][];
  omitted_q: number;
  omitted_t2: number | null;
  omitted_t2_absolute: number | null;
};
type Row = {
  id: string;
  class: string;
  role: string;
  scores: number[];
  t2: number | null;
  q: number;
  outside_t2: boolean | null;
  outside_q: boolean | null;
  terms: Terms;
};
type Receipt = {
  schema_version: string;
  model_kind: string;
  reference_population: string;
  reference_count: number;
  components: number;
  feature_values: number[] | null;
  feature_labels: string[] | null;
  feature_units: string | null;
  space: string;
  q_units: string;
  t2_units: string;
  t2_limit: number | null;
  q_limit: number | null;
  screening_method: string;
  q_limit_method: string;
  score_covariance_rank: number;
  t2_unavailable_reason: string | null;
  q_unavailable_reason: string | null;
  rows: Row[];
};
const props = defineProps<{
  artifactUid: string;
  projectId: number;
  nodeId: string;
  workflowId: number | null;
}>();
const emit = defineEmits<{ "open-workflow": [] }>();
const { appConfig, appMode, isFeatureEnabled } = useAppConfig();
const sherpa = useSherpaStore();
const receipt = ref<Receipt | null>(null);
const receiptHash = ref("");
const runId = ref(0);
const advisorError = ref("");
const loading = ref(false);
const error = ref("");
const selected = ref<string[]>([]);
const query = ref("");
const page = ref(0);
const scoreX = ref(0);
const scoreY = ref(1);
let request = 0;
watch(
  () => [props.artifactUid, props.projectId, props.nodeId] as const,
  async (_, __, onCleanup) => {
    const current = ++request;
    const controller = new AbortController();
    onCleanup(() => controller.abort());
    receipt.value = null;
    receiptHash.value = "";
    runId.value = 0;
    selected.value = [];
    loading.value = true;
    error.value = "";
    try {
      const { data } = await api.get<{
        run_id: number;
        node_id: string;
        receipt_sha256: string;
        receipt: Receipt;
      }>(`/models/${encodeURIComponent(props.artifactUid)}/plsda-diagnostics`, {
        params: { project_id: props.projectId },
        signal: controller.signal,
      });
      if (current !== request || controller.signal.aborted) return;
      if (
        data.node_id !== props.nodeId ||
        data.receipt.schema_version !== "spectrasherpa-plsda-sample-diagnostics/1"
      )
        throw new Error("Saved classifier diagnostic identity does not match this model.");
      receipt.value = data.receipt;
      receiptHash.value = data.receipt_sha256;
      runId.value = data.run_id;
      scoreX.value = 0;
      scoreY.value = Math.min(1, data.receipt.components - 1);
    } catch (cause) {
      if (current === request && !controller.signal.aborted)
        error.value =
          (cause as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
          "Exact PLS-DA sample diagnostics are unavailable for this model.";
    } finally {
      if (current === request) loading.value = false;
    }
  },
  { immediate: true },
);
const selectedSet = computed(() => new Set(selected.value));
const advisorAvailable = computed(
  () =>
    appMode.value !== "local" &&
    appConfig.value?.advisorContextPolicy !== "receipt" &&
    (isFeatureEnabled("sherpaAdvisor") || appConfig.value?.siteProfile === "pro"),
);
const advisorDisabled = computed(
  () =>
    !receipt.value ||
    !selected.value.length ||
    !props.workflowId ||
    !runId.value ||
    sherpa.chatState === "chatting",
);
function askAdvisor(kind: "samples" | "terms" | "next") {
  if (!advisorAvailable.value || advisorDisabled.value || !receipt.value || !props.workflowId)
    return;
  try {
    advisorError.value = "";
    const selectedIds =
      kind === "terms" ? (focused.value ? [focused.value.id] : []) : [...selected.value];
    if (!selectedIds.length || new Set(selectedIds).size !== selectedIds.length)
      throw new Error("Select saved observations first.");
    const selectAll = selectedIds.length === receipt.value.rows.length;
    if (
      !selectAll &&
      (selectedIds.length > 1024 ||
        selectedIds.reduce((n, id) => n + new TextEncoder().encode(id).length, 0) > 4096)
    )
      throw new Error("Narrow the selection before asking Sherpa.");
    const prompts = {
      samples:
        "Explain these selected saved PLS-DA calibration samples using their exact T-squared and Q evidence. Distinguish global screening from classification validity.",
      terms:
        "Explain this saved PLS-DA sample's Q and signed T-squared variable terms. Distinguish them from component loadings and chemical causes; include omitted mass.",
      next: "What should I inspect next for these saved PLS-DA calibration samples, without treating screening as a class probability or automatic exclusion?",
    };
    requestAdvisorPrompt(prompts[kind], {
      diagnosticScope: {
        project_id: props.projectId,
        model_kind: "plsda",
        reference: {
          kind: "saved_plsda",
          artifact_uid: props.artifactUid,
          workflow_id: props.workflowId,
          run_id: runId.value,
          node_id: props.nodeId,
          receipt_sha256: receiptHash.value,
          selected_ids: selectAll ? [] : selectedIds,
          select_all: selectAll,
          variable_ids: [],
        },
      },
    });
  } catch (cause) {
    advisorError.value =
      cause instanceof Error ? cause.message : "Saved Advisor evidence is unavailable.";
  }
}
const allowed = computed(() => new Set(receipt.value?.rows.map((r) => r.id) || []));
const focused = computed(
  () => receipt.value?.rows.find((row) => selectedSet.value.has(row.id)) || null,
);
const palette = ["#0072B2", "#009E73", "#D55E00", "#CC79A7", "#E69F00", "#56B4E9"];
const classColors = computed(
  () =>
    new Map(
      [...new Set(receipt.value?.rows.map((r) => r.class) || [])]
        .sort()
        .map((label, i) => [label, palette[i % palette.length]]),
    ),
);
const config = { responsive: true, displaylogo: false };
const layout = { height: 380, dragmode: "lasso", margin: { t: 45, l: 65, r: 20, b: 70 } };
function number(value: number | null | undefined) {
  return value == null ? "—" : Number(value).toPrecision(5);
}
function traces(x: (r: Row) => number | null, y: (r: Row) => number | null) {
  const groups = new Map<string, Row[]>();
  for (const row of receipt.value?.rows || []) {
    if (x(row) == null || y(row) == null) continue;
    const rows = groups.get(row.class) || [];
    rows.push(row);
    groups.set(row.class, rows);
  }
  return [...groups].map(([label, rows]) => ({
    type: "scatter",
    mode: "markers",
    name: label,
    x: rows.map(x),
    y: rows.map(y),
    customdata: rows.map((r) => r.id),
    marker: { color: classColors.value.get(label), size: 8 },
    selected: { marker: { size: 12, opacity: 1 } },
    unselected: { marker: { opacity: 0.25 } },
    hovertemplate: "%{customdata}<br>x=%{x:.4g}<br>y=%{y:.4g}<extra>%{fullData.name}</extra>",
  }));
}
const scoreTraces = computed(() =>
  traces(
    (r) => r.scores[scoreX.value] ?? null,
    (r) => (receipt.value?.components === 1 ? 0 : (r.scores[scoreY.value] ?? null)),
  ),
);
const scoreLayout = computed(() => ({
  ...layout,
  title: "PLS-DA calibration scores",
  xaxis: { title: `LV ${scoreX.value + 1}` },
  yaxis: {
    title: receipt.value?.components === 1 ? "Zero display axis" : `LV ${scoreY.value + 1}`,
  },
  uirevision: `plsda-score:${props.artifactUid}:${scoreX.value}:${scoreY.value}`,
}));
const rowOrder = computed(() => new Map(receipt.value?.rows.map((row, index) => [row.id, index + 1]) || []));
const influenceTraces = computed(() =>
  traces(
    (r) => (qOnly.value ? (rowOrder.value.get(r.id) ?? null) : r.t2),
    (r) => r.q,
  ),
);
const qOnly = computed(() => receipt.value?.rows.every((row) => row.t2 == null) ?? false);
const influenceLayout = computed(() => ({
  ...layout,
  title: qOnly.value
    ? "Q residual by calibration observation order — T² unavailable"
    : "Predictor influence — T² versus Q",
  xaxis: { title: qOnly.value ? "Calibration observation order (one-based)" : "Hotelling T²" },
  yaxis: { title: "Q residual" },
  uirevision: `plsda-influence:${props.artifactUid}`,
  shapes: [
    ...(receipt.value?.t2_limit != null
      ? [
          {
            type: "line",
            x0: receipt.value.t2_limit,
            x1: receipt.value.t2_limit,
            y0: 0,
            y1: 1,
            yref: "paper",
            line: { color: "#555" },
          },
        ]
      : []),
    ...(receipt.value?.q_limit != null
      ? [
          {
            type: "line",
            x0: 0,
            x1: 1,
            xref: "paper",
            y0: receipt.value.q_limit,
            y1: receipt.value.q_limit,
            line: { color: "#555" },
          },
        ]
      : []),
  ],
}));
const termVariables = computed(() => {
  const row = focused.value;
  if (!row) return { x: [] as (string | number)[], variables: [] as Terms["variables"] };
  const variables = row.terms.variables;
  const x = variables.map(
    ([i]) =>
      receipt.value?.feature_labels?.[i] ||
      (receipt.value?.feature_values?.[i] ?? `Variable ${i + 1}`),
  );
  return { x, variables };
});
const qTermTraces = computed(() => [
  {
    type: "bar",
    name: "Q contribution",
    x: termVariables.value.x,
    y: termVariables.value.variables.map(([, q]) => q),
  },
]);
const t2TermTraces = computed(() => [
  {
    type: "bar",
    name: "Signed T² contribution",
    x: termVariables.value.x,
    y: termVariables.value.variables.map(([, , t]) => t),
  },
]);
const qTermLayout = computed(() => ({
  ...layout,
  dragmode: "zoom",
  title: `Selected-sample Q terms — ${focused.value?.id || ""}`,
  xaxis: { title: receipt.value?.feature_units || "Fitted variable" },
  yaxis: { title: `Q contribution (${receipt.value?.q_units || ""})` },
  uirevision: `plsda-q-terms:${props.artifactUid}:${focused.value?.id}`,
}));
const t2TermLayout = computed(() => ({
  ...layout,
  dragmode: "zoom",
  title: `Selected-sample signed T² terms — ${focused.value?.id || ""}`,
  xaxis: { title: receipt.value?.feature_units || "Fitted variable" },
  yaxis: { title: `Signed T² contribution (${receipt.value?.t2_units || ""})` },
  uirevision: `plsda-t2-terms:${props.artifactUid}:${focused.value?.id}`,
}));
function selectPoints(event: unknown) {
  selected.value = selectedSampleIds(event, allowed.value);
}
function toggle(id: string) {
  selected.value = selectedSet.value.has(id)
    ? selected.value.filter((value) => value !== id)
    : [...selected.value, id];
}
const filtered = computed(() =>
  (receipt.value?.rows || []).filter((row) =>
    row.id.toLowerCase().includes(query.value.toLowerCase()),
  ),
);
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / 50)));
const pageRows = computed(() => filtered.value.slice(page.value * 50, (page.value + 1) * 50));
watch([query, pages], () => {
  page.value = 0;
});
</script>

<style scoped>
.plsda-diagnostics {
  margin-top: 1.5rem;
}
.plsda-diagnostics__plots {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 1rem;
}
.plsda-diagnostics__controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem;
  margin: 0.75rem 0;
}
.plsda-diagnostics table {
  width: 100%;
  border-collapse: collapse;
  margin: 1rem 0;
}
.plsda-diagnostics th,
.plsda-diagnostics td {
  border-bottom: 1px solid var(--surface-border);
  padding: 0.35rem;
  text-align: left;
}
.plsda-diagnostics tr.is-selected {
  background: var(--surface-hover);
}
</style>
