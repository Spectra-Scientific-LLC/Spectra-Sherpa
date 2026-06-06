<template>
  <section class="detail-section">
    <div class="section-header" @click="$emit('toggle')">
      <div class="section-title">
        <i :class="expanded ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
        <h2>Settings</h2>
      </div>
      <span class="section-badge" v-if="settingsCount">{{ settingsCount }} parameters</span>
    </div>
    <Transition name="collapse">
      <div v-if="expanded" class="section-content">
        <div v-if="hasValidationErrors" class="validation-error-banner">
          <div class="error-banner-header">
            <i class="pi pi-exclamation-triangle"></i>
            <div class="error-banner-content">
              <strong>{{ displayedValidationErrors.length }} validation error{{ displayedValidationErrors.length > 1 ? 's' : '' }}</strong>
              <span>Please fix the following errors before running:</span>
            </div>
          </div>
          <ul class="error-list">
            <li v-for="error in displayedValidationErrors" :key="error.param_name">
              <strong>{{ error.param_name }}:</strong> {{ error.message }}
            </li>
          </ul>
        </div>

        <div v-if="!params.length" class="empty-section">
          <i class="pi pi-cog" />
          <p>No configurable parameters</p>
          <small>This node type does not have any settings to configure.</small>
        </div>
        <div v-else class="settings-form">
          <div
            v-for="param in params"
            :key="param.name"
            class="param-field"
            :class="{ 'has-error': getParamError(param.name) }"
          >
            <label :for="param.name">
              {{ param.label }}
              <span v-if="param.required" class="required-mark">*</span>
            </label>
            <small v-if="param.description" class="param-description">
              {{ param.description }}
            </small>

            <InputNumber
              v-if="param.type === 'number'"
              :model-value="localParams[param.name]"
              @update:model-value="(v) => $emit('updateParam', param.name, v)"
              :id="param.name"
              :min="param.min"
              :max="param.max"
              :step="param.step || 1"
              :minFractionDigits="param.step && param.step < 1 ? 2 : 0"
              :maxFractionDigits="param.step && param.step < 1 ? 4 : 0"
              :placeholder="param.required ? '' : 'Optional input'"
              class="full-width"
              :class="{ 'p-invalid': getParamError(param.name) }"
            />

            <div v-else-if="param.type === 'boolean'" class="toggle-field">
              <InputSwitch
:model-value="localParams[param.name]"
              @update:model-value="(v) => $emit('updateParam', param.name, v)" :id="param.name" />
              <span class="toggle-label">{{ localParams[param.name] ? 'Enabled' : 'Disabled' }}</span>
            </div>

            <Dropdown
              v-else-if="param.type === 'select'"
              :model-value="localParams[param.name]"
              @update:model-value="(v) => $emit('updateParam', param.name, v)"
              :id="param.name"
              :options="param.options"
              :optionLabel="param.optionLabel || 'label'"
              :optionValue="param.optionValue || 'value'"
              class="full-width"
              :class="{ 'p-invalid': getParamError(param.name) }"
            />

            <div v-else-if="param.type === 'model_select'" class="model-select-row">
              <div v-if="!modelSelectOptions.length && !modelOptionsLoading" class="model-select-banner">
                <i class="pi pi-info-circle"></i>
                <span>No trained artifacts yet — run a training node first.</span>
              </div>
              <Dropdown
                :model-value="localParams[param.name]"
                @update:model-value="(v) => $emit('updateParam', param.name, v)"
                :id="param.name"
                :options="modelSelectOptions"
                optionLabel="label"
                optionValue="value"
                placeholder="Select saved artifact"
                class="full-width"
                filter
                showClear
                :loading="modelOptionsLoading"
                :class="{ 'p-invalid': getParamError(param.name) }"
              />
              <Button
                icon="pi pi-refresh"
                class="p-button-text p-button-sm"
                title="Refresh saved artifacts"
                :loading="modelOptionsLoading"
                @click="loadModelOptions"
              />
            </div>

            <InputText
              v-else
              :model-value="localParams[param.name]"
              @update:model-value="(v) => $emit('updateParam', param.name, v)"
              :id="param.name"
              :placeholder="param.required ? '' : 'Optional input'"
              class="full-width"
              :class="{ 'p-invalid': getParamError(param.name) }"
            />

            <small v-if="getParamError(param.name)" class="param-error-message">
              {{ getParamError(param.name) }}
            </small>
          </div>

          <div class="settings-actions">
            <Button
              label="Reset to Defaults"
              icon="pi pi-refresh"
              class="p-button-outlined p-button-secondary"
              @click="$emit('reset')"
            />
          </div>
        </div>
      </div>
    </Transition>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import Button from "primevue/button";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import InputSwitch from "primevue/inputswitch";
import Dropdown from "primevue/dropdown";
import api from "@/api/client";
import { useProjectStore } from "@/stores/project";
import { useWorkflowStore } from "@/stores/workflow";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Param = any;

interface ValidationError {
  param_name: string;
  message: string;
}

interface ModelSelectItem {
  artifact_uid: string;
  name: string;
  display_name?: string | null;
  model_type: string;
  n_features: number;
  n_components?: number | null;
}

const props = defineProps<{
  expanded: boolean;
  settingsCount: number;
  params: Param[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  localParams: Record<string, any>;
  hasValidationErrors: boolean;
  displayedValidationErrors: ValidationError[];
  getParamError: (name: string) => string | null;
}>();

defineEmits<{
  (e: "toggle"): void;
  (e: "reset"): void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (e: "updateParam", name: string, value: any): void;
}>();

const projectStore = useProjectStore();
const workflowStore = useWorkflowStore();
const modelOptionsLoading = ref(false);
const modelSelectItems = ref<ModelSelectItem[]>([]);

const hasModelSelectParam = computed(() =>
  props.params.some((param) => param.type === "model_select"),
);

const modelSelectOptions = computed(() =>
  modelSelectItems.value.map((model) => {
    const name = model.display_name || model.name;
    const pieces = [
      model.model_type,
      `${model.n_features} feature${model.n_features === 1 ? "" : "s"}`,
    ];
    if (model.n_components != null) {
      pieces.push(`${model.n_components} component${model.n_components === 1 ? "" : "s"}`);
    }
    return {
      label: `${name} · ${pieces.join(" · ")}`,
      value: model.artifact_uid,
    };
  }),
);

async function loadModelOptions(): Promise<void> {
  if (!hasModelSelectParam.value) return;
  modelOptionsLoading.value = true;
  try {
    const params: Record<string, unknown> = {};
    if (projectStore.currentProjectId != null) {
      params.project_id = projectStore.currentProjectId;
    }
    const response = await api.get<ModelSelectItem[]>("/models/select", { params });
    modelSelectItems.value = response.data;
  } catch (err) {
    console.warn("[node-settings] failed to load model artifacts", err);
    modelSelectItems.value = [];
  } finally {
    modelOptionsLoading.value = false;
  }
}

function collectModelIds(value: unknown, ids = new Set<string>()): Set<string> {
  if (!value || typeof value !== "object") return ids;
  if (Array.isArray(value)) {
    for (const item of value) collectModelIds(item, ids);
    return ids;
  }
  const record = value as Record<string, unknown>;
  for (const key of ["model_id", "artifact_uid"]) {
    const candidate = record[key];
    if (typeof candidate === "string" && candidate.length > 0) ids.add(candidate);
  }
  for (const child of Object.values(record)) {
    collectModelIds(child, ids);
  }
  return ids;
}

watch(
  [hasModelSelectParam, () => projectStore.currentProjectId],
  ([needsModels]) => {
    if (needsModels) void loadModelOptions();
  },
  { immediate: true },
);

watch(
  () => workflowStore.lastExecutionResults,
  (results) => {
    if (!hasModelSelectParam.value || !results) return;
    if (collectModelIds(results).size > 0) void loadModelOptions();
  },
);
</script>

<style scoped>
.detail-section {
  background: #1e293b;
  border-radius: 12px;
  margin-bottom: 24px;
  overflow: hidden;
  border: 1px solid #334155;
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  cursor: pointer;
  transition: background 0.15s;
}
.section-header:hover {
  background: rgba(51, 65, 85, 0.5);
}
.section-title {
  display: flex;
  align-items: center;
  gap: 12px;
}
.section-title i {
  font-size: 0.85rem;
  color: #64748b;
}
.section-title h2 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
}
.section-badge {
  padding: 4px 10px;
  background: #334155;
  border-radius: 12px;
  font-size: 0.75rem;
  color: #94a3b8;
}
.section-content {
  padding: 20px;
  border-top: 1px solid #334155;
}
.collapse-enter-active,
.collapse-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}
.collapse-enter-from,
.collapse-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}
.empty-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 20px;
  text-align: center;
  color: #64748b;
}
.empty-section i {
  font-size: 2.5rem;
  margin-bottom: 16px;
  color: #475569;
}
.empty-section p {
  margin: 0 0 8px;
  font-size: 1rem;
}
.empty-section small {
  color: #475569;
  font-size: 0.85rem;
}

.validation-error-banner {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 16px;
}
.error-banner-header {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.error-banner-header i {
  color: #ef4444;
  font-size: 1.1rem;
  margin-top: 2px;
}
.error-banner-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.error-banner-content strong {
  color: #f87171;
  font-size: 0.9rem;
}
.error-banner-content span {
  color: #94a3b8;
  font-size: 0.85rem;
}
.error-list {
  margin: 10px 0 0;
  padding-left: 30px;
  color: #cbd5e1;
  font-size: 0.85rem;
}
.error-list li {
  margin-bottom: 4px;
}
.error-list strong {
  color: #f8fafc;
  font-family: "JetBrains Mono", monospace;
  font-size: 0.8rem;
}

.settings-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.param-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.param-field.has-error label {
  color: #f87171;
}
.param-field label {
  font-size: 0.9rem;
  font-weight: 500;
  color: #cbd5e1;
}
.required-mark {
  color: #ef4444;
  margin-left: 2px;
}
.param-description {
  color: #64748b;
  font-size: 0.8rem;
  margin-bottom: 4px;
}
.param-error-message {
  color: #f87171;
  font-size: 0.8rem;
  margin-top: 2px;
}
.toggle-field {
  display: flex;
  align-items: center;
  gap: 12px;
}
.toggle-label {
  color: #94a3b8;
  font-size: 0.9rem;
}
.full-width {
  width: 100%;
}
.model-select-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
}
.model-select-banner {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 0.75rem;
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 8px;
  color: #cbd5e1;
  background: rgba(15, 23, 42, 0.35);
  font-size: 0.85rem;
}
.settings-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 12px;
  border-top: 1px solid #334155;
}
</style>
