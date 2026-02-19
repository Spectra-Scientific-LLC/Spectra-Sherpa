/**
 * Sherpa subscription upgrade composable
 *
 * Provides a guard + modal trigger for subscription-gated features.
 * Components call `requireFeature('sherpaPeakId')` before executing a
 * gated action — if the feature is disabled, the upgrade modal is shown
 * and the function returns false.
 */

import { ref } from 'vue'
import { useAppConfig } from '@/composables/useAppConfig'
import type { AppFeatures } from '@/types/config'

const showUpgradeModal = ref(false)
const upgradeFeature = ref('')
const upgradeMessage = ref('')

const FEATURE_LABELS: Record<string, string> = {
  sherpaPeakId: 'Peak Identification',
  sherpaCodeGen: 'Code Generation',
  sherpaWriteReport: 'Report Writing',
  sherpaAgenticTools: 'Agentic Tools',
  sherpaFullContext: 'Full DAG Context',
  sherpaAdvisor: 'Sherpa Advisor',
}

function showUpgrade(feature: string, message?: string): void {
  upgradeFeature.value = FEATURE_LABELS[feature] || feature
  upgradeMessage.value =
    message ||
    `${FEATURE_LABELS[feature] || feature} requires a Sherpa Pro subscription.`
  showUpgradeModal.value = true
}

function closeUpgrade(): void {
  showUpgradeModal.value = false
}

/**
 * Guard a subscription-gated action.
 *
 * Returns `true` if the feature is enabled and the caller should proceed.
 * Returns `false` and shows the upgrade modal if the feature is disabled.
 */
function requireFeature(feature: keyof AppFeatures): boolean {
  const { isFeatureEnabled } = useAppConfig()
  if (isFeatureEnabled(feature)) {
    return true
  }
  showUpgrade(feature)
  return false
}

export function useSherpaUpgrade() {
  return {
    showUpgradeModal,
    upgradeFeature,
    upgradeMessage,
    showUpgrade,
    closeUpgrade,
    requireFeature,
  }
}
