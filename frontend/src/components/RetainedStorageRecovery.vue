<template>
  <div class="storage-recovery">
    <Button
      label="Reclaim Storage"
      icon="pi pi-trash"
      class="p-button-text p-button-sm"
      :loading="reclaimingStorage"
      @click="reclaimStorage"
    />
    <p>
      Reclaim unused outputs across your projects while preserving saved runs and recently written
      files.
    </p>
    <details>
      <summary>Details</summary>
      Only unreferenced outputs older than 24 hours are removed; saved runs and their shared outputs
      remain intact.
    </details>
    <p v-if="storageMessage" role="status">{{ storageMessage }}</p>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import Button from "primevue/button";
import { useRunsStore } from "@/stores/runs";
const runsStore = useRunsStore();
const reclaimingStorage = ref(false);
const storageMessage = ref("");
async function reclaimStorage(): Promise<void> {
  reclaimingStorage.value = true;
  storageMessage.value = "";
  try {
    const result = await runsStore.reclaimStorage();
    const mib = (bytes: number) => (bytes / 1024 / 1024).toFixed(2);
    storageMessage.value =
      `Removed ${result.removed_files} unreferenced files. ` +
      `Retained output storage: ${mib(result.used_bytes)} MiB of ${mib(result.quota_bytes)} MiB. ` +
      `Files written within the last ${result.grace_seconds / 3600} hours remain protected.`;
  } catch (_err: unknown) {
    storageMessage.value = "Storage reclamation failed. No success was confirmed; retry.";
  } finally {
    reclaimingStorage.value = false;
  }
}
</script>
