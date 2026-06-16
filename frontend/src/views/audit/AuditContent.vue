<template>
  <section class="audit-page">
    <header class="tab-header">
      <h1>Audit</h1>
      <AuditCapabilityStrip :caps="auditConfig" :can-query="canQuery" />
    </header>

    <section v-if="!hasAnyAuditCapability" class="notice">
      <i class="pi pi-lock" aria-hidden="true"></i>
      <span>Audit capabilities are not enabled for this deployment.</span>
      <a class="notice-action" href="mailto:support@spectrascientific.com?subject=Spectra%20Sherpa%20audit%20upgrade">
        Request upgrade
      </a>
    </section>

    <section class="workbench-layout">
      <AuditFilterChips
        v-model:scope-type="form.scopeType"
        v-model:scope-id="form.scopeId"
        v-model:action="form.action"
        v-model:target-type="form.targetType"
        v-model:target-id="form.targetId"
        v-model:request-id="form.requestId"
        v-model:since="form.since"
        v-model:until="form.until"
        v-model:format="form.format"
        v-model:include-pdf="form.includePdf"
        :caps="auditConfig"
        :can-query="canQuery"
        :is-generating="isGenerating"
        :is-exporting="isExporting"
        :is-loading-events="isLoadingEvents"
        @refresh="refreshEvents"
        @generate-pack="generatePack"
        @export="exportAudit"
      />

      <aside class="status-panel" aria-live="polite">
        <ChainHealthCard
          :caps="auditConfig"
          :is-checking-chain="isCheckingChain"
          :chain-status-label="chainStatusLabel"
          @verify="refreshChainStatus"
        />

        <div v-if="errorMessage" class="status error">
          <i class="pi pi-exclamation-triangle" aria-hidden="true"></i>
          <span>{{ errorMessage }}</span>
        </div>

        <ReportPackPanel :last-pack="lastPack" />
      </aside>
    </section>

    <AuditTimeline
      :events="events"
      :can-query="canQuery"
      :is-loading-events="isLoadingEvents"
      :has-more-events="hasMoreEvents"
      @load-more="loadMoreEvents"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";

import { api } from "@/api";
import { useAppConfig } from "@/composables/useAppConfig";
import {
  blobFromResponseData,
  downloadBlob,
  filenameFromContentDisposition,
} from "@/utils/download";
import AuditCapabilityStrip from "./AuditCapabilityStrip.vue";
import AuditFilterChips from "./AuditFilterChips.vue";
import AuditTimeline from "./AuditTimeline.vue";
import ChainHealthCard from "./ChainHealthCard.vue";
import ReportPackPanel from "./ReportPackPanel.vue";
import { extractApiErrorMessage } from "./auditFormatters";
import type {
  AuditEventResponse,
  AuditFilterForm,
  ChainStatus,
  ExportFormat,
  LastPack,
} from "./types";

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
const events = ref<AuditEventResponse["events"]>([]);
const nextCursor = ref<string | null>(null);
const hasMoreEvents = ref(false);

const form = reactive<AuditFilterForm>({
  scopeType: "Workflow",
  scopeId: "",
  action: "",
  targetType: "Workflow",
  targetId: "",
  requestId: "",
  since: "",
  until: "",
  format: "jsonl",
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
    downloadBlob(blob, filenameFromContentDisposition(response.headers["content-disposition"], "audit-report-pack.zip"));

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
    downloadBlob(blobFromResponseData(response.data), filenameFromContentDisposition(response.headers["content-disposition"], fallback));
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
  padding: 0 1rem 1.5rem;
}

.notice {
  align-items: center;
  background: #fff7ed;
  border: 1px solid #fed7aa;
  border-radius: 8px;
  color: #9a3412;
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  padding: 12px;
}

.notice-action {
  color: #7c2d12;
  font-weight: 800;
  margin-left: auto;
  text-decoration: underline;
}

.workbench-layout {
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(0, 1.45fr) minmax(280px, 0.75fr);
  margin-bottom: 16px;
}

.status-panel {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px;
}

.status {
  align-items: center;
  border-radius: 8px;
  display: flex;
  gap: 8px;
  padding: 12px;
}

.status.error {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #991b1b;
}

@media (max-width: 980px) {
  .workbench-layout {
    grid-template-columns: 1fr;
  }
}
</style>
