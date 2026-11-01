<template>
  <a v-if="destination" :href="destination" class="retained-map-link" @click.stop>Inspect retained exclusions · Run #{{ runId }}</a>
  <span v-else>Retained source run map unavailable</span>
</template>

<script setup lang="ts">
import { computed } from 'vue';
const props = defineProps<{ runId?: number | null; projectId?: number | null }>();
// Navigation only: lists never read source outputs to construct this link.
const destination = computed(() => Number.isSafeInteger(props.runId) && Number(props.runId) > 0
  && Number.isSafeInteger(props.projectId) && Number(props.projectId) > 0
  ? `/runs/${props.runId}?project=${props.projectId}&tab=inspect&view=Summary#retained-observation-exclusions` : null);
</script>
