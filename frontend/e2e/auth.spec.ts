import { test, expect } from "./fixtures/auth";

test.describe("OSS local-mode auth boundary", () => {
  test("workflow is reachable without managed login", async ({ page }) => {
    await page.goto("/workflow");
    await expect(page).toHaveURL(/\/workflow/);
    await expect(page.locator(".sidebar")).toBeVisible();
  });

  test("login route is not an OSS-managed auth form", async ({ page }) => {
    await page.goto("/login");

    await expect(page.getByPlaceholder("Enter your username")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Sign In" })).toHaveCount(0);
  });

  test("register route is not an OSS-managed auth form", async ({ page }) => {
    await page.goto("/register");

    await expect(page.getByPlaceholder("Enter your username")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /register|sign up/i })).toHaveCount(0);
  });
});
