<template>
  <section class="builder-content">
    <div class="section-header">
      <div>
        <h1>Synthesis</h1>
        <p class="section-subtitle">
          Create synthetic spectra by blending species with custom concentration profiles
        </p>
      </div>
    </div>

    <TabView v-model:activeIndex="activeTab" class="content-tabs">
      <TabPanel header="Preprocess">
        <PreprocessTab />
      </TabPanel>
      <TabPanel header="Blend">
        <BlendTab />
      </TabPanel>
      <TabPanel header="Export">
        <ExportTab />
      </TabPanel>
    </TabView>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue";
import TabView from "primevue/tabview";
import TabPanel from "primevue/tabpanel";
import { useExperimentStore } from "@/stores/experiment";
import { useBuilderStore } from "@/stores/builder";
import PreprocessTab from "./PreprocessTab.vue";
import BlendTab from "./BlendTab.vue";
import ExportTab from "./ExportTab.vue";

const store = useExperimentStore();
const builderStore = useBuilderStore();
const activeTab = ref(0);

onMounted(async () => {
  await store.fetchExperiments();
  await builderStore.fetchCurveDefaults();
});
</script>

<style scoped>
.builder-content {
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
</style>
