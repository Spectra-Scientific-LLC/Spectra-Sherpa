<template>
  <section class="nist-content">
    <div class="section-header">
      <div>
        <h1>Library</h1>
        <p class="section-subtitle">
          Search and import reference spectra from NIST and other databases
        </p>
      </div>
      <div class="header-actions">
        <span
          v-if="jobStore.connectionStatus !== 'connected'"
          class="ws-status"
          :class="jobStore.connectionStatus"
        >
          {{
            jobStore.connectionStatus === "connecting"
              ? "Realtime reconnecting..."
              : "Realtime disconnected"
          }}
          <span v-if="jobStore.lastError">({{ jobStore.lastError }})</span>
        </span>
      </div>
    </div>

    <TabView v-model:activeIndex="activeTab">
      <TabPanel header="Search">
        <SearchTab @switch-to-library="activeTab = 1" />
      </TabPanel>
      <TabPanel header="Library">
        <LibraryTab />
      </TabPanel>
      <TabPanel header="Blend">
        <BlendTab />
      </TabPanel>
    </TabView>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue";
import TabView from "primevue/tabview";
import TabPanel from "primevue/tabpanel";
import { useJobStore } from "@/stores/job";
import SearchTab from "./SearchTab.vue";
import LibraryTab from "./LibraryTab.vue";
import BlendTab from "./BlendTab.vue";

const jobStore = useJobStore();
const activeTab = ref(0);

onMounted(() => {
  jobStore.connect();
  jobStore.fetchJobs();
});
</script>

<style scoped>
.nist-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.ws-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid #fde047;
  background: #fefce8;
  color: #a16207;
  font-size: 0.85rem;
}

.ws-status.disconnected {
  border-color: #fecaca;
  background: #fef2f2;
  color: #b91c1c;
}

.ws-status.connecting {
  border-color: #fde047;
  background: #fefce8;
  color: #a16207;
}
</style>
