import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { mkdirSync, writeFileSync, readFileSync, openSync } from "node:fs";
import { resolve, sep, join } from "node:path";
import { execFileSync, spawn } from "node:child_process";
import { createHash } from "node:crypto";
const base = "http://127.0.0.1:8000/api",
  out = "test-results/c5";
let transcript: any[] = [],
  pending: Promise<void>[] = [];
test.beforeEach(() => {
  mkdirSync(out, { recursive: true });
  transcript = [];
  pending = [];
});
test.afterEach(async ({}, info) => {
  await Promise.allSettled(pending);
  writeFileSync(
    join(out, info.title.replace(/[^a-z0-9]/gi, "_") + ".http.json"),
    JSON.stringify(transcript, null, 2),
  );
});
function observe(page: Page) {
  page.on("response", (r) => {
    if (!r.url().includes("/api/")) return;
    pending.push(
      (async () => {
        const h = r.headers(),
          post = r.request().postData();
        transcript.push({
          url: r.url(),
          method: r.request().method(),
          status: r.status(),
          request:
            post && Buffer.byteLength(post) > 4096
              ? {
                  size: Buffer.byteLength(post),
                  sha256: createHash("sha256").update(post).digest("hex"),
                }
              : post,
          body: h["content-type"]?.includes("json")
            ? await r.text()
            : "[binary download saved separately]",
          completeness: h["x-dossier-completeness"],
        });
      })(),
    );
  });
  page.on("requestfailed", (r) =>
    transcript.push({ url: r.url(), network_failure: r.failure() }),
  );
}
async function call(
  request: APIRequestContext,
  method: "get" | "put" | "post",
  path: string,
  data?: unknown,
) {
  const r = await request[method](
    base + path,
    data === undefined ? {} : { data },
  );
  const body = await r.text();
  transcript.push({
    method,
    path,
    status: r.status(),
    request:
      JSON.stringify(data ?? "").length > 4096
        ? "[oversized synthetic input]"
        : data,
    body,
  });
  return r;
}
async function challenge(request: APIRequestContext, label: string) {
  const name = "C5 " + label + " " + Date.now();
  const r = await call(request, "post", "/challenges", {
    name,
    category: "Misc",
    ai_usage_level: "A1",
  });
  expect(r.status()).toBe(201);
  return { ...(await r.json()), name };
}
async function idle(page: Page) {
  await expect(
    page.getByRole("button", { name: "刷新", exact: true }),
  ).toBeEnabled();
}
async function enter(page: Page, name: string) {
  observe(page);
  await page.goto("/");
  await idle(page);
  await page.getByRole("button", { name: new RegExp("Misc.*" + name) }).click();
  await idle(page);
  await page.getByRole("button", { name: "Writeup", exact: true }).click();
}
async function save(page: Page, status: number, version: number) {
  const r = page.waitForResponse(
    (r) => r.url().endsWith("/writeup/draft") && r.request().method() === "PUT",
  );
  await page.getByRole("button", { name: "保存到服务器", exact: true }).click();
  expect((await r).status()).toBe(status);
  await idle(page);
  await expect(page.locator(".save-status")).toHaveText(
    `已保存（版本 v${version}）`,
  );
}
async function download(
  page: Page,
  name: string,
  unsaved = false,
  expected = "incomplete",
) {
  if (unsaved) page.once("dialog", (d) => d.accept());
  const wait = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载证据 ZIP", exact: true }).click();
  const d = await wait;
  await d.saveAs(join(out, name));
  await idle(page);
  expect(d.suggestedFilename()).toContain("evidence-" + expected + "-");
  return join(out, name);
}
function verify(
  zip: string,
  generated: string,
  human?: string,
  version?: number,
  corrupt = false,
  complete = false,
) {
  const gen = zip + ".generated.md";
  writeFileSync(gen, generated);
  const args = ["-B", "tests/assert_draft_zip.py", zip, gen];
  if (human !== undefined) {
    const humanFile = zip + ".human.md";
    writeFileSync(humanFile, human);
    args.push("--human", humanFile, "--version", String(version));
  }
  if (corrupt) args.push("--corrupt");
  if (complete) args.push("--complete");
  const result = execFileSync(process.env.CTF_TEST_PYTHON || "python", args, {
    encoding: "utf8",
  });
  console.log(result.trim());
}

test("C5 save reload update fresh browser and final ZIP closure", async ({
  page,
  request,
  browser,
}) => {
  const c = await challenge(request, "persistence");
  await enter(page, c.name);
  const editor = page.getByLabel("Markdown 人工编辑");
  const v1 = "# C5 human v1\n\n中文人工稿。Synthetic only.\n";
  await editor.fill(v1);
  await save(page, 201, 1);
  expect(
    await page.evaluate(
      (cid) => localStorage.getItem("ctf-workbench:draft:v1:" + cid),
      c.challenge_id,
    ),
  ).toBeNull();
  await page.reload();
  await idle(page);
  await page.getByRole("button", { name: "Writeup", exact: true }).click();
  await expect(editor).toHaveValue(v1);
  const generated = (
    await (
      await call(
        request,
        "get",
        `/challenges/${c.challenge_id}/writeup/preview`,
      )
    ).json()
  ).markdown;
  verify(await download(page, "human-v1.zip"), generated, v1, 1);
  const v2 = "# C5 human v2\n\n第二版，必须出现在最终 ZIP。\n";
  await editor.fill(v2);
  await save(page, 200, 2);
  await page.reload();
  await idle(page);
  await page.getByRole("button", { name: "Writeup", exact: true }).click();
  await expect(editor).toHaveValue(v2);
  await page.screenshot({
    path: join(out, "saved-desktop.png"),
    fullPage: true,
  });
  const other = await browser.newContext({ baseURL: "http://127.0.0.1:5173" }),
    fresh = await other.newPage();
  await enter(fresh, c.name);
  await expect(fresh.getByLabel("Markdown 人工编辑")).toHaveValue(v2);
  await expect(fresh.locator(".draft-metadata")).toContainText("服务器版本 v2");
  await fresh.setViewportSize({ width: 390, height: 844 });
  expect(
    await fresh.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await fresh.screenshot({
    path: join(out, "saved-mobile.png"),
    fullPage: true,
  });
  verify(await download(fresh, "human-v2.zip"), generated, v2, 2);
  await other.close();
  const server = await (
    await call(request, "get", `/challenges/${c.challenge_id}/writeup/draft`)
  ).json();
  expect(server.content).toBe(v2);
  expect(server.sha256).toBe(createHash("sha256").update(v2).digest("hex"));
  expect(server.size).toBe(Buffer.byteLength(v2));
  const exportedMetadata = JSON.parse(
    readFileSync(join(out, "human-v2.zip.verification.json"), "utf8"),
  ).human_metadata;
  expect(exportedMetadata.saved_at).toBe(server.saved_at);
  expect(exportedMetadata.sha256).toBe(server.sha256);
  expect(exportedMetadata.size).toBe(server.size);
  const untouched = await (
    await call(request, "get", `/challenges/${c.challenge_id}/events`)
  ).json();
  expect(untouched).toEqual([]);
});

test("C5 complete synthetic dossier exports saved human and generated draft", async ({
  page,
  request,
}) => {
  await call(request, "put", "/project", {
    project_name: "C5 synthetic acceptance",
    ai_policy_summary:
      "Synthetic A1 tests; no real competition, no actual tool execution.",
  });
  const c = await challenge(request, "complete-dossier");
  const archive = join(out, "synthetic-original.zip");
  execFileSync(process.env.CTF_TEST_PYTHON || "python", [
    "-B",
    "-c",
    "import zipfile,sys;z=zipfile.ZipFile(sys.argv[1],'w');z.writestr('README.txt','C5 synthetic attachment; not executed');z.close()",
    archive,
  ]);
  const imported = await request.post(
    base + `/challenges/${c.challenge_id}/imports`,
    {
      multipart: {
        file: {
          name: "synthetic-original.zip",
          mimeType: "application/zip",
          buffer: readFileSync(archive),
        },
      },
    },
  );
  expect(imported.status()).toBe(201);
  transcript.push({
    method: "POST",
    path: "/imports",
    status: imported.status(),
    body: await imported.text(),
  });
  await call(request, "post", `/challenges/${c.challenge_id}/notes`, {
    text: "Synthetic test approach only, not real solving.",
    kind: "approach",
  });
  await call(
    request,
    "post",
    `/challenges/${c.challenge_id}/manual-operations`,
    {
      command: "synthetic declaration only; never run",
      working_directory: "C:\\synthetic",
      purpose: "Synthetic manual claim fixture, not actual execution",
      result_note:
        "This command was not executed by test; execution_verified remains false.",
      exit_code: 0,
    },
  );
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=",
    "base64",
  );
  for (const kind of [
    "execution",
    "flag_capture",
    "platform_verification",
    "source_code",
  ]) {
    const bytes =
      kind === "source_code"
        ? Buffer.from("# Synthetic core evidence only; not executed\n")
        : Buffer.concat([png, Buffer.from("SYNTHETIC NOT REAL " + kind)]);
    const r = await request.post(
      base + `/challenges/${c.challenge_id}/artifacts`,
      {
        multipart: {
          file: {
            name:
              "synthetic-" + kind + (kind === "source_code" ? ".py" : ".png"),
            mimeType: kind === "source_code" ? "text/plain" : "image/png",
            buffer: bytes,
          },
          evidence_kind: kind,
        },
      },
    );
    expect(r.status()).toBe(201);
    transcript.push({
      method: "POST",
      path: "/artifacts",
      status: r.status(),
      body: await r.text(),
    });
  }
  const p = await (
    await call(request, "get", `/challenges/${c.challenge_id}/writeup/preview`)
  ).json();
  expect(p.completeness).toBe("complete");
  await enter(page, c.name);
  const human =
    "# C5 final saved human draft\n\nAll evidence is SYNTHETIC, not real Flag or platform proof.\n";
  await page.getByLabel("Markdown 人工编辑").fill(human);
  await save(page, 201, 1);
  verify(
    await download(page, "complete-human-dossier.zip", false, "complete"),
    p.markdown,
    human,
    1,
    false,
    true,
  );
  await expect(
    page.getByRole("status").filter({ hasText: "实际导出完整性：complete" }),
  ).toBeVisible();
  await page.screenshot({
    path: join(out, "complete-closure.png"),
    fullPage: true,
  });
});

test("C5 two windows conflict preserves editor and requires manual merge", async ({
  page,
  request,
  browser,
}) => {
  const c = await challenge(request, "concurrency");
  expect(
    (
      await call(
        request,
        "put",
        `/challenges/${c.challenge_id}/writeup/draft`,
        { content: "initial", base_version: 0 },
      )
    ).status(),
  ).toBe(201);
  const other = await browser.newContext({ baseURL: "http://127.0.0.1:5173" }),
    b = await other.newPage();
  await enter(page, c.name);
  await enter(b, c.name);
  await page.getByLabel("Markdown 人工编辑").fill("window A v2");
  await b.getByLabel("Markdown 人工编辑").fill("window B unsaved");
  await save(page, 200, 2);
  let puts = 0;
  b.on("request", (r) => {
    if (r.method() === "PUT" && r.url().endsWith("/draft")) puts++;
  });
  const response = b.waitForResponse(
    (r) => r.status() === 409 && r.url().endsWith("/draft"),
  );
  await b.getByRole("button", { name: "保存到服务器", exact: true }).click();
  await response;
  await idle(b);
  await expect(b.getByLabel("Markdown 人工编辑")).toHaveValue(
    "window B unsaved",
  );
  await expect(b.getByLabel("服务器最新稿（只读）")).toHaveValue("window A v2");
  await expect(
    b.getByRole("button", { name: "保存到服务器", exact: true }),
  ).toBeDisabled();
  await b.waitForTimeout(200);
  expect(puts).toBe(1);
  await b.screenshot({
    path: join(out, "version-conflict.png"),
    fullPage: true,
  });
  await b.setViewportSize({ width: 390, height: 844 });
  expect(
    await b.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
  ).toBe(true);
  await b.screenshot({
    path: join(out, "version-conflict-mobile.png"),
    fullPage: true,
  });
  await b
    .getByRole("button", {
      name: "保留本地内容，按最新版本手动合并",
      exact: true,
    })
    .click();
  expect(puts).toBe(1);
  await b.getByLabel("Markdown 人工编辑").fill("manual merge A + B");
  await save(b, 200, 3);
  expect(
    (
      await (
        await call(
          request,
          "get",
          `/challenges/${c.challenge_id}/writeup/draft`,
        )
      ).json()
    ).content,
  ).toBe("manual merge A + B");
  await other.close();
});

test("C5 same profile second window retains unsaved draft after first saves", async ({
  page,
  context,
  request,
}) => {
  const c = await challenge(request, "shared-profile");
  await call(request, "put", `/challenges/${c.challenge_id}/writeup/draft`, {
    content: "v1",
    base_version: 0,
  });
  const second = await context.newPage();
  await enter(page, c.name);
  await enter(second, c.name);
  await page.getByLabel("Markdown 人工编辑").fill("same-profile A");
  await second
    .getByLabel("Markdown 人工编辑")
    .fill("same-profile B must survive");
  await save(page, 200, 2);
  await second.reload();
  await idle(second);
  await second.getByRole("button", { name: "Writeup", exact: true }).click();
  await expect(second.getByLabel("Markdown 人工编辑")).toHaveValue(
    "same-profile B must survive",
  );
  await expect(second.getByLabel("服务器最新稿（只读）")).toHaveValue(
    "same-profile A",
  );
  await expect(second.locator(".save-status")).toHaveText("版本冲突");
  await second
    .getByRole("button", {
      name: "保留本地内容，按最新版本手动合并",
      exact: true,
    })
    .click();
  await save(second, 200, 3);
  await second.close();
});

test("C5 legacy migration and server-local divergent content choice", async ({
  request,
  browser,
}) => {
  const c = await challenge(request, "legacy");
  const key = "ctf-workbench:draft:v1:" + c.challenge_id;
  const ctx = await browser.newContext({
      baseURL: "http://127.0.0.1:5173",
      storageState: {
        cookies: [],
        origins: [
          {
            origin: "http://127.0.0.1:5173",
            localStorage: [{ name: key, value: "# legacy local synthetic" }],
          },
        ],
      },
    }),
    p = await ctx.newPage();
  await enter(p, c.name);
  await expect(
    p.getByText("发现本地未同步的人工稿，是否保存到服务器？", { exact: true }),
  ).toBeVisible();
  await expect(p.getByLabel("Markdown 人工编辑")).toHaveValue(
    "# legacy local synthetic",
  );
  await expect(
    p.getByRole("button", { name: "保存到服务器", exact: true }),
  ).toBeDisabled();
  expect(
    (
      await call(request, "get", `/challenges/${c.challenge_id}/writeup/draft`)
    ).status(),
  ).toBe(404);
  const put = p.waitForResponse((r) => r.request().method() === "PUT");
  await p.getByRole("button", { name: "确认迁移并保存", exact: true }).click();
  const response = await put;
  expect(response.status()).toBe(201);
  expect(response.request().postDataJSON().base_version).toBe(0);
  await idle(p);
  expect(await p.evaluate((k) => localStorage.getItem(k), key)).toBeNull();
  await ctx.close();
  const divergent = await browser.newContext({
      baseURL: "http://127.0.0.1:5173",
      storageState: {
        cookies: [],
        origins: [
          {
            origin: "http://127.0.0.1:5173",
            localStorage: [{ name: key, value: "# different local copy" }],
          },
        ],
      },
    }),
    q = await divergent.newPage();
  await enter(q, c.name);
  await expect(q.locator(".save-status")).toHaveText("版本冲突");
  await expect(q.getByLabel("Markdown 人工编辑")).toHaveValue(
    "# different local copy",
  );
  await expect(q.getByLabel("服务器最新稿（只读）")).toHaveValue(
    "# legacy local synthetic",
  );
  await q
    .getByRole("button", { name: "采用服务器稿（放弃本地修改）", exact: true })
    .click();
  await expect(q.getByLabel("Markdown 人工编辑")).toHaveValue(
    "# legacy local synthetic",
  );
  expect(await q.evaluate((k) => localStorage.getItem(k), key)).toBeNull();
  await divergent.close();
});

test("C5 empty and over 1MiB drafts retain content and exact server errors", async ({
  page,
  request,
}) => {
  const c = await challenge(request, "limits");
  await enter(page, c.name);
  await page.getByLabel("Markdown 人工编辑").fill(" ");
  await page.getByRole("button", { name: "保存到服务器", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("不能为空");
  const large = "界".repeat(349526);
  await page.getByLabel("Markdown 人工编辑").fill(large);
  await page.getByRole("button", { name: "保存到服务器", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("1 MiB");
  expect(await page.getByLabel("Markdown 人工编辑").inputValue()).toBe(large);
  expect(
    await page.evaluate(
      (cid) => localStorage.getItem("ctf-workbench:draft:v1:" + cid),
      c.challenge_id,
    ),
  ).toBe(large);
  expect(
    (
      await call(
        request,
        "put",
        `/challenges/${c.challenge_id}/writeup/draft`,
        { content: " ", base_version: 0 },
      )
    ).status(),
  ).toBe(422);
  expect(
    (
      await call(
        request,
        "put",
        `/challenges/${c.challenge_id}/writeup/draft`,
        { content: large, base_version: 0 },
      )
    ).status(),
  ).toBe(413);
  expect(
    (
      await call(request, "get", `/challenges/${c.challenge_id}/writeup/draft`)
    ).status(),
  ).toBe(404);
});

test("C5 no human draft and corrupted draft export generated fallback", async ({
  page,
  request,
}) => {
  test.skip(
    !process.env.CTF_TEST_DATA_DIR,
    "Requires explicitly isolated synthetic data directory",
  );
  const c = await challenge(request, "fallback");
  await enter(page, c.name);
  const generated = (
    await (
      await call(
        request,
        "get",
        `/challenges/${c.challenge_id}/writeup/preview`,
      )
    ).json()
  ).markdown;
  verify(await download(page, "no-human.zip"), generated);
  await expect(
    page.getByRole("status").filter({ hasText: "尚未保存人工稿" }),
  ).toBeVisible();
  await page.getByLabel("Markdown 人工编辑").fill("valid before corruption");
  await save(page, 201, 1);
  const data = resolve(process.env.CTF_TEST_DATA_DIR!),
    file = resolve(data, "writeups", c.challenge_id + ".json");
  expect(file.startsWith(data + sep)).toBe(true);
  const doc = JSON.parse(readFileSync(file, "utf8"));
  doc.content = "C5_TAMPERED";
  writeFileSync(file, JSON.stringify(doc));
  await page
    .getByRole("button", { name: "重新读取人工稿", exact: true })
    .click();
  await idle(page);
  await expect(page.getByRole("alert")).toContainText("读取服务器人工稿失败");
  await expect(page.getByLabel("Markdown 人工编辑")).toHaveValue(
    "valid before corruption",
  );
  verify(
    await download(page, "corrupted.zip", true),
    generated,
    undefined,
    undefined,
    true,
  );
  await expect(
    page.getByRole("status").filter({ hasText: "服务器人工稿校验异常" }),
  ).toBeVisible();
  await page.screenshot({
    path: join(out, "corruption-fallback.png"),
    fullPage: true,
  });
});

test("C5 actual backend disconnect keeps local draft and reconnect migrates", async ({
  page,
  request,
}) => {
  test.skip(
    !process.env.CTF_TEST_BACKEND_PID ||
      !process.env.CTF_TEST_BACKEND_APP_DIR ||
      !process.env.CTF_TEST_DATA_DIR,
    "Requires explicitly owned backend PID and isolated app/data paths",
  );
  const c = await challenge(request, "outage");
  await enter(page, c.name);
  await page
    .getByLabel("Markdown 人工编辑")
    .fill("# must survive actual server outage");
  process.kill(Number(process.env.CTF_TEST_BACKEND_PID));
  await expect
    .poll(async () => {
      try {
        await request.get(base + "/health", { timeout: 500 });
        return false;
      } catch {
        return true;
      }
    })
    .toBe(true);
  try {
    await page
      .getByRole("button", { name: "保存到服务器", exact: true })
      .click();
    await expect(page.getByRole("alert")).toContainText("保存失败");
    await page
      .getByRole("button", { name: "重新读取人工稿", exact: true })
      .click();
    await idle(page);
    await expect(page.getByRole("alert")).toContainText("读取服务器人工稿失败");
    await expect(page.getByLabel("Markdown 人工编辑")).toHaveValue(
      "# must survive actual server outage",
    );
    expect(
      await page.evaluate(
        (cid) => localStorage.getItem("ctf-workbench:draft:v1:" + cid),
        c.challenge_id,
      ),
    ).toBe("# must survive actual server outage");
    await page.screenshot({
      path: join(out, "backend-disconnected.png"),
      fullPage: true,
    });
  } finally {
    const fd = openSync(join(out, "backend-restarted.log"), "a");
    const child = spawn(
      process.env.CTF_TEST_PYTHON || "python",
      [
        "-B",
        "-m",
        "uvicorn",
        "app.main:app",
        "--app-dir",
        process.env.CTF_TEST_BACKEND_APP_DIR!,
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
      ],
      {
        env: {
          ...process.env,
          CTF_DATA_DIR: process.env.CTF_TEST_DATA_DIR,
          CTF_RUN_LIVE_MODEL: "0",
          PYTHONDONTWRITEBYTECODE: "1",
        },
        stdio: ["ignore", fd, fd],
        detached: true,
        windowsHide: true,
      },
    );
    child.unref();
    writeFileSync(
      join(out, "restarted-backend.json"),
      JSON.stringify({ pid: child.pid }),
    );
    await expect
      .poll(
        async () => {
          try {
            return (
              await request.get(base + "/health", { timeout: 1000 })
            ).status();
          } catch {
            return 0;
          }
        },
        { timeout: 15000 },
      )
      .toBe(200);
  }
  await page.reload();
  await idle(page);
  await page.getByRole("button", { name: "Writeup", exact: true }).click();
  await expect(page.getByLabel("Markdown 人工编辑")).toHaveValue(
    "# must survive actual server outage",
  );
  await page
    .getByRole("button", { name: "确认迁移并保存", exact: true })
    .click();
  await idle(page);
  await expect(page.locator(".save-status")).toHaveText("已保存（版本 v1）");
});
