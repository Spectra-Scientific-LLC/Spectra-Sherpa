import { ref } from "vue";

export type DemoUpgradeContext = {
  message: string;
  upgradeUrl: string;
  availablePlans: string[];
  blockedCapability?: string;
} | null;

// Sliding-window quota state. The demo backend tracks two independent
// caps per category (executions, sherpa): a 60-minute rolling window
// and a 24-hour rolling window. The `null` sentinel on the "used"
// counters means "not yet fetched" — UI hides the bar until a real
// number arrives.
export const executionsLastHour = ref<number | null>(null);
export const executionsLastDay = ref<number | null>(null);
export const executionsLimitHour = ref(0);
export const executionsLimitDay = ref(0);

export const sherpaLastHour = ref<number | null>(null);
export const sherpaLastDay = ref<number | null>(null);
export const sherpaLimitHour = ref(0);
export const sherpaLimitDay = ref(0);

export const uploadsLastWeek = ref<number | null>(null);
export const uploadsLimitWeek = ref(0);
export const uploadsResetWeekAt = ref<string | null>(null);

export const showUpgradeModal = ref(false);
export const upgradeModalContext = ref<DemoUpgradeContext>(null);

export interface DemoQuotaWindowSnapshot {
  lastHour: number;
  lastDay: number;
  limitPerHour: number;
  limitPerDay: number;
  resetHourAt?: string | null;
  resetDayAt?: string | null;
}

export interface DemoUploadQuotaWindowSnapshot {
  lastWeek: number;
  limitPerWeek: number;
  resetWeekAt?: string | null;
}

export function updateDemoQuotaFromFetch(
  executions: DemoQuotaWindowSnapshot,
  sherpa: DemoQuotaWindowSnapshot,
  uploads?: DemoUploadQuotaWindowSnapshot
): void {
  executionsLastHour.value = executions.lastHour;
  executionsLastDay.value = executions.lastDay;
  executionsLimitHour.value = executions.limitPerHour;
  executionsLimitDay.value = executions.limitPerDay;
  sherpaLastHour.value = sherpa.lastHour;
  sherpaLastDay.value = sherpa.lastDay;
  sherpaLimitHour.value = sherpa.limitPerHour;
  sherpaLimitDay.value = sherpa.limitPerDay;
  if (uploads) {
    uploadsLastWeek.value = uploads.lastWeek;
    uploadsLimitWeek.value = uploads.limitPerWeek;
    uploadsResetWeekAt.value = uploads.resetWeekAt ?? null;
  }
}

/** Update from a structured 429 detail emitted by the demo quota gate. */
export function updateDemoQuotaFromRateLimit(detail: {
  limit_type?: string;
  limit_per_hour?: number;
  limit_per_day?: number;
  limit_per_week?: number;
  remaining?: number;
}): void {
  // The 429 detail describes the binding window that just rejected the
  // request. We update the matching category's *limit* refs so the
  // banner reflects current contract, and leave the lastHour/Day
  // counters alone (they'll refresh on the next /quota fetch).
  if (detail.limit_type === "upload") {
    if (typeof detail.limit_per_week === "number") uploadsLimitWeek.value = detail.limit_per_week;
  } else if (detail.limit_type === "sherpa") {
    if (typeof detail.limit_per_hour === "number") sherpaLimitHour.value = detail.limit_per_hour;
    if (typeof detail.limit_per_day === "number") sherpaLimitDay.value = detail.limit_per_day;
  } else {
    if (typeof detail.limit_per_hour === "number") executionsLimitHour.value = detail.limit_per_hour;
    if (typeof detail.limit_per_day === "number") executionsLimitDay.value = detail.limit_per_day;
  }
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
