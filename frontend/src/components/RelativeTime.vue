<template>
  <time v-if="date" :datetime="date.toISOString()" :title="formatTimestamp(date)">{{ formatRelativeTime(date) }}</time>
  <span v-else>{{ formatRelativeTime(value) }}</span>
</template>
<script setup lang="ts">
// "5 min ago" with the exact time and zone kept on the element (title and
// machine-readable datetime), so the friendly wording never hides the value.
import { computed } from "vue";
import { formatRelativeTime, formatTimestamp, parseTimestamp, type TimestampInput } from "@/utils/format";

const props = defineProps<{ value: TimestampInput }>();
const date = computed(() => parseTimestamp(props.value));
</script>
