import { test } from "node:test";
import assert from "node:assert/strict";
import { DraftSession, draftBytes, MAX_DRAFT_BYTES } from "../src/drafts.ts";
const failure = (status, detail) =>
  Object.assign(new Error(String(status)), { status, detail });
const record = (version, content = "server") => ({
  challenge_id: "synthetic",
  version,
  content,
  size: draftBytes(content),
  sha256: "synthetic-unit-metadata",
  saved_at: "2026-11-08T00:00:00+00:00",
  is_human_draft: true,
});
function setup({ server = null, local = null, base = null } = {}) {
  const writes = [];
  const cache = { local, base };
  const io = {
    read: async () => {
      if (!server) throw failure(404);
      return server;
    },
    write: async (body) => {
      writes.push(body);
      return record(body.base_version + 1, body.content);
    },
    getLocal: () => cache.local,
    setLocal: (v) => (cache.local = v),
    clearLocal: () => (cache.local = null),
    getBase: () => cache.base,
    setBase: (v) => (cache.base = v),
  };
  return { s: new DraftSession(io), io, cache, writes };
}
test("404 is absence and does not issue a write", async () => {
  const { s, writes } = setup();
  await s.load();
  assert.equal(s.baseVersion, 0);
  assert.equal(s.content, "");
  assert.equal(s.migration, false);
  assert.deepEqual(writes, []);
});
test("legacy local draft requires explicit migration", async () => {
  const { s, cache, writes } = setup({ local: "legacy" });
  await s.load();
  assert.equal(s.migration, true);
  assert.equal(s.content, "legacy");
  assert.equal(cache.local, "legacy");
  assert.deepEqual(writes, []);
  await s.save();
  assert.equal(writes[0].base_version, 0);
});
test("server restores with version and timestamp", async () => {
  const { s } = setup({ server: record(3) });
  await s.load();
  assert.equal(s.content, "server");
  assert.equal(s.server.version, 3);
  assert.equal(s.state, "saved");
});
test("different server and local content requires choice", async () => {
  const { s, writes, cache } = setup({
    server: record(2),
    local: "local",
    base: 1,
  });
  await s.load();
  assert.equal(s.content, "local");
  assert.equal(s.state, "conflict");
  assert.equal(s.current.version, 2);
  await s.save();
  assert.deepEqual(writes, []);
  assert.equal(cache.local, "local");
});
test("identical cache and server preserves cache until explicit action", async () => {
  const { s, cache } = setup({ server: record(2), local: "server" });
  await s.load();
  assert.equal(s.state, "saved");
  assert.equal(cache.local, "server");
});
test("successful create clears local only after acknowledgement", async () => {
  const { s, cache, writes } = setup();
  await s.load();
  s.edit("human");
  await s.save();
  assert.deepEqual(writes, [{ content: "human", base_version: 0 }]);
  assert.equal(s.server.version, 1);
  assert.equal(cache.local, null);
  assert.equal(cache.base, 1);
});
test("updates use loaded server version", async () => {
  const { s, writes } = setup({ server: record(4) });
  await s.load();
  s.edit("changed");
  await s.save();
  assert.equal(writes[0].base_version, 4);
  assert.equal(s.baseVersion, 5);
});
test("409 retains editor and never automatically retries", async () => {
  const { s, io, cache } = setup({ server: record(1) });
  await s.load();
  let calls = 0;
  io.write = async () => {
    calls++;
    throw failure(409, { current: record(2, "latest") });
  };
  s.edit("mine");
  await s.save();
  await s.save();
  assert.equal(calls, 1);
  assert.equal(s.content, "mine");
  assert.equal(cache.local, "mine");
  assert.equal(s.current.content, "latest");
});
test("explicit keep-local rebases but does not submit", async () => {
  const { s, writes } = setup({ server: record(2), local: "mine", base: 1 });
  await s.load();
  s.keepLocalOnLatest();
  assert.deepEqual(writes, []);
  assert.equal(s.content, "mine");
  assert.equal(s.baseVersion, 2);
  await s.save();
  assert.equal(writes[0].base_version, 2);
});
test("explicit server choice does not write", async () => {
  const { s, cache, writes } = setup({ server: record(2), local: "mine" });
  await s.load();
  s.useServer();
  assert.equal(s.content, "server");
  assert.equal(cache.local, null);
  assert.equal(s.state, "saved");
  assert.deepEqual(writes, []);
});
test("read outage preserves local and prevents base-zero overwrite", async () => {
  const { s, io, cache } = setup({ local: "irreplaceable" });
  io.read = async () => {
    throw new Error("disconnected");
  };
  await s.load();
  assert.equal(s.content, "irreplaceable");
  assert.equal(cache.local, "irreplaceable");
  assert.equal(s.baseVersion, null);
  assert.equal(s.canSave, false);
});
test("save outage preserves cache and error state", async () => {
  const { s, io, cache } = setup();
  await s.load();
  s.edit("irreplaceable");
  io.write = async () => {
    throw Error("offline");
  };
  await s.save();
  assert.equal(s.state, "error");
  assert.equal(s.content, "irreplaceable");
  assert.equal(cache.local, "irreplaceable");
});
test("integrity 409 without current is not treated as mergeable conflict", async () => {
  const { s, io } = setup({ local: "mine" });
  io.read = async () => {
    throw failure(409, "corrupted sidecar");
  };
  await s.load();
  assert.equal(s.state, "error");
  assert.equal(s.hasConflict, false);
  assert.equal(s.content, "mine");
  assert.equal(s.canSave, false);
});
for (const status of [413, 422])
  test(`HTTP ${status} save keeps user content`, async () => {
    const { s, io, cache } = setup();
    await s.load();
    s.edit("mine");
    io.write = async () => {
      throw failure(status, "invalid");
    };
    await s.save();
    assert.equal(s.state, "error");
    assert.equal(cache.local, "mine");
  });
test("empty draft never gets a write", async () => {
  const { s, writes } = setup();
  await s.load();
  s.edit("  \n");
  await s.save();
  assert.equal(s.state, "error");
  assert.equal(writes.length, 0);
});
test("UTF-8 exact 1MiB boundary is accepted", async () => {
  const { s, writes } = setup();
  await s.load();
  const content = "A".repeat(MAX_DRAFT_BYTES - 3) + "界";
  assert.equal(draftBytes(content), MAX_DRAFT_BYTES);
  s.edit(content);
  await s.save();
  assert.equal(writes.length, 1);
});
test("UTF-8 over boundary is refused without truncation", async () => {
  const { s, writes, cache } = setup();
  await s.load();
  const content = "界".repeat(349526);
  s.edit(content);
  await s.save();
  assert.equal(s.state, "error");
  assert.equal(writes.length, 0);
  assert.equal(cache.local, content);
});
test("typing during save survives response and uses new base", async () => {
  const { s, io, cache } = setup();
  await s.load();
  let finish;
  io.write = () => new Promise((r) => (finish = r));
  s.edit("snapshot");
  const pending = s.save();
  s.edit("new typing");
  finish(record(1, "snapshot"));
  await pending;
  assert.equal(s.content, "new typing");
  assert.equal(cache.local, "new typing");
  assert.equal(s.state, "unsaved");
  assert.equal(s.baseVersion, 1);
});
test("parallel save clicks do not duplicate requests", async () => {
  const { s, io } = setup();
  await s.load();
  let finish,
    calls = 0;
  io.write = () => {
    calls++;
    return new Promise((r) => (finish = r));
  };
  s.edit("snapshot");
  const pending = s.save();
  await s.save();
  assert.equal(calls, 1);
  finish(record(1, "snapshot"));
  await pending;
});
test("generated preview never replaces local or saved human draft", async () => {
  const { s } = setup({ server: record(1, "human") });
  await s.load();
  assert.equal(s.useGenerated("generated"), false);
  assert.equal(s.content, "human");
  s.edit("local");
  assert.equal(s.useGenerated("generated"), false);
  assert.equal(s.content, "local");
});
test("current null conflict requires explicit choice and version zero", async () => {
  const { s, io } = setup({ server: record(1) });
  await s.load();
  s.edit("mine");
  io.write = async () => {
    throw failure(409, { current: null });
  };
  await s.save();
  assert.equal(s.hasConflict, true);
  s.keepLocalOnLatest();
  assert.equal(s.baseVersion, 0);
  assert.equal(s.content, "mine");
});
test("storage quota failure warns without losing in-memory text", async () => {
  const { s, io } = setup();
  await s.load();
  io.setLocal = () => {
    throw Error("quota");
  };
  io.write = async () => {
    throw Error("offline");
  };
  s.edit("mine");
  await s.save();
  assert.equal(s.content, "mine");
  assert.match(s.storageWarning, /存储失败/);
});
test("sessions are independent per challenge", async () => {
  const a = setup(),
    b = setup();
  await a.s.load();
  await b.s.load();
  a.s.edit("challenge A");
  assert.equal(b.s.content, "");
  assert.equal(b.cache.local, null);
});

import { createDraftCache } from "../src/drafts.ts";
function storage() {
  const map = new Map();
  return {
    getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => map.set(k, v),
    removeItem: (k) => map.delete(k),
  };
}
test("same-profile windows preserve unsaved text through another window save", async () => {
  const shared = storage(),
    a = createDraftCache("legacy", shared, storage()),
    b = createDraftCache("legacy", shared, storage());
  a.setLocal("A");
  a.setBase(1);
  b.setLocal("B");
  b.setBase(1);
  a.setLocal("A");
  a.clearLocal();
  a.setBase(2);
  assert.equal(b.getLocal(), "B");
  assert.equal(b.getBase(), 1);
});
test("cache can still recover historical localStorage-only text", () => {
  const shared = storage();
  shared.setItem("legacy", "original");
  const cache = createDraftCache("legacy", shared, storage());
  assert.equal(cache.getLocal(), "original");
  cache.setLocal("migrating");
  cache.clearLocal();
  assert.equal(shared.getItem("legacy"), null);
});
