<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { request } from "../../api";
import {
  artifactContentPath,
  riskLevelLabel,
  sizeLabel,
  toolArgumentsJson,
  toolStatusLabel,
  toolTarget,
} from "../../domain";
import type { ToolProposal } from "../../domain";

const props = defineProps<{
  challengeId: string | null;
  /** AI usage level of the selected challenge; only A2 may propose/approve/execute. */
  aiUsageLevel?: string;
  /** Changes whenever the parent reloaded events, so the list stays in sync. */
  refreshToken?: number;
}>();
const emit = defineEmits<{ changed: [] }>();

const proposals = ref<ToolProposal[]>([]);
const busy = ref("");
const error = ref("");
const loaded = ref(false);
let loadGeneration = 0;

const allowed = computed(() => props.aiUsageLevel === "A2");
const actionsDisabled = computed(() => !allowed.value || !!busy.value);

function message(errorValue: unknown): string {
  return errorValue instanceof Error ? errorValue.message : String(errorValue);
}

async function load() {
  const cid = props.challengeId;
  const generation = ++loadGeneration;
  if (!cid) {
    proposals.value = [];
    loaded.value = false;
    error.value = "";
    return;
  }
  try {
    const rows = await request<ToolProposal[]>(
      "/challenges/" + encodeURIComponent(cid) + "/tool-proposals",
    );
    // A response for a previous challenge/selection must never populate the
    // list of the newly selected challenge.
    if (generation !== loadGeneration || props.challengeId !== cid) return;
    proposals.value = Array.isArray(rows) ? rows : [];
    loaded.value = true;
    error.value = "";
  } catch (loadError) {
    if (generation !== loadGeneration || props.challengeId !== cid) return;
    proposals.value = [];
    loaded.value = true;
    error.value = "读取工具申请失败：" + message(loadError);
  }
}

async function act(
  proposalId: string,
  action: "approve" | "reject" | "cancel" | "execute",
) {
  const cid = props.challengeId;
  if (!cid || busy.value || !allowed.value) return;
  busy.value = proposalId + ":" + action;
  error.value = "";
  try {
    const path =
      "/challenges/" +
      encodeURIComponent(cid) +
      "/tool-proposals/" +
      encodeURIComponent(proposalId) +
      "/" +
      action;
    // Execution may take up to the runner timeout, so allow a longer wait.
    // Approve/reject/cancel never execute anything by themselves.
    const updated = await request<ToolProposal>(
      path,
      action === "execute" ? undefined : { approving_user: "local-user" },
      "POST",
      "/api",
      action === "execute" ? 60000 : 30000,
    );
    if (props.challengeId !== cid) return;
    if (updated && updated.proposal_id) {
      proposals.value = proposals.value.map((proposal) =>
        proposal.proposal_id === updated.proposal_id ? updated : proposal,
      );
    }
    emit("changed");
  } catch (actionError) {
    if (props.challengeId === cid) {
      error.value =
        (action === "approve"
          ? "批准失败："
          : action === "execute"
            ? "执行失败："
            : action === "reject"
              ? "拒绝失败："
              : "取消失败：") + message(actionError);
    }
  } finally {
    if (props.challengeId === cid) busy.value = "";
  }
}

function artifactId(proposal: ToolProposal): string {
  if (proposal.output_artifact_id) return proposal.output_artifact_id;
  return proposal.artifact_ids?.[0] ?? "";
}

watch(
  () => props.challengeId,
  (cid, previous) => {
    if (cid !== previous) {
      // Switching challenges clears the previous challenge's list immediately.
      proposals.value = [];
      busy.value = "";
      error.value = "";
      loaded.value = false;
      loadGeneration += 1;
    }
    void load();
  },
  { immediate: true },
);
watch(
  () => props.refreshToken,
  () => void load(),
);
</script>

<template>
  <section class="tool-approval">
    <h4>本地工具审批（只读）</h4>
    <p class="muted">
      AI 只能提出申请。候选工具固定为只读工具，不经过 Shell、不访问网络、不写文件。
      批准与执行是<strong>两个独立的人工步骤</strong>：批准不会执行任何工具，需要再单独点击“执行”。
    </p>
    <p v-if="!allowed" class="warning" role="status">
      当前题目 AI 等级为 {{ aiUsageLevel || "unknown" }}，仅 A2 允许工具申请、批准与执行。
    </p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="!loaded" class="muted">正在读取工具申请…</p>
    <p v-else-if="!proposals.length" class="muted">暂无工具申请。</p>
    <article
      v-for="proposal in proposals"
      :key="proposal.proposal_id"
      class="tool-proposal"
      :data-status="proposal.status"
    >
      <header>
        <strong class="tool-name">{{ proposal.tool_name }}</strong>
        <span class="tool-status">
          <span class="status-label">{{ toolStatusLabel(proposal.status) }}</span>
          · {{ riskLevelLabel(proposal.risk_level) }}
        </span>
      </header>
      <p class="tool-reason">{{ proposal.reason }}</p>
      <p v-if="toolTarget(proposal.arguments)" class="tool-target">
        目标：<code>{{ toolTarget(proposal.arguments) }}</code>
      </p>
      <pre class="tool-arguments">{{ toolArgumentsJson(proposal.arguments) }}</pre>
      <dl class="tool-trace">
        <dt>申请时间</dt>
        <dd>{{ proposal.proposed_at || "未知" }}<span v-if="proposal.expires_at">（过期 {{ proposal.expires_at }}）</span></dd>
        <dt>提出者</dt>
        <dd>{{ proposal.proposed_by === "user" ? "用户" : "AI" }}<span v-if="proposal.model_call_id"> · 模型调用 {{ proposal.model_call_id }}</span></dd>
        <dt v-if="proposal.approval_id">批准 ID</dt>
        <dd v-if="proposal.approval_id">
          {{ proposal.approval_id }}
          <span v-if="proposal.approved_by"> · {{ proposal.approved_by }}</span>
          <span v-if="proposal.approved_at"> · {{ proposal.approved_at }}</span>
        </dd>
        <dt v-if="proposal.execution_id">执行 ID</dt>
        <dd v-if="proposal.execution_id">
          {{ proposal.execution_id }}
          <span v-if="proposal.started_at"> · 开始 {{ proposal.started_at }}</span>
          <span v-if="proposal.finished_at"> · 结束 {{ proposal.finished_at }}</span>
        </dd>
      </dl>

      <section
        v-if="['succeeded', 'failed', 'timed_out'].includes(proposal.status)"
        class="tool-result"
      >
        <h5>执行结果：{{ toolStatusLabel(proposal.status) }}</h5>
        <p v-if="proposal.error" class="error">{{ proposal.error }}</p>
        <pre v-if="proposal.output_summary">{{ proposal.output_summary }}</pre>
        <p v-if="proposal.output_sha256" class="tool-hash">
          输出 SHA-256：<code>{{ proposal.output_sha256 }}</code>
        </p>
        <p v-if="typeof proposal.output_size === 'number'">
          输出大小：{{ sizeLabel(proposal.output_size) }}
        </p>
        <p v-if="proposal.output_artifact_id">
          Artifact ID：<code>{{ proposal.output_artifact_id }}</code>
        </p>
        <a
          v-if="challengeId && artifactId(proposal)"
          :href="artifactContentPath(challengeId, artifactId(proposal))"
          download
        >
          下载工具输出 Artifact
        </a>
      </section>

      <div v-if="proposal.status === 'pending'" class="approval-actions">
        <button
          class="primary"
          type="button"
          :disabled="actionsDisabled"
          @click="act(proposal.proposal_id, 'approve')"
        >
          批准
        </button>
        <button
          type="button"
          :disabled="actionsDisabled"
          @click="act(proposal.proposal_id, 'reject')"
        >
          拒绝
        </button>
        <button
          type="button"
          :disabled="actionsDisabled"
          @click="act(proposal.proposal_id, 'cancel')"
        >
          取消
        </button>
        <small class="muted">批准后仍需单独点击“执行”；工具不会因批准而运行。</small>
      </div>
      <div v-else-if="proposal.status === 'approved'" class="approval-actions">
        <button
          class="primary"
          type="button"
          :disabled="actionsDisabled"
          @click="act(proposal.proposal_id, 'execute')"
        >
          执行
        </button>
        <button
          type="button"
          :disabled="actionsDisabled"
          @click="act(proposal.proposal_id, 'cancel')"
        >
          取消
        </button>
        <small class="muted">已批准，等待人工点击“执行”。</small>
      </div>
      <p v-else-if="proposal.status === 'running'" class="muted" role="status">
        工具执行中，请稍候刷新。
      </p>
    </article>
  </section>
</template>

<style scoped>
.tool-approval {
  margin-top: 24px;
  padding-top: 18px;
  border-top: 1px solid #dce5ec;
  min-width: 0;
}
.tool-proposal {
  border: 1px solid #dce5ec;
  border-radius: 8px;
  margin: 12px 0;
  padding: 14px;
  background: #fbfcfd;
  min-width: 0;
  overflow-wrap: anywhere;
}
.tool-proposal header {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
}
.tool-name {
  overflow-wrap: anywhere;
}
.tool-status {
  font-size: 12px;
  color: #4c6076;
  white-space: normal;
}
.status-label {
  font-weight: 600;
  color: #1c5c50;
}
.tool-proposal[data-status="rejected"] .status-label,
.tool-proposal[data-status="failed"] .status-label {
  color: #a63c39;
}
.tool-proposal[data-status="timed_out"] .status-label,
.tool-proposal[data-status="expired"] .status-label,
.tool-proposal[data-status="cancelled"] .status-label {
  color: #926424;
}
.tool-proposal[data-status="succeeded"] .status-label {
  color: #217459;
}
.tool-reason {
  line-height: 1.7;
  margin: 10px 0 6px;
  overflow-wrap: anywhere;
}
.tool-target {
  font-size: 12px;
  margin: 6px 0;
  overflow-wrap: anywhere;
}
.tool-arguments {
  max-height: 200px;
  overflow: auto;
  background: #f3f6f9;
  padding: 10px;
  border-radius: 6px;
  margin: 8px 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.tool-trace {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 4px 12px;
  font-size: 12px;
  margin: 8px 0;
  overflow-wrap: anywhere;
}
.tool-trace dt {
  color: #687a8d;
}
.tool-trace dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.tool-result {
  background: #f3f7f6;
  border: 1px solid #d5e3df;
  border-radius: 6px;
  padding: 12px;
  margin: 10px 0;
  overflow-wrap: anywhere;
}
.tool-result h5 {
  margin: 0 0 8px;
  font-size: 13px;
}
.tool-result pre {
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.tool-hash code {
  overflow-wrap: anywhere;
}
.approval-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
}
.approval-actions small {
  flex-basis: 100%;
}
@media (max-width: 650px) {
  .tool-trace {
    display: block;
  }
  .tool-trace dd {
    margin: 0 0 6px;
  }
}
</style>
