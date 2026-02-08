<template>
  <section class="card settings-view">
    <div class="section-header">
      <div>
        <h1>Settings</h1>
        <p class="section-subtitle">Configure application settings, API keys, and DOE profiles.</p>
      </div>
    </div>

    <TabView v-model:activeIndex="activeTab" class="page-tabs">
      <TabPanel header="API Keys">
        <ApiKeysTab />
      </TabPanel>
      <TabPanel header="DOE Configurations">
        <DOEConfigTab />
      </TabPanel>
      <TabPanel header="Integrations">
        <div class="panel">
          <h3>External Connections</h3>
          <p class="muted-text">Connect external services in a future release.</p>
        </div>
      </TabPanel>
    </TabView>
  </section>
</template>

<script setup lang="ts">
import { ref } from "vue";
import TabPanel from "primevue/tabpanel";
import TabView from "primevue/tabview";
import ApiKeysTab from "./settings/ApiKeysTab.vue";
import DOEConfigTab from "./settings/DOEConfigTab.vue";

const activeTab = ref(0);
</script>

<style scoped>
.settings-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.tab-actions {
  display: flex;
  justify-content: flex-end;
}

.status-message {
  font-size: 0.9rem;
}

.status-message.success {
  color: #15803d;
}

.status-message.error {
  color: #b91c1c;
}
</style>
