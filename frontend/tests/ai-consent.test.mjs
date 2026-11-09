import { test } from "node:test";
import assert from "node:assert/strict";
import {
  aiConsentMatchesChallenge,
  aiConsentTarget,
  aiPanelStateAfterSwitch,
  assertAIConsentForChallenge,
} from "../src/ai-consent.ts";

test("AI consent granted on challenge A is not valid for challenge B", () => {
  const consentChallengeId = aiConsentTarget("challenge-a", true);
  assert.equal(consentChallengeId, "challenge-a");
  assert.equal(aiConsentMatchesChallenge(consentChallengeId, "challenge-a"), true);
  assert.equal(aiConsentMatchesChallenge(consentChallengeId, "challenge-b"), false);
});

test("switching challenge clears consent and the pending question", () => {
  const switched = aiPanelStateAfterSwitch();
  assert.deepEqual(switched, { consentChallengeId: null, question: "" });
  assert.equal(aiConsentMatchesChallenge(switched.consentChallengeId, "challenge-a"), false);
  assert.equal(aiConsentMatchesChallenge(switched.consentChallengeId, "challenge-b"), false);
});

test("A -> B -> A never restores the old consent", () => {
  let consentChallengeId = aiConsentTarget("challenge-a", true);
  assert.equal(aiConsentMatchesChallenge(consentChallengeId, "challenge-a"), true);
  for (const switchedTo of ["challenge-b", "challenge-a"]) {
    const switched = aiPanelStateAfterSwitch();
    consentChallengeId = switched.consentChallengeId;
    assert.equal(consentChallengeId, null);
    assert.equal(aiConsentMatchesChallenge(consentChallengeId, switchedTo), false);
  }
});

test("unchecking consent or checking without a selected challenge grants nothing", () => {
  assert.equal(aiConsentTarget("challenge-a", false), null);
  assert.equal(aiConsentTarget(undefined, true), null);
  assert.equal(aiConsentTarget(null, true), null);
});

test("request-time guard rejects missing or stale consent and accepts current consent", () => {
  assert.throws(
    () => assertAIConsentForChallenge(null, "challenge-b"),
    /not valid for the current challenge/,
  );
  assert.throws(
    () => assertAIConsentForChallenge("challenge-a", "challenge-b"),
    /not valid for the current challenge/,
  );
  assert.doesNotThrow(() => assertAIConsentForChallenge("challenge-b", "challenge-b"));
});
