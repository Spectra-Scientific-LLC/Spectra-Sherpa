import { ref } from "vue";

export type DemoUpgradeContext = {
  message: string;
  upgradeUrl: string;
  availablePlans: string[];
  blockedCapability?: string;
} | null;

export const executionsRemaining = ref<number | null>(null);
export const executionsLimit = ref(25);
export const sherpaRemaining = ref<number | null>(null);
export const sherpaLimit = ref(20);
export const showUpgradeModal = ref(false);
export const upgradeModalContext = ref<DemoUpgradeContext>(null);

export function updateDemoQuotaFromFetch(
  executionRemaining: number,
  executionCap: number,
  sherpaQuotaRemaining: number,
  sherpaQuotaCap: number
): void {
  executionsRemaining.value = executionRemaining;
  executionsLimit.value = executionCap;
  sherpaRemaining.value = sherpaQuotaRemaining;
  sherpaLimit.value = sherpaQuotaCap;
}

export function updateDemoQuotaFromRateLimit(
  remaining: number,
  limit: number
): void {
  executionsRemaining.value = remaining;
  executionsLimit.value = limit;
}

export function openDemoUpgradeModal(
  context: DemoUpgradeContext
): void {
  upgradeModalContext.value = context;
  showUpgradeModal.value = true;
}

export function closeDemoUpgradeModal(): void {
  showUpgradeModal.value = false;
  upgradeModalContext.value = null;
}
