<template>
  <div class="overview-tab">
    <DataTable
      :value="store.experiments"
      stripedRows
      responsiveLayout="scroll"
      :loading="store.loading"
      dataKey="id"
      :paginator="true"
      :rows="25"
      paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink CurrentPageReport RowsPerPageDropdown"
      :rowsPerPageOptions="[10, 25, 50]"
      currentPageReportTemplate="Showing {first} to {last} of {totalRecords} experiments"
    >
      <Column field="id" header="ID" sortable style="width: 80px" />
      <Column field="name" header="Name" sortable>
        <template #body="slotProps">
          <strong>{{ slotProps.data.name }}</strong>
        </template>
      </Column>
      <Column field="description" header="Description" />
      <Column header="Created" sortable field="created_at" style="width: 180px">
        <template #body="slotProps">
          {{ formatDateTime(slotProps.data.created_at) }}
        </template>
      </Column>
      <Column header="Files" style="width: 100px">
        <template #body="slotProps">
          <Tag :value="slotProps.data.file_count || 0" severity="info" />
        </template>
      </Column>
      <Column header="Actions" style="width: 120px">
        <template #body="slotProps">
          <Button
            icon="pi pi-eye"
            class="p-button-rounded p-button-text p-button-sm"
            v-tooltip.top="'View Details'"
            @click="$emit('view-details', slotProps.data.id)"
          />
          <Button
            icon="pi pi-pencil"
            class="p-button-rounded p-button-text p-button-sm"
            v-tooltip.top="'Edit'"
            @click="editExperiment(slotProps.data)"
          />
          <Button
            icon="pi pi-trash"
            class="p-button-rounded p-button-text p-button-danger p-button-sm"
            v-tooltip.top="'Delete'"
            @click="deleteExperiment(slotProps.data.id)"
          />
        </template>
      </Column>
    </DataTable>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue';
import { useToast } from 'primevue/usetoast';
import Button from 'primevue/button';
import Column from 'primevue/column';
import DataTable from 'primevue/datatable';
import Tag from 'primevue/tag';

import { useExperimentStore } from '@/stores/experiment';
import { formatDateTime } from '@/utils/format';

const store = useExperimentStore();
const toast = useToast();

const emit = defineEmits<{
  'view-details': [experimentId: number];
}>();

onMounted(() => {
  store.fetchExperiments().catch(() => {
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: 'Failed to load experiments',
      life: 3000,
    });
  });
});

const editExperiment = (experiment: any) => {
  // TODO: Implement edit functionality
  toast.add({
    severity: 'info',
    summary: 'Edit',
    detail: `Edit functionality for "${experiment.name}" coming soon`,
    life: 3000,
  });
};

const deleteExperiment = async (experimentId: number) => {
  if (!confirm('Delete this experiment? This action cannot be undone.')) {
    return;
  }

  try {
    await store.deleteExperiment(experimentId);
    toast.add({
      severity: 'success',
      summary: 'Deleted',
      detail: 'Experiment deleted successfully',
      life: 3000,
    });
  } catch {
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: 'Failed to delete experiment',
      life: 3000,
    });
  }
};
</script>

<style scoped>
.overview-tab {
  background: #ffffff;
  border-radius: 8px;
  padding: 20px;
}
</style>
