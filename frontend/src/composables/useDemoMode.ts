/**
 * Demo mode composable
 *
 * Centralizes all demo-mode state: quota tracking, upgrade modal control,
 * and banner severity. Module-level refs ensure state is shared across
 * all component instances (same pattern as useBackendStatus).
 */

import { computed, readonly } from 'vue'
import api from '@/api/client'
import { useAppConfig } from '@/composables/useAppConfig'
import type { DemoQuotaResponse } from '@/types/config'
import {
  closeDemoUpgradeModal,
  executionsLimit,
  executionsRemaining,
  openDemoUpgradeModal,
  sherpaLimit,
  sherpaRemaining,
  showUpgradeModal,
  updateDemoQuotaFromFetch,
  updateDemoQuotaFromRateLimit,
  upgradeModalContext,
} from '@/composables/demoModeState'

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
      const { data } = await api.get<DemoQuotaResponse>('/config/demo/quota')
      if (data.demo && data.executions && data.sherpa) {
        updateDemoQuotaFromFetch(
          data.executions.remaining,
          data.executions.limit,
          data.sherpa.remaining,
          data.sherpa.limit,
        )
      }
    } catch {
      // Non-critical; banner degrades to static mode without quota numbers
    }
  }

  /** Called from API interceptor when 429 with demo fields is received */
  function updateFromRateLimit(remaining: number, limit: number): void {
    updateDemoQuotaFromRateLimit(remaining, limit)
  }

  /** Called from API interceptor or WS handler to show the upgrade modal */
  function triggerUpgradeModal(context: typeof upgradeModalContext.value): void {
    openDemoUpgradeModal(context)
  }

  function closeUpgradeModal(): void {
    closeDemoUpgradeModal()
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
