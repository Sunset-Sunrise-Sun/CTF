import { test } from "node:test";
import assert from "node:assert/strict";
import { eventLabel, completeness, filePath, draftKey } from "../src/domain.ts";
import { request, limitedBlob, ApiError } from "../src/api.ts";
test("manual claims never become verified execution", () =>
  assert.match(
    eventLabel({ actor: "user", event_type: "manual_operation_recorded" }),
    /人工申报.*未验证/,
  ));
test("agent text cannot masquerade as human execution", () =>
  assert.match(
    eventLabel({ actor: "agent", event_type: "manual_operation_recorded" }),
    /^ai_suggestion/,
  ));
test("proposal is never an execution", () =>
  assert.match(
    eventLabel({ actor: "user", event_type: "tool_proposed" }),
    /未执行/,
  ));
test("missing or contradictory completeness fails closed", () => {
  assert.match(completeness(), /不完整/);
  assert.match(
    completeness({ completeness: "complete", missing_requirements: ["flag"] }),
    /不完整/,
  );
});
test("edited report is always subject to review", () =>
  assert.match(
    completeness({ completeness: "complete", missing_requirements: [] }, true),
    /待复核/,
  ));
test("drafts are isolated by challenge", () =>
  assert.notEqual(draftKey("a"), draftKey("b")));
test("file path segments encode URLs without query injection", () =>
  assert.equal(
    filePath("src/中文 #?.py"),
    "src/%E4%B8%AD%E6%96%87%20%23%3F.py",
  ));
test("API reports validation detail and preserves HTTP status", async () => {
  const old = global.fetch;
  global.fetch = async () =>
    new Response(JSON.stringify({ detail: [{ msg: "invalid" }] }), {
      status: 422,
    });
  try {
    await assert.rejects(
      request("/x"),
      (e) =>
        e instanceof ApiError &&
        e.status === 422 &&
        e.message.includes("invalid"),
    );
  } finally {
    global.fetch = old;
  }
});
test("declared oversized preview is cancelled", async () => {
  const old = global.fetch;
  let cancelled = false;
  global.fetch = async () =>
    new Response(
      new ReadableStream({
        cancel() {
          cancelled = true;
        },
      }),
      { headers: { "content-length": "1048577" } },
    );
  try {
    await assert.rejects(limitedBlob("/x"), /1 MiB/);
    assert.equal(cancelled, true);
  } finally {
    global.fetch = old;
  }
});
test("chunked preview cannot bypass byte cap", async () => {
  const old = global.fetch;
  global.fetch = async () => new Response(new Uint8Array(1048577));
  try {
    await assert.rejects(limitedBlob("/x"), /1 MiB/);
  } finally {
    global.fetch = old;
  }
});
