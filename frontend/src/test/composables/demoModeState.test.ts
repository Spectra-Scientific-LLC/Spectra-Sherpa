import { describe, expect, it } from "vitest";
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
  updateDemoQuotaFromRateLimit,
  uploadsLastWeek,
  uploadsLimitWeek,
  uploadsResetWeekAt,
  upgradeModalContext,
} from "@/composables/demoModeState";

describe("demoModeState", () => {
  describe("updateDemoQuotaFromFetch", () => {
    it("updates all four windows for both categories", () => {
      updateDemoQuotaFromFetch(
        { lastHour: 5, lastDay: 40, limitPerHour: 100, limitPerDay: 5000 },
        { lastHour: 2, lastDay: 12, limitPerHour: 50, limitPerDay: 1000 },
        { lastWeek: 1, limitPerWeek: 1, resetWeekAt: "2026-06-03T10:00:00" }
      );

      expect(executionsLastHour.value).toBe(5);
      expect(executionsLastDay.value).toBe(40);
      expect(executionsLimitHour.value).toBe(100);
      expect(executionsLimitDay.value).toBe(5000);

      expect(sherpaLastHour.value).toBe(2);
      expect(sherpaLastDay.value).toBe(12);
      expect(sherpaLimitHour.value).toBe(50);
      expect(sherpaLimitDay.value).toBe(1000);
      expect(uploadsLastWeek.value).toBe(1);
      expect(uploadsLimitWeek.value).toBe(1);
      expect(uploadsResetWeekAt.value).toBe("2026-06-03T10:00:00");
    });
  });

  describe("updateDemoQuotaFromRateLimit", () => {
    it("updates execution limits from a workflow 429 detail", () => {
      executionsLimitHour.value = 0;
      executionsLimitDay.value = 0;
      updateDemoQuotaFromRateLimit({
        limit_type: "execution",
        limit_per_hour: 75,
        limit_per_day: 4000,
        remaining: 0,
      });
      expect(executionsLimitHour.value).toBe(75);
      expect(executionsLimitDay.value).toBe(4000);
    });

    it("routes sherpa 429 detail to the sherpa refs", () => {
      sherpaLimitHour.value = 0;
      sherpaLimitDay.value = 0;
      updateDemoQuotaFromRateLimit({
        limit_type: "sherpa",
        limit_per_hour: 40,
        limit_per_day: 800,
        remaining: 0,
      });
      expect(sherpaLimitHour.value).toBe(40);
      expect(sherpaLimitDay.value).toBe(800);
    });

    it("routes upload 429 detail to the upload refs", () => {
      uploadsLimitWeek.value = 0;
      updateDemoQuotaFromRateLimit({
        limit_type: "upload",
        limit_per_week: 1,
        remaining: 0,
      });
      expect(uploadsLimitWeek.value).toBe(1);
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
