<template>
  <section class="settings-content">
    <header class="tab-header">
      <h1>Settings</h1>
    </header>

    <!-- Demo / enterprise-managed mode: deployment settings are locked,
         but per-user HITRAN and preferences stay editable. -->
    <div v-if="isDemoMode" class="demo-region">
      <div class="demo-notice">
        <div class="demo-notice-body">
          <span class="eyebrow">Managed</span>
          <h3>Deployment settings managed by administrator</h3>
          <p>
            LLM providers and integrations are pre-configured for this
            environment. Add your own HITRAN key below to use live HITRAN
            synthesis; shared deployment keys are not provided for HITRAN.
          </p>
          <p class="demo-hint">
            In a self-hosted or local installation, this page also lets you
            configure LLM providers, API keys, and data-privacy preferences.
          </p>
        </div>
      </div>

      <ApiKeysTab />
      <IntegrationsTab privacy-only />

      <div v-if="showGuidanceSettings" class="my-preferences">
        <span class="eyebrow">Your Account</span>
        <h3 class="my-preferences-title">My preferences</h3>
        <p class="my-preferences-subtitle">
          These settings are personal to your account and can be changed
          even on a managed deployment.
        </p>
        <GuidanceSettingsSection class="demo-guidance" />
      </div>
    </div>

    <TabView v-else v-model:activeIndex="activeTab" class="settings-tabs">
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
  gap: 1.5rem;
  padding: 0 1rem 3rem;
  color: var(--text-color);
  font-size: 0.9375rem;
  line-height: 1.5;
}

.eyebrow {
  color: var(--text-color-secondary);
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.demo-region {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  max-width: 920px;
}

.demo-notice {
  display: flex;
  padding: 1.25rem;
  max-width: 920px;
  margin: 0;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  background: var(--surface-card);
}

.demo-notice-body {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.demo-notice h3 {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 500;
  color: var(--text-color);
}

.demo-notice p {
  margin: 0.25rem 0 0;
  font-size: 0.9375rem;
  color: var(--text-color-secondary);
  line-height: 1.5;
}

.demo-hint {
  margin-top: 0.5rem !important;
  font-size: 0.8125rem;
}

.my-preferences {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  max-width: 920px;
  padding: 1.25rem;
  border: 1px solid var(--surface-border);
  background: var(--surface-card);
  border-radius: 8px;
}

.my-preferences-title {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 500;
  color: var(--text-color);
}

.my-preferences-subtitle {
  margin: 0 0 0.75rem;
  font-size: 0.875rem;
  color: var(--text-color-secondary);
  line-height: 1.5;
}

.demo-guidance {
  width: 100%;
  text-align: left;
}

/* Zen tab styling — underline-only, no boxed chrome */
.settings-tabs :deep(.p-tabview-nav) {
  border-bottom: 1px solid var(--surface-border);
  background: transparent;
}

.settings-tabs :deep(.p-tabview-nav li .p-tabview-nav-link) {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-color-secondary);
  font-weight: 500;
  font-size: 0.9375rem;
  padding: 0.625rem 1rem;
}

.settings-tabs :deep(.p-tabview-nav li.p-highlight .p-tabview-nav-link) {
  color: var(--primary-color);
  border-bottom-color: var(--primary-color);
  background: transparent;
}

.settings-tabs :deep(.p-tabview-panels) {
  padding: 1.5rem 0;
  background: transparent;
}
</style>
