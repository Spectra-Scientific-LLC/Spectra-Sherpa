<template>
  <Dialog
    v-model:visible="showUpgradeModal"
    header="Upgrade Required"
    :modal="true"
    :closable="true"
    :style="{ width: '480px' }"
    @hide="closeUpgradeModal"
  >
    <div class="upgrade-content">
      <div class="upgrade-icon">
        <i class="pi pi-lock" style="font-size: 2rem; color: #f59e0b"></i>
      </div>
      <p class="upgrade-message">{{ upgradeModalContext?.message }}</p>

      <div v-if="upgradeModalContext?.blockedCapability" class="upgrade-capability">
        <Tag severity="warning" :value="formatCapability(upgradeModalContext.blockedCapability)" />
      </div>

      <div v-if="upgradeModalContext?.availablePlans?.length" class="upgrade-plans">
        <h4>Available Plans</h4>
        <div class="plan-chips">
          <Tag
            v-for="plan in upgradeModalContext.availablePlans"
            :key="plan"
            severity="info"
            :value="plan.charAt(0).toUpperCase() + plan.slice(1)"
          />
        </div>
      </div>
    </div>

    <template #footer>
      <Button label="Maybe Later" class="p-button-text" @click="closeUpgradeModal" />
      <a
        :href="upgradeModalContext?.upgradeUrl || '#'"
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
import { useDemoMode } from '@/composables/useDemoMode'

const { showUpgradeModal, upgradeModalContext, closeUpgradeModal } = useDemoMode()

function formatCapability(cap: string): string {
  return cap.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())
}
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
  background: #fef3c7;
  border-radius: 50%;
}

.upgrade-message {
  margin: 0;
  color: #334155;
  font-size: 0.95rem;
  line-height: 1.5;
}

.upgrade-capability {
  margin-top: 4px;
}

.upgrade-plans h4 {
  margin: 0 0 8px;
  font-size: 0.85rem;
  color: #64748b;
  font-weight: 600;
}

.plan-chips {
  display: flex;
  gap: 8px;
  justify-content: center;
}
</style>
