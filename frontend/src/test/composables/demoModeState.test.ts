import { describe, expect, it } from "vitest";
import {
  executionsRemaining,
  executionsLimit,
  sherpaRemaining,
  sherpaLimit,
  showUpgradeModal,
  upgradeModalContext,
  updateDemoQuotaFromFetch,
  updateDemoQuotaFromRateLimit,
  openDemoUpgradeModal,
  closeDemoUpgradeModal,
} from "@/composables/demoModeState";

describe("demoModeState", () => {
  describe("updateDemoQuotaFromFetch", () => {
    it("updates all quota refs", () => {
      updateDemoQuotaFromFetch(10, 25, 5, 20);

      expect(executionsRemaining.value).toBe(10);
      expect(executionsLimit.value).toBe(25);
      expect(sherpaRemaining.value).toBe(5);
      expect(sherpaLimit.value).toBe(20);
    });
  });

  describe("updateDemoQuotaFromRateLimit", () => {
    it("updates execution quota only", () => {
      updateDemoQuotaFromRateLimit(3, 50);

      expect(executionsRemaining.value).toBe(3);
      expect(executionsLimit.value).toBe(50);
    });
  });

  describe("upgrade modal", () => {
    it("opens and closes modal with context", () => {
      const ctx = {
        message: "Upgrade needed",
        upgradeUrl: "https://pricing",
        availablePlans: ["pro"],
        blockedCapability: "sherpa_chat",
      };

      openDemoUpgradeModal(ctx);

      expect(showUpgradeModal.value).toBe(true);
      expect(upgradeModalContext.value).toEqual(ctx);

      closeDemoUpgradeModal();

      expect(showUpgradeModal.value).toBe(false);
      expect(upgradeModalContext.value).toBeNull();
    });
  });
});
