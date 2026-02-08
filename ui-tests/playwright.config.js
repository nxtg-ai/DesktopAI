const { defineConfig } = require("@playwright/test");
const path = require("path");
const fs = require("fs");

const venvPython = path.resolve(__dirname, "../.venv/bin/python");
const backendPython =
  process.env.BACKEND_PYTHON || (fs.existsSync(venvPython) ? ".venv/bin/python" : "python3");
const baseURL = process.env.UI_TEST_BASE_URL || "http://127.0.0.1:8000";
const headless = process.env.PLAYWRIGHT_HEADLESS === "0" ? false : true;
const reuseServerOnly = process.env.UI_TEST_REUSE_SERVER === "1";
const runId = process.env.UI_TEST_RUN_ID || `${Date.now()}-${process.pid}`;

const webServerConfig = {
  command: `${backendPython} -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000`,
  cwd: path.resolve(__dirname, ".."),
  port: 8000,
  timeout: 120_000,
  reuseExistingServer: false,
  env: {
    BACKEND_DB_PATH: `artifacts/ui/playwright/desktopai-ui-test-${runId}.db`,
    CLASSIFIER_USE_OLLAMA: "0",
    AUTONOMY_PLANNER_MODE: "deterministic",
    UI_TELEMETRY_ARTIFACT_DIR: "artifacts/ui/telemetry",
  },
};

const config = {
  testDir: path.join(__dirname, "tests"),
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["html", { open: "never", outputFolder: path.resolve(__dirname, "../artifacts/ui/playwright/report") }]],
  outputDir: path.resolve(__dirname, "../artifacts/ui/playwright/test-results"),
  use: {
    baseURL,
    headless,
    trace: "on",
    screenshot: "on",
    video: "on",
  },
};

if (!reuseServerOnly) {
  config.webServer = webServerConfig;
}

module.exports = defineConfig(config);
