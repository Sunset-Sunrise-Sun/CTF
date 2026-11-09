import { expect, test } from "@playwright/test";

const KEY = "synthetic-e2e-deepseek-key-1234567890";

async function openSettings(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "模型服务设置" }).click();
  await expect(
    page.getByRole("heading", { name: "模型服务设置" }),
  ).toBeVisible();
}

function field(page: import("@playwright/test").Page, label: string) {
  return page
    .locator("label")
    .filter({ hasText: label })
    .locator("input")
    .first();
}

function effectiveNetwork(page: import("@playwright/test").Page) {
  return page
    .locator("p.key-state")
    .filter({ hasText: "当前有效状态：" })
    .first();
}

test("model service settings save, mask, show/hide, network switch and reload", async ({
  page,
}) => {
  // Test-connection is the only mocked call in this test: no real network.
  await page.route("**/api/model/test", async (route) => {
    await route.fulfill({
      status: 200,
      json: {
        success: true,
        provider: "deepseek",
        model_id: "deepseek-flash",
        call_id: "synthetic-e2e-call-id",
        sent_synthetic_content_only: true,
      },
    });
  });
  await openSettings(page);
  await expect(page.getByText("未配置 API Key")).toBeVisible();
  await expect(page.getByText("默认关闭", { exact: false })).toBeVisible();
  await expect(field(page, "模型")).toHaveValue("DeepSeek-V4.1-Flash");
  await expect(
    page.getByText(
      "API Key 将发送至当前填写的 API 地址，请确认该地址属于你信任的服务商。",
      { exact: true },
    ),
  ).toBeVisible();

  const keyInput = field(page, "API Key");
  await keyInput.fill(KEY);
  await expect(keyInput).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "显示", exact: true }).click();
  await expect(keyInput).toHaveAttribute("type", "text");
  await page.getByRole("button", { name: "隐藏", exact: true }).click();
  await expect(keyInput).toHaveAttribute("type", "password");

  await field(page, "API 地址").fill("https://api.deepseek.com");
  await field(page, "模型").fill("deepseek-chat");
  await page.getByRole("button", { name: "保存配置", exact: true }).click();
  await expect(
    page.getByText("已保存在本机（Windows DPAPI 加密）"),
  ).toBeVisible();
  await expect(keyInput).toHaveValue("");
  expect(await page.content()).not.toContain(KEY);
  const storage = await page.evaluate(() => JSON.stringify(window.localStorage));
  expect(storage).not.toContain(KEY);
  // Saving the key must not enable networking.
  await expect(effectiveNetwork(page)).toContainText("已关闭");
  await expect(
    page.getByRole("button", { name: "测试连接", exact: true }),
  ).toBeDisabled();

  await page.getByLabel("允许联网调用模型").check();
  await page.getByRole("button", { name: "保存联网开关", exact: true }).click();
  await expect(effectiveNetwork(page)).toContainText("已开启");
  await page.getByRole("button", { name: "测试连接", exact: true }).click();
  await expect(page.getByText("连接成功：仅发送固定合成提示")).toBeVisible();

  // Reload: non-secret status is recovered from disk; key remains masked.
  await page.reload();
  await page.getByRole("button", { name: "模型服务设置" }).click();
  await expect(
    page.getByText("已保存在本机（Windows DPAPI 加密）"),
  ).toBeVisible();
  await expect(field(page, "API Key")).toHaveValue("");
  await expect(field(page, "模型")).toHaveValue("deepseek-chat");
  expect(await page.content()).not.toContain(KEY);

  // Screenshot the configured state before cleaning the shared E2E backend.
  await page.setViewportSize({ width: 390, height: 1000 });
  await page.screenshot({
    path: "test-results/model-settings-390px.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
  ).toBe(true);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: "test-results/model-settings-1440px.png",
    fullPage: true,
  });

  // Leave the shared E2E backend in a safe state for other specs.
  await page.getByLabel("允许联网调用模型").uncheck();
  await page.getByRole("button", { name: "保存联网开关", exact: true }).click();
  await page.getByRole("button", { name: "清除已保存 Key", exact: true }).click();
  await expect(page.getByText("未配置 API Key")).toBeVisible();
});

test("environment key on a custom address needs explicit UI authorization", async ({ page }) => {
  let putBody: Record<string, unknown> | null = null;
  const envStatus = {
    provider: "deepseek",
    base_url: "https://trusted.example",
    default_base_url: "https://api.deepseek.com",
    model_id: "deepseek-chat",
    default_model_id: "deepseek-flash",
    key_configured: true,
    key_source: "environment",
    key_storage_available: true,
    key_error: null,
    config_error: null,
    network_enabled: true,
    network_setting: true,
    network_env_override: false,
    env_key_custom_base_url_authorized: false,
    env_key_custom_base_url_authorization_required: true,
  };
  await page.route("**/api/model/settings", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, json: envStatus });
      return;
    }
    putBody = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({
      status: 200,
      json: { ...envStatus, env_key_custom_base_url_authorized: true, env_key_custom_base_url_authorization_required: false },
    });
  });
  await openSettings(page);
  await expect(
    page.getByText("尚未授权环境变量 API Key 发送到当前自定义 API 地址", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("环境变量 API Key 用于自定义地址需要先明确授权"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "测试连接", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("checkbox", { name: /我授权在此 API 地址使用服务器环境变量/ }),
  ).toBeVisible();
  await page
    .getByRole("checkbox", { name: /我授权在此 API 地址使用服务器环境变量/ })
    .check();
  await page.getByRole("button", { name: "保存配置", exact: true }).click();
  await expect.poll(() => putBody?.authorize_env_key_custom_base_url).toBe(true);
});

test("corrupt config disables connection testing in the UI", async ({ page }) => {
  await page.route("**/api/model/settings", async (route) => {
    await route.fulfill({
      status: 200,
      json: {
        provider: "deepseek",
        base_url: "https://api.deepseek.com",
        default_base_url: "https://api.deepseek.com",
        model_id: "deepseek-flash",
        default_model_id: "deepseek-flash",
        key_configured: false,
        key_source: null,
        key_storage_available: true,
        key_error: null,
        config_error: "invalid_config",
        network_enabled: true,
        network_setting: true,
        network_env_override: false,
        env_key_custom_base_url_authorized: false,
        env_key_custom_base_url_authorization_required: false,
      },
    });
  });
  await openSettings(page);
  await expect(page.getByText("配置文件无法读取", { exact: false })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "测试连接", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByText("配置损坏：请重新保存有效配置"),
  ).toBeVisible();
});

test("connection failure is reported without exposing the key", async ({ page }) => {
  await page.route("**/api/model/settings", async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      json: {
        provider: "deepseek",
        base_url: "https://api.deepseek.com",
        default_base_url: "https://api.deepseek.com",
        model_id: "deepseek-flash",
        default_model_id: "deepseek-flash",
        key_configured: true,
        key_source: "settings",
        key_storage_available: true,
        key_error: null,
        config_error: null,
        network_enabled: true,
        network_setting: true,
        network_env_override: false,
      },
    });
  });
  await page.route("**/api/model/test", async (route) => {
    await route.fulfill({
      status: 503,
      json: { detail: { code: "missing_credentials" } },
    });
  });
  await openSettings(page);
  await page.getByRole("button", { name: "测试连接", exact: true }).click();
  await expect(page.getByText("连接测试失败：", { exact: false })).toBeVisible();
  expect(await page.content()).not.toContain(KEY);
});
