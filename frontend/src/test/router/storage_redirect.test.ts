import { describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import router from "@/router";

describe("legacy Storage route entry", () => {
  it.each(["/dashboard#storage", "/dashboard?tab=storage"])(
    "redirects %s before Dashboard can load",
    async (url) => {
      const dashboardLoader = vi.fn(async () => ({ template: "<div>Dashboard</div>" }));
      const route = router.getRoutes().find((item) => item.path === "/dashboard")!;
      const testRouter = createRouter({
        history: createMemoryHistory(),
        routes: [
          { path: "/dashboard", beforeEnter: route.beforeEnter, component: dashboardLoader },
          { path: "/settings", component: { template: "<div>Settings</div>" } },
        ],
      });
      await testRouter.push(url);
      expect(testRouter.currentRoute.value.fullPath).toBe("/settings?tab=storage");
      expect(dashboardLoader).not.toHaveBeenCalled();
    },
  );
});
