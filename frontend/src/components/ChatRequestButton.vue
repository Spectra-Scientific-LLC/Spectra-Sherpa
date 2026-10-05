<template>
  <Button
    :severity="busy ? 'danger' : undefined"
    :aria-label="busy ? 'Stop analysis' : 'Send message'"
    :title="busy ? 'Stop analysis' : 'Send message'"
    :disabled="!busy && disabled"
    class="chat-request-button"
    @click="busy ? $emit('stop') : $emit('send')"
  >
    <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" :data-state="busy ? 'stop' : 'send'">
      <rect v-if="busy" x="5" y="5" width="14" height="14" rx="1" fill="currentColor" />
      <path v-else d="M3 3 22 12 3 21l3-8 10-1-10-1Z" fill="currentColor" />
    </svg>
  </Button>
</template>

<script setup lang="ts">
import Button from "primevue/button";
defineProps<{ busy: boolean; disabled: boolean }>();
defineEmits<{ (event: "stop"): void; (event: "send"): void }>();
</script>

<style scoped>
.chat-request-button { min-width: 44px; min-height: 44px; justify-content: center; }
</style>
