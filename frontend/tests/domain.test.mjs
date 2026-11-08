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

import { loadImportDetails } from "../src/api.ts";
test("unverified manifest never fetches details or exposes stale files", async () => {
  const rows = await loadImportDetails(
    [
      {
        import_id: "bad",
        manifest_verified: false,
        integrity_error: "binding failed",
        files: [{ relative_path: "stale" }],
      },
    ],
    async () => {
      throw Error("must not fetch");
    },
  );
  assert.deepEqual(rows[0].files, []);
  assert.equal(rows[0].integrity_error, "binding failed");
});
test("one 409 preserves other verified imports", async () => {
  const rows = await loadImportDetails(
    [
      { import_id: "bad", manifest_verified: true },
      { import_id: "good", manifest_verified: true },
    ],
    async (id) => {
      if (id === "bad") throw new ApiError(409, "integrity");
      return {
        import_id: id,
        manifest_verified: true,
        files: [{ relative_path: "valid" }],
      };
    },
  );
  assert.equal(rows[0].manifest_verified, false);
  assert.match(rows[0].integrity_error, /409/);
  assert.equal(rows[1].files[0].relative_path, "valid");
});
test("unknown or downgraded verification never exposes files", async () => {
  const rows = await loadImportDetails(
    [{ import_id: "old" }, { import_id: "changed", manifest_verified: true }],
    async (id) => ({ import_id: id, files: [{}], manifest_verified: false }),
  );
  assert.ok(
    rows.every((r) => r.manifest_verified === false && r.files.length === 0),
  );
});

import { exportState } from "../src/domain.ts";
test("actual incomplete export overrides complete preview", () => {
  const p = exportState(
    { completeness: "complete", missing_requirements: [] },
    "incomplete",
  );
  assert.match(completeness(p), /不完整/);
  assert.ok(p.missing_requirements.includes("export_snapshot_incomplete"));
});
test("missing export header fails closed; complete header cannot remove missing requirements", () => {
  assert.match(
    completeness(
      exportState({ completeness: "complete", missing_requirements: [] }, null),
    ),
    /不完整/,
  );
  assert.match(
    completeness(
      exportState(
        { completeness: "incomplete", missing_requirements: ["code"] },
        "complete",
      ),
    ),
    /不完整/,
  );
});
