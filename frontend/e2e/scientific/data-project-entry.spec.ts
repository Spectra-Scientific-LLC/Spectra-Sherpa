import { test, expect } from "@playwright/test";
import { createDataset } from "./journeys";

for (const key of ["project", "project_id"]) {
  test(`Data deep link (${key}) overrides a remembered different project @smoke`, async ({ page, request }, testInfo) => {
    const target = await createDataset(request, "mixture-ir");
    const other = await createDataset(request, `Iris remembered ${key} ${testInfo.repeatEachIndex}`, { source: "sklearn", name: "iris" });
    await page.goto("/data?tab=import");
    await page.locator(".project-dropdown").click();
    await page.getByRole("option", { name: other.project.name, exact: true }).click();
    await expect(page.locator(".project-value")).toHaveText(other.project.name);

    const link = `/data?${key}=${target.project.id}&experimentId=${target.experiment.id}&fileId=${target.files[0].id}&tab=my-dataset`;
    await page.goto(link);
    for (let visit = 0; visit < 2; visit++) {
      await expect(page.locator(".project-value")).toHaveText(target.project.name);
      const heading = page.locator(".focused-dataset-details > summary");
      await expect(heading).toContainText("mixture-ir");
      await heading.click();
      await expect(page.getByRole("checkbox", { name: "Include sample mixture-ir-01", exact: true }).first()).toBeChecked();
      await expect(page.getByRole("checkbox", { name: "Include sample mixture-ir-02", exact: true }).first()).not.toBeChecked();
      if (visit === 0) await page.reload();
    }
  });
}
