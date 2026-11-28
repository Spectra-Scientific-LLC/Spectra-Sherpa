import { beforeEach, describe, expect, it } from "vitest";

import { navigationRegistry } from "@/navigation/workspace";
import { usePrimaryNavigation } from "@/composables/usePrimaryNavigation";

describe("usePrimaryNavigation", () => {
  beforeEach(() => usePrimaryNavigation().clear());

  it("keeps contributions reactive and removes them by owner", () => {
    const navigation = usePrimaryNavigation();
    navigation.addItems(
      [{ label: "Optimize", to: "/campaigns", icon: "pi pi-chart-line", before: "/deploy" }],
      "server:campaign",
    );

    expect(navigation.items.value).toEqual([
      { label: "Optimize", to: "/campaigns", icon: "pi pi-chart-line", before: "/deploy" },
    ]);

    const pages = navigationRegistry.tree();
    expect(pages.findIndex(({ entry }) => entry.label === "Optimize"))
      .toBe(pages.findIndex(({ id }) => id === "host:deploy") - 1);
    navigation.removeItems("server:campaign");
    expect(navigation.items.value).toEqual([]);
    expect(navigationRegistry.tree().some(({ entry }) => entry.label === "Optimize")).toBe(false);
  });
});
