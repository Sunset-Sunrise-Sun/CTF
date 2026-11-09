export interface Challenge {
  challenge_id: string;
  name: string;
  category: string;
  description: string;
  score?: number | null;
  ai_usage_level?: string;
  solve_status: string;
}
export interface Project {
  project_id: string;
  project_name: string;
  competition_name: string;
  competition_type: string;
  ai_policy_summary: string;
  rules_filename?: string;
  rules_sha256?: string;
  rules_size?: number;
}
export interface AuditEvent {
  event_id: string;
  sequence: number;
  occurred_at: string;
  actor: string;
  event_type: string;
  payload: Record<string, unknown>;
  artifact_ids: string[];
  event_hash: string;
}
export interface Artifact {
  artifact_id: string;
  original_filename: string;
  sha256: string;
  size: number;
  media_type: string;
  ingested_at: string;
  evidence_kind?: string;
  source_event_id: string;
  capture_time_claim?: string;
}
export interface ImportFile {
  relative_path: string;
  size: number;
  sha256: string;
  media_type: string;
}
export interface ImportRecord {
  import_id: string;
  original_filename: string;
  extracted_file_count: number;
  total_uncompressed_size: number;
  files?: ImportFile[];
  warnings: string[];
  manifest_verified?: boolean;
  integrity_error?: string | null;
}
export interface WriteupRequirement {
  code: string;
  label: string;
  status: "proven" | "missing" | "not_applicable";
  reason: string;
  evidence: string[];
  remediation: string | null;
}
export interface Preview {
  markdown: string;
  completeness: string;
  missing_requirements: string[];
  requirements?: WriteupRequirement[];
  not_applicable_requirements?: string[];
  warnings: string[];
}
export function exportState(p: Preview, header: string | null): Preview {
  return header === "complete"
    ? p
    : {
        ...p,
        completeness: "incomplete",
        missing_requirements: [
          ...p.missing_requirements,
          "export_snapshot_incomplete",
        ],
      };
}
export const categories = ["Crypto", "Web", "Pwn", "Reverse", "Misc"];
export const evidenceKinds = [
  "challenge_archive",
  "analysis",
  "execution",
  "execution_output",
  "flag_capture",
  "platform_verification",
  "source_code",
  "other",
];
export function eventLabel(e: AuditEvent): string {
  if (
    e.actor === "agent" ||
    ["agent_message", "plan", "hypothesis", "tool_proposed"].includes(
      e.event_type,
    )
  )
    return "ai_suggestion · 建议 / 未执行";
  if (e.event_type === "manual_operation_recorded")
    return "human_action · 人工申报 / 未验证执行";
  if (/^(tool|command)_(started|finished)$/.test(e.event_type))
    return "tool_execution · 历史记录（本轮未启用）";
  if (e.event_type === "verification")
    return "verified_result · 验证申报（非独立认证）";
  return "observation · 记录 / 观察";
}
export function sizeLabel(n: number) {
  return n < 1024
    ? `${n} B`
    : n < 1048576
      ? `${(n / 1024).toFixed(1)} KiB`
      : `${(n / 1048576).toFixed(1)} MiB`;
}
export function filePath(s: string) {
  return s.split("/").map(encodeURIComponent).join("/");
}
export function draftKey(cid: string) {
  return `ctf-workbench:draft:v1:${cid}`;
}
export type ToolStatus =
  | "pending"
  | "approved"
  | "running"
  | "succeeded"
  | "failed"
  | "timed_out"
  | "rejected"
  | "cancelled"
  | "expired";

/** A tool proposal row plus its approval/execution trace (fixed read-only tools). */
export interface ToolProposal {
  proposal_id: string;
  challenge_id: string;
  model_call_id?: string | null;
  tool_name: string;
  arguments: Record<string, unknown>;
  reason: string;
  risk_level?: string | null;
  status: string;
  proposed_by?: string | null;
  proposed_at?: string | null;
  expires_at?: string | null;
  approval_id?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
  decision_note?: string | null;
  execution_id?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  decision_event_id?: string | null;
  started_event_id?: string | null;
  finished_event_id?: string | null;
  artifact_ids?: string[];
  output_artifact_id?: string | null;
  output_sha256?: string | null;
  output_size?: number | null;
  output_summary?: string | null;
  error?: string | null;
}

/** Exact Chinese status mapping required by the P0 contract. */
export const TOOL_STATUS_LABELS: Readonly<Record<ToolStatus, string>> =
  Object.freeze({
    pending: "待批准",
    approved: "已批准",
    running: "运行中",
    succeeded: "成功",
    failed: "失败",
    timed_out: "已超时",
    rejected: "已拒绝",
    cancelled: "已取消",
    expired: "已过期",
  });

const TOOL_STATUS_UNKNOWN = "未知状态";

/** Chinese label for a tool proposal status; unknown values never look approved. */
export function toolStatusLabel(status: string | null | undefined): string {
  if (!status) return TOOL_STATUS_UNKNOWN;
  return TOOL_STATUS_LABELS[status as ToolStatus] ?? TOOL_STATUS_UNKNOWN;
}

const RISK_LEVEL_LABELS: Readonly<Record<string, string>> = Object.freeze({
  low: "低风险",
  medium: "中风险",
  high: "高风险",
});

export function riskLevelLabel(risk: string | null | undefined): string {
  return RISK_LEVEL_LABELS[risk ?? ""] ?? "风险未知";
}

/** The declared target path/pattern of a fixed read-only tool, if any. */
export function toolTarget(argumentsValue: Record<string, unknown>): string {
  for (const key of ["path", "relative_path", "pattern"]) {
    const value = argumentsValue?.[key];
    if (typeof value === "string" && value) return value;
  }
  return "";
}

export function toolArgumentsJson(argumentsValue: Record<string, unknown>): string {
  try {
    return JSON.stringify(argumentsValue ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

export interface ModelCallRecord {
  call_id: string;
  challenge_id: string | null;
  provider_id: string;
  model_id: string;
  purpose: string;
  synthetic: boolean;
  data_scope: string;
  requested_at: string;
  completed_at?: string | null;
  response_status: string;
  error_category?: string | null;
  usage?: Record<string, number> | null;
}

export const MODEL_CALL_STATUS_LABELS: Readonly<Record<string, string>> =
  Object.freeze({
    success: "成功",
    failed: "失败",
    error: "错误",
    unknown: "未终结（未知）",
  });

export function modelCallStatusLabel(status: string | null | undefined): string {
  if (!status) return "未知状态";
  return MODEL_CALL_STATUS_LABELS[status] ?? "未知状态";
}

/**
 * Model calls relevant to the current challenge: its own chat calls plus
 * challenge-free synthetic connectivity calls. Calls of other challenges are
 * never shown on this challenge.
 */
export function relevantModelCalls<
  T extends { challenge_id: string | null; synthetic?: boolean },
>(calls: T[], challengeId: string | null | undefined): T[] {
  if (!challengeId) return [];
  return calls.filter(
    (call) =>
      call.synthetic === true ||
      call.challenge_id === null ||
      call.challenge_id === challengeId,
  );
}

export interface FlagConfirmationSummary {
  flag_sha256_prefix: string;
  flag_length: number;
  confirmed_by: string;
  occurred_at: string;
  platform_verified: false;
}

/**
 * Summaries of human Flag confirmations. Only digest prefix, length, confirmer
 * and time are exposed; the plaintext Flag (if a legacy payload accidentally
 * carries one) is never copied, and platform verification is always false.
 */
export function flagConfirmationSummaries(
  events: AuditEvent[],
): FlagConfirmationSummary[] {
  return events
    .filter((event) => event.event_type === "flag_confirmed")
    .map((event) => {
      const payload = (event.payload ?? {}) as Record<string, unknown>;
      const digest =
        typeof payload.flag_sha256 === "string" ? payload.flag_sha256 : "";
      const length =
        typeof payload.flag_length === "number" &&
        Number.isFinite(payload.flag_length)
          ? payload.flag_length
          : 0;
      return {
        flag_sha256_prefix: /^[0-9a-f]{64}$/i.test(digest)
          ? digest.slice(0, 16) + "…"
          : "（摘要缺失）",
        flag_length: Math.max(0, Math.trunc(length)),
        confirmed_by:
          typeof payload.confirmed_by === "string" && payload.confirmed_by
            ? payload.confirmed_by
            : "未知确认人",
        occurred_at: event.occurred_at,
        platform_verified: false as const,
      };
    });
}

export function artifactContentPath(
  challengeId: string,
  artifactId: string,
): string {
  return (
    "/api/challenges/" +
    encodeURIComponent(challengeId) +
    "/artifacts/" +
    encodeURIComponent(artifactId) +
    "/content"
  );
}

export function completeness(p?: Preview, edited = false) {
  return !p
    ? "未校验 · 不完整"
    : edited
      ? "人工编辑 · 待复核"
      : p.completeness === "complete" && !p.missing_requirements.length
        ? "后端标记完整 · 仍需人工复核"
        : "不完整 · 存在缺失证据";
}
