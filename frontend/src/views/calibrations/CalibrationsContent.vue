<template>
  <section class="calibrations-content">
    <div class="section-header">
      <div>
        <h1>Calibration</h1>
        <p class="section-subtitle">
          Build and manage wavelength and concentration calibration models
        </p>
      </div>
      <div class="header-actions">
        <Button
          label="New Calibration"
          icon="pi pi-plus"
          @click="handleNewCalibration"
        />
      </div>
    </div>

    <TabView v-model:activeIndex="activeTab" class="content-tabs">
      <TabPanel header="Overview">
        <OverviewTab @view-details="handleViewDetails" />
      </TabPanel>
      <TabPanel header="Create">
        <CreateTab @created="handleCreated" />
      </TabPanel>
      <TabPanel header="Fit Model">
        <FitModelTab :calibration-id="selectedCalibrationId" />
      </TabPanel>
      <TabPanel header="Models">
        <ModelsTab :calibration-id="selectedCalibrationId" />
      </TabPanel>
    </TabView>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue";
import Button from "primevue/button";
import TabView from "primevue/tabview";
import TabPanel from "primevue/tabpanel";
import { useCalibrationStore } from "@/stores/calibration";
import { useJobStore } from "@/stores/job";
import OverviewTab from "./OverviewTab.vue";
import CreateTab from "./CreateTab.vue";
import FitModelTab from "./FitModelTab.vue";
import ModelsTab from "./ModelsTab.vue";

const store = useCalibrationStore();
const jobStore = useJobStore();

const activeTab = ref(0);
const selectedCalibrationId = ref<number | null>(null);

const handleNewCalibration = () => {
  activeTab.value = 1; // Switch to Create tab
};

const handleCreated = () => {
  activeTab.value = 0; // Back to Overview
  store.fetchCalibrations();
};

const handleViewDetails = async (calibrationId: number) => {
  selectedCalibrationId.value = calibrationId;
  await store.selectCalibration(calibrationId);
  activeTab.value = 2; // Switch to Fit Model tab
};

onMounted(() => {
  store.fetchCalibrations();
  jobStore.connect();
  jobStore.fetchJobs();
});
</script>

<style scoped>
.calibrations-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.section-subtitle {
  margin-top: 4px;
  color: #64748b;
  font-size: 0.95rem;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
