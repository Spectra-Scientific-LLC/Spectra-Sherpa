import { beforeEach, describe, expect, it } from "vitest";

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

    navigation.removeItems("server:campaign");
    expect(navigation.items.value).toEqual([]);
  });
});
