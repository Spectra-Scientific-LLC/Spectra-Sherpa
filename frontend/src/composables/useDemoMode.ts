/**
 * Demo mode composable
 *
 * Centralizes all demo-mode state: quota tracking, upgrade modal control,
 * and banner severity. Module-level refs ensure state is shared across
 * all component instances (same pattern as useBackendStatus).
 */

import { ref, computed, readonly } from 'vue'
import { useAppConfig } from '@/composables/useAppConfig'
import type { DemoQuotaResponse } from '@/types/config'

// Module-level state (shared singleton)
const executionsRemaining = ref<number | null>(null)
const executionsLimit = ref(25)
const sherpaRemaining = ref<number | null>(null)
const sherpaLimit = ref(20)
const showUpgradeModal = ref(false)
const upgradeModalContext = ref<{
  message: string
  upgradeUrl: string
  availablePlans: string[]
  blockedCapability?: string
} | null>(null)

export function useDemoMode() {
  const { siteProfile, config } = useAppConfig()

  const isDemoMode = computed(() => siteProfile.value === 'demo')

  const demoContract = computed(() => config.value?.demo ?? null)

  const executionPercent = computed(() => {
    if (executionsRemaining.value === null || executionsLimit.value === 0) return 0
    return Math.round(
      ((executionsLimit.value - executionsRemaining.value) / executionsLimit.value) * 100,
    )
  })

  const bannerSeverity = computed<'info' | 'warning' | 'danger'>(() => {
    if (executionPercent.value >= 100) return 'danger'
    if (executionPercent.value >= 80) return 'warning'
    return 'info'
  })

  async function fetchQuota(): Promise<void> {
    if (!isDemoMode.value) return
    try {
      // Lazy import to avoid circular dependency (this file is imported by client.ts interceptor)
      const { default: api } = await import('@/api/client')
      const { data } = await api.get<DemoQuotaResponse>('/config/demo/quota')
      if (data.demo && data.executions && data.sherpa) {
        executionsRemaining.value = data.executions.remaining
        executionsLimit.value = data.executions.limit
        sherpaRemaining.value = data.sherpa.remaining
        sherpaLimit.value = data.sherpa.limit
      }
    } catch {
      // Non-critical; banner degrades to static mode without quota numbers
    }
  }

  /** Called from API interceptor when 429 with demo fields is received */
  function updateFromRateLimit(remaining: number, limit: number): void {
    executionsRemaining.value = remaining
    executionsLimit.value = limit
  }

  /** Called from API interceptor or WS handler to show the upgrade modal */
  function triggerUpgradeModal(context: typeof upgradeModalContext.value): void {
    upgradeModalContext.value = context
    showUpgradeModal.value = true
  }

  function closeUpgradeModal(): void {
    showUpgradeModal.value = false
    upgradeModalContext.value = null
  }

  return {
    isDemoMode,
    demoContract,
    executionsRemaining: readonly(executionsRemaining),
    executionsLimit: readonly(executionsLimit),
    sherpaRemaining: readonly(sherpaRemaining),
    sherpaLimit: readonly(sherpaLimit),
    executionPercent,
    bannerSeverity,
    showUpgradeModal,
    upgradeModalContext: readonly(upgradeModalContext),
    fetchQuota,
    updateFromRateLimit,
    triggerUpgradeModal,
    closeUpgradeModal,
  }
}
