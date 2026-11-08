import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests",
  testMatch: "ai-assistant.spec.ts",
  workers: 1,
  timeout: 60000,
  use: {
    baseURL: "http://127.0.0.1:15174",
    browserName: "chromium",
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "python -m uvicorn app.main:app --host 127.0.0.1 --port 18002",
      cwd: "../backend",
      url: "http://127.0.0.1:18002/api/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120000,
      env: {
        CTF_DATA_DIR: "../.playwright-ai-data",
        CTF_MODEL_NETWORK_ENABLED: "false",
      },
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 15174",
      cwd: ".",
      url: "http://127.0.0.1:15174",
      reuseExistingServer: !process.env.CI,
      timeout: 120000,
    },
  ],
});
