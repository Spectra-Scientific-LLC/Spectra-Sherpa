<template>
  <section class="settings-content">
    <div class="section-header">
      <div>
        <h1>Settings</h1>
        <p class="section-subtitle">Configure API keys, integrations, and preferences.</p>
      </div>
    </div>

    <TabView v-model:activeIndex="activeTab">
      <TabPanel header="API Keys">
        <ApiKeysTab />
      </TabPanel>
      <TabPanel header="Integrations">
        <IntegrationsTab />
      </TabPanel>
      <TabPanel header="Data & Privacy">
        <DataPrivacyTab />
      </TabPanel>
      <TabPanel header="Preferences">
        <PreferencesTab />
      </TabPanel>
    </TabView>
  </section>
</template>

<script setup lang="ts">
import { ref } from "vue";
import TabView from "primevue/tabview";
import TabPanel from "primevue/tabpanel";
import ApiKeysTab from "./ApiKeysTab.vue";
import IntegrationsTab from "./IntegrationsTab.vue";
import DataPrivacyTab from "./DataPrivacyTab.vue";
import PreferencesTab from "./PreferencesTab.vue";

const activeTab = ref(0);
</script>

<style scoped>
.settings-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
}
</style>
