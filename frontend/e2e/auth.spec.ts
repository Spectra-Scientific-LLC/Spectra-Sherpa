import { test, expect, login } from "./fixtures/auth";

test.describe("Authentication", () => {
  test("login with valid credentials lands on project page", async ({
    page,
  }) => {
    await login(page);
    await expect(page).toHaveURL(/\/project/);
    // Sidebar should be visible with navigation
    await expect(page.locator(".sidebar")).toBeVisible();
  });

  test("login with bad credentials shows error", async ({ page }) => {
    await page.goto("/login");
    await page.getByPlaceholder("Enter your username").fill("nobody");
    await page.getByPlaceholder("Enter your password").fill("wrongpassword");
    await page.getByRole("button", { name: "Sign In" }).click();
    // Should stay on login page with an error
    await expect(page).toHaveURL(/\/login/);
    await expect(page.locator(".text-red-500")).toBeVisible();
  });

  test("unauthenticated access redirects to login", async ({ page }) => {
    await page.goto("/workflow");
    await expect(page).toHaveURL(/\/login/);
  });

  test("logout returns to login page", async ({ authenticatedPage: page }) => {
    // Look for user menu / logout button in the topbar
    const userMenu = page.locator(".topbar-right");
    await userMenu.locator("button").first().click();
    // Look for logout/sign-out option in the dropdown
    const logoutOption = page.getByText(/log\s*out|sign\s*out/i);
    if (await logoutOption.isVisible()) {
      await logoutOption.click();
      await expect(page).toHaveURL(/\/login/);
    }
  });
});
