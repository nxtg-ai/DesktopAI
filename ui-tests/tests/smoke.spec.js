const { test, expect } = require("@playwright/test");
const fs = require("fs");
const path = require("path");

test("desktop ui smoke journey emits telemetry", async ({ page, request }) => {
  await request.post("/api/ui-telemetry/reset?clear_artifacts=true");

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Live Desktop Context" })).toBeVisible();
  await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });

  await page.fill("#autonomy-objective", "Observe desktop and verify outcome");
  await page.click("#autonomy-start-btn");
  await expect(page.locator("#autonomy-status")).toHaveText(/running|completed|waiting_approval/, {
    timeout: 15_000,
  });

  // Give the buffered telemetry writer time to flush a batch.
  await page.waitForTimeout(5000);
  const sessionId = await page.evaluate(() => window.__desktopaiTelemetrySessionId);
  expect(sessionId).toBeTruthy();
  await page.context().close();

  const resp = await request.get(`/api/ui-telemetry?session_id=${encodeURIComponent(sessionId)}&limit=200`);
  expect(resp.ok()).toBeTruthy();
  const payload = await resp.json();
  const kinds = payload.events.map((event) => event.kind);
  expect(kinds).toContain("ui_boot");
  expect(kinds).toContain("ws_open");
  expect(kinds).toContain("autonomy_start_requested");
});

test("live event ingestion updates UI and emits stream telemetry", async ({ page, request }) => {
  await request.post("/api/ui-telemetry/reset?clear_artifacts=true");

  await page.goto("/");
  await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });

  const title = `Playwright Event ${Date.now()}`;
  const eventResp = await request.post("/api/events", {
    data: {
      type: "foreground",
      hwnd: "0xFEED",
      title,
      process_exe: "Code.exe",
      pid: 42424,
      timestamp: new Date().toISOString(),
      source: "playwright",
    },
  });
  expect(eventResp.ok()).toBeTruthy();

  await expect(page.locator("#current-title")).toHaveText(title, { timeout: 15_000 });
  await expect(page.locator("#events .event-item").first()).toBeVisible({ timeout: 15_000 });

  await page.waitForTimeout(5000);
  const sessionId = await page.evaluate(() => window.__desktopaiTelemetrySessionId);
  expect(sessionId).toBeTruthy();
  await page.context().close();

  const telemetryResp = await request.get(
    `/api/ui-telemetry?session_id=${encodeURIComponent(sessionId)}&limit=200`
  );
  expect(telemetryResp.ok()).toBeTruthy();
  const payload = await telemetryResp.json();
  const kinds = payload.events.map((event) => event.kind);
  expect(kinds).toContain("event_stream_received");
});

test("autonomy approval journey is reflected in UI and telemetry", async ({ page, request }) => {
  await request.post("/api/ui-telemetry/reset?clear_artifacts=true");

  await page.goto("/");
  await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });

  await page.fill("#autonomy-objective", "Open outlook, draft reply, then send email");
  await page.uncheck("#autonomy-auto-approve");
  await page.click("#autonomy-start-btn");

  await expect(page.locator("#autonomy-status")).toHaveText("waiting_approval", { timeout: 15_000 });
  await expect(page.locator("#autonomy-approve-btn")).toBeEnabled({ timeout: 15_000 });

  await page.click("#autonomy-approve-btn");
  await expect(page.locator("#autonomy-status")).toHaveText("completed", { timeout: 15_000 });

  await page.waitForTimeout(5000);
  const sessionId = await page.evaluate(() => window.__desktopaiTelemetrySessionId);
  expect(sessionId).toBeTruthy();
  await page.context().close();

  const telemetryResp = await request.get(
    `/api/ui-telemetry?session_id=${encodeURIComponent(sessionId)}&limit=300`
  );
  expect(telemetryResp.ok()).toBeTruthy();
  const payload = await telemetryResp.json();
  const kinds = payload.events.map((event) => event.kind);
  expect(kinds).toContain("autonomy_waiting_approval");
  expect(kinds).toContain("autonomy_approve_requested");
  expect(kinds).toContain("autonomy_approved");
});

test("autonomy cancel journey is reflected in UI and telemetry", async ({ page, request }) => {
  await request.post("/api/ui-telemetry/reset?clear_artifacts=true");

  await page.goto("/");
  await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });

  await page.fill("#autonomy-objective", "Open outlook, draft reply, then send email");
  await page.uncheck("#autonomy-auto-approve");
  await page.click("#autonomy-start-btn");

  await expect(page.locator("#autonomy-status")).toHaveText("waiting_approval", { timeout: 15_000 });
  await expect(page.locator("#autonomy-cancel-btn")).toBeEnabled({ timeout: 15_000 });
  await page.click("#autonomy-cancel-btn");
  await expect(page.locator("#autonomy-status")).toHaveText("cancelled", { timeout: 15_000 });

  await page.waitForTimeout(5000);
  const sessionId = await page.evaluate(() => window.__desktopaiTelemetrySessionId);
  expect(sessionId).toBeTruthy();
  await page.context().close();

  const telemetryResp = await request.get(
    `/api/ui-telemetry?session_id=${encodeURIComponent(sessionId)}&limit=300`
  );
  expect(telemetryResp.ok()).toBeTruthy();
  const payload = await telemetryResp.json();
  const kinds = payload.events.map((event) => event.kind);
  expect(kinds).toContain("autonomy_waiting_approval");
  expect(kinds).toContain("autonomy_cancel_requested");
  expect(kinds).toContain("autonomy_cancelled");
});

test("telemetry gate journey emits required kinds", async ({ page, request }) => {
  await request.post("/api/ui-telemetry/reset?clear_artifacts=true");

  await page.goto("/");
  await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });

  const title = `Gate Event ${Date.now()}`;
  const eventResp = await request.post("/api/events", {
    data: {
      type: "foreground",
      hwnd: "0xBEEF",
      title,
      process_exe: "Code.exe",
      pid: 53535,
      timestamp: new Date().toISOString(),
      source: "playwright-gate",
    },
  });
  expect(eventResp.ok()).toBeTruthy();
  await expect(page.locator("#current-title")).toHaveText(title, { timeout: 15_000 });

  await page.fill("#autonomy-objective", "Open outlook, draft reply, then send email");
  await page.uncheck("#autonomy-auto-approve");
  await page.click("#autonomy-start-btn");

  await expect(page.locator("#autonomy-status")).toHaveText("waiting_approval", { timeout: 15_000 });
  await page.click("#autonomy-approve-btn");
  await expect(page.locator("#autonomy-status")).toHaveText("completed", { timeout: 15_000 });

  await page.waitForTimeout(5000);
  const sessionId = await page.evaluate(() => window.__desktopaiTelemetrySessionId);
  expect(sessionId).toBeTruthy();
  const sessionFile = path.resolve(__dirname, "../../artifacts/ui/telemetry/latest-gate-session.txt");
  fs.mkdirSync(path.dirname(sessionFile), { recursive: true });
  fs.writeFileSync(sessionFile, `${sessionId}\n`, "utf-8");
  await page.context().close();

  const telemetryResp = await request.get(
    `/api/ui-telemetry?session_id=${encodeURIComponent(sessionId)}&limit=400`
  );
  expect(telemetryResp.ok()).toBeTruthy();
  const payload = await telemetryResp.json();
  const kinds = payload.events.map((event) => event.kind);
  expect(kinds).toContain("ui_boot");
  expect(kinds).toContain("ws_open");
  expect(kinds).toContain("event_stream_received");
  expect(kinds).toContain("autonomy_waiting_approval");
  expect(kinds).toContain("autonomy_approved");
});

test("journey console shows telemetry session events", async ({ page, request }) => {
  await request.post("/api/ui-telemetry/reset?clear_artifacts=true");

  await page.goto("/");
  await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });

  await page.fill("#autonomy-objective", "Observe desktop and verify outcome");
  await page.click("#autonomy-start-btn");
  await expect(page.locator("#autonomy-status")).toHaveText(/running|completed|waiting_approval/, {
    timeout: 15_000,
  });

  const sessionId = await page.evaluate(() => window.__desktopaiTelemetrySessionId);
  expect(sessionId).toBeTruthy();

  await expect(page.locator("#journey-session")).toBeVisible({ timeout: 15_000 });
  await page.selectOption("#journey-session", sessionId);
  await page.click("#journey-refresh-btn");

  await expect(page.locator("#journey-events .event-item").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("#journey-events")).toContainText("autonomy_start_requested", {
    timeout: 15_000,
  });
});

test("runtime logs panel shows backend log entries", async ({ page, request }) => {
  await page.goto("/");
  await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });

  const title = `Runtime Log Event ${Date.now()}`;
  const eventResp = await request.post("/api/events", {
    data: {
      type: "foreground",
      hwnd: "0xD00D",
      title,
      process_exe: "Code.exe",
      pid: 61616,
      timestamp: new Date().toISOString(),
      source: "playwright-runtime-log",
    },
  });
  expect(eventResp.ok()).toBeTruthy();

  await page.click("#runtime-logs-refresh-btn");
  await expect(page.locator("#runtime-log-count")).not.toHaveText("0", { timeout: 15_000 });
  await expect(page.locator("#runtime-logs")).toContainText("event_received", { timeout: 15_000 });
});

test("runtime logs panel supports filter and clear actions", async ({ page, request }) => {
  await page.goto("/");
  await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });

  const title = `Runtime Filter Event ${Date.now()}`;
  const eventResp = await request.post("/api/events", {
    data: {
      type: "foreground",
      hwnd: "0xD00E",
      title,
      process_exe: "Code.exe",
      pid: 61617,
      timestamp: new Date().toISOString(),
      source: "playwright-runtime-filter",
    },
  });
  expect(eventResp.ok()).toBeTruthy();

  await page.fill("#runtime-logs-search", "event_received");
  await page.selectOption("#runtime-logs-level", "INFO");
  await page.click("#runtime-logs-refresh-btn");
  await expect(page.locator("#runtime-logs")).toContainText("event_received", { timeout: 15_000 });

  await page.click("#runtime-logs-clear-btn");
  await expect(page.locator("#runtime-log-count")).toHaveText("0", { timeout: 15_000 });
});

test("runtime logs can correlate to active telemetry session", async ({ page, request }) => {
  await request.post("/api/ui-telemetry/reset?clear_artifacts=true");

  await page.goto("/");
  await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });

  const title = `Runtime Correlate Event ${Date.now()}`;
  const eventResp = await request.post("/api/events", {
    data: {
      type: "foreground",
      hwnd: "0xD00F",
      title,
      process_exe: "Code.exe",
      pid: 61618,
      timestamp: new Date().toISOString(),
      source: "playwright-runtime-correlate",
    },
  });
  expect(eventResp.ok()).toBeTruthy();

  await page.click("#journey-refresh-btn");
  await page.click("#runtime-logs-correlate-btn");
  await expect(page.locator("#runtime-logs-meta")).toContainText("session", { timeout: 15_000 });
  await expect(page.locator("#runtime-logs")).toContainText("event_received", { timeout: 15_000 });
});

test("runtime log correlated view stays pinned across polling", async ({ page, request }) => {
  await request.post("/api/ui-telemetry/reset?clear_artifacts=true");

  await page.goto("/");
  await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });

  const title = `Runtime Correlate Sticky ${Date.now()}`;
  const eventResp = await request.post("/api/events", {
    data: {
      type: "foreground",
      hwnd: "0xD010",
      title,
      process_exe: "Code.exe",
      pid: 61619,
      timestamp: new Date().toISOString(),
      source: "playwright-runtime-correlate-sticky",
    },
  });
  expect(eventResp.ok()).toBeTruthy();

  await page.click("#journey-refresh-btn");
  await page.click("#runtime-logs-correlate-btn");
  await expect(page.locator("#runtime-logs-meta")).toContainText("session", { timeout: 15_000 });

  // Polling runs every 5s; correlated view should remain pinned.
  await page.waitForTimeout(6500);
  await expect(page.locator("#runtime-logs-meta")).toContainText("session", { timeout: 5_000 });
});

test("readiness status panel refreshes in UI", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });

  await page.click("#readiness-status-refresh-btn");
  await expect(page.locator("#readiness-status-result")).toContainText(
    /Readiness: (ready|check warnings) \| required \d+\/\d+ \| warnings \d+/,
    {
      timeout: 15_000,
    }
  );
  await expect(page.locator("#readiness-status-checks .event-item").first()).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.locator("#readiness-status-checks")).toContainText("ollama_available", {
    timeout: 15_000,
  });
});

test("planner mode can be updated from UI", async ({ page, request }) => {
  const originalResp = await request.get("/api/autonomy/planner");
  expect(originalResp.ok()).toBeTruthy();
  const original = await originalResp.json();
  const originalMode = original.mode || "deterministic";

  await request.post("/api/autonomy/planner", { data: { mode: "deterministic" } });
  try {
    await page.goto("/");
    await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });
    await expect(page.locator("#planner-mode-select")).toHaveValue("deterministic", {
      timeout: 15_000,
    });

    await page.selectOption("#planner-mode-select", "auto");
    await page.click("#planner-mode-apply-btn");
    await expect(page.locator("#planner-mode-meta")).toContainText("Planner mode: auto", {
      timeout: 15_000,
    });
    await expect(page.locator("#planner-mode-meta")).toContainText("source runtime_override", {
      timeout: 15_000,
    });

    await page.click("#planner-mode-reset-btn");
    await expect(page.locator("#planner-mode-meta")).toContainText("source config_default", {
      timeout: 15_000,
    });

    const afterResp = await request.get("/api/autonomy/planner");
    expect(afterResp.ok()).toBeTruthy();
    const after = await afterResp.json();
    expect(after.source).toBe("config_default");
    expect(after.mode).toBe(after.configured_default_mode);
  } finally {
    await request.post("/api/autonomy/planner", { data: { mode: originalMode } });
  }
});

test("ollama model override can be updated from UI", async ({ page, request }) => {
  const modelsResp = await request.get("/api/ollama/models");
  expect(modelsResp.ok()).toBeTruthy();
  const modelsPayload = await modelsResp.json();
  const models = Array.isArray(modelsPayload.models) ? modelsPayload.models : [];
  test.skip(models.length === 0, "No installed Ollama models available for override test.");

  const targetModel = models[0];

  // Start from configured default to avoid cross-test contamination.
  await request.delete("/api/ollama/model");
  try {
    await page.goto("/");
    await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });
    await expect(page.locator("#ollama-model-select")).toBeVisible({ timeout: 15_000 });

    await expect
      .poll(async () => {
        return await page.locator("#ollama-model-select option").count();
      })
      .toBeGreaterThan(0);

    await page.selectOption("#ollama-model-select", targetModel);
    await page.click("#ollama-model-apply-btn");

    await expect(page.locator("#ollama-model-meta")).toContainText(`Ollama model: ${targetModel}`, {
      timeout: 15_000,
    });
    await expect(page.locator("#ollama-model-meta")).toContainText("source runtime_override", {
      timeout: 15_000,
    });

    const statusResp = await request.get("/api/ollama");
    expect(statusResp.ok()).toBeTruthy();
    const statusPayload = await statusResp.json();
    expect(statusPayload.active_model).toBe(targetModel);
    expect(statusPayload.ollama_model_source).toBe("runtime_override");

    await page.click("#ollama-model-reset-btn");
    await expect(page.locator("#ollama-model-meta")).toContainText("source config_default", {
      timeout: 15_000,
    });

    const resetStatusResp = await request.get("/api/ollama");
    expect(resetStatusResp.ok()).toBeTruthy();
    const resetStatus = await resetStatusResp.json();
    expect(resetStatus.ollama_model_source).toBe("config_default");
    expect(resetStatus.active_model).toBe(resetStatus.configured_model);
  } finally {
    await request.delete("/api/ollama/model");
  }
});

test("ollama probe can be executed from UI", async ({ page, request }) => {
  await page.goto("/");
  await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });
  await expect(page.locator("#ollama-probe-btn")).toBeVisible({ timeout: 15_000 });

  await page.click("#ollama-probe-btn");
  await expect(page.locator("#ollama-probe-result")).toContainText(/Probe: (ok|failed|error)/, {
    timeout: 20_000,
  });

  await page.waitForTimeout(5000);
  const sessionId = await page.evaluate(() => window.__desktopaiTelemetrySessionId);
  expect(sessionId).toBeTruthy();
  await page.context().close();

  const encoded = encodeURIComponent(sessionId);
  const telemetryResp = await request.get(`/api/ui-telemetry?session_id=${encoded}&limit=400`);
  expect(telemetryResp.ok()).toBeTruthy();
  const payload = await telemetryResp.json();
  const kinds = payload.events.map((event) => event.kind);
  expect(kinds).toContain("ollama_probe_requested");
  expect(kinds.some((kind) => kind === "ollama_probe_completed" || kind === "ollama_probe_failed")).toBeTruthy();
});

test("runtime readiness preflight panel updates in UI", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });

  await expect(page.locator("#executor-status")).toContainText("Executor:", { timeout: 15_000 });
  await page.click("#executor-preflight-btn");
  await expect(page.locator("#executor-preflight-result")).toContainText(/Preflight: (passed|failed|error)/, {
    timeout: 15_000,
  });
  await expect(page.locator("#executor-preflight-checks .event-item").first()).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.locator("#executor-preflight-checks")).toContainText("ok", {
    timeout: 15_000,
  });
});

test("readiness gate can be executed from UI", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });

  await page.fill("#autonomy-objective", "Open outlook, draft reply, then send email");
  await page.check("#autonomy-auto-approve");
  await page.click("#readiness-gate-btn");

  await expect(page.locator("#readiness-gate-result")).toContainText("completed", {
    timeout: 15_000,
  });
});

test("readiness matrix can be executed from UI", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#status")).toHaveText("live", { timeout: 15_000 });

  await page.fill(
    "#readiness-matrix-objectives",
    "Observe desktop and verify outcome\nOpen outlook, draft reply, then send email"
  );
  await page.check("#autonomy-auto-approve");
  await page.click("#readiness-matrix-btn");

  await expect(page.locator("#readiness-matrix-result")).toContainText("2/2 passed", {
    timeout: 20_000,
  });
  await expect(page.locator("#readiness-matrix-results .event-item").first()).toBeVisible({
    timeout: 20_000,
  });
});
