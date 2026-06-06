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
  executionsLastDay,
  executionsLastHour,
  executionsLimitDay,
  executionsLimitHour,
  openDemoUpgradeModal,
  sherpaLastDay,
  sherpaLastHour,
  sherpaLimitDay,
  sherpaLimitHour,
  showUpgradeModal,
  updateDemoQuotaFromFetch,
  upgradeModalContext,
  uploadsLastWeek,
  uploadsLimitWeek,
  uploadsResetWeekAt,
} from '@/composables/demoModeState'

function windowPercent(used: number | null, limit: number): number {
  if (used == null || !limit) return 0
  return Math.min(100, Math.round((used / limit) * 100))
}

export function useDemoMode() {
  const { siteProfile, config } = useAppConfig()

  const isDemoMode = computed(() => siteProfile?.value === 'demo')

  const demoContract = computed(() => config?.value?.demo ?? null)

  // Pick the tightest window (hourly vs daily) — that's the one closest
  // to throttling the user. Used by the demo banner to color itself.
  const executionPercent = computed(() => Math.max(
    windowPercent(executionsLastHour.value, executionsLimitHour.value),
    windowPercent(executionsLastDay.value, executionsLimitDay.value),
  ))

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
        updateDemoQuotaFromFetch(data.executions, data.sherpa, data.uploads)
      }
    } catch {
      // Non-critical; banner degrades to static mode without quota numbers
    }
  }

  /** Called from API interceptor when 429 with demo fields is received */
  function updateFromRateLimit(detail: {
    limit_type?: string
    limit_per_hour?: number
    limit_per_day?: number
    limit_per_week?: number
    remaining?: number
  }): void {
    // Re-export so callers don't need to import the state module
    // directly. Implementation lives in demoModeState.
    import('@/composables/demoModeState').then(({ updateDemoQuotaFromRateLimit }) => {
      updateDemoQuotaFromRateLimit(detail)
    })
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
    executionsLastHour: readonly(executionsLastHour),
    executionsLastDay: readonly(executionsLastDay),
    executionsLimitHour: readonly(executionsLimitHour),
    executionsLimitDay: readonly(executionsLimitDay),
    sherpaLastHour: readonly(sherpaLastHour),
    sherpaLastDay: readonly(sherpaLastDay),
    sherpaLimitHour: readonly(sherpaLimitHour),
    sherpaLimitDay: readonly(sherpaLimitDay),
    uploadsLastWeek: readonly(uploadsLastWeek),
    uploadsLimitWeek: readonly(uploadsLimitWeek),
    uploadsResetWeekAt: readonly(uploadsResetWeekAt),
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
