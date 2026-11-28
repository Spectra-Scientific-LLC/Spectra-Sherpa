<template>
  <section class="settings-content">
    <WorkspacePageHeader :title="settingsTitles[activeTab] || 'Settings'" :identity="settingsIdentity" />
    <WorkspaceTabs
:model-value="activeTab" :tab-ids="settingsTabIds" class="settings-tabs"
      @update:model-value="selectSettingsTab">
    <TabPanel v-if="isManaged" header="General">
    <!-- Hosted Pro exposes personal disclosure and acquisition preferences. -->
    <div v-if="isHostedPro" class="demo-region">
      <div class="demo-notice" role="status">
        <h3>Hosted providers are managed by your operator</h3>
      </div>
      <ApiKeysTab hitran-only />
      <IntegrationsTab privacy-only />
      <PlateFormatSettingsSection />
      <DisplayPreferencesSection />
      <div v-if="showGuidanceSettings" class="my-preferences">
        <span class="eyebrow">Your Account</span>
        <h3 class="my-preferences-title">My preferences</h3>
        <GuidanceSettingsSection class="pro-guidance" />
      </div>
    </div>
    <div v-else-if="isDemoMode" class="demo-region">
      <div class="demo-notice">
        <div class="demo-notice-body">
          <span class="eyebrow">Managed</span>
          <h3>Deployment settings managed by administrator</h3>
          <p>HITRAN requires your own key.</p>
        </div>
      </div>

      <ApiKeysTab />
      <IntegrationsTab privacy-only />
      <PlateFormatSettingsSection />
      <DisplayPreferencesSection />

      <div v-if="showGuidanceSettings" class="my-preferences">
        <span class="eyebrow">Your Account</span>
        <h3 class="my-preferences-title">My preferences</h3>
        <GuidanceSettingsSection class="demo-guidance" />
      </div>
    </div>

    </TabPanel>
      <TabPanel v-if="!isManaged" header="General">
        <section class="navigation-setting">
          <fieldset>
            <legend>Navigation</legend>
            <label><input name="navigation-mode" type="radio" :checked="navigationMode === 'menu-bar'"
              :disabled="!hasNativeNavigation" @change="setNavigationMode('menu-bar')" /> Menu bar</label>
            <label><input name="navigation-mode" type="radio" :checked="navigationMode === 'sidebar'"
              @change="setNavigationMode('sidebar')" /> Sidebar</label>
          </fieldset>
        </section>
        <PlateFormatSettingsSection />
        <DisplayPreferencesSection />
      </TabPanel>
      <TabPanel v-if="!isManaged" header="Compute">
        <dl class="compute-status" aria-label="Current work">
          <dt>Running jobs</dt><dd>{{ runningJobs }}</dd>
          <dt>Queued jobs</dt><dd>{{ queuedJobs }}</dd>
        </dl>
      </TabPanel>
      <TabPanel v-if="!isManaged" :header="appMode === 'local' ? 'Chat' : 'API Keys'">
        <ApiKeysTab />
        <div v-if="appMode === 'local'" id="settings-chat-privacy" />
      </TabPanel>
      <TabPanel v-if="!isManaged" header="Integrations">
        <div v-if="appMode === 'local'" id="settings-service-privacy" />
        <IntegrationsTab v-else />
      </TabPanel>
      <TabPanel v-if="canEditCustomNodes" header="Custom nodes">
        <CustomNodesSettingsSection />
      </TabPanel>
      <TabPanel v-if="!isManaged && showGuidanceSettings" header="Guidance">
        <GuidanceSettingsSection />
      </TabPanel>
      <TabPanel header="Storage">
        <RetainedStorageRecovery />
      </TabPanel>
    </WorkspaceTabs>
    <Teleport v-if="!isManaged && appMode === 'local'" defer
      :to="activeTab === 'chat' ? '#settings-chat-privacy' : '#settings-service-privacy'">
      <IntegrationsTab :privacy-scope="activeTab === 'chat' ? 'chat' : 'services'" />
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { navigationTab } from "@/router/legacyRoutes";
import WorkspacePageHeader from "@/components/workspace/WorkspacePageHeader.vue";
import CustomNodesSettingsSection from "./CustomNodesSettingsSection.vue";
import { hasNativeNavigation, navigationMode, setNavigationMode } from "@/navigation/mode";
import { useJobStore } from "@/stores/job";
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import WorkspaceTabs from "@/components/workspace/WorkspaceTabs.vue";
import TabPanel from "primevue/tabpanel";
import ApiKeysTab from "./ApiKeysTab.vue";
import GuidanceSettingsSection from "./GuidanceSettingsSection.vue";
import IntegrationsTab from "./IntegrationsTab.vue";
import PlateFormatSettingsSection from "./PlateFormatSettingsSection.vue";
import DisplayPreferencesSection from "./DisplayPreferencesSection.vue";
import RetainedStorageRecovery from "@/components/RetainedStorageRecovery.vue";
import { useAppConfig } from "@/composables/useAppConfig";
import { useDemoMode } from "@/composables/useDemoMode";

const route = useRoute();
const router = useRouter();
const activeTab = ref("general");
const { isDemoMode } = useDemoMode();
const { appMode, siteProfile, isFeatureEnabled, appConfig } = useAppConfig();
const isHostedPro = computed(() => appMode.value === "enterprise" && siteProfile?.value === "pro");
const isManaged = computed(() => isHostedPro.value || isDemoMode.value);
const showGuidanceSettings = computed(
  () => appMode.value !== "local" && isFeatureEnabled("sherpaGuidance"),
);
const canEditCustomNodes = computed(() => !isManaged.value && appMode.value === "local" && !appConfig?.value?.desktop);
const jobStore = useJobStore();
const runningJobs = computed(() => (jobStore.jobs ?? []).filter(job => job.status === "running").length);
const queuedJobs = computed(() => (jobStore.jobs ?? []).filter(job => job.status === "pending").length);
const settingsTitles: Record<string, string> = {
  general: "General", compute: "Compute", chat: "Chat", "api-keys": "API Keys",
  integrations: "Integrations", "custom-nodes": "Custom nodes", guidance: "Guidance", storage: "Storage",
};
const settingsIdentity = computed(() => activeTab.value === "chat" ? "Used by chat and Data Story" : undefined);
const settingsTabIds = computed(() => isManaged.value ? ["general", "storage"] : [
  "general", "compute", appMode.value === "local" ? "chat" : "api-keys", "integrations",
  ...(canEditCustomNodes.value ? ["custom-nodes"] : []),
  ...(showGuidanceSettings.value ? ["guidance"] : []), "storage",
]);
watch([() => navigationTab(route.query), () => route.hash, settingsTabIds], () => {
  const tab = navigationTab(route.query);
  const requested = typeof tab === "string" ? tab : route.hash?.slice(1);
  const selected = requested === "preferences" || requested === "data" ? "general"
    : requested === "api-keys" && appMode.value === "local" ? "chat" : requested;
  activeTab.value = selected && settingsTabIds.value.includes(selected) ? selected : settingsTabIds.value[0];
}, { immediate: true });
function selectSettingsTab(tab: string): void {
  activeTab.value = tab;
  void router.push({ query: { ...route.query, tab }, hash: "" });
}
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

:global(.content:has(.settings-content)) {
  background: var(--workspace-background);
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

/* Match the rimmed workspace subtabs. */
.settings-tabs :deep(.p-tabview-nav) {
  gap: 0.375rem;
  border-bottom: 1px solid var(--surface-border);
  background: transparent;
}

.settings-tabs :deep(.p-tabview-nav li .p-tabview-nav-link) {
  background: transparent;
  border: 1px solid color-mix(in srgb, var(--text-color-secondary) 55%, var(--surface-border));
  border-radius: 6px 6px 0 0;
  margin-bottom: 0;
  color: var(--text-color-secondary);
  font-weight: 500;
  font-size: 0.9375rem;
  padding: 0.625rem 1rem;
}

.settings-tabs :deep(.p-tabview-nav li.p-highlight .p-tabview-nav-link) {
  color: var(--primary-color);
  border-color: var(--primary-color);
  background: color-mix(in srgb, var(--primary-color) 8%, transparent);
}

.settings-tabs :deep(.p-tabview-panels) {
  padding: 1.5rem 0;
  background: transparent;
}
.navigation-setting fieldset { display: flex; flex-wrap: wrap; gap: .75rem 1rem; border: 1px solid var(--surface-border); border-radius: .65rem; }
.navigation-setting label { display: inline-flex; align-items: center; gap: .35rem; }
.navigation-setting input { accent-color: var(--ss-action); }
.compute-status { display: grid; grid-template-columns: max-content auto; gap: .5rem 1rem; }
.compute-status dd { margin: 0; }
</style>
