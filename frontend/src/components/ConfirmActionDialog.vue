<template>
  <Dialog
    :visible="!!request"
    modal
    :header="request?.options.title"
    :style="{ width: '420px' }"
    :breakpoints="{ '480px': '92vw' }"
    class="confirm-action-dialog"
    @update:visible="(visible: boolean) => { if (!visible) settleConfirmation(false); }"
  >
    <p class="confirm-action-dialog__message">{{ request?.options.message }}</p>
    <template #footer>
      <!-- Focus starts on Cancel so Enter or Space never confirms by accident. -->
      <Button label="Cancel" class="p-button-text" autofocus @click="settleConfirmation(false)" />
      <Button
        :label="request?.options.acceptLabel"
        :class="{ 'p-button-danger': request?.options.destructive }"
        @click="settleConfirmation(true)"
      />
    </template>
  </Dialog>
</template>
<script setup lang="ts">
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import { watch } from "vue";
import { cancelPendingConfirmation, pendingConfirmation, settleConfirmation } from "@/composables/useConfirmAction";
import { useAuthStore } from "@/stores/auth";

const request = pendingConfirmation;
// A confirmation belongs to the person who was asked: sign-out or a switch of
// account closes it as declined.
const authStore = useAuthStore();
watch(() => authStore.user?.id ?? null, () => cancelPendingConfirmation());
</script>
<style scoped>
.confirm-action-dialog__message {
  margin: 0;
  line-height: 1.5;
}
</style>
