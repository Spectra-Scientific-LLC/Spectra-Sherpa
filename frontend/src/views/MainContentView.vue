<template>
  <div class="main-content-wrapper">
    <!-- Workspace (Hub) -->
    <WorkflowBuilderContent v-if="currentView === 'workspace' || currentView === 'builder'" />

    <!-- Operations Section -->
    <CalibrationsContent v-else-if="currentView === 'calibration'" />
    <ProcessContent v-else-if="currentView === 'process'" />
    <AnalysisMethodsContent v-else-if="currentView === 'analysis'" />

    <!-- Templates -->
    <TemplatesContent v-else-if="currentView === 'templates'" />

    <!-- Fallback to Workspace -->
    <WorkflowBuilderContent v-else />
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";

// Operations tab components
import CalibrationsContent from "@/views/calibrations/CalibrationsContent.vue";
import ProcessContent from "@/views/process/ProcessContent.vue";
import AnalysisMethodsContent from "@/views/analysis-methods/AnalysisMethodsContent.vue";

// Workspace (main hub) - the unified workflow canvas
import WorkflowBuilderContent from "@/views/workflow-builder/WorkflowBuilderContent.vue";
import TemplatesContent from "@/views/templates/TemplatesContent.vue";

const route = useRoute();

// Get current view from route subTab param
const currentView = computed(() => {
  return route.params.subTab as string || "workspace";
});
</script>

<style scoped>
.main-content-wrapper {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: auto;
  padding: 20px;
}
</style>
