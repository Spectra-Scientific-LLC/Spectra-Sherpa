// Product limit shared by all interactive Advisor surfaces. Campaign jobs have
// their own progress, cancellation and execution budgets.
export const SHERPA_RESPONSE_TIMEOUT_MS = 60_000;
export const SHERPA_SYNC_TIMEOUT_MS = 60_000;
export function sherpaResponseTimeoutMs(_sync = false): number {
  return SHERPA_RESPONSE_TIMEOUT_MS;
}
