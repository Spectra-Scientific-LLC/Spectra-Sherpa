<template>
  <WorkspaceTabs v-model="selected" :tab-ids="tabIds">
    <TabPanel header="History"><input v-model="draft" aria-label="Retained draft" /></TabPanel>
    <TabPanel header="Batch">Batch panel</TabPanel>
  </WorkspaceTabs>
</template>

<script setup lang="ts">
import { ref } from "vue";
import TabPanel from "primevue/tabpanel";
import WorkspaceTabs from "@/components/workspace/WorkspaceTabs.vue";

// A compiled, stable slot that deliberately has no route dependency. Unlike
// hand-built render-function slots, route reuse must not force its redraw.
const tabIds = ["history", "batch"];
const selected = ref("history");
const draft = ref("");
</script>
