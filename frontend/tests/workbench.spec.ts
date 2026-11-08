import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { writeFileSync } from "node:fs";
import { resolve, sep } from "node:path";
const zip = Buffer.from(
  "UEsDBBQAAAAAAJxKaF1WnRzILwAAAC8AAAAMAAAAc3JjL2hlbGxvLnB5IyBTeW50aGV0aWMgb2ZmbGluZSBmaXh0dXJlCnByaW50KCJzeW50aGV0aWMiKQpQSwMEFAAAAAAAnEpoXV2kLFYqAAAAKgAAAAoAAABSRUFETUUudHh0U3ludGhldGljIFpJUCBmaXh0dXJlLiBObyByZWFsIGNoYWxsZW5nZS4KUEsBAhQAFAAAAAAAnEpoXVadHMgvAAAALwAAAAwAAAAAAAAAAAAAAIABAAAAAHNyYy9oZWxsby5weVBLAQIUABQAAAAAAJxKaF1dpCxWKgAAACoAAAAKAAAAAAAAAAAAAACAAVkAAABSRUFETUUudHh0UEsFBgAAAAACAAIAcgAAAKsAAAAAAA==",
  "base64",
);
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=",
  "base64",
);
test("real FastAPI: full synthetic manual workflow, reload and downloads", async ({
  page,
}) => {
  const consoleErrors: string[] = [];
  page.on("pageerror", (e) => consoleErrors.push(e.message));
  const calls: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/")) calls.push(r.method() + " " + r.url());
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "每一个结论，都有证据可循。" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "刷新", exact: true }),
  ).toBeEnabled();
  if (!(await page.getByLabel("项目名称", { exact: true }).isVisible()))
    await page.getByText("比赛项目设置", { exact: true }).click();
  await page
    .getByLabel("项目名称", { exact: true })
    .fill("Synthetic MVP project");
  await page
    .getByLabel("比赛名称", { exact: true })
    .fill("Synthetic local practice");
  await page.getByLabel("比赛类型", { exact: true }).fill("practice");
  await page
    .getByLabel("规则概要与 AI 限制")
    .fill("Synthetic test only. No actual competition. Manual execution.");
  await page.getByRole("button", { name: "保存项目", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("项目已保存");
  await page.getByText("共享比赛规则 PDF", { exact: true }).click();
  await page.getByLabel("上传规则（项目共享）").setInputFiles({
    name: "synthetic-rules.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4\n% Synthetic rules fixture only\n%%EOF"),
  });
  await expect(page.getByText("下载规则原件")).toBeVisible();
  await page.getByText("＋ 创建题目", { exact: true }).click();
  await page
    .getByLabel("题目名称", { exact: true })
    .fill("Synthetic frontend acceptance");
  await page
    .getByLabel("描述", { exact: true })
    .fill("Synthetic offline data, not a real challenge.");
  await page.getByLabel("分值", { exact: true }).fill("100");
  await page.getByRole("button", { name: "创建题目", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Synthetic frontend acceptance" }),
  ).toBeVisible();
  await expect(page.getByText("规则未确认，Agent 流程禁用。")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "刷新", exact: true }),
  ).toBeEnabled();
  await page.getByLabel("题目 ZIP", { exact: true }).setInputFiles({
    name: "synthetic.zip",
    mimeType: "application/zip",
    buffer: zip,
  });
  await expect(page.getByText("2 个文件", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "src/hello.py", exact: true }).click();
  await expect(page.locator(".code-preview")).toContainText(
    "Synthetic offline fixture",
  );
  await page.getByRole("button", { name: "运行记录", exact: true }).click();
  await page
    .getByLabel("实际执行命令", { exact: true })
    .fill("echo synthetic-manual-claim");
  await page.getByLabel("工作目录", { exact: true }).fill("C:\\synthetic");
  await page
    .getByLabel("执行目的", { exact: true })
    .fill("Synthetic UI record only; command not executed by test.");
  await page.getByLabel("退出码（可选）").fill("0");
  await page
    .getByLabel("运行结果说明", { exact: true })
    .fill("User declaration fixture, not verified execution.");
  await page.getByRole("button", { name: "保存人工申报", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "human_action · 人工申报 / 未验证执行" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "校验事件链" }).click();
  await expect(
    page.getByText("事件链一致（不证明操作或截图真实性）"),
  ).toBeVisible();
  await page.getByRole("button", { name: "题目与导入", exact: true }).click();
  for (const kind of ["execution", "flag_capture", "platform_verification"]) {
    await page.getByLabel("证据类型", { exact: true }).selectOption(kind);
    const done = page.waitForResponse(
      (r) => r.url().endsWith("/artifacts") && r.request().method() === "POST",
    );
    await page.getByLabel("上传证据", { exact: true }).setInputFiles({
      name: `synthetic-${kind}.png`,
      mimeType: "image/png",
      buffer: Buffer.concat([
        png,
        Buffer.from("Synthetic classification fixture " + kind),
      ]),
    });
    expect((await done).ok()).toBeTruthy();
    await expect(
      page.locator(".artifact").filter({ hasText: `synthetic-${kind}.png` }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "刷新", exact: true }),
    ).toBeEnabled();
  }
  await page.getByRole("button", { name: /▧ synthetic-execution.png/ }).click();
  await expect(page.getByAltText("用户上传的原始证据预览")).toBeVisible();
  expect(
    await page
      .getByAltText("用户上传的原始证据预览")
      .evaluate((img: HTMLImageElement) => img.naturalWidth),
  ).toBeGreaterThan(0);
  await page.getByLabel("笔记类型", { exact: true }).selectOption("approach");
  await page
    .getByLabel("选手笔记", { exact: true })
    .fill("Synthetic manual approach note, not reconstructed from a Flag.");
  await page.getByRole("button", { name: "追加笔记", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "刷新", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Writeup", exact: true }).click();
  await page
    .getByRole("button", { name: "生成服务器初稿", exact: true })
    .click();
  await expect(page.getByLabel("Markdown 人工编辑")).toHaveValue(
    /题目基本信息/,
  );
  await expect(page.getByLabel("Markdown 人工编辑")).toHaveValue(/人工申报/);
  await page
    .getByLabel("Markdown 人工编辑")
    .fill(
      "# Synthetic edited draft\n\n[证据缺失：此为自动化合成验收，非真实 Flag 截图]",
    );
  await expect(
    page.locator(".no-print").getByText("人工编辑 · 待复核", { exact: true }),
  ).toBeVisible();
  const md = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "下载 Markdown", exact: true })
    .click();
  expect((await md).suggestedFilename()).toMatch(/\.md$/);
  mkdirSync("test-results/demo", { recursive: true });
  await (await md).saveAs("test-results/demo/edited.md");
  const dl = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载证据 ZIP", exact: true }).click();
  expect((await dl).suggestedFilename()).toMatch(/evidence-.*\.zip$/);
  await (await dl).saveAs("test-results/demo/evidence.zip");
  await expect(
    page.getByRole("button", { name: "刷新", exact: true }),
  ).toBeEnabled();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Synthetic frontend acceptance" }),
  ).toBeVisible();
  await expect(page.getByText("2 个文件", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Writeup", exact: true }).click();
  await expect(page.getByLabel("Markdown 人工编辑")).toHaveValue(
    /Synthetic edited draft/,
  );
  mkdirSync("test-results/demo", { recursive: true });
  await page.screenshot({
    path: "test-results/demo/writeup.png",
    fullPage: true,
  });
  await page.emulateMedia({ media: "print" });
  await page.pdf({
    path: "test-results/demo/print.pdf",
    format: "A4",
    printBackground: true,
  });
  await page.screenshot({
    path: "test-results/demo/print.png",
    fullPage: true,
  });
  await page.emulateMedia({ media: "screen" });
  await page.getByRole("button", { name: "题目与导入", exact: true }).click();
  await page.screenshot({
    path: "test-results/demo/workbench.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/demo/mobile.png",
    fullPage: true,
  });
  expect(consoleErrors).toEqual([]);
  expect(calls.some((s) => /\/manual-operations$/.test(s))).toBe(true);
  expect(calls.some((s) => /\/export$/.test(s))).toBe(true);
  expect(calls.some((s) => /\/execute|\/model|\/submit/.test(s))).toBe(false);
});

test("real API rejection remains a failure in the UI", async ({
  page,
  request,
}) => {
  const name = "Synthetic invalid ZIP " + Date.now();
  const c = await request.post("http://127.0.0.1:8000/api/challenges", {
    data: { name, category: "Misc", ai_usage_level: "A0" },
  });
  expect(c.status()).toBe(201);
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "刷新", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: new RegExp("Misc.*" + name) }).click();
  await expect(
    page.getByRole("button", { name: "刷新", exact: true }),
  ).toBeEnabled();
  await page.getByLabel("题目 ZIP", { exact: true }).setInputFiles({
    name: "invalid.zip",
    mimeType: "application/zip",
    buffer: Buffer.from("Synthetic malformed ZIP"),
  });
  await expect(page.getByRole("alert")).toContainText("422");
  await expect(
    page.getByText("失败或结果未知，请刷新核对后重试"),
  ).toBeVisible();
  await expect(page.locator(".import")).toHaveCount(0);
});

test("real unverified manifest stays visible without blocking sibling import", async ({
  page,
  request,
}) => {
  test.skip(
    !process.env.CTF_TEST_DATA_DIR,
    "Requires explicit isolated synthetic backend data directory",
  );
  const name = "Synthetic manifest review " + Date.now();
  const created = await request.post("http://127.0.0.1:8000/api/challenges", {
    data: { name, category: "Misc" },
  });
  expect(created.status()).toBe(201);
  const c = await created.json();
  const records = [];
  for (let n = 0; n < 2; n++) {
    const r = await request.post(
      `http://127.0.0.1:8000/api/challenges/${c.challenge_id}/imports`,
      {
        multipart: {
          file: {
            name: `synthetic-${n}.zip`,
            mimeType: "application/zip",
            buffer: zip,
          },
        },
      },
    );
    expect(r.status()).toBe(201);
    records.push(await r.json());
  }
  const dataRoot = resolve(process.env.CTF_TEST_DATA_DIR!);
  const manifest = resolve(
    dataRoot,
    "challenges",
    c.challenge_id,
    "imports",
    records[0].import_id,
    "manifest.json",
  );
  expect(manifest.startsWith(dataRoot + sep)).toBe(true);
  writeFileSync(manifest, "{}");
  const urls: string[] = [];
  page.on("request", (r) => urls.push(r.url()));
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "刷新", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: new RegExp("Misc.*" + name) }).click();
  await expect(
    page.getByRole("button", { name: "刷新", exact: true }),
  ).toBeEnabled();
  await expect(page.locator(".import")).toHaveCount(2);
  const bad = page.locator(".import").filter({ hasText: "synthetic-0.zip" });
  await expect(bad).toContainText("完整性异常 / 文件访问禁用");
  await expect(bad.getByRole("alert")).toBeVisible();
  await expect(bad.getByRole("link")).toHaveCount(0);
  await expect(
    page
      .locator(".import")
      .filter({ hasText: "synthetic-1.zip" })
      .getByRole("button", { name: "src/hello.py", exact: true }),
  ).toBeVisible();
  expect(
    urls.some((url) => url.endsWith("/imports/" + records[0].import_id)),
  ).toBe(false);
});
