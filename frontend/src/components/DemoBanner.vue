<template>
  <div v-if="isDemoMode" class="demo-banner" :class="bannerSeverity">
    <i class="pi pi-info-circle"></i>
    <span class="demo-banner-text">
      <strong>Demo Mode</strong>
      <template v-if="executionsRemaining !== null">
        &mdash; {{ executionsRemaining }} of {{ executionsLimit }} executions remaining
      </template>
    </span>
    <a
      :href="demoContract?.upgrade_url || 'https://spectrascientific.ai/pricing'"
      target="_blank"
      rel="noopener"
      class="demo-upgrade-btn"
    >
      <i class="pi pi-arrow-up-right"></i>
      Upgrade
    </a>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useDemoMode } from '@/composables/useDemoMode'

const {
  isDemoMode,
  demoContract,
  executionsRemaining,
  executionsLimit,
  bannerSeverity,
  fetchQuota,
} = useDemoMode()

onMounted(() => {
  fetchQuota()
})
</script>

<style scoped>
.demo-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 10001;
  padding: 8px 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  font-size: 13px;
  font-weight: 500;
  animation: slideDown 0.3s ease-out;
}

.demo-banner.info {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  color: white;
}

.demo-banner.warning {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
  color: white;
}

.demo-banner.danger {
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
  color: white;
}

.demo-banner i.pi {
  font-size: 1rem;
}

.demo-upgrade-btn {
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.3);
  color: white;
  padding: 4px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  text-decoration: none;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: all 0.2s;
}

.demo-upgrade-btn:hover {
  background: rgba(255, 255, 255, 0.35);
  border-color: rgba(255, 255, 255, 0.5);
}

@keyframes slideDown {
  from {
    transform: translateY(-100%);
  }
  to {
    transform: translateY(0);
  }
}
</style>
