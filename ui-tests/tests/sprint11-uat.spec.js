const { test, expect } = require("@playwright/test");

/**
 * Sprint 11 UAT — Voice UX polish verification:
 *   1. Chat mic button visible in input bar
 *   2. Auto-speak toggle visible and localStorage-persisted
 *   3. Chat greeting regression check
 *   4. Chat streaming regression check
 *   5. API endpoints still return 200
 *   6. Full page screenshot for visual review
 */

test.describe("Sprint 11 UAT — Voice UX", () => {
  let consoleErrors;

  test.beforeEach(async ({ page }) => {
    consoleErrors = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
  });

  // ── UAT-S11-01: Chat mic button visible ─────────────────────────────
  test("UAT-S11-01: chat mic button is visible in the input bar", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Live Desktop Context" })).toBeVisible({ timeout: 15_000 });
    await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });

    // Mic button should be visible
    const micBtn = page.locator("#chat-mic-btn");
    await expect(micBtn).toBeVisible({ timeout: 5_000 });

    // It should have an aria-label for accessibility
    await expect(micBtn).toHaveAttribute("aria-label", "Voice input");

    // It should contain an SVG icon
    const svg = micBtn.locator("svg");
    await expect(svg).toBeVisible();

    // It should be positioned between the input and Send button
    const inputBar = page.locator(".chat-input-bar");
    const children = await inputBar.locator("> *").all();
    expect(children.length).toBeGreaterThanOrEqual(3); // input, mic, send

    const realErrors = consoleErrors.filter((e) => !e.includes("favicon.ico"));
    expect(realErrors).toEqual([]);
  });

  // ── UAT-S11-02: Auto-speak toggle visible and persists ──────────────
  test("UAT-S11-02: auto-speak toggle is visible and persists via localStorage", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });

    // Auto-speak toggle should exist
    const toggle = page.locator("#chat-autospeak-toggle");
    await expect(toggle).toBeVisible({ timeout: 5_000 });

    // Should be unchecked by default
    await expect(toggle).not.toBeChecked();

    // Check the toggle
    await toggle.check();
    await expect(toggle).toBeChecked();

    // Verify localStorage was set
    const stored = await page.evaluate(() => localStorage.getItem("desktopai-autospeak"));
    expect(stored).toBe("true");

    // Reload page and verify persistence
    await page.reload();
    await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });
    const toggleAfter = page.locator("#chat-autospeak-toggle");
    await expect(toggleAfter).toBeChecked();

    // Clean up
    await toggleAfter.uncheck();
    await page.evaluate(() => localStorage.removeItem("desktopai-autospeak"));

    const realErrors = consoleErrors.filter((e) => !e.includes("favicon.ico"));
    expect(realErrors).toEqual([]);
  });

  // ── UAT-S11-03: Chat greeting regression ────────────────────────────
  test("UAT-S11-03: chat greeting still works after voice UX changes", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });

    await page.fill("#chat-input", "hello");
    await page.click("#chat-send-btn");

    await expect(page.locator(".chat-msg.agent .chat-msg-bubble").last()).toBeVisible({ timeout: 10_000 });
    const response = await page.locator(".chat-msg.agent .chat-msg-bubble").last().textContent();
    expect(response.length).toBeGreaterThan(0);

    await expect(page.locator(".chat-badge.source").filter({ hasText: /greeting/i })).toBeVisible({ timeout: 5_000 });

    const realErrors = consoleErrors.filter((e) => !e.includes("favicon.ico"));
    expect(realErrors).toEqual([]);
  });

  // ── UAT-S11-04: Chat streaming regression ───────────────────────────
  test("UAT-S11-04: chat LLM streaming still works after voice UX changes", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });

    await page.fill("#chat-input", "what is 2+2?");
    await page.click("#chat-send-btn");

    await expect(page.locator(".chat-msg.agent .chat-msg-bubble").last()).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(".chat-msg.agent.streaming")).toHaveCount(0, { timeout: 60_000 });

    const response = await page.locator(".chat-msg.agent .chat-msg-bubble").last().textContent();
    expect(response.length).toBeGreaterThan(5);

    await expect(page.locator(".chat-badge.source").filter({ hasText: /ollama/i })).toBeVisible({ timeout: 5_000 });
  });

  // ── UAT-S11-05: API endpoints health check ──────────────────────────
  test("UAT-S11-05: all API endpoints still return 200", async ({ request }) => {
    const endpoints = [
      "/api/readiness/status",
      "/api/stt/status",
      "/api/tts/voices",
      "/api/commands/history",
      "/api/commands/last-undoable",
      "/api/personality",
      "/api/autonomy/promotion",
      "/api/recipes",
    ];

    for (const endpoint of endpoints) {
      const resp = await request.get(endpoint);
      expect(resp.ok(), `${endpoint} should return 200`).toBeTruthy();
    }
  });

  // ── UAT-S11-06: Full page screenshot ────────────────────────────────
  test("UAT-S11-06: full page screenshot for visual review", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status")).toHaveText(/live|connecting/, { timeout: 15_000 });
    await page.waitForTimeout(2000);

    await page.screenshot({
      path: "artifacts/ui/playwright/sprint11-uat-fullpage.png",
      fullPage: true,
    });
  });
});
