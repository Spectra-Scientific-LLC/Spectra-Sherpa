<template>
  <main class="audit-page">
    <header class="audit-header">
      <div>
        <p class="eyebrow">Audit</p>
        <h1>Evidence Workbench</h1>
      </div>
      <div class="capability-strip" aria-label="Audit capabilities">
        <span :class="['capability', { enabled: canQuery }]">Query</span>
        <span :class="['capability', { enabled: auditConfig?.fullPipeline }]">Chain</span>
        <span :class="['capability', { enabled: auditConfig?.reportPack }]">Pack</span>
        <span :class="['capability', { enabled: auditConfig?.exportAudited }]">Export</span>
      </div>
    </header>

    <section v-if="!hasAnyAuditCapability" class="notice">
      <i class="pi pi-lock" aria-hidden="true"></i>
      <span>Audit capabilities are not enabled for this deployment.</span>
      <a class="notice-action" href="mailto:support@spectrascientific.com?subject=Spectra%20Sherpa%20audit%20upgrade">
        Request upgrade
      </a>
    </section>

    <section class="workbench-layout">
      <section class="filter-panel" aria-labelledby="audit-filters-heading">
        <div class="section-heading">
          <div>
            <p class="eyebrow">Scope</p>
            <h2 id="audit-filters-heading">Evidence Filters</h2>
          </div>
          <button class="ghost-action" type="button" :disabled="isLoadingEvents || !canQuery" @click="refreshEvents">
            <i class="pi pi-refresh" aria-hidden="true"></i>
            <span>{{ isLoadingEvents ? "Loading" : "Refresh" }}</span>
          </button>
        </div>

        <form class="field-grid" @submit.prevent="refreshEvents">
          <label>
            Scope
            <select v-model="form.scopeType">
              <option value="">Any</option>
              <option value="Project">Project</option>
              <option value="Workflow">Workflow</option>
              <option value="ModelArtifact">Model artifact</option>
              <option value="ProjectDataSource">Project data source</option>
            </select>
          </label>

          <label>
            Scope ID
            <input v-model.trim="form.scopeId" type="text" placeholder="Optional" />
          </label>

          <label>
            Action
            <input v-model.trim="form.action" type="text" placeholder="workflow.updated" />
          </label>

          <label>
            Target Type
            <input v-model.trim="form.targetType" type="text" placeholder="Workflow" />
          </label>

          <label>
            Target ID
            <input v-model.trim="form.targetId" type="text" placeholder="Optional" />
          </label>

          <label>
            Request ID
            <input v-model.trim="form.requestId" type="text" placeholder="Optional" />
          </label>

          <label>
            Since
            <input v-model="form.since" type="datetime-local" />
          </label>

          <label>
            Until
            <input v-model="form.until" type="datetime-local" />
          </label>

          <label>
            Pack Format
            <select v-model="form.format">
              <option value="jsonl">JSONL</option>
              <option value="csv">CSV</option>
            </select>
          </label>

          <label class="checkbox-field">
            <input v-model="form.includePdf" type="checkbox" />
            <span>Include PDF summary</span>
          </label>
        </form>

        <div class="action-row">
          <button
            class="primary-action"
            type="button"
            data-testid="generate-report-pack"
            :disabled="isGenerating || !auditConfig?.reportPack"
            @click="generatePack"
          >
            <i class="pi pi-file-export" aria-hidden="true"></i>
            <span>{{ isGenerating ? "Generating" : "Generate Pack" }}</span>
          </button>
          <button
            class="secondary-action"
            type="button"
            data-testid="export-jsonl"
            :disabled="isExporting || !auditConfig?.exportAudited"
            @click="exportAudit('jsonl')"
          >
            <i class="pi pi-download" aria-hidden="true"></i>
            <span>JSONL</span>
          </button>
          <button
            class="secondary-action"
            type="button"
            data-testid="export-csv"
            :disabled="isExporting || !auditConfig?.exportAudited"
            @click="exportAudit('csv')"
          >
            <i class="pi pi-download" aria-hidden="true"></i>
            <span>CSV</span>
          </button>
        </div>

        <div v-if="!auditConfig?.reportPack || !auditConfig?.exportAudited" class="inline-note">
          <i class="pi pi-info-circle" aria-hidden="true"></i>
          <span>Unavailable actions are controlled by audit entitlements from the server.</span>
        </div>
      </section>

      <aside class="status-panel" aria-live="polite">
        <div class="chain-card">
          <div>
            <p class="eyebrow">Chain Health</p>
            <h2>{{ chainStatusLabel }}</h2>
          </div>
          <button
            class="ghost-action"
            type="button"
            data-testid="verify-chain"
            :disabled="isCheckingChain || !auditConfig?.fullPipeline"
            @click="refreshChainStatus"
          >
            <i class="pi pi-shield" aria-hidden="true"></i>
            <span>{{ isCheckingChain ? "Checking" : "Verify" }}</span>
          </button>
        </div>

        <div v-if="errorMessage" class="status error">
          <i class="pi pi-exclamation-triangle" aria-hidden="true"></i>
          <span>{{ errorMessage }}</span>
        </div>

        <div v-if="lastPack" class="manifest-panel">
          <div class="manifest-head">
            <div>
              <p class="eyebrow">Latest Pack</p>
              <h2>{{ shortId(lastPack.packId) }}</h2>
            </div>
            <span :class="['verify-badge', { ok: lastPack.verificationOk }]">
              {{ lastPack.verificationOk ? "Verified" : "Blocked" }}
            </span>
          </div>

          <dl class="metrics">
            <div>
              <dt>Rows</dt>
              <dd>{{ lastPack.rowCount }}</dd>
            </div>
            <div>
              <dt>Files</dt>
              <dd>{{ lastPack.fileCount }}</dd>
            </div>
            <div>
              <dt>SHA-256</dt>
              <dd>{{ shortId(lastPack.sha256, 12) }}</dd>
            </div>
          </dl>
        </div>

        <div v-else class="empty-panel">
          <p class="eyebrow">Report Pack</p>
          <p>Generate a pack to download manifest, evidence rows, verification proof, and validation templates.</p>
        </div>
      </aside>
    </section>

    <section class="timeline-panel" aria-labelledby="audit-timeline-heading">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Timeline</p>
          <h2 id="audit-timeline-heading">Audit Events</h2>
        </div>
        <span class="row-count">{{ events.length }} rows</span>
      </div>

      <div v-if="isLoadingEvents && events.length === 0" class="timeline-state">Loading audit events...</div>
      <div v-else-if="!canQuery" class="timeline-state">Audit query is not enabled for this deployment.</div>
      <div v-else-if="events.length === 0" class="timeline-state">No audit events match the current filters.</div>

      <ol v-else class="event-list" data-testid="audit-event-list">
        <li v-for="event in events" :key="event.id" class="event-row">
          <div class="event-marker" aria-hidden="true"></div>
          <div class="event-body">
            <div class="event-main">
              <div>
                <p class="event-action">{{ event.action }}</p>
                <p class="event-target">{{ event.target_type }} {{ event.target_id }}</p>
              </div>
              <time :datetime="event.ts_app_utc">{{ formatDate(event.ts_app_utc) }}</time>
            </div>
            <dl class="event-meta">
              <div>
                <dt>Actor</dt>
                <dd>{{ event.actor_kind }}{{ event.actor_id ? `:${event.actor_id}` : "" }}</dd>
              </div>
              <div>
                <dt>Request</dt>
                <dd>{{ shortId(event.request_id, 10) }}</dd>
              </div>
              <div>
                <dt>Event</dt>
                <dd>#{{ event.id }}</dd>
              </div>
            </dl>
            <details v-if="hasEventState(event)" class="state-details">
              <summary>State snapshot</summary>
              <pre>{{ renderEventState(event) }}</pre>
            </details>
          </div>
        </li>
      </ol>

      <button v-if="hasMoreEvents" class="load-more" type="button" :disabled="isLoadingEvents" @click="loadMoreEvents">
        <i class="pi pi-chevron-down" aria-hidden="true"></i>
        <span>{{ isLoadingEvents ? "Loading" : "Load older events" }}</span>
      </button>
    </section>
  </main>
</template>

<script setup lang="ts">
import axios from "axios";
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import { api } from "@/api";
import { useAppConfig } from "@/composables/useAppConfig";

interface AuditEventRecord {
  id: number;
  tenant_id: string;
  actor_id: number | null;
  actor_kind: string;
  action: string;
  target_type: string;
  target_id: string;
  before_state: Record<string, unknown> | null;
  after_state: Record<string, unknown> | null;
  context: Record<string, unknown> | null;
  request_id: string;
  ts_app_utc: string;
  ts_db_utc: string;
}

interface AuditEventResponse {
  events: AuditEventRecord[];
  next_cursor: string | null;
  has_more: boolean;
}

interface ChainStatus {
  ok: boolean;
  rows_checked: number;
  unchained_event_count: number;
  orphan_chain_row_count: number;
}

interface LastPack {
  packId: string;
  rowCount: number;
  fileCount: number;
  sha256: string;
  verificationOk: boolean;
}

type ExportFormat = "csv" | "jsonl";

const { appConfig } = useAppConfig();
const route = useRoute();
const auditConfig = computed(() => appConfig.value?.audit);
const canQuery = computed(() => Boolean(auditConfig.value?.localQuery || auditConfig.value?.fullPipeline));
const hasAnyAuditCapability = computed(() =>
  Boolean(canQuery.value || auditConfig.value?.reportPack || auditConfig.value?.exportAudited),
);

const isGenerating = ref(false);
const isExporting = ref(false);
const isLoadingEvents = ref(false);
const isCheckingChain = ref(false);
const errorMessage = ref("");
const lastPack = ref<LastPack | null>(null);
const chainStatus = ref<ChainStatus | null>(null);
const events = ref<AuditEventRecord[]>([]);
const nextCursor = ref<string | null>(null);
const hasMoreEvents = ref(false);

const form = reactive({
  scopeType: "Workflow",
  scopeId: "",
  action: "",
  targetType: "Workflow",
  targetId: "",
  requestId: "",
  since: "",
  until: "",
  format: "jsonl" as ExportFormat,
  includePdf: true,
});

const chainStatusLabel = computed(() => {
  if (!auditConfig.value?.fullPipeline) return "Unavailable";
  if (isCheckingChain.value && !chainStatus.value) return "Checking";
  if (!chainStatus.value) return "Not checked";
  if (chainStatus.value.ok) return "Verified";
  return "Blocked";
});

function toIso(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function toDateTimeLocal(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const offsetMs = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

function queryString(name: string): string {
  const value = route.query[name];
  return typeof value === "string" ? value : "";
}

function applyRouteQuery(): void {
  form.scopeType = queryString("scope_type") || form.scopeType;
  form.scopeId = queryString("scope_id");
  form.action = queryString("action");
  form.targetType = queryString("target_type") || form.targetType;
  form.targetId = queryString("target_id");
  form.requestId = queryString("request_id");
  form.since = queryString("since") ? toDateTimeLocal(queryString("since")) : "";
  form.until = queryString("until") ? toDateTimeLocal(queryString("until")) : "";
  form.format = queryString("format") === "csv" ? "csv" : "jsonl";
}

function withoutEmptyValues(payload: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(payload).filter(([, value]) => value !== null && value !== ""));
}

function eventFilterParams(): Record<string, unknown> {
  return withoutEmptyValues({
    action: form.action || null,
    target_type: form.targetType || null,
    target_id: form.targetId || null,
    request_id: form.requestId || null,
    since: toIso(form.since),
    until: toIso(form.until),
    limit: 50,
  });
}

function reportPackPayload(): Record<string, unknown> {
  return withoutEmptyValues({
    format: form.format,
    scope_type: form.scopeType || null,
    scope_id: form.scopeId || null,
    action: form.action || null,
    target_type: form.targetType || null,
    target_id: form.targetId || null,
    request_id: form.requestId || null,
    since: toIso(form.since),
    until: toIso(form.until),
    include_pdf: form.includePdf,
  });
}

function extractFilename(disposition: string | undefined, fallback: string): string {
  const match = disposition?.match(/filename="([^"]+)"/);
  return match?.[1] ?? fallback;
}

function shortId(value: string | null | undefined, length = 8): string {
  if (!value) return "n/a";
  return value.length > length ? value.slice(0, length) : value;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(date);
}

function hasEventState(event: AuditEventRecord): boolean {
  return Boolean(event.before_state || event.after_state || event.context);
}

function renderEventState(event: AuditEventRecord): string {
  return JSON.stringify(
    {
      before_state: event.before_state,
      after_state: event.after_state,
      context: event.context,
    },
    null,
    2,
  );
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function formatDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message?: unknown }).message;
    return typeof message === "string" ? message : null;
  }
  if (detail) return JSON.stringify(detail);
  return null;
}

async function extractApiErrorMessage(err: unknown, fallback: string): Promise<string> {
  if (!axios.isAxiosError(err)) return fallback;

  const data = err.response?.data;
  if (data instanceof Blob) {
    const text = await data.text();
    if (!text) return err.message || fallback;
    try {
      const parsed = JSON.parse(text);
      return formatDetail(parsed.detail) ?? err.message ?? fallback;
    } catch {
      return text;
    }
  }

  return formatDetail(data?.detail) ?? err.message ?? fallback;
}

async function refreshEvents(): Promise<void> {
  if (!canQuery.value) return;
  isLoadingEvents.value = true;
  errorMessage.value = "";

  try {
    const response = await api.get<AuditEventResponse>("/audit/events", {
      params: eventFilterParams(),
    });
    events.value = response.data.events;
    nextCursor.value = response.data.next_cursor;
    hasMoreEvents.value = response.data.has_more;
  } catch (err) {
    errorMessage.value = await extractApiErrorMessage(err, "Audit event query failed.");
  } finally {
    isLoadingEvents.value = false;
  }
}

async function refreshChainStatus(): Promise<void> {
  if (!auditConfig.value?.fullPipeline) return;
  isCheckingChain.value = true;

  try {
    const response = await api.get<ChainStatus>("/audit/verify");
    chainStatus.value = response.data;
  } catch (err) {
    errorMessage.value = await extractApiErrorMessage(err, "Audit chain verification failed.");
  } finally {
    isCheckingChain.value = false;
  }
}

async function loadMoreEvents(): Promise<void> {
  if (!canQuery.value || !nextCursor.value) return;
  isLoadingEvents.value = true;
  errorMessage.value = "";

  try {
    const response = await api.get<AuditEventResponse>("/audit/events", {
      params: {
        ...eventFilterParams(),
        cursor: nextCursor.value,
      },
    });
    events.value = [...events.value, ...response.data.events];
    nextCursor.value = response.data.next_cursor;
    hasMoreEvents.value = response.data.has_more;
  } catch (err) {
    errorMessage.value = await extractApiErrorMessage(err, "Older audit events could not be loaded.");
  } finally {
    isLoadingEvents.value = false;
  }
}

async function generatePack(): Promise<void> {
  if (!auditConfig.value?.reportPack) return;
  isGenerating.value = true;
  errorMessage.value = "";

  try {
    const response = await api.post("/audit/report-pack", reportPackPayload(), {
      responseType: "blob",
    });
    const blob = new Blob([response.data], { type: "application/zip" });
    downloadBlob(blob, extractFilename(response.headers["content-disposition"], "audit-report-pack.zip"));

    lastPack.value = {
      packId: response.headers["x-audit-report-pack-id"] ?? "",
      rowCount: Number(response.headers["x-audit-report-pack-row-count"] ?? 0),
      fileCount: Number(response.headers["x-audit-report-pack-file-count"] ?? 0),
      sha256: response.headers["x-audit-report-pack-sha256"] ?? "",
      verificationOk: response.headers["x-audit-report-pack-verified"] === "true",
    };
    await refreshEvents();
    await refreshChainStatus();
  } catch (err) {
    errorMessage.value = await extractApiErrorMessage(err, "Report pack generation failed.");
  } finally {
    isGenerating.value = false;
  }
}

async function exportAudit(format: ExportFormat): Promise<void> {
  if (!auditConfig.value?.exportAudited) return;
  isExporting.value = true;
  errorMessage.value = "";

  try {
    const response = await api.get("/audit/export", {
      params: {
        ...eventFilterParams(),
        format,
      },
      responseType: "blob",
    });
    const fallback = `audit-export.${format}`;
    downloadBlob(new Blob([response.data]), extractFilename(response.headers["content-disposition"], fallback));
    await refreshEvents();
  } catch (err) {
    errorMessage.value = await extractApiErrorMessage(err, "Audit export failed.");
  } finally {
    isExporting.value = false;
  }
}

onMounted(() => {
  applyRouteQuery();
  if (canQuery.value) {
    void refreshEvents();
  }
  if (auditConfig.value?.fullPipeline) {
    void refreshChainStatus();
  }
});
</script>

<style scoped>
.audit-page {
  background: #f8fafc;
  color: #0f172a;
  min-height: 100%;
  padding: 24px;
}

.audit-header,
.section-heading,
.manifest-head,
.event-main {
  align-items: center;
  display: flex;
  justify-content: space-between;
}

.audit-header {
  gap: 16px;
  margin-bottom: 20px;
}

.audit-header h1,
.section-heading h2,
.manifest-head h2 {
  font-size: 1.35rem;
  letter-spacing: 0;
  margin: 2px 0 0;
}

.eyebrow {
  color: #64748b;
  font-size: 0.76rem;
  font-weight: 700;
  letter-spacing: 0;
  margin: 0;
  text-transform: uppercase;
}

.capability-strip,
.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.capability,
.verify-badge,
.row-count {
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  color: #64748b;
  font-size: 0.82rem;
  font-weight: 700;
  padding: 6px 10px;
}

.capability.enabled,
.verify-badge.ok {
  background: #dcfce7;
  border-color: #86efac;
  color: #166534;
}

.notice,
.status,
.inline-note {
  align-items: center;
  border-radius: 8px;
  display: flex;
  gap: 8px;
}

.notice,
.inline-note {
  background: #fff7ed;
  border: 1px solid #fed7aa;
  color: #9a3412;
}

.notice {
  margin-bottom: 16px;
  padding: 12px;
}

.notice-action {
  color: #7c2d12;
  font-weight: 800;
  margin-left: auto;
  text-decoration: underline;
}

.inline-note {
  font-size: 0.86rem;
  margin-top: 12px;
  padding: 10px;
}

.workbench-layout {
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(0, 1.45fr) minmax(280px, 0.75fr);
  margin-bottom: 16px;
}

.filter-panel,
.status-panel,
.timeline-panel {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px;
}

.field-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 16px;
}

label {
  color: #334155;
  display: flex;
  flex-direction: column;
  font-size: 0.84rem;
  font-weight: 700;
  gap: 6px;
}

.checkbox-field {
  align-items: center;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  flex-direction: row;
  min-height: 38px;
  padding: 8px 10px;
}

.checkbox-field input {
  border: 0;
  min-height: auto;
  padding: 0;
  width: auto;
}

input,
select {
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  color: #0f172a;
  font: inherit;
  min-height: 38px;
  padding: 8px 10px;
}

.action-row {
  margin-top: 16px;
}

.primary-action,
.secondary-action,
.ghost-action,
.load-more {
  align-items: center;
  border-radius: 8px;
  cursor: pointer;
  display: inline-flex;
  font-weight: 700;
  gap: 8px;
  min-height: 40px;
  padding: 0 14px;
}

.primary-action {
  background: #1d4ed8;
  border: 0;
  color: #ffffff;
}

.secondary-action,
.ghost-action,
.load-more {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #0f172a;
}

.primary-action:disabled,
.secondary-action:disabled,
.ghost-action:disabled,
.load-more:disabled {
  background: #e2e8f0;
  color: #64748b;
  cursor: not-allowed;
}

.status {
  padding: 12px;
}

.status.error {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #991b1b;
}

.metrics,
.event-meta {
  display: grid;
  gap: 10px;
}

.metrics {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 16px 0 0;
}

.metrics div {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px;
}

.metrics dt,
.event-meta dt {
  color: #64748b;
  font-size: 0.74rem;
  font-weight: 700;
  margin-bottom: 4px;
  text-transform: uppercase;
}

.metrics dd,
.event-meta dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.metrics dd {
  font-size: 1rem;
  font-weight: 800;
}

.empty-panel {
  color: #475569;
  line-height: 1.5;
}

.chain-card {
  align-items: center;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  display: flex;
  justify-content: space-between;
  margin-bottom: 14px;
  padding: 12px;
}

.chain-card h2 {
  font-size: 1.1rem;
  letter-spacing: 0;
  margin: 2px 0 0;
}

.timeline-state {
  color: #475569;
  padding: 28px 0 10px;
}

.event-list {
  list-style: none;
  margin: 16px 0 0;
  padding: 0;
}

.event-row {
  display: grid;
  gap: 12px;
  grid-template-columns: 14px minmax(0, 1fr);
  padding: 12px 0;
}

.event-row + .event-row {
  border-top: 1px solid #e2e8f0;
}

.event-marker {
  background: #2563eb;
  border-radius: 999px;
  height: 10px;
  margin-top: 5px;
  width: 10px;
}

.event-action {
  font-weight: 800;
  margin: 0;
}

.event-target {
  color: #475569;
  margin: 3px 0 0;
}

.event-main time {
  color: #64748b;
  font-size: 0.84rem;
  text-align: right;
}

.event-meta {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 10px;
}

.state-details {
  margin-top: 10px;
}

.state-details summary {
  color: #1d4ed8;
  cursor: pointer;
  font-weight: 700;
}

.state-details pre {
  background: #0f172a;
  border-radius: 8px;
  color: #e2e8f0;
  font-size: 0.78rem;
  max-height: 260px;
  overflow: auto;
  padding: 12px;
  white-space: pre-wrap;
}

.load-more {
  margin-top: 12px;
}

@media (max-width: 980px) {
  .workbench-layout,
  .field-grid,
  .metrics,
  .event-meta {
    grid-template-columns: 1fr;
  }

  .audit-header,
  .section-heading,
  .event-main {
    align-items: flex-start;
    flex-direction: column;
    gap: 12px;
  }

  .event-main time {
    text-align: left;
  }
}
</style>
