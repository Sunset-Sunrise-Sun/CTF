import { test } from "node:test";
import assert from "node:assert/strict";
import {
  TOOL_STATUS_LABELS,
  artifactContentPath,
  flagConfirmationSummaries,
  modelCallStatusLabel,
  relevantModelCalls,
  riskLevelLabel,
  toolArgumentsJson,
  toolStatusLabel,
  toolTarget,
} from "../src/domain.ts";
import {
  aiAttachmentStateAfterSwitch,
  asyncResponseApplies,
} from "../src/ai-consent.ts";

test("every required tool status has the exact Chinese label", () => {
  assert.deepEqual(
    Object.fromEntries(
      [
        "pending",
        "approved",
        "running",
        "succeeded",
        "failed",
        "timed_out",
        "rejected",
        "cancelled",
        "expired",
      ].map((status) => [status, toolStatusLabel(status)]),
    ),
    {
      pending: "待批准",
      approved: "已批准",
      running: "运行中",
      succeeded: "成功",
      failed: "失败",
      timed_out: "已超时",
      rejected: "已拒绝",
      cancelled: "已取消",
      expired: "已过期",
    },
  );
  assert.equal(Object.keys(TOOL_STATUS_LABELS).length, 9);
});

test("unknown or missing tool status never reads as approved/success", () => {
  for (const status of [undefined, null, "", "some_new_status", "APPROVED"]) {
    const label = toolStatusLabel(status);
    assert.equal(label, "未知状态");
    assert.doesNotMatch(label, /已批准|成功/);
  }
});

test("risk labels are Chinese and unknown risk is not downgraded to low", () => {
  assert.equal(riskLevelLabel("low"), "低风险");
  assert.equal(riskLevelLabel("medium"), "中风险");
  assert.equal(riskLevelLabel("high"), "高风险");
  assert.equal(riskLevelLabel(undefined), "风险未知");
  assert.equal(riskLevelLabel("critical"), "风险未知");
});

test("tool arguments expose the declared target path", () => {
  assert.equal(toolTarget({ path: "sample.bin" }), "sample.bin");
  assert.equal(toolTarget({ relative_path: "src/a.py" }), "src/a.py");
  assert.equal(toolTarget({ pattern: "flag" }), "flag");
  assert.equal(toolTarget({}), "");
  assert.equal(toolTarget({ path: 42 }), "");
  assert.equal(
    toolArgumentsJson({ path: "a", extra: 1 }),
    JSON.stringify({ path: "a", extra: 1 }, null, 2),
  );
});

test("artifact download path is challenge-scoped and URL-encoded", () => {
  assert.equal(
    artifactContentPath("cid/1", "art id?x"),
    "/api/challenges/cid%2F1/artifacts/art%20id%3Fx/content",
  );
});

test("model calls shown for a challenge exclude other challenges", () => {
  const calls = [
    { call_id: "a", challenge_id: "challenge-a", synthetic: false },
    { call_id: "b", challenge_id: "challenge-b", synthetic: false },
    { call_id: "s", challenge_id: null, synthetic: true },
    { call_id: "legacy", challenge_id: null, synthetic: false },
  ];
  assert.deepEqual(
    relevantModelCalls(calls, "challenge-a").map((call) => call.call_id),
    ["a", "s", "legacy"],
  );
  assert.deepEqual(relevantModelCalls(calls, null), []);
  assert.equal(modelCallStatusLabel("success"), "成功");
  assert.equal(modelCallStatusLabel("failed"), "失败");
  assert.equal(modelCallStatusLabel("unknown"), "未终结（未知）");
  assert.equal(modelCallStatusLabel("weird"), "未知状态");
});

const event = (payload, occurred_at = "2026-11-09T01:02:03+00:00") => ({
  event_id: "e",
  sequence: 1,
  occurred_at,
  actor: "user",
  event_type: "flag_confirmed",
  payload,
  artifact_ids: [],
  event_hash: "f".repeat(64),
});

test("Flag summaries expose digest prefix, length and confirmer only", () => {
  const secret = "flag{PLAINTEXT_MUST_NOT_LEAK}";
  const digest = "a".repeat(64);
  const summaries = flagConfirmationSummaries([
    event({
      flag_sha256: digest,
      flag_length: secret.length,
      confirmed_by: "local-user",
      note: "n",
      // A hostile/legacy payload must never be copied into the summary.
      flag: secret,
      platform_verified: true,
    }),
  ]);
  assert.equal(summaries.length, 1);
  assert.equal(summaries[0].flag_sha256_prefix, "a".repeat(16) + "…");
  assert.equal(summaries[0].flag_length, secret.length);
  assert.equal(summaries[0].confirmed_by, "local-user");
  assert.equal(summaries[0].platform_verified, false);
  const serialized = JSON.stringify(summaries);
  assert.ok(!serialized.includes(secret));
  assert.ok(!serialized.includes(digest));
  assert.ok(!serialized.includes("platform_verified\":true"));
});

test("Flag summaries fail closed on malformed payloads", () => {
  const summaries = flagConfirmationSummaries([
    event({ flag_length: -5 }),
    event({ flag_sha256: "not-a-digest", flag_length: "12" }),
  ]);
  assert.equal(summaries[0].flag_sha256_prefix, "（摘要缺失）");
  assert.equal(summaries[0].flag_length, 0);
  assert.equal(summaries[0].confirmed_by, "未知确认人");
  assert.equal(summaries[1].flag_sha256_prefix, "（摘要缺失）");
  assert.equal(summaries[1].flag_length, 0);
  assert.ok(summaries.every((summary) => summary.platform_verified === false));
});

test("only flag_confirmed events produce summaries", () => {
  assert.deepEqual(
    flagConfirmationSummaries([
      { ...event({}), event_type: "manual_operation_recorded" },
      { ...event({ flag_sha256: "b".repeat(64), flag_length: 8 }) },
    ]).length,
    1,
  );
});

test("switching challenge clears attachment selection and attachment consent", () => {
  assert.deepEqual(aiAttachmentStateAfterSwitch(), {
    selectedEvidenceKeys: [],
    attachmentConsent: false,
  });
});

test("a stale cross-challenge or older-generation response never applies", () => {
  const current = { challengeId: "challenge-b", generation: 7 };
  // Response started before the switch (challenge A, generation 6).
  assert.equal(
    asyncResponseApplies({ challengeId: "challenge-a", generation: 6 }, current),
    false,
  );
  // Switch A -> B -> A: old A response must still be discarded.
  assert.equal(
    asyncResponseApplies({ challengeId: "challenge-a", generation: 6 }, {
      challengeId: "challenge-a",
      generation: 8,
    }),
    false,
  );
  assert.equal(
    asyncResponseApplies({ challengeId: "challenge-b", generation: 7 }, current),
    true,
  );
});
