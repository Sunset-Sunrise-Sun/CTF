// Capture the independently launched P1 workbench.  The synthetic key is only
// sent to the isolated backend's DPAPI store; it is never printed or stored in
// browser storage.
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const frontend = process.env.P1_FRONTEND_URL || "http://127.0.0.1:15190/";
const backend = process.env.P1_BACKEND_URL || "http://127.0.0.1:18110";
const outDir = process.env.P1_SCREENSHOT_DIR || "run-screenshots";
const key = "synthetic-independent-run-key-1234567890";
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch(
  process.env.CTF_E2E_CHANNEL ? { channel: process.env.CTF_E2E_CHANNEL } : {},
);
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const result = { frontend, backend, key_visible: false, storage_contains_key: false };

try {
  await page.goto(frontend, { waitUntil: "networkidle" });
  const saved = await page.request.put(`${backend}/api/model/settings`, {
    data: { base_url: "https://api.deepseek.com", model_id: "deepseek-chat", api_key: key },
  });
  result.settings_status = saved.status();
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("button", { name: "模型服务设置" }).click();
  await page.getByRole("heading", { name: "模型服务设置" }).waitFor();
  await page.getByText("服务商与凭证", { exact: true }).waitFor();
  await page.getByText("已保存在本机（Windows DPAPI 加密）").waitFor();
  await page.screenshot({ path: join(outDir, "model-settings-1440px.png"), fullPage: true });
  result.key_visible = (await page.content()).includes(key);
  result.storage_contains_key = (
    await page.evaluate(() => JSON.stringify(window.localStorage))
  ).includes(key);

  await page.setViewportSize({ width: 390, height: 1000 });
  await page.screenshot({ path: join(outDir, "model-settings-390px.png"), fullPage: true });
  result.mobile_no_horizontal_overflow = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth + 1,
  );
  result.final_viewport = page.viewportSize();
} finally {
  // Do not leave the synthetic key in the isolated run's settings store.
  await page.request
    .put(`${backend}/api/model/settings`, {
      data: { clear_api_key: true },
    })
    .catch(() => {});
  writeFileSync(join(outDir, "run-screenshots.json"), JSON.stringify(result, null, 2));
  await browser.close();
}
