<template>
  <section class="filter-panel" aria-labelledby="audit-filters-heading">
    <div class="section-heading">
      <div>
        <p class="eyebrow">Scope</p>
        <h2 id="audit-filters-heading">Evidence Filters</h2>
      </div>
      <button
        class="ghost-action"
        type="button"
        :disabled="isLoadingEvents || !canQuery"
        @click="$emit('refresh')"
      >
        <i class="pi pi-refresh" aria-hidden="true"></i>
        <span>{{ isLoadingEvents ? "Loading" : "Refresh" }}</span>
      </button>
    </div>

    <form class="field-grid" @submit.prevent="$emit('refresh')">
      <label>
        Scope
        <select v-model="scopeType">
          <option value="">Any</option>
          <option value="Project">Project</option>
          <option value="Workflow">Workflow</option>
          <option value="ModelArtifact">Model artifact</option>
          <option value="ProjectDataSource">Project data source</option>
        </select>
      </label>

      <label>
        Scope ID
        <input v-model.trim="scopeId" type="text" placeholder="Optional" />
      </label>

      <label>
        Action
        <input v-model.trim="action" type="text" placeholder="workflow.updated" />
      </label>

      <label>
        Target Type
        <input v-model.trim="targetType" type="text" placeholder="Workflow" />
      </label>

      <label>
        Target ID
        <input v-model.trim="targetId" type="text" placeholder="Optional" />
      </label>

      <label>
        Request ID
        <input v-model.trim="requestId" type="text" placeholder="Optional" />
      </label>

      <label>
        Since
        <input v-model="since" type="datetime-local" />
      </label>

      <label>
        Until
        <input v-model="until" type="datetime-local" />
      </label>

      <label>
        Pack Format
        <select v-model="format">
          <option value="jsonl">JSONL</option>
          <option value="csv">CSV</option>
        </select>
      </label>

      <label class="checkbox-field">
        <input v-model="includePdf" type="checkbox" />
        <span>Include PDF summary</span>
      </label>
    </form>

    <div class="action-row">
      <button
        class="primary-action"
        type="button"
        data-testid="generate-report-pack"
        :disabled="isGenerating || !caps?.reportPack"
        @click="$emit('generate-pack')"
      >
        <i class="pi pi-file-export" aria-hidden="true"></i>
        <span>{{ isGenerating ? "Generating" : "Generate Pack" }}</span>
      </button>
      <button
        class="secondary-action"
        type="button"
        data-testid="export-jsonl"
        :disabled="isExporting || !caps?.exportAudited"
        @click="$emit('export', 'jsonl')"
      >
        <i class="pi pi-download" aria-hidden="true"></i>
        <span>JSONL</span>
      </button>
      <button
        class="secondary-action"
        type="button"
        data-testid="export-csv"
        :disabled="isExporting || !caps?.exportAudited"
        @click="$emit('export', 'csv')"
      >
        <i class="pi pi-download" aria-hidden="true"></i>
        <span>CSV</span>
      </button>
    </div>

    <div v-if="!caps?.reportPack || !caps?.exportAudited" class="inline-note">
      <i class="pi pi-info-circle" aria-hidden="true"></i>
      <span>Unavailable actions are controlled by audit entitlements from the server.</span>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { AuditCapabilities, ExportFormat } from "./types";

defineProps<{
  caps: AuditCapabilities | undefined;
  canQuery: boolean;
  isGenerating: boolean;
  isExporting: boolean;
  isLoadingEvents: boolean;
}>();

defineEmits<{
  (e: "refresh"): void;
  (e: "generate-pack"): void;
  (e: "export", format: ExportFormat): void;
}>();

// Per-field two-way bindings. The parent owns the form's reactive
// container; mutating it from a child via `v-model="form.x"` would
// trip vue/no-mutating-props because the prop reference itself is
// being written through. defineModel keeps writes flowing back via
// emit('update:fieldName', ...), which the parent binds with
// v-model:fieldName="form.fieldName".
const scopeType = defineModel<string>("scopeType", { required: true });
const scopeId = defineModel<string>("scopeId", { required: true });
const action = defineModel<string>("action", { required: true });
const targetType = defineModel<string>("targetType", { required: true });
const targetId = defineModel<string>("targetId", { required: true });
const requestId = defineModel<string>("requestId", { required: true });
const since = defineModel<string>("since", { required: true });
const until = defineModel<string>("until", { required: true });
const format = defineModel<ExportFormat>("format", { required: true });
const includePdf = defineModel<boolean>("includePdf", { required: true });
</script>

<style scoped>
.filter-panel {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px;
}

.section-heading {
  align-items: center;
  display: flex;
  justify-content: space-between;
}

.section-heading h2 {
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
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
}

.primary-action,
.secondary-action,
.ghost-action {
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
.ghost-action {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #0f172a;
}

.primary-action:disabled,
.secondary-action:disabled,
.ghost-action:disabled {
  background: #e2e8f0;
  color: #64748b;
  cursor: not-allowed;
}

.inline-note {
  align-items: center;
  background: #fff7ed;
  border: 1px solid #fed7aa;
  border-radius: 8px;
  color: #9a3412;
  display: flex;
  font-size: 0.86rem;
  gap: 8px;
  margin-top: 12px;
  padding: 10px;
}

@media (max-width: 980px) {
  .field-grid {
    grid-template-columns: 1fr;
  }

  .section-heading {
    align-items: flex-start;
    flex-direction: column;
    gap: 12px;
  }
}
</style>
