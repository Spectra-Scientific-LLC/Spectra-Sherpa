<template>
  <div class="results-panel">
    <div class="panel-header">
      <h3>Results</h3>
      <Button
        v-if="hasResults"
        icon="pi pi-times"
        class="p-button-text p-button-sm"
        @click="clearResults"
      />
    </div>

    <div v-if="!hasResults" class="empty-state">
      <i class="pi pi-chart-line"></i>
      <p>Execute nodes to see results here</p>
    </div>

    <div v-else class="results-content">
      <!-- Tabs for different result types -->
      <TabView>
        <TabPanel header="Plot">
          <div class="plot-container">
            <!-- Placeholder for Plotly chart -->
            <div class="plot-placeholder">
              <i class="pi pi-chart-line"></i>
              <p>Spectrum plot will appear here</p>
            </div>
          </div>
        </TabPanel>

        <TabPanel header="Metrics">
          <div class="metrics-container">
            <div v-for="(value, key) in currentMetrics" :key="key" class="metric-row">
              <span class="metric-label">{{ formatMetricLabel(key) }}</span>
              <span class="metric-value">{{ formatMetricValue(value) }}</span>
            </div>
          </div>
        </TabPanel>

        <TabPanel header="Data">
          <div class="data-container">
            <DataTable
              :value="currentDataPreview"
              :scrollable="true"
              scroll-height="300px"
              class="compact-table"
            >
              <Column
                v-for="col in dataColumns"
                :key="col.field"
                :field="col.field"
                :header="col.header"
              />
            </DataTable>
          </div>
        </TabPanel>
      </TabView>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import Button from "primevue/button";
import TabView from "primevue/tabview";
import TabPanel from "primevue/tabpanel";
import DataTable from "primevue/datatable";
import Column from "primevue/column";

interface Props {
  nodeResults: Map<string, any>;
}

const props = defineProps<Props>();

const hasResults = computed(() => props.nodeResults && props.nodeResults.size > 0);

// Mock data for demonstration
const currentMetrics = computed(() => {
  // TODO: Get actual metrics from nodeResults
  return {
    samples: 0,
    wavelengths: 0,
    mean_intensity: 0,
    std_dev: 0,
  };
});

const currentDataPreview = computed(() => {
  // TODO: Get actual data preview from nodeResults
  return [];
});

const dataColumns = computed(() => {
  if (currentDataPreview.value.length === 0) {
    return [];
  }
  return Object.keys(currentDataPreview.value[0]).map((key) => ({
    field: key,
    header: key.toUpperCase(),
  }));
});

const clearResults = () => {
  // TODO: Clear results from parent component
  console.log("Clear results");
};

const formatMetricLabel = (key: string) => {
  return key
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
};

const formatMetricValue = (value: any) => {
  if (typeof value === "number") {
    return value.toFixed(4);
  }
  return String(value);
};
</script>

<style scoped>
.results-panel {
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  max-height: 50%;
  overflow: hidden;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border-bottom: 1px solid #e2e8f0;
}

.panel-header h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
}

.empty-state {
  padding: 40px 20px;
  text-align: center;
  color: #64748b;
}

.empty-state i {
  font-size: 2rem;
  margin-bottom: 8px;
}

.results-content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.plot-container,
.metrics-container,
.data-container {
  padding: 16px;
}

.plot-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  background: #f5f7fa;
  border-radius: 8px;
  color: #64748b;
}

.plot-placeholder i {
  font-size: 3rem;
  margin-bottom: 12px;
}

.metrics-container {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.metric-row {
  display: flex;
  justify-content: space-between;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 6px;
}

.metric-label {
  font-weight: 500;
  color: #64748b;
}

.metric-value {
  font-family: monospace;
  color: #1e293b;
}

.compact-table {
  font-size: 0.85rem;
}
</style>
