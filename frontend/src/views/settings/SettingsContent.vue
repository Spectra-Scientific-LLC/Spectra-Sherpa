<template>
  <section class="settings-content">
    <div class="section-header">
      <div>
        <h1>Settings</h1>
        <p class="section-subtitle">Configure API keys, integrations, and preferences.</p>
      </div>
    </div>

    <!-- Demo / enterprise-managed mode: deployment settings are locked,
         but per-user preferences (e.g. guidance) stay editable. -->
    <div v-if="isDemoMode">
      <div class="demo-notice">
        <div class="demo-notice-icon">
          <i class="pi pi-lock" />
        </div>
        <h3>Deployment Settings Managed by Administrator</h3>
        <p>
          API keys, LLM providers, and integrations are pre-configured for
          this environment and can't be changed here.
        </p>
        <p class="demo-hint">
          In a self-hosted or local installation, this page also lets you
          configure LLM providers, API keys, and data-privacy preferences.
        </p>
      </div>

      <div v-if="showGuidanceSettings" class="my-preferences">
        <h3 class="my-preferences-title">
          <i class="pi pi-user-edit" /> My Preferences
        </h3>
        <p class="my-preferences-subtitle">
          These settings are personal to your account and can be changed
          even on a managed deployment.
        </p>
        <GuidanceSettingsSection class="demo-guidance" />
      </div>
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

.my-preferences {
  max-width: 520px;
  margin: 24px auto 0;
  padding: 24px 28px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
}

.my-preferences-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 6px;
  font-size: 1.05rem;
  font-weight: 600;
  color: #1e293b;
}

.my-preferences-title i {
  color: #6366f1;
}

.my-preferences-subtitle {
  margin: 0 0 16px;
  font-size: 0.85rem;
  color: #64748b;
  line-height: 1.5;
}

.demo-guidance {
  width: 100%;
  text-align: left;
}
</style>
