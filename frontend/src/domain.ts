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
}
export interface Preview {
  markdown: string;
  completeness: string;
  missing_requirements: string[];
  warnings: string[];
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
export function completeness(p?: Preview, edited = false) {
  return !p
    ? "未校验 · 不完整"
    : edited
      ? "人工编辑 · 待复核"
      : p.completeness === "complete" && !p.missing_requirements.length
        ? "后端标记完整 · 仍需人工复核"
        : "不完整 · 存在缺失证据";
}
