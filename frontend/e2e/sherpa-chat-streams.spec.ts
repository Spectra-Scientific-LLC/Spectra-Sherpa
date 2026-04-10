import { test, expect } from "./fixtures/auth";

test.describe("Sherpa Chat Streaming", () => {
  test("open chat, send a message, receive streamed response", async ({
    authenticatedPage: page,
  }) => {
    // Open the chat panel via the topbar toggle
    await page.getByRole("button", { name: "Toggle chat panel" }).click();

    // Chat panel should be visible
    await expect(page.locator(".chat-input__field")).toBeVisible();

    // Type a short prompt
    await page.locator(".chat-input__field").fill("What is PCA?");
    await page.locator(".chat-input__field").press("Enter");

    // Wait for a response to appear in the chat messages area.
    // Streamed responses arrive progressively — wait for at least some text.
    const messages = page.locator(".chat-messages .message-content");
    await expect(messages.last()).toBeVisible({ timeout: 30_000 });

    // Verify the response contains meaningful text (not empty)
    const responseText = await messages.last().textContent();
    expect(responseText!.length).toBeGreaterThan(20);
  });
});
