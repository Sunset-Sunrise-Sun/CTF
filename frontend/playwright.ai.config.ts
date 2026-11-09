import { defineConfig } from "@playwright/test";
import { mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Never reuse acceptance storage, including when a process ID is recycled.
const isolatedRoot = mkdtempSync(join(tmpdir(), "ctf-ai-e2e-"));
const isolatedTmp = join(isolatedRoot, "tmp");
mkdirSync(isolatedTmp);
console.log(`AI E2E isolated root: ${isolatedRoot}`);

// The isolated AI acceptance run uses the bundled Chromium by default. On a
// developer machine without the bundled download (offline), set
// CTF_E2E_CHANNEL=msedge to run the same suite against the installed browser.
const browserChannel = process.env.CTF_E2E_CHANNEL;

export default defineConfig({
  testDir: "tests",
  testMatch: ["ai-assistant.spec.ts", "model-settings.spec.ts"],
  workers: 1,
  timeout: 60000,
  use: {
    baseURL: "http://127.0.0.1:15174",
    ...(browserChannel ? { channel: browserChannel } : { browserName: "chromium" as const }),
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "python -m uvicorn app.main:app --host 127.0.0.1 --port 18002",
      cwd: "../backend",
      url: "http://127.0.0.1:18002/api/health",
      reuseExistingServer: false,
      timeout: 120000,
      env: {
        CTF_DATA_DIR: join(isolatedRoot, "data"),
        CTF_MODEL_NETWORK_ENABLED: "false",
        CTF_RUN_LIVE_MODEL: "0",
        TEMP: isolatedTmp,
        TMP: isolatedTmp,
        TMPDIR: isolatedTmp,
      },
    },
    {
      command: "npm run dev -- --config vite.ai.config.ts --host 127.0.0.1 --port 15174 --strictPort",
      cwd: ".",
      url: "http://127.0.0.1:15174",
      reuseExistingServer: false,
      timeout: 120000,
    },
  ],
});
