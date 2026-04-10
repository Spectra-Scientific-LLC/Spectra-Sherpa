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

    // Wait for an assistant response bubble to appear.
    // Streamed responses arrive progressively — wait for at least some text.
    const bubbles = page.locator(".chat-message.assistant .chat-bubble");
    await expect(bubbles.last()).toBeVisible({ timeout: 30_000 });

    // Verify the response contains meaningful text (not empty)
    const responseText = await bubbles.last().textContent();
    expect(responseText!.length).toBeGreaterThan(20);
  });
});
