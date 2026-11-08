import { test, expect } from "@playwright/test";

test("AI assistant stays safely disabled until server opt-in and per-request consent", async ({
  page,
  request,
}) => {
  const name = "Synthetic AI gate " + Date.now();
  const created = await request.post("http://127.0.0.1:8000/api/challenges", {
    data: {
      name,
      category: "Web",
      description: "Synthetic fixture only. No real target or credentials.",
      ai_usage_level: "A2",
    },
  });
  expect(created.status()).toBe(201);
  const challenge = await created.json();

  const status = await request.get("http://127.0.0.1:8000/api/model/status");
  expect(status.ok()).toBeTruthy();
  const modelStatus = await status.json();
  expect(modelStatus.network_enabled).toBe(false);
  expect(modelStatus.execution_enabled).toBe(false);

  const modelCalls: string[] = [];
  page.on("request", (r) => {
    if (/\\/api\\/challenges\\/[^/]+\\/ai\\/chat/.test(r.url())) {
      modelCalls.push(r.method() + " " + r.url());
    }
  });
  await page.goto("/");
  await page.getByRole("button", { name: new RegExp("Web.*" + name) }).click();
  await page.getByRole("button", { name: "AI 解题助手", exact: true }).click();
  await expect(page.getByRole("heading", { name: "AI 辅助解题 · DeepSeek" })).toBeVisible();
  await expect(page.getByText("服务器未开启模型联网")).toBeVisible();
  await page.getByLabel("向 AI 提问").fill("请分析这个合成题目。");
  await page.getByLabel(/我确认将本题描述/).check();
  await expect(
    page.getByRole("button", { name: "发送问题并获取分析" }),
  ).toBeDisabled();
  expect(modelCalls).toEqual([]);

  const rejected = await request.post(
    `http://127.0.0.1:8000/api/challenges/${challenge.challenge_id}/ai/chat`,
    {
      data: {
        question: "Synthetic gate test",
        confirm_external_processing: true,
      },
    },
  );
  expect(rejected.status()).toBe(503);
  expect(modelCalls).toEqual([]);
});
