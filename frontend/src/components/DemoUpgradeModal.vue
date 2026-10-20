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
        <i class="pi pi-lock" aria-hidden="true"></i>
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
        href="https://docs.spectrascientific.ai"
        target="_blank"
        rel="noopener"
        class="upgrade-link upgrade-link--outlined"
      >
        <i class="pi pi-book" aria-hidden="true"></i> View Docs
      </a>
      <a
        v-if="upgradeModalContext?.upgradeUrl"
        :href="upgradeModalContext.upgradeUrl"
        target="_blank"
        rel="noopener"
        class="upgrade-link"
      >
        <i class="pi pi-external-link" aria-hidden="true"></i> View Plans
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
  background: var(--ss-surface-subtle);
  border-radius: 50%;
}
.upgrade-icon i { font-size: 2rem; color: var(--text-color); }
.upgrade-link { display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.75rem 1rem;
  border: 1px solid var(--primary-color); border-radius: var(--border-radius);
  background: var(--primary-color); color: var(--primary-color-text); text-decoration: none; font-weight: 600; }
.upgrade-link--outlined { background: transparent; color: var(--primary-color); }
.upgrade-link:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 3px; }

.upgrade-message {
  margin: 0;
  color: var(--ss-action-text);
  font-size: 0.95rem;
  line-height: 1.5;
}

.upgrade-capability {
  margin-top: 4px;
}

.upgrade-plans h4 {
  margin: 0 0 8px;
  font-size: 0.85rem;
  color: var(--ss-text-muted);
  font-weight: 600;
}

.plan-chips {
  display: flex;
  gap: 8px;
  justify-content: center;
}
</style>
