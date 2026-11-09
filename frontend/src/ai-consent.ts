/** Challenge-bound AI data-sharing consent.
 *
 * The user confirms sending the *current* challenge's context to the model.
 * That confirmation is valid only for the challenge that was selected when it
 * was given. Switching challenges must clear both the confirmation and the
 * pending question, and the request path must re-check the binding immediately
 * before sending.
 */

export type AIPanelStateAfterSwitch = {
  consentChallengeId: null;
  question: "";
};

/** State to apply when the user switches to another challenge. */
export function aiPanelStateAfterSwitch(): AIPanelStateAfterSwitch {
  return { consentChallengeId: null, question: "" };
}

/** Challenge ID to bind when the consent checkbox changes. */
export function aiConsentTarget(
  currentChallengeId: string | null | undefined,
  checked: boolean,
): string | null {
  return checked ? (currentChallengeId ?? null) : null;
}

/** Whether a saved confirmation belongs to the currently selected challenge. */
export function aiConsentMatchesChallenge(
  consentChallengeId: string | null | undefined,
  currentChallengeId: string | null | undefined,
): boolean {
  return (
    typeof consentChallengeId === "string" &&
    consentChallengeId.length > 0 &&
    typeof currentChallengeId === "string" &&
    consentChallengeId === currentChallengeId
  );
}

/** Request-time guard: throw when consent is absent or belongs to another challenge. */
export function assertAIConsentForChallenge(
  consentChallengeId: string | null | undefined,
  currentChallengeId: string | null | undefined,
): void {
  if (!aiConsentMatchesChallenge(consentChallengeId, currentChallengeId)) {
    throw new Error(
      "AI data-sharing consent is not valid for the current challenge",
    );
  }
}

export type AIAttachmentSelectionAfterSwitch = {
  selectedEvidenceKeys: string[];
  attachmentConsent: false;
};

/** Attachment scope is per request and belongs to the old challenge only. */
export function aiAttachmentStateAfterSwitch(): AIAttachmentSelectionAfterSwitch {
  return { selectedEvidenceKeys: [], attachmentConsent: false };
}

export type AIRequestIdentity = {
  challengeId: string | null | undefined;
  generation: number;
};

/**
 * Whether an async AI response may still update the panel. A response from an
 * older selection generation, or from another challenge, must be discarded so
 * it can never overwrite the newly selected challenge.
 */
export function asyncResponseApplies(
  request: AIRequestIdentity,
  current: AIRequestIdentity,
): boolean {
  return (
    request.generation === current.generation &&
    request.challengeId === current.challengeId
  );
}
