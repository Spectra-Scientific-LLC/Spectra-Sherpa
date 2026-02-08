<template>
  <div class="models-tab">
    <div v-if="!calibrationId" class="empty-state">
      <i class="pi pi-database" style="font-size: 3rem; color: #94a3b8"></i>
      <h3>No Calibration Selected</h3>
      <p>Select a calibration from the Overview tab to view model versions.</p>
    </div>

    <div v-else class="models-content">
      <div class="tab-section">
        <div class="section-header">
          <h3>Model Versions</h3>
          <div class="tab-actions">
            <Button
              label="Export All"
              icon="pi pi-download"
              class="p-button-text"
              @click="exportAllModels"
            />
            <Button
              label="Refresh"
              icon="pi pi-refresh"
              class="p-button-text"
              @click="refreshModels"
            />
          </div>
        </div>

        <div v-if="store.models.length === 0" class="empty-models">
          <i class="pi pi-inbox" style="font-size: 2.5rem; color: #cbd5e1"></i>
          <h4>No Models Yet</h4>
          <p>Fit a model in the "Fit Model" tab to create versions</p>
        </div>

        <DataTable
          v-else
          :value="store.models"
          stripedRows
          :rows="15"
          :paginator="store.models.length > 15"
          currentPageReportTemplate="Showing {first} to {last} of {totalRecords} models"
        >
          <Column field="version_name" header="Version Name" sortable>
            <template #body="slotProps">
              <span v-if="slotProps.data.version_name">
                {{ slotProps.data.version_name }}
              </span>
              <span v-else class="muted-text">
                (Auto-generated v{{ slotProps.data.id }})
              </span>
            </template>
          </Column>
          <Column field="model_type" header="Model Type" sortable />
          <Column field="r_squared" header="R² Score" sortable>
            <template #body="slotProps">
              <span :class="getR2Class(slotProps.data.r_squared)">
                {{ slotProps.data.r_squared?.toFixed(4) || "N/A" }}
              </span>
            </template>
          </Column>
          <Column field="rmse" header="RMSE" sortable>
            <template #body="slotProps">
              {{ slotProps.data.rmse?.toFixed(6) || "N/A" }}
            </template>
          </Column>
          <Column header="Created" sortable>
            <template #body="slotProps">
              {{ formatDateTime(slotProps.data.created_at) }}
            </template>
          </Column>
          <Column header="Active" style="width: 100px">
            <template #body="slotProps">
              <div class="active-toggle">
                <InputSwitch
                  :modelValue="slotProps.data.is_active"
                  @update:modelValue="() => toggleActive(slotProps.data.id)"
                />
                <span v-if="slotProps.data.is_active" class="active-badge">
                  <i class="pi pi-check"></i>
                </span>
              </div>
            </template>
          </Column>
          <Column header="Actions" style="width: 150px">
            <template #body="slotProps">
              <Button
                label="Details"
                icon="pi pi-info-circle"
                class="p-button-text p-button-sm"
                @click="viewModelDetails(slotProps.data)"
              />
            </template>
          </Column>
        </DataTable>
      </div>

      <!-- Model Comparison Section -->
      <div v-if="store.models.length > 1" class="tab-section">
        <div class="section-header">
          <h3>Model Comparison</h3>
        </div>

        <div class="comparison-grid">
          <div class="comparison-card">
            <div class="card-icon">
              <i class="pi pi-star-fill"></i>
            </div>
            <div class="card-content">
              <div class="card-label">Best R² Score</div>
              <div class="card-value">
                {{ bestR2Model?.r_squared?.toFixed(4) || "N/A" }}
              </div>
              <div class="card-detail">
                {{ bestR2Model?.version_name || `Model ${bestR2Model?.id}` }}
              </div>
            </div>
          </div>

          <div class="comparison-card">
            <div class="card-icon">
              <i class="pi pi-chart-line"></i>
            </div>
            <div class="card-content">
              <div class="card-label">Lowest RMSE</div>
              <div class="card-value">
                {{ lowestRMSEModel?.rmse?.toFixed(6) || "N/A" }}
              </div>
              <div class="card-detail">
                {{ lowestRMSEModel?.version_name || `Model ${lowestRMSEModel?.id}` }}
              </div>
            </div>
          </div>

          <div class="comparison-card">
            <div class="card-icon">
              <i class="pi pi-check-circle"></i>
            </div>
            <div class="card-content">
              <div class="card-label">Active Model</div>
              <div class="card-value">
                {{ activeModel?.model_type || "None" }}
              </div>
              <div class="card-detail">
                {{ activeModel?.version_name || `Model ${activeModel?.id}` }}
              </div>
            </div>
          </div>

          <div class="comparison-card">
            <div class="card-icon">
              <i class="pi pi-database"></i>
            </div>
            <div class="card-content">
              <div class="card-label">Total Models</div>
              <div class="card-value">{{ store.models.length }}</div>
              <div class="card-detail">
                {{ uniqueModelTypes.length }} type(s)
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Model Details Dialog -->
    <Dialog
      v-model:visible="detailsVisible"
      :header="`Model Details: ${selectedModel?.version_name || 'Version ' + selectedModel?.id}`"
      :modal="true"
      style="width: min(600px, 90vw)"
    >
      <div v-if="selectedModel" class="model-details">
        <div class="detail-row">
          <label>Model Type:</label>
          <span>{{ selectedModel.model_type }}</span>
        </div>
        <div class="detail-row">
          <label>R² Score:</label>
          <span :class="getR2Class(selectedModel.r_squared)">
            {{ selectedModel.r_squared?.toFixed(6) || "N/A" }}
          </span>
        </div>
        <div class="detail-row">
          <label>RMSE:</label>
          <span>{{ selectedModel.rmse?.toFixed(6) || "N/A" }}</span>
        </div>
        <div class="detail-row">
          <label>Created:</label>
          <span>{{ formatDateTime(selectedModel.created_at) }}</span>
        </div>
        <div class="detail-row">
          <label>Status:</label>
          <span :class="selectedModel.is_active ? 'status-active' : 'status-inactive'">
            {{ selectedModel.is_active ? "Active" : "Inactive" }}
          </span>
        </div>
      </div>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import Button from "primevue/button";
import Column from "primevue/column";
import DataTable from "primevue/datatable";
import Dialog from "primevue/dialog";
import InputSwitch from "primevue/inputswitch";
import { useToast } from "primevue/usetoast";
import { useCalibrationStore } from "@/stores/calibration";
import { downloadJson } from "@/utils/download";
import { formatDateTime } from "@/utils/format";

interface Props {
  calibrationId: number | null;
}

const props = defineProps<Props>();

const store = useCalibrationStore();
const toast = useToast();

const detailsVisible = ref(false);
const selectedModel = ref<any>(null);

const bestR2Model = computed(() => {
  if (store.models.length === 0) return null;
  return [...store.models].sort((a, b) => (b.r_squared || 0) - (a.r_squared || 0))[0];
});

const lowestRMSEModel = computed(() => {
  if (store.models.length === 0) return null;
  return [...store.models].sort((a, b) => (a.rmse || Infinity) - (b.rmse || Infinity))[0];
});

const activeModel = computed(() => {
  return store.models.find((m) => m.is_active);
});

const uniqueModelTypes = computed(() => {
  return [...new Set(store.models.map((m) => m.model_type))];
});

// Watch for calibration changes
watch(
  () => props.calibrationId,
  async (newId) => {
    if (newId) {
      await store.fetchModels(newId);
    }
  },
  { immediate: true }
);

const getR2Class = (r2: number | null | undefined) => {
  if (r2 === null || r2 === undefined) return "muted-text";
  if (r2 >= 0.95) return "r2-excellent";
  if (r2 >= 0.85) return "r2-good";
  if (r2 >= 0.70) return "r2-fair";
  return "r2-poor";
};

const toggleActive = async (modelId: number) => {
  if (!props.calibrationId) return;

  try {
    await store.activateModel(props.calibrationId, modelId);
    toast.add({
      severity: "success",
      summary: "Model Activated",
      detail: "Model has been set as active",
      life: 3000,
    });
  } catch {
    toast.add({
      severity: "error",
      summary: "Activation Failed",
      detail: "Unable to activate model",
      life: 3000,
    });
  }
};

const viewModelDetails = (model: any) => {
  selectedModel.value = model;
  detailsVisible.value = true;
};

const refreshModels = async () => {
  if (!props.calibrationId) return;
  await store.fetchModels(props.calibrationId);
  toast.add({
    severity: "info",
    summary: "Refreshed",
    detail: "Model list updated",
    life: 2000,
  });
};

const exportAllModels = () => {
  if (!store.models.length) return;

  downloadJson(
    {
      calibration_id: props.calibrationId,
      models: store.models,
      exported_at: new Date().toISOString(),
    },
    `calibration_${props.calibrationId}_models.json`
  );

  toast.add({
    severity: "success",
    summary: "Exported",
    detail: `${store.models.length} model(s) exported to JSON`,
    life: 3000,
  });
};
</script>

<style scoped>
.models-tab {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
  color: #64748b;
}

.empty-state h3 {
  margin: 16px 0 8px;
  font-size: 1.2rem;
  color: #475569;
}

.models-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.tab-section {
  background: #ffffff;
  border-radius: 8px;
  padding: 20px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e2e8f0;
}

.section-header h3 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
}

.tab-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.empty-models {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
  color: #94a3b8;
  background: #f8fafc;
  border-radius: 8px;
  border: 2px dashed #e2e8f0;
}

.empty-models h4 {
  margin: 16px 0 8px;
  color: #64748b;
}

.empty-models p {
  color: #94a3b8;
}

.active-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
}

.active-badge {
  color: #10b981;
  font-weight: 600;
}

.r2-excellent {
  color: #10b981;
  font-weight: 600;
}

.r2-good {
  color: #3b82f6;
  font-weight: 600;
}

.r2-fair {
  color: #f59e0b;
}

.r2-poor {
  color: #ef4444;
}

.comparison-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
}

.comparison-card {
  display: flex;
  gap: 16px;
  padding: 16px;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}

.card-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  background: #ffffff;
  border-radius: 8px;
  color: #3b82f6;
  font-size: 1.5rem;
}

.card-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.card-label {
  font-size: 0.85rem;
  color: #64748b;
  font-weight: 500;
}

.card-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #1e293b;
}

.card-detail {
  font-size: 0.85rem;
  color: #94a3b8;
}

.model-details {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.detail-row {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 12px;
  align-items: center;
  padding: 12px;
  background: #f8fafc;
  border-radius: 6px;
}

.detail-row label {
  font-weight: 600;
  color: #475569;
}

.status-active {
  color: #10b981;
  font-weight: 600;
}

.status-inactive {
  color: #94a3b8;
}

.muted-text {
  color: #94a3b8;
}
</style>
