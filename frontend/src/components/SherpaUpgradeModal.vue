<template>
  <Dialog
    v-model:visible="showUpgradeModal"
    header="Sherpa Pro Required"
    :modal="true"
    :closable="true"
    :style="{ width: '480px' }"
    @hide="closeUpgrade"
  >
    <div class="upgrade-content">
      <div class="upgrade-icon">
        <i class="pi pi-lock" style="font-size: 2rem; color: #3b82f6"></i>
      </div>
      <p class="upgrade-message">{{ upgradeMessage }}</p>

      <div v-if="upgradeFeature" class="upgrade-capability">
        <Tag severity="info" :value="upgradeFeature" />
      </div>
    </div>

    <template #footer>
      <Button label="Maybe Later" class="p-button-text" @click="closeUpgrade" />
      <a
        :href="upgradeUrl"
        target="_blank"
        rel="noopener"
        style="text-decoration: none"
      >
        <Button label="View Plans" icon="pi pi-external-link" />
      </a>
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import Dialog from 'primevue/dialog'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import { computed } from 'vue'
import { useAppConfig } from '@/composables/useAppConfig'
import { useSherpaUpgrade } from '@/composables/useSherpaUpgrade'

const { config } = useAppConfig()
const { showUpgradeModal, upgradeFeature, upgradeMessage, closeUpgrade } =
  useSherpaUpgrade()

const upgradeUrl = computed(
  () => config.value?.subscription?.upgrade_url || 'https://spectrasherpa.com/pricing'
)
</script>

<style scoped>
.upgrade-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 8px 0;
  text-align: center;
}

.upgrade-icon {
  width: 64px;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #dbeafe;
  border-radius: 50%;
}

.upgrade-message {
  margin: 0;
  color: var(--text-color);
  font-size: 0.95rem;
  line-height: 1.5;
}

.upgrade-capability {
  margin-top: 4px;
}
</style>
