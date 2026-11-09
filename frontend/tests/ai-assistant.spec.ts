import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

test("A2 attachment selection needs its own fresh confirmation", async ({ page, request }) => {
  const created = await request.post("http://127.0.0.1:18002/api/challenges", {
    data: { name: "Synthetic attachment opt-in " + Date.now(), category: "Misc", ai_usage_level: "A2" },
  });
  expect(created.status()).toBe(201);
  const challenge = await created.json();
  const artifacts = [];
  for (const name of ["first-fixture.txt", "second-fixture.txt"]) {
    const upload = await request.post(`http://127.0.0.1:18002/api/challenges/${challenge.challenge_id}/artifacts`, {
      multipart: { file: { name, mimeType: "text/plain", buffer: Buffer.from(name) } },
    });
    expect(upload.status()).toBe(201);
    artifacts.push(await upload.json());
  }
  await page.route("**/api/model/status", route => route.fulfill({ json: {
    network_enabled: true, credentials_configured: true, provider: "deepseek", model_id: "synthetic",
  } }));
  const sent: unknown[] = [];
  await page.route("**/api/challenges/*/ai/chat", async route => {
    sent.push(route.request().postDataJSON());
    await route.fulfill({ status: 201, json: { answer: "Synthetic UI fixture" } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: new RegExp(challenge.name) }).click();
  await page.getByRole("button", { name: "AI 解题助手", exact: true }).click();
  await page.getByText("本轮附件范围（可选，最多 12 个）", { exact: true }).click();
  await page.getByLabel("向 AI 提问").fill("Synthetic attachment question");
  const first = page.getByRole("checkbox", { name: "first-fixture.txt", exact: true });
  const second = page.getByRole("checkbox", { name: "second-fixture.txt", exact: true });
  const baseConsent = page.getByLabel(/我确认将本题描述/);
  const fileConsent = page.getByLabel(/我确认外发本轮明确选中/);
  const send = page.getByRole("button", { name: "发送问题并获取分析" });
  await first.check();
  await baseConsent.check();
  await expect(send).toBeDisabled();
  await fileConsent.check();
  await expect(send).toBeEnabled();
  await second.check();
  await expect(baseConsent).not.toBeChecked();
  await expect(fileConsent).not.toBeChecked();
  await second.uncheck();
  await fileConsent.check();
  await baseConsent.check();
  await send.click();
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0]).toMatchObject({
    consent_challenge_id: challenge.challenge_id, confirm_attachments: true,
    selected_files: [], selected_artifacts: [{ artifact_id: artifacts[0].artifact_id, sha256: artifacts[0].sha256 }],
  });
});

test("isolated real API rejects cross-challenge consent and panel fits desktop/mobile", async ({
  page,
  request,
}, testInfo) => {
  const response = await request.post("http://127.0.0.1:18002/api/challenges", {
    data: {
      name: `Synthetic layout and consent ${Date.now()}`,
      category: "Misc",
      ai_usage_level: "A2",
    },
  });
  expect(response.status()).toBe(201);
  const challenge = await response.json();
  const mismatch = await request.post(
    `http://127.0.0.1:18002/api/challenges/${challenge.challenge_id}/ai/chat`,
    {
      data: {
        question: "Synthetic local rejection only",
        confirm_external_processing: true,
        consent_challenge_id: "a-different-challenge",
      },
    },
  );
  expect(mismatch.status()).toBe(409);
  const events = await request.get(
    `http://127.0.0.1:18002/api/challenges/${challenge.challenge_id}/events`,
  );
  expect(await events.json()).toEqual([]);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/");
    await page.getByRole("button", { name: new RegExp(challenge.name) }).click();
    await page.getByRole("button", { name: "AI 解题助手", exact: true }).click();
    await expect(page.getByRole("heading", { name: "AI 辅助解题 · DeepSeek" })).toBeVisible();
    await expect(page.getByRole("button", { name: "发送问题并获取分析" })).toBeDisabled();
    const evidenceDir = process.env.CTF_EVIDENCE_DIR ?? testInfo.outputDir;
    mkdirSync(evidenceDir, { recursive: true });
    const screenshot = join(evidenceDir, `synthetic-ai-panel-${width}px.png`);
    await page.screenshot({ path: screenshot, fullPage: true });
    await testInfo.attach(`synthetic-ai-panel-${width}px`, { path: screenshot });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  }
});

test("AI assistant stays safely disabled until server opt-in and per-request consent", async ({
  page,
  request,
}) => {
  const name = "Synthetic AI gate " + Date.now();
  const created = await request.post("http://127.0.0.1:18002/api/challenges", {
    data: {
      name,
      category: "Web",
      description: "Synthetic fixture only. No real target or credentials.",
      ai_usage_level: "A2",
    },
  });
  expect(created.status()).toBe(201);
  const challenge = await created.json();

  const status = await request.get("http://127.0.0.1:18002/api/model/status");
  expect(status.ok()).toBeTruthy();
  const modelStatus = await status.json();
  expect(modelStatus.network_enabled).toBe(false);
  expect(modelStatus.execution_enabled).toBe(false);

  const modelCalls: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/challenges/") && r.url().includes("/ai/chat")) {
      modelCalls.push(r.method() + " " + r.url());
    }
  });
  await page.goto("/");
  await page.getByRole("button", { name: new RegExp("Web.*" + name) }).click();
  await page.getByRole("button", { name: "AI 解题助手", exact: true }).click();
  await expect(page.getByRole("heading", { name: "AI 辅助解题 · DeepSeek" })).toBeVisible();
  await expect(page.getByText("服务器未开启模型联网")).toBeVisible();
  await expect(
    page.getByRole("button", { name: /测试 API 连接/ }),
  ).toBeDisabled();
  await page.getByLabel("向 AI 提问").fill("请分析这个合成题目。");
  await page.getByLabel(/我确认将本题描述/).check();
  await expect(
    page.getByRole("button", { name: "发送问题并获取分析" }),
  ).toBeDisabled();
  expect(modelCalls).toEqual([]);

  const rejected = await request.post(
    `http://127.0.0.1:18002/api/challenges/${challenge.challenge_id}/ai/chat`,
    {
      data: {
        question: "Synthetic gate test",
        confirm_external_processing: true,
        consent_challenge_id: challenge.challenge_id,
      },
    },
  );
  expect(rejected.status()).toBe(503);
  expect(modelCalls).toEqual([]);
});

test("AI consent is challenge-bound, cleared on switch, and re-checked at request time", async ({
  page,
  request,
}) => {
  const stamp = Date.now();
  const create = async (label: string) => {
    const response = await request.post("http://127.0.0.1:18002/api/challenges", {
      data: {
        name: `Synthetic consent ${label} ${stamp}`,
        category: "Misc",
        description: "Synthetic fixture only. No real target or credentials.",
        ai_usage_level: "A2",
      },
    });
    expect(response.status()).toBe(201);
    return response.json();
  };
  const challengeA = await create("A");
  const challengeB = await create("B");
  const calls: { path: string; body: Record<string, unknown> }[] = [];

  await page.route("**/api/model/status", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        network_enabled: true,
        provider: "deepseek",
        model_id: "deepseek-flash",
        credentials_configured: true,
        execution_enabled: false,
      }),
    });
  });
  await page.route("**/api/challenges/*/ai/chat", async (route) => {
    calls.push({
      path: new URL(route.request().url()).pathname,
      body: route.request().postDataJSON(),
    });
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        event_id: `synthetic-ai-event-${calls.length}`,
        answer: "Synthetic unverified suggestion.",
        provider_id: "deepseek",
        model_id: "deepseek-flash",
        included_files: [],
        verification_status: "unverified_suggestion",
      }),
    });
  });

  await page.goto("/");
  const challengeButton = (name: string) =>
    page.getByRole("button", { name: new RegExp(name) });
  const openAIPanel = () =>
    page.getByRole("button", { name: "AI 解题助手", exact: true }).click();
  const question = page.getByLabel("向 AI 提问");
  const consent = page.getByLabel(/我确认将本题描述/);
  const send = page.getByRole("button", { name: "发送问题并获取分析" });
  const nameA = `Synthetic consent A ${stamp}`;
  const nameB = `Synthetic consent B ${stamp}`;

  await challengeButton(nameA).click();
  await openAIPanel();
  await expect(
    page.getByText("已配置联网开关与凭证（实际连通性以请求结果为准）"),
  ).toBeVisible();
  await question.fill("A-only pending question");
  await consent.check();
  await expect(send).toBeEnabled();

  // Switching to B must clear both consent and the pending question.
  await challengeButton(nameB).click();
  await openAIPanel();
  await expect(consent).not.toBeChecked();
  await expect(question).toHaveValue("");
  await expect(send).toBeDisabled();
  expect(calls).toEqual([]);

  // A -> B -> A must not restore the old consent.
  await challengeButton(nameA).click();
  await openAIPanel();
  await expect(consent).not.toBeChecked();
  await expect(question).toHaveValue("");
  await expect(send).toBeDisabled();
  expect(calls).toEqual([]);

  // Reloading the page must not restore consent or a question for A.
  await question.fill("A question before reload");
  await consent.check();
  await expect(send).toBeEnabled();
  await page.reload();
  await openAIPanel();
  await expect(consent).not.toBeChecked();
  await expect(question).toHaveValue("");
  await expect(send).toBeDisabled();
  expect(calls).toEqual([]);

  // B must be confirmed again before its request can be sent.
  await challengeButton(nameB).click();
  await openAIPanel();
  await expect(send).toBeDisabled();
  await question.fill("B question after explicit consent");
  await consent.check();
  await expect(send).toBeEnabled();
  await send.click();
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0].path).toBe(`/api/challenges/${challengeB.challenge_id}/ai/chat`);
  expect(calls[0].body).toMatchObject({
    question: "B question after explicit consent",
    confirm_external_processing: true,
    consent_challenge_id: challengeB.challenge_id,
  });
  await expect(consent).not.toBeChecked();
});

test("per-challenge AI history still restores after switching challenges", async ({
  page,
  request,
}) => {
  const stamp = Date.now();
  const create = async (label: string) => {
    const response = await request.post("http://127.0.0.1:18002/api/challenges", {
      data: {
        name: `Synthetic history ${label} ${stamp}`,
        category: "Misc",
        description: "Synthetic fixture only. No real target or credentials.",
        ai_usage_level: "A2",
      },
    });
    expect(response.status()).toBe(201);
    return response.json();
  };
  const challengeA = await create("A");
  const challengeB = await create("B");
  const eventForA = {
    event_id: "synthetic-history-event-a",
    challenge_id: challengeA.challenge_id,
    sequence: 1,
    occurred_at: "2026-11-08T00:00:00+00:00",
    actor: "agent",
    event_type: "agent_message",
    payload: {
      provider_id: "deepseek",
      model_id: "deepseek-flash",
      question: "A previous question",
      answer: "A previous answer",
      included_files: [],
      verification_status: "unverified_suggestion",
      execution_performed: false,
    },
    artifact_ids: [],
    event_refs: [],
    previous_event_hash: "0".repeat(64),
    event_hash: "1".repeat(64),
  };

  await page.route("**/api/challenges/*/events", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const body = pathname.includes(challengeA.challenge_id) ? [eventForA] : [];
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });

  await page.goto("/");
  const challengeButton = (name: string) =>
    page.getByRole("button", { name: new RegExp(name) });
  const openAIPanel = () =>
    page.getByRole("button", { name: "AI 解题助手", exact: true }).click();
  const nameA = `Synthetic history A ${stamp}`;
  const nameB = `Synthetic history B ${stamp}`;

  await challengeButton(nameA).click();
  await openAIPanel();
  const history = page.locator(".ai-answer");
  await expect(history.getByText("A previous answer", { exact: true })).toBeVisible();
  await expect(history.getByText("本题 AI 对话记录（均为未验证建议）")).toBeVisible();
  await expect(page.getByLabel(/我确认将本题描述/)).not.toBeChecked();

  // Switching to B does not inherit A's history or consent.
  await challengeButton(nameB).click();
  await openAIPanel();
  await expect(page.locator(".ai-answer")).toHaveCount(0);
  await expect(page.getByLabel(/我确认将本题描述/)).not.toBeChecked();

  // Going back to A restores A's recorded history, still with no consent.
  await challengeButton(nameA).click();
  await openAIPanel();
  await expect(history.getByText("A previous answer", { exact: true })).toBeVisible();
  await expect(page.getByLabel(/我确认将本题描述/)).not.toBeChecked();
});
async function createSyntheticChallenge(
  request: import("@playwright/test").APIRequestContext,
  label: string,
  level = "A2",
) {
  const response = await request.post("http://127.0.0.1:18002/api/challenges", {
    data: {
      name:
        "Synthetic " + label + " " + Date.now() + Math.floor(Math.random() * 1000),
      category: "Misc",
      description: "Synthetic fixture only. No real target or credentials.",
      ai_usage_level: level,
    },
  });
  expect(response.status()).toBe(201);
  return response.json();
}

const proposalFixture = (
  challengeId: string,
  overrides: Record<string, unknown> = {},
) => ({
  proposal_id: "synthetic-proposal-" + Math.random().toString(16).slice(2),
  challenge_id: challengeId,
  model_call_id: "synthetic-call",
  tool_name: "file_inspect",
  arguments: { path: "sample.bin" },
  reason: "Synthetic file format check",
  risk_level: "low",
  status: "pending",
  proposed_by: "agent",
  proposed_at: "2026-11-09T00:00:00+00:00",
  expires_at: "2026-11-09T01:00:00+00:00",
  approval_id: null,
  approved_by: null,
  approved_at: null,
  execution_id: null,
  started_at: null,
  finished_at: null,
  artifact_ids: [],
  output_artifact_id: null,
  output_sha256: null,
  output_size: null,
  output_summary: null,
  error: null,
  ...overrides,
});

test("tool proposals approve and execute as two separate human steps", async ({
  page,
  request,
}, testInfo) => {
  const challenge = await createSyntheticChallenge(request, "tool two-step");
  let proposal = proposalFixture(challenge.challenge_id);
  const approveCalls: Record<string, unknown>[] = [];
  const executeCalls: string[] = [];
  await page.route("**/api/challenges/*/tool-proposals", async (route) => {
    await route.fulfill({ status: 200, json: [proposal] });
  });
  await page.route(
    "**/api/challenges/*/tool-proposals/*/approve",
    async (route) => {
      approveCalls.push(route.request().postDataJSON());
      proposal = {
        ...proposal,
        status: "approved",
        approval_id: "synthetic-approval",
        approved_by: "local-user",
        approved_at: "2026-11-09T00:10:00+00:00",
      };
      await route.fulfill({ status: 200, json: proposal });
    },
  );
  await page.route(
    "**/api/challenges/*/tool-proposals/*/execute",
    async (route) => {
      executeCalls.push(new URL(route.request().url()).pathname);
      proposal = {
        ...proposal,
        status: "succeeded",
        execution_id: "synthetic-execution",
        started_at: "2026-11-09T00:11:00+00:00",
        finished_at: "2026-11-09T00:11:01+00:00",
        output_artifact_id: "synthetic-output-artifact",
        artifact_ids: ["synthetic-output-artifact"],
        output_sha256: "c".repeat(64),
        output_size: 42,
        output_summary: "Synthetic read-only tool output summary.",
      };
      await route.fulfill({ status: 200, json: proposal });
    },
  );
  await page.route("**/api/model/calls", async (route) => {
    await route.fulfill({
      status: 200,
      json: {
        calls: [
          {
            call_id: "synthetic-call-success",
            challenge_id: challenge.challenge_id,
            provider_id: "deepseek",
            model_id: "deepseek-flash",
            purpose: "challenge_chat",
            synthetic: false,
            data_scope: "challenge_context",
            requested_at: "2026-11-09T00:00:00+00:00",
            completed_at: "2026-11-09T00:00:01+00:00",
            response_status: "success",
            error_category: null,
            usage: null,
          },
          {
            call_id: "synthetic-call-unknown",
            challenge_id: null,
            provider_id: "deepseek",
            model_id: "deepseek-flash",
            purpose: "synthetic_connectivity",
            synthetic: true,
            data_scope: "synthetic_prompt",
            requested_at: "2026-11-09T00:00:00+00:00",
            completed_at: null,
            response_status: "unknown",
            error_category: null,
            usage: null,
          },
          {
            call_id: "other-challenge-call",
            challenge_id: "a-different-challenge",
            provider_id: "deepseek",
            model_id: "deepseek-flash",
            purpose: "challenge_chat",
            synthetic: false,
            data_scope: "challenge_context",
            requested_at: "2026-11-09T00:00:00+00:00",
            completed_at: "2026-11-09T00:00:01+00:00",
            response_status: "success",
            error_category: null,
            usage: null,
          },
        ],
      },
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: new RegExp(challenge.name) }).click();
  await page.getByRole("button", { name: "AI 解题助手", exact: true }).click();
  const toolPanel = page.locator(".tool-approval");
  await expect(
    toolPanel.getByText("file_inspect", { exact: true }),
  ).toBeVisible();
  await expect(toolPanel.getByText("Synthetic file format check")).toBeVisible();
  await expect(toolPanel.getByText("sample.bin", { exact: true })).toBeVisible();
  await expect(toolPanel.getByText("待批准", { exact: true })).toBeVisible();
  await expect(toolPanel.getByText("低风险", { exact: false })).toBeVisible();
  await expect(
    toolPanel.getByRole("button", { name: "批准", exact: true }),
  ).toBeEnabled();
  // No bundled approve-and-execute action and no execute before approval.
  await expect(
    toolPanel.getByRole("button", { name: "批准并执行" }),
  ).toHaveCount(0);
  await expect(
    toolPanel.getByRole("button", { name: "执行", exact: true }),
  ).toHaveCount(0);
  await expect(toolPanel.getByText("pending", { exact: true })).toHaveCount(0);

  await toolPanel.getByRole("button", { name: "批准", exact: true }).click();
  await expect.poll(() => approveCalls.length).toBe(1);
  expect(approveCalls[0]).toMatchObject({ approving_user: "local-user" });
  // Approval alone must never execute the tool.
  expect(executeCalls).toEqual([]);
  await expect(toolPanel.getByText("已批准", { exact: true })).toBeVisible();
  const executeButton = toolPanel.getByRole("button", {
    name: "执行",
    exact: true,
  });
  await expect(executeButton).toBeEnabled();

  await executeButton.click();
  await expect.poll(() => executeCalls.length).toBe(1);
  await expect(toolPanel.getByText("成功", { exact: true })).toBeVisible();
  await expect(
    toolPanel.getByText("Synthetic read-only tool output summary."),
  ).toBeVisible();
  await expect(
    toolPanel.getByText("c".repeat(64), { exact: false }),
  ).toBeVisible();
  await expect(
    toolPanel.getByText("synthetic-output-artifact", { exact: false }).first(),
  ).toBeVisible();
  const artifactLink = toolPanel.getByRole("link", {
    name: "下载工具输出 Artifact",
  });
  await expect(artifactLink).toBeVisible();
  expect(await artifactLink.getAttribute("href")).toBe(
    "/api/challenges/" +
      challenge.challenge_id +
      "/artifacts/synthetic-output-artifact/content",
  );
  await expect(toolPanel.getByText("succeeded", { exact: true })).toHaveCount(0);

  // Model call audit status comes from GET /api/model/calls.
  const audit = page.locator(".model-audit");
  await expect(audit.getByText("合成连通测试", { exact: false })).toBeVisible();
  await expect(
    audit.getByText("synthetic-call-success", { exact: false }),
  ).toBeVisible();
  await expect(audit.getByText("未终结（未知）", { exact: false })).toBeVisible();
  await expect(
    audit.getByText("other-challenge-call", { exact: false }),
  ).toHaveCount(0);

  // Desktop and 390px mobile: no horizontal overflow with long hashes/ids.
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.reload();
    await page
      .getByRole("button", { name: new RegExp(challenge.name) })
      .click();
    await page.getByRole("button", { name: "AI 解题助手", exact: true }).click();
    await expect(
      page.locator(".tool-approval").getByText("成功", { exact: true }),
    ).toBeVisible();
    const evidenceDir = process.env.CTF_EVIDENCE_DIR ?? testInfo.outputDir;
    mkdirSync(evidenceDir, { recursive: true });
    const screenshot = join(
      evidenceDir,
      "synthetic-ai-tools-" + width + "px.png",
    );
    await page.screenshot({ path: screenshot, fullPage: true });
    await testInfo.attach("synthetic-ai-tools-" + width + "px", {
      path: screenshot,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    ).toBe(true);
  }
});

test("every tool status renders its Chinese label and no raw English status", async ({
  page,
  request,
}) => {
  const challenge = await createSyntheticChallenge(request, "tool statuses");
  const statuses = [
    "pending",
    "approved",
    "running",
    "succeeded",
    "failed",
    "timed_out",
    "rejected",
    "cancelled",
    "expired",
  ];
  const expected: Record<string, string> = {
    pending: "待批准",
    approved: "已批准",
    running: "运行中",
    succeeded: "成功",
    failed: "失败",
    timed_out: "已超时",
    rejected: "已拒绝",
    cancelled: "已取消",
    expired: "已过期",
  };
  const fixtures = statuses.map((status, index) =>
    proposalFixture(challenge.challenge_id, {
      proposal_id: "status-proposal-" + status,
      tool_name: "list_files",
      arguments: { path: ".", index },
      reason: "Synthetic status " + status,
      status,
    }),
  );
  await page.route("**/api/challenges/*/tool-proposals", async (route) => {
    await route.fulfill({ status: 200, json: fixtures });
  });
  await page.route("**/api/model/status", async (route) => {
    await route.fulfill({
      status: 200,
      json: {
        network_enabled: false,
        provider: "deepseek",
        model_id: "deepseek-flash",
        credentials_configured: false,
        execution_enabled: false,
      },
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: new RegExp(challenge.name) }).click();
  await page.getByRole("button", { name: "AI 解题助手", exact: true }).click();
  const toolPanel = page.locator(".tool-approval");
  for (const status of statuses) {
    await expect(
      toolPanel.getByText(expected[status], { exact: true }),
    ).toBeVisible();
  }
  for (const status of statuses) {
    await expect(toolPanel.getByText(status, { exact: true })).toHaveCount(0);
  }
});

test("switching challenge clears tool list, Flag input, consent and question", async ({
  page,
  request,
}) => {
  const challengeA = await createSyntheticChallenge(request, "switch A");
  const challengeB = await createSyntheticChallenge(request, "switch B");
  const proposalA = proposalFixture(challengeA.challenge_id, {
    proposal_id: "only-for-challenge-a",
    reason: "Only visible for challenge A",
  });
  await page.route("**/api/model/status", async (route) => {
    await route.fulfill({
      status: 200,
      json: {
        network_enabled: true,
        provider: "deepseek",
        model_id: "deepseek-flash",
        credentials_configured: true,
        execution_enabled: false,
      },
    });
  });
  await page.route("**/api/challenges/*/tool-proposals", async (route) => {
    const body = route.request().url().includes(challengeA.challenge_id)
      ? [proposalA]
      : [];
    await route.fulfill({ status: 200, json: body });
  });
  await page.goto("/");
  const openAI = async (name: string) => {
    await page.getByRole("button", { name: new RegExp(name) }).click();
    await page.getByRole("button", { name: "AI 解题助手", exact: true }).click();
  };
  await openAI(challengeA.name);
  await expect(
    page.locator(".tool-approval").getByText("Only visible for challenge A"),
  ).toBeVisible();
  const question = page.getByLabel("向 AI 提问");
  const consent = page.getByLabel(/我确认将本题描述/);
  const flagInput = page.getByLabel("输入已确认的 Flag");
  const send = page.getByRole("button", { name: "发送问题并获取分析" });
  await question.fill("A pending question that must not survive a switch");
  await consent.check();
  await flagInput.fill("flag{A_SWITCH_TEST}");
  await expect(send).toBeEnabled();

  await openAI(challengeB.name);
  await expect(page.locator(".tool-approval")).toContainText("暂无工具申请。");
  await expect(page.locator(".tool-approval")).not.toContainText(
    "Only visible for challenge A",
  );
  await expect(question).toHaveValue("");
  await expect(consent).not.toBeChecked();
  await expect(flagInput).toHaveValue("");
  await expect(send).toBeDisabled();

  // A -> B -> A restores A's server-side tool list, never the old confirmations.
  await openAI(challengeA.name);
  await expect(
    page.locator(".tool-approval").getByText("Only visible for challenge A"),
  ).toBeVisible();
  await expect(question).toHaveValue("");
  await expect(consent).not.toBeChecked();
  await expect(flagInput).toHaveValue("");
  await expect(send).toBeDisabled();
});

test("an old challenge AI response never overwrites the newly selected challenge", async ({
  page,
  request,
}) => {
  const challengeA = await createSyntheticChallenge(request, "stale A");
  const challengeB = await createSyntheticChallenge(request, "stale B");
  await page.route("**/api/model/status", async (route) => {
    await route.fulfill({
      status: 200,
      json: {
        network_enabled: true,
        provider: "deepseek",
        model_id: "deepseek-flash",
        credentials_configured: true,
        execution_enabled: false,
      },
    });
  });
  let releaseResponse: (() => void) | undefined;
  const responseGate = new Promise<void>((resolve) => {
    releaseResponse = resolve;
  });
  let requestStarted = false;
  await page.route("**/api/challenges/*/ai/chat", async (route) => {
    requestStarted = true;
    await responseGate;
    await route.fulfill({
      status: 201,
      json: {
        event_id: "synthetic-stale-event",
        answer: "STALE_ANSWER_FROM_OLD_CHALLENGE",
        provider_id: "deepseek",
        model_id: "deepseek-flash",
        included_files: [],
        verification_status: "unverified_suggestion",
      },
    });
  });
  await page.goto("/");
  const openAI = async (name: string) => {
    await page.getByRole("button", { name: new RegExp(name) }).click();
    await page.getByRole("button", { name: "AI 解题助手", exact: true }).click();
  };
  await openAI(challengeA.name);
  await page.getByLabel("向 AI 提问").fill("A question with a delayed answer");
  await page.getByLabel(/我确认将本题描述/).check();
  await page.getByRole("button", { name: "发送问题并获取分析" }).click();
  await expect.poll(() => requestStarted).toBe(true);

  await openAI(challengeB.name);
  releaseResponse?.();
  await page.waitForTimeout(400);
  expect(await page.content()).not.toContain("STALE_ANSWER_FROM_OLD_CHALLENGE");
  await expect(page.locator(".ai-answer")).toHaveCount(0);
  await expect(page.locator(".banner.error")).toHaveCount(0);
  await expect(page.getByLabel("向 AI 提问")).toHaveValue("");
});

test("human Flag confirmation shows only a digest summary, never plaintext", async ({
  page,
  request,
}) => {
  const challenge = await createSyntheticChallenge(request, "flag summary");
  const flag = "flag{SYNTHETIC_UI_" + Date.now() + "}";
  await page.route("**/api/model/status", async (route) => {
    await route.fulfill({
      status: 200,
      json: {
        network_enabled: false,
        provider: "deepseek",
        model_id: "deepseek-flash",
        credentials_configured: false,
        execution_enabled: false,
      },
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: new RegExp(challenge.name) }).click();
  await page.getByRole("button", { name: "AI 解题助手", exact: true }).click();
  await page.getByLabel("输入已确认的 Flag").fill(flag);
  await page.getByRole("button", { name: "记录人工确认" }).click();
  await expect(
    page.getByText("Flag 已人工确认（仅记录 SHA-256/长度）"),
  ).toBeVisible();
  const record = page.locator(".flag-record");
  await expect(record).toHaveCount(1);
  await expect(record).toContainText("SHA-256");
  await expect(record).toContainText("长度 " + flag.length);
  await expect(record).toContainText("local-user");
  await expect(record).toContainText("platform_verified=false");
  await expect(page.getByLabel("输入已确认的 Flag")).toHaveValue("");
  expect(await page.content()).not.toContain(flag);

  const events = await request.get(
    "http://127.0.0.1:18002/api/challenges/" +
      challenge.challenge_id +
      "/events",
  );
  const body = await events.json();
  const flagEvent = body.find(
    (event: { event_type: string }) => event.event_type === "flag_confirmed",
  );
  expect(flagEvent).toBeTruthy();
  expect(flagEvent.payload.platform_verified).toBe(false);
  expect(flagEvent.payload.flag_length).toBe(flag.length);
  expect(JSON.stringify(body)).not.toContain(flag);
});

test("a real read-only tool runs only after approval and a separate execute", async ({
  page,
  request,
}, testInfo) => {
  const challenge = await createSyntheticChallenge(request, "real tool");
  const proposed = await request.post(
    "http://127.0.0.1:18002/api/challenges/" +
      challenge.challenge_id +
      "/tool-proposals",
    {
      data: {
        tool_name: "list_files",
        arguments: { path: "." },
        reason: "List the synthetic workspace",
      },
    },
  );
  expect(proposed.status()).toBe(201);
  expect((await proposed.json()).status).toBe("pending");
  const eventTypes = async () => {
    const response = await request.get(
      "http://127.0.0.1:18002/api/challenges/" +
        challenge.challenge_id +
        "/events",
    );
    expect(response.ok()).toBeTruthy();
    return (await response.json()).map(
      (event: { event_type: string }) => event.event_type,
    );
  };

  await page.goto("/");
  await page.getByRole("button", { name: new RegExp(challenge.name) }).click();
  await page.getByRole("button", { name: "AI 解题助手", exact: true }).click();
  const toolPanel = page.locator(".tool-approval");
  await expect(toolPanel.getByText("list_files", { exact: true })).toBeVisible();
  await expect(toolPanel.getByText("待批准", { exact: true })).toBeVisible();
  expect(await eventTypes()).toEqual(["tool_proposed"]);

  await toolPanel.getByRole("button", { name: "批准", exact: true }).click();
  await expect(toolPanel.getByText("已批准", { exact: true })).toBeVisible();
  // Approval must not start the tool; the backend event chain proves it.
  expect(await eventTypes()).toEqual(["tool_proposed", "tool_approved"]);

  await toolPanel.getByRole("button", { name: "执行", exact: true }).click();
  await expect(toolPanel.getByText("成功", { exact: true })).toBeVisible();
  expect(await eventTypes()).toEqual([
    "tool_proposed",
    "tool_approved",
    "tool_started",
    "artifact_added",
    "tool_finished",
  ]);
  const artifactLink = toolPanel.getByRole("link", {
    name: "下载工具输出 Artifact",
  });
  await expect(artifactLink).toBeVisible();
  const href = await artifactLink.getAttribute("href");
  expect(href).toContain("/artifacts/");
  const artifact = await request.get("http://127.0.0.1:18002" + href);
  expect(artifact.ok()).toBeTruthy();
  expect((await artifact.body()).length).toBeGreaterThan(0);

  const evidenceDir = process.env.CTF_EVIDENCE_DIR ?? testInfo.outputDir;
  mkdirSync(evidenceDir, { recursive: true });
  const screenshot = join(
    evidenceDir,
    "real-tool-approval-after-execution.png",
  );
  await page.screenshot({ path: screenshot, fullPage: true });
  await testInfo.attach("real-tool-approval-after-execution", {
    path: screenshot,
  });
});
