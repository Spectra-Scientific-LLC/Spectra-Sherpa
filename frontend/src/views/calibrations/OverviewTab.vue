<template>
  <div class="overview-tab">
    <div class="tab-section">
      <div class="section-header">
        <h3>Calibration Models</h3>
        <div class="tab-actions">
          <Button
            label="Refresh"
            icon="pi pi-refresh"
            class="p-button-text"
            @click="store.fetchCalibrations"
          />
        </div>
      </div>

      <DataTable
        :value="store.calibrations"
        :paginator="true"
        :rows="25"
        stripedRows
        :loading="store.loading"
        currentPageReportTemplate="Showing {first} to {last} of {totalRecords} calibrations"
      >
        <Column field="id" header="ID" sortable style="width: 80px" />
        <Column field="compound_name" header="Compound" sortable />
        <Column field="concentration_mode" header="Mode" sortable />
        <Column field="x_unit" header="Units" />
        <Column header="Created" sortable>
          <template #body="slotProps">
            {{ formatDateTime(slotProps.data.created_at) }}
          </template>
        </Column>
        <Column header="Actions" style="width: 150px">
          <template #body="slotProps">
            <Button
              label="Details"
              icon="pi pi-chart-line"
              class="p-button-text p-button-sm"
              @click="$emit('view-details', slotProps.data.id)"
            />
          </template>
        </Column>
      </DataTable>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from "vue";
import Button from "primevue/button";
import Column from "primevue/column";
import DataTable from "primevue/datatable";
import { useCalibrationStore } from "@/stores/calibration";
import { formatDateTime } from "@/utils/format";

const store = useCalibrationStore();

const emit = defineEmits<{
  "view-details": [calibrationId: number];
}>();

onMounted(() => {
  store.fetchCalibrations();
});
</script>

<style scoped>
.overview-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
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
</style>
