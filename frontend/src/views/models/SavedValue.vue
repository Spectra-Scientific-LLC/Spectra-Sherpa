<template>
  <dl v-if="entries.length" class="saved-value">
    <template v-for="[key, item] in entries" :key="key">
      <dt>{{ key.replace(/_/g, ' ') }}</dt>
      <dd>
        <details v-if="item !== null && typeof item === 'object'" @toggle="expanded[key] = ($event.target as HTMLDetailsElement).open">
          <summary>{{ Array.isArray(item) ? `${item.length} items` : 'Details' }}</summary>
          <pre v-if="expanded[key]">{{ JSON.stringify(item, null, 2) }}</pre>
        </details>
        <span v-else>{{ item === null ? 'Not recorded' : String(item) }}</span>
      </dd>
    </template>
  </dl>
  <p v-else>{{ value == null ? 'Not recorded' : typeof value === 'object' ? 'No fields recorded.' : String(value) }}</p>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
const props = defineProps<{ value: unknown }>();
const expanded = ref<Record<string, boolean>>({});
const entries = computed(() => props.value !== null && typeof props.value === 'object' ? Object.entries(props.value) : []);
watch(() => props.value, () => { expanded.value = {}; });
</script>

<style scoped>
.saved-value { display: grid; grid-template-columns: minmax(8rem, 1fr) minmax(0, 2fr); gap: .65rem; }
dt, dd { margin: 0; overflow-wrap: anywhere; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 24rem; overflow: auto; }
</style>
