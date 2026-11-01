<template>
  <RouterLink v-if="destination" :to="destination" class="retained-map-link"
    :title="`Observation exclusions recorded in run #${runId}`"
    :aria-label="`Inspect retained exclusions for run #${runId}`" @click.stop>Exclusions</RouterLink>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { RouterLink } from 'vue-router';
const props = defineProps<{ runId?: number | null; projectId?: number | null }>();
// Navigation only: lists never read source outputs to construct this link.
const destination = computed(() => Number.isSafeInteger(props.runId) && Number(props.runId) > 0
  && Number.isSafeInteger(props.projectId) && Number(props.projectId) > 0
  ? `/runs/${props.runId}?project=${props.projectId}&tab=inspect&view=Summary#retained-observation-exclusions` : null);
</script>
