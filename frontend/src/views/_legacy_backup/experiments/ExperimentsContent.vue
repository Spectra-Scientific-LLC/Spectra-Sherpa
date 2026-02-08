<template>
  <div class="experiments-content">
    <div class="section-header">
      <div>
        <h1>Experiments</h1>
        <p class="section-subtitle">
          Manage experimental spectra from your lab instruments with DOE metadata
        </p>
      </div>
      <Button label="New Experiment" icon="pi pi-plus" @click="goToCreate" />
    </div>

    <TabView v-model:activeIndex="activeTab" class="content-tabs">
      <TabPanel header="Overview">
        <OverviewTab @view-details="handleViewDetails" />
      </TabPanel>

      <TabPanel header="Create">
        <CreateTab @created="handleCreated" />
      </TabPanel>

      <TabPanel header="Files">
        <FilesTab :experiment-id="selectedExperimentId" />
      </TabPanel>

      <TabPanel header="Versions">
        <VersionsTab :experiment-id="selectedExperimentId" />
      </TabPanel>

      <TabPanel header="DOE">
        <DoeTab :experiment-id="selectedExperimentId" />
      </TabPanel>
    </TabView>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import Button from 'primevue/button';
import TabView from 'primevue/tabview';
import TabPanel from 'primevue/tabpanel';

import OverviewTab from './OverviewTab.vue';
import CreateTab from './CreateTab.vue';
import FilesTab from './FilesTab.vue';
import VersionsTab from './VersionsTab.vue';
import DoeTab from './DoeTab.vue';

const activeTab = ref(0);
const selectedExperimentId = ref<number | null>(null);

const goToCreate = () => {
  activeTab.value = 1; // Switch to Create tab
};

const handleCreated = (experimentId: number) => {
  selectedExperimentId.value = experimentId;
  activeTab.value = 2; // Switch to Files tab after creation
};

const handleViewDetails = (experimentId: number) => {
  selectedExperimentId.value = experimentId;
  activeTab.value = 2; // Switch to Files tab
};
</script>

<style scoped>
.experiments-content {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 24px;
  border-bottom: 1px solid #e2e8f0;
}

.section-header h1 {
  margin: 0;
  font-size: 1.75rem;
  font-weight: 600;
  color: #1e293b;
}

.section-subtitle {
  margin: 4px 0 0 0;
  font-size: 0.875rem;
  color: #64748b;
}

.content-tabs {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.content-tabs :deep(.p-tabview-panels) {
  flex: 1;
  overflow: auto;
  padding: 24px;
  background: #f8fafc;
}
</style>
