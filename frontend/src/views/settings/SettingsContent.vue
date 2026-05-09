<template>
  <section class="settings-content">
    <div class="section-header">
      <div>
        <h1>Settings</h1>
        <p class="section-subtitle">Configure API keys, integrations, and preferences.</p>
      </div>
    </div>

    <!-- Demo / enterprise-managed mode: no user-configurable settings -->
    <div v-if="isDemoMode" class="demo-notice">
      <div class="demo-notice-icon">
        <i class="pi pi-lock" />
      </div>
      <h3>Settings Managed by Administrator</h3>
      <p>
        API keys, integrations, and preferences are pre-configured for this
        demo environment. No user changes are required.
      </p>
      <p class="demo-hint">
        In a self-hosted or local installation, this page allows you to
        configure LLM providers, API keys, and data-privacy preferences.
      </p>
      <GuidanceSettingsSection v-if="showGuidanceSettings" class="demo-guidance" />
    </div>

    <TabView v-else v-model:activeIndex="activeTab">
      <TabPanel header="API Keys">
        <ApiKeysTab />
      </TabPanel>
      <TabPanel header="Integrations">
        <IntegrationsTab />
      </TabPanel>
      <TabPanel v-if="showGuidanceSettings" header="Guidance">
        <GuidanceSettingsSection />
      </TabPanel>
    </TabView>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import TabView from "primevue/tabview";
import TabPanel from "primevue/tabpanel";
import ApiKeysTab from "./ApiKeysTab.vue";
import GuidanceSettingsSection from "./GuidanceSettingsSection.vue";
import IntegrationsTab from "./IntegrationsTab.vue";
import { useAppConfig } from "@/composables/useAppConfig";
import { useDemoMode } from "@/composables/useDemoMode";

const activeTab = ref(0);
const { isDemoMode } = useDemoMode();
const { appMode, isFeatureEnabled } = useAppConfig();
const showGuidanceSettings = computed(
  () => appMode.value !== "local" && isFeatureEnabled("sherpaGuidance")
);
</script>

<style scoped>
.settings-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
}

.demo-notice {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 64px 32px;
  max-width: 520px;
  margin: 48px auto 0;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
}

.demo-notice-icon {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 20px;
}

.demo-notice-icon i {
  font-size: 1.5rem;
  color: #64748b;
}

.demo-notice h3 {
  margin: 0 0 12px;
  font-size: 1.15rem;
  font-weight: 600;
  color: #1e293b;
}

.demo-notice p {
  margin: 0 0 8px;
  font-size: 0.9rem;
  color: #64748b;
  line-height: 1.6;
}

.demo-hint {
  margin-top: 12px;
  font-size: 0.8rem;
  color: #94a3b8;
}

.demo-guidance {
  width: min(520px, 100%);
  margin-top: 24px;
  text-align: left;
}
</style>
