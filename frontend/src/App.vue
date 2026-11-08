<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import {
  request,
  upload,
  limitedBlob,
  saveBlob,
  loadImportDetails,
} from "./api";
import {
  categories,
  evidenceKinds,
  eventLabel,
  sizeLabel,
  filePath,
  draftKey,
  completeness,
  exportState,
} from "./domain";
import type {
  Challenge,
  Project,
  Artifact,
  AuditEvent,
  ImportRecord,
  ImportFile,
  Preview,
} from "./domain";
import "./style.css";
import {
  DraftSession,
  draftBytes,
  MAX_DRAFT_BYTES,
  createDraftCache,
} from "./drafts";
import type { HumanDraft } from "./drafts";
const draft = ref<DraftSession>();
const challenges = ref<Challenge[]>([]),
  selected = ref<Challenge>(),
  project = ref<Project>(),
  events = ref<AuditEvent[]>([]),
  artifacts = ref<Artifact[]>([]),
  imports = ref<ImportRecord[]>([]);
const busy = ref(""),
  error = ref(""),
  notice = ref(""),
  tab = ref("overview"),
  progress = ref<number | null>(null),
  uploadStatus = ref(""),
  aiQuestion = ref(""),
  aiAnswer = ref(""),
  aiBusy = ref(false),
  aiConsent = ref(false),
  aiStatus = ref<{network_enabled:boolean; provider:string; model_id:string; credentials_configured:boolean; execution_enabled:boolean}>(),
  integrity = ref<{
    valid: boolean;
    earliest_affected_sequence?: number | null;
  }>();
const projectForm = reactive({
  project_name: "",
  competition_name: "",
  competition_type: "",
  ai_policy_summary: "",
});
const challengeForm = reactive({
  name: "",
  category: "Misc",
  description: "",
  score: "",
  ai_usage_level: "unknown",
});
const operation = reactive({
  command: "",
  working_directory: "",
  purpose: "",
  exit_code: "",
  result_note: "",
  started_at_claim: "",
  finished_at_claim: "",
});
const evidence = reactive({ evidence_kind: "other", capture_time_claim: "" }),
  note = ref(""),
  noteKind = ref("note"),
  retrospective = ref(false);
const markdown = computed({
    get: () => draft.value?.content ?? "",
    set: (value) => draft.value?.edit(value),
  }),
  preview = ref<Preview>(),
  edited = computed(
    () =>
      !!draft.value &&
      draft.value.origin !== "empty" &&
      draft.value.origin !== "generated" &&
      draft.value.state !== "saved",
  ),
  previewText = ref(""),
  previewImage = ref(""),
  previewName = ref("");
const selectedId = computed(() => selected.value?.challenge_id),
  root = computed(
    () => "/challenges/" + encodeURIComponent(selectedId.value || ""),
  );
const suggestions = computed(() =>
    events.value.filter((e) => eventLabel(e).startsWith("ai_suggestion")),
  ),
  aiHistory = computed(() =>
    events.value.filter((e) => e.event_type === "agent_message"),
  ),
  status = computed(() => completeness(preview.value, edited.value));
let previewVersion = 0;
function clearFile() {
  previewVersion++;
  if (previewImage.value) URL.revokeObjectURL(previewImage.value);
  previewImage.value = "";
  previewText.value = "";
  previewName.value = "";
}
async function guard(label: string, action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = label;
  error.value = "";
  notice.value = "";
  try {
    await action();
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = "";
  }
}
async function loadProject() {
  try {
    project.value = await request<Project>("/project");
    Object.assign(projectForm, {
      project_name: project.value.project_name,
      competition_name: project.value.competition_name,
      competition_type: project.value.competition_type,
      ai_policy_summary: project.value.ai_policy_summary,
    });
  } catch (e) {
    if (String(e).includes("404")) {
      notice.value = "尚未创建项目，或后端项目接口不可用。";
    } else throw e;
  }
}
async function refresh() {
  clearFile();
  imports.value = [];
  const p = root.value;
  const [es, as, im] = await Promise.all([
    request<AuditEvent[]>(p + "/events"),
    request<Artifact[]>(p + "/artifacts"),
    request<ImportRecord[]>(p + "/imports"),
  ]);
  events.value = es.sort((a, b) => a.sequence - b.sequence);
  artifacts.value = as;
  imports.value = await loadImportDetails(im, (id) =>
    request<ImportRecord>(p + "/imports/" + encodeURIComponent(id)),
  );
  preview.value = undefined;
  integrity.value = undefined;
}
async function reload() {
  challenges.value = await request<Challenge[]>("/challenges");
  await loadProject();
  await loadAIStatus();
  if (selected.value) await refresh();
}
async function select(c: Challenge) {
  if (selected.value?.challenge_id === c.challenge_id) return;
  selected.value = c;
  clearFile();
  events.value = [];
  artifacts.value = [];
  imports.value = [];
  preview.value = undefined;
  integrity.value = undefined;
  const key = draftKey(c.challenge_id),
    endpoint =
      "/challenges/" + encodeURIComponent(c.challenge_id) + "/writeup/draft";
  draft.value = new DraftSession({
    read: () => request<HumanDraft>(endpoint),
    write: (body) => request<HumanDraft>(endpoint, body, "PUT"),
    ...createDraftCache(
      key,
      {
        getItem: (k) => localStorage.getItem(k),
        setItem: (k, v) => localStorage.setItem(k, v),
        removeItem: (k) => localStorage.removeItem(k),
      },
      {
        getItem: (k) => sessionStorage.getItem(k),
        setItem: (k, v) => sessionStorage.setItem(k, v),
        removeItem: (k) => sessionStorage.removeItem(k),
      },
    ),
  });
  tab.value = "overview";
  note.value = "";
  noteKind.value = "note";
  uploadStatus.value = "";
  Object.assign(operation, {
    command: "",
    working_directory: "",
    purpose: "",
    exit_code: "",
    result_note: "",
    started_at_claim: "",
    finished_at_claim: "",
  });
  try {
    localStorage.setItem("ctf-workbench:selected", c.challenge_id);
  } catch {
    notice.value = "浏览器存储不可用，请手动下载草稿。";
  }
  await Promise.all([refresh(), draft.value.load()]);
}
async function loadAIStatus() {
  try {
    aiStatus.value = await request<{
      network_enabled: boolean;
      provider: string;
      model_id: string;
      credentials_configured: boolean;
      execution_enabled: boolean;
    }>("/model/status");
  } catch {
    aiStatus.value = undefined;
  }
}
async function askAI() {
  if (!selectedId.value || !aiQuestion.value.trim() || !aiConsent.value) return;
  aiBusy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const result = await request<{
      event_id:string; answer:string; provider_id:string; model_id:string;
      included_files:string[]; verification_status:string;
    }>(root.value + "/ai/chat", {
      question: aiQuestion.value.trim(),
      confirm_external_processing: true,
    }, "POST");
    aiAnswer.value = result.answer;
    aiQuestion.value = "";
    aiConsent.value = false;
    notice.value = "AI 建议已记录到事件时间线；未执行任何命令。";
    await refresh();
  } catch (e) {
    error.value = String(e);
  } finally {
    aiBusy.value = false;
  }
}
async function saveProject() {
  project.value = await request<Project>("/project", { ...projectForm }, "PUT");
  notice.value = "项目已保存";
}
async function createChallenge() {
  const c = await request<Challenge>(
    "/challenges",
    {
      ...challengeForm,
      score: challengeForm.score === "" ? null : Number(challengeForm.score),
    },
    "POST",
  );
  challenges.value = await request("/challenges");
  await select(c);
  challengeForm.name = "";
}
function chosen(e: Event) {
  return (e.target as HTMLInputElement).files?.[0];
}
async function sendFile(kind: "rules" | "zip" | "artifact", file?: File) {
  if (!file || (kind !== "rules" && !selectedId.value)) return;
  await guard("上传文件", async () => {
    uploadStatus.value = "正在上传";
    progress.value = 0;
    try {
      await upload(
        kind === "rules"
          ? "/project/rules"
          : root.value + (kind === "zip" ? "/imports" : "/artifacts"),
        file,
        kind === "artifact" ? { ...evidence } : {},
        (n) => {
          progress.value = n;
          uploadStatus.value =
            n === 100 ? "上传完毕，等待服务器校验 / 解压" : "正在上传";
        },
      );
      uploadStatus.value =
        kind === "zip" ? "解压完成（未执行文件）" : "服务器已保存";
      if (kind === "rules") await loadProject();
      else await refresh();
      notice.value = "文件已保存。同内容去重时保留原始分类与接收时间。";
    } catch (e) {
      uploadStatus.value = "失败或结果未知，请刷新核对后重试";
      throw e;
    }
  });
}
function drop(e: DragEvent) {
  void sendFile("zip", e.dataTransfer?.files[0]);
}
async function showFile(name: string, type: string, path: string) {
  clearFile();
  const version = previewVersion,
    b = await limitedBlob(
      path,
      /^image\/(png|jpeg|gif|webp)(;|$)/.test(type) ? 10485760 : 1048576,
    );
  if (version !== previewVersion) return;
  previewName.value = name;
  tab.value = "files";
  if (/^image\/(png|jpeg|gif|webp)(;|$)/.test(type))
    previewImage.value = URL.createObjectURL(b);
  else if (
    type.startsWith("text/") ||
    /\.(py|c|h|js|ts|json|md|txt|sh)$/i.test(name)
  ) {
    const text = await b.text();
    if (version === previewVersion) previewText.value = text;
  } else
    previewText.value = "此格式请下载原件；HTML / SVG 不渲染，代码不执行。";
}
function importPath(i: ImportRecord, f: ImportFile) {
  return (
    root.value +
    "/imports/" +
    i.import_id +
    "/files/" +
    filePath(f.relative_path)
  );
}
async function record() {
  await request(
    root.value + "/manual-operations",
    {
      ...operation,
      exit_code:
        operation.exit_code === "" ? null : Number(operation.exit_code),
      started_at_claim: operation.started_at_claim || null,
      finished_at_claim: operation.finished_at_claim || null,
    },
    "POST",
  );
  await refresh();
  tab.value = "timeline";
  notice.value = "已保存人工申报，非工作台执行或验证。";
}
async function addNote() {
  await request(
    root.value + "/notes",
    {
      text: note.value,
      retrospective: retrospective.value,
      kind: noteKind.value,
    },
    "POST",
  );
  note.value = "";
  await refresh();
}
async function generate() {
  preview.value = await request<Preview>(root.value + "/writeup/preview");
  if (!draft.value?.useGenerated(preview.value.markdown))
    notice.value = "已刷新服务器初稿，当前人工稿保留；可在下方查看初稿。";
  tab.value = "writeup";
}
async function discard() {
  if (
    !draft.value ||
    !window.confirm("放弃本地修改并重新读取服务器人工稿？不会删除服务器稿件。")
  )
    return;
  draft.value.io.clearLocal();
  draft.value.memoryLocal = false;
  await draft.value.load();
}
async function saveDraft() {
  await draft.value?.save();
}
async function reloadDraft() {
  await draft.value?.load();
}
function downloadMarkdown() {
  saveBlob(
    new Blob([markdown.value], { type: "text/markdown;charset=utf-8" }),
    (selected.value?.name || "writeup") + ".md",
  );
}
async function exportZip() {
  if (
    draft.value?.content &&
    draft.value.state !== "saved" &&
    !window.confirm(
      "当前编辑内容未保存到服务器。ZIP 只采用服务器已保存人工稿；没有有效人工稿时采用初稿。是否继续导出？",
    )
  )
    return;
  let source = "尚未保存人工稿，将采用服务器初稿并注明。";
  try {
    const current = await request<HumanDraft>(root.value + "/writeup/draft");
    source =
      "导出请求前服务器人工稿 v" +
      current.version +
      "；最终来源及版本以 ZIP manifest 为准。";
  } catch (e) {
    const status = (e as { status?: number }).status;
    if (status === 409)
      source = "服务器人工稿校验异常，将由后端回退初稿并标为 incomplete。";
    else if (status !== 404) throw e;
  }
  const p = await request<Preview>(root.value + "/writeup/preview");
  preview.value = p;
  const r = await fetch("/api" + root.value + "/export");
  if (!r.ok) throw new Error("档案导出失败：" + r.status);
  const exported = r.headers.get("X-Dossier-Completeness");
  preview.value = exportState(p, exported);
  saveBlob(
    await r.blob(),
    `evidence-${exported || "incomplete"}-${selectedId.value}.zip`,
  );
  notice.value =
    source +
    " ZIP 含最终稿及 writeup_generated.md 初稿；未保存的本地编辑不在其中。实际导出完整性：" +
    (exported || "未确认 / incomplete");
}
async function copyCommand() {
  await navigator.clipboard.writeText(operation.command);
  notice.value = "已复制，请自行检查后在 PowerShell 中手动运行。";
}
async function verify() {
  integrity.value = await request(root.value + "/integrity");
}
function print() {
  window.print();
}
onMounted(() =>
  guard("连接工作台", async () => {
    await reload();
    let cid: string | null = null;
    try {
      cid = localStorage.getItem("ctf-workbench:selected");
    } catch {}
    const c = challenges.value.find((c) => c.challenge_id === cid);
    if (c) await select(c);
  }),
);
onUnmounted(clearFile);
</script>
<template>
  <header class="topbar">
    <div>
      <span class="eyebrow">LOCAL · EVIDENCE FIRST</span>
      <h1>CTF <span>Workbench</span></h1>
    </div>
    <div class="context">
      <strong>{{
        project?.competition_name || project?.project_name || "尚未配置比赛"
      }}</strong
      ><span
        >{{ selected?.name || "选择一道题目开始" }} ·
        {{ busy || "人工执行模式" }}</span
      >
    </div>
    <span class="pill">● 本地工作台 · 自动执行关闭</span>
  </header>
  <div v-if="error" class="banner error" role="alert">
    {{ error }} <button @click="error = ''">关闭</button>
  </div>
  <div v-if="notice" class="banner" role="status">{{ notice }}</div>
  <main class="layout" :aria-busy="!!busy">
    <aside class="sidebar">
      <div class="section-title">
        比赛与题目
        <button :disabled="!!busy" @click="guard('刷新', reload)">刷新</button>
      </div>
      <details :open="!project">
        <summary>比赛项目设置</summary>
        <form @submit.prevent="guard('保存项目', saveProject)">
          <fieldset :disabled="!!busy">
            <label
              >项目名称<input
                v-model="projectForm.project_name"
                required
                maxlength="200" /></label
            ><label
              >比赛名称<input
                v-model="projectForm.competition_name"
                maxlength="200" /></label
            ><label
              >比赛类型<input
                v-model="projectForm.competition_type"
                maxlength="100"
                placeholder="练习 / 正式比赛" /></label
            ><label
              >规则概要与 AI 限制<textarea
                v-model="projectForm.ai_policy_summary"
                maxlength="4000"
                placeholder="人工核对 PDF 后填写，不自动推断"
              /></label
            ><button class="primary">保存项目</button>
          </fieldset>
        </form>
      </details>
      <details>
        <summary>共享比赛规则 PDF</summary>
        <label
          >上传规则（项目共享）<input
            type="file"
            accept=".pdf,application/pdf"
            :disabled="!!busy || !project"
            @change="sendFile('rules', chosen($event))" /></label
        ><template v-if="project?.rules_sha256"
          ><p>
            {{ project.rules_filename }} ·
            {{ sizeLabel(project.rules_size || 0) }}
          </p>
          <code>{{ project.rules_sha256 }}</code
          ><a href="/api/project/rules/content" download
            >下载规则原件</a
          ></template
        >
        <p class="muted">规则由本项目全部题目共享。替换会更新项目配置。</p>
      </details>
      <nav aria-label="题目列表">
        <button
          v-for="c in challenges"
          :key="c.challenge_id"
          :class="['challenge', { active: c.challenge_id === selectedId }]"
          :disabled="!!busy"
          @click="guard('读取题目', () => select(c))"
        >
          <small>{{ c.category }} · {{ c.score ?? "—" }} 分</small
          ><strong>{{ c.name }}</strong
          ><small
            >AI {{ c.ai_usage_level || "unknown" }} ·
            {{ c.solve_status }}</small
          >
        </button>
        <p v-if="!challenges.length" class="muted">还没有题目，先创建一道。</p>
      </nav>
      <details>
        <summary>＋ 创建题目</summary>
        <form @submit.prevent="guard('创建题目', createChallenge)">
          <fieldset :disabled="!!busy">
            <label
              >题目名称<input
                v-model="challengeForm.name"
                required
                maxlength="200"
            /></label>
            <div class="row">
              <label
                >分类<select v-model="challengeForm.category">
                  <option v-for="c in categories" :key="c">{{ c }}</option>
                </select></label
              ><label
                >分值<input
                  v-model="challengeForm.score"
                  type="number"
                  min="0"
                  max="1000000"
                  step="1"
              /></label>
            </div>
            <label>描述<textarea v-model="challengeForm.description" /></label
            ><label
              >AI 使用等级<select v-model="challengeForm.ai_usage_level">
                <option value="unknown">未确认（禁用 Agent 流程）</option>
                <option>A0</option>
                <option>A1</option>
                <option>A2</option>
              </select></label
            ><button class="primary">创建题目</button>
          </fieldset>
        </form>
      </details>
      <template v-if="selected"
        ><div class="section-title">
          证据索引 <span>{{ artifacts.length }}</span>
        </div>
        <button
          v-for="a in artifacts"
          :key="a.artifact_id"
          class="file-button"
          :disabled="!!busy"
          @click="
            guard('读取证据', () =>
              showFile(
                a.original_filename,
                a.media_type,
                root + '/artifacts/' + a.artifact_id + '/content',
              ),
            )
          "
        >
          ▧ {{ a.original_filename
          }}<small
            >{{ a.evidence_kind || "other" }} · {{ sizeLabel(a.size) }}</small
          >
        </button></template
      >
      <details v-if="selected && imports.length" open>
        <summary>题目文件树</summary>
        <div v-for="i in imports" :key="i.import_id">
          <small>{{ i.original_filename }}</small>
          <button
            v-for="f in i.files"
            :key="f.relative_path"
            class="file-button"
            :disabled="!!busy"
            @click="
              guard('读取文件', () =>
                showFile(f.relative_path, f.media_type, importPath(i, f)),
              )
            "
          >
            ↳ {{ f.relative_path }}
          </button>
        </div>
      </details>
    </aside>
    <section class="workspace">
      <template v-if="selected"
        ><div class="workspace-title">
          <div>
            <span class="eyebrow"
              >{{ selected.category }} / AI
              {{ selected.ai_usage_level || "unknown" }}</span
            >
            <h2>{{ selected.name }}</h2>
          </div>
          <span class="pill">解题状态 {{ selected.solve_status }}</span>
        </div>
        <nav class="tabs" aria-label="工作区">
          <button
            v-for="t in [
              ['overview', '题目与导入'],
              ['ai', 'AI 解题助手'],
              ['files', '文件预览'],
              ['operations', '运行记录'],
              ['timeline', '事件时间线'],
              ['writeup', 'Writeup'],
            ]"
            :key="t[0]"
            :class="{ active: tab === t[0] }"
            @click="tab = t[0]"
          >
            {{ t[1] }}
          </button>
        </nav>
        <section v-show="tab === 'overview'" class="panel">
          <h3>题目描述</h3>
          <p class="description">
            {{ selected.description || "尚未填写描述" }}
          </p>
          <div class="dropzone" @dragover.prevent @drop.prevent="drop">
            <strong>导入题目 ZIP</strong>
            <p>拖放 ZIP 或选择文件。服务器安全解压，不运行文件。</p>
            <input
              aria-label="题目 ZIP"
              type="file"
              accept=".zip,application/zip"
              :disabled="!!busy"
              @change="sendFile('zip', chosen($event))"
            />
          </div>
          <div v-if="uploadStatus" role="status">
            <progress :value="progress ?? undefined" max="100" />
            {{ uploadStatus }} {{ progress === null ? "" : progress + "%" }}
          </div>
          <div v-for="i in imports" :key="i.import_id" class="import">
            <h4>{{ i.original_filename }}</h4>
            <p>
              {{ i.extracted_file_count }} 个文件 ·
              {{ sizeLabel(i.total_uncompressed_size) }} ·
              {{
                i.manifest_verified === true
                  ? "清单已校验 / 未执行"
                  : "完整性异常 / 文件访问禁用"
              }}
            </p>
            <p v-if="i.manifest_verified !== true" class="error" role="alert">
              {{ i.integrity_error || "清单未通过校验" }}
            </p>
            <p v-for="w in i.warnings" :key="w" class="warning">{{ w }}</p>
            <ul class="file-tree">
              <li v-for="f in i.files" :key="f.relative_path">
                <button
                  :disabled="!!busy"
                  @click="
                    guard('读取导入文件', () =>
                      showFile(f.relative_path, f.media_type, importPath(i, f)),
                    )
                  "
                >
                  {{ f.relative_path }}</button
                ><small>{{ sizeLabel(f.size) }}</small
                ><code>{{ f.sha256 }}</code
                ><a :href="'/api' + importPath(i, f)" download>原件</a>
              </li>
            </ul>
          </div>
          <h3>上传脚本 / 证据</h3>
          <p class="muted">保留原始字节。不修改截图，不回填服务器接收时间。</p>
          <div class="row">
            <label
              >证据类型<select
                v-model="evidence.evidence_kind"
                aria-label="证据类型"
              >
                <option v-for="k in evidenceKinds" :key="k">{{ k }}</option>
              </select></label
            ><label
              >拍摄时间（用户申报，可选）<input
                v-model="evidence.capture_time_claim"
                placeholder="ISO 8601，含时区"
            /></label>
          </div>
          <input
            aria-label="上传证据"
            type="file"
            :disabled="!!busy"
            @change="sendFile('artifact', chosen($event))"
          />
          <article v-for="a in artifacts" :key="a.artifact_id" class="artifact">
            <strong>{{ a.original_filename }}</strong
            ><span
              >{{ a.evidence_kind || "other" }} · {{ sizeLabel(a.size) }}</span
            ><code>SHA256 {{ a.sha256 }}</code
            ><small
              >服务器接收 {{ a.ingested_at }} · 来源
              {{ a.source_event_id }}</small
            ><small v-if="a.capture_time_claim"
              >用户申报拍摄时间
              {{ a.capture_time_claim }}（非可信系统时间）</small
            ><a
              :href="'/api' + root + '/artifacts/' + a.artifact_id + '/content'"
              download
              >下载原件</a
            >
          </article>
        </section>
        <section v-show="tab === 'files'" class="panel">
          <h3>{{ previewName || "选择左侧证据或导入清单中的文件" }}</h3>
          <img
            v-if="previewImage"
            :src="previewImage"
            class="preview-image"
            alt="用户上传的原始证据预览"
          />
          <pre v-if="previewText" class="code-preview">{{ previewText }}</pre>
          <p class="muted">
            文本预览最大 1 MiB，图片 10 MiB；代码仅作文本展示。HTML / SVG
            不渲染。
          </p>
        </section>
        <section v-show="tab === 'operations'" class="panel">
          <span class="pill">人工申报 · execution_verified=false</span>
          <h3>记录一次本地运行</h3>
          <p>复制命令 → 打开 PowerShell → 手动运行 → 上传截图 → 补录结果</p>
          <p class="warning">
            不要记录 API Key、密码或 Token。工作台不执行此命令。
          </p>
          <form @submit.prevent="guard('保存人工申报', record)">
            <fieldset :disabled="!!busy">
              <label
                >实际执行命令<textarea
                  v-model="operation.command"
                  required
                  maxlength="4000"
                /></label
              ><button
                type="button"
                :disabled="!operation.command"
                @click="guard('复制命令', copyCommand)"
              >
                复制命令</button
              ><label
                >工作目录<input
                  v-model="operation.working_directory"
                  required
                  maxlength="500" /></label
              ><label
                >执行目的<input
                  v-model="operation.purpose"
                  required
                  maxlength="500" /></label
              ><label
                >退出码（可选）<input
                  v-model="operation.exit_code"
                  type="number"
                  step="1" /></label
              ><label
                >运行结果说明<textarea
                  v-model="operation.result_note"
                  required
                  maxlength="4000"
                />
              </label>
              <div class="row">
                <label
                  >开始时间（用户申报）<input
                    v-model="operation.started_at_claim"
                    placeholder="ISO 8601，含时区" /></label
                ><label
                  >结束时间（用户申报）<input
                    v-model="operation.finished_at_claim"
                    placeholder="ISO 8601，含时区"
                /></label>
              </div>
              <button class="primary">保存人工申报</button>
            </fieldset>
          </form>
          <details>
            <summary>Docker 命令建议（不执行）</summary>
            <pre>
docker build -t ctf-local .
docker run --rm --network none ctf-local</pre
            >
            <p>仅适用于已检查并信任的 Dockerfile；自行核对挂载、网络与规则。</p>
          </details>
        </section>
        <section v-show="tab === 'ai'" class="panel ai-panel">
          <h3>AI 辅助解题 · DeepSeek</h3>
          <p class="muted">模型只提供分析建议，不执行命令、不访问比赛目标、不提交 Flag。AI 回答会写入事件时间线，并标记为未验证建议。</p>
          <div class="ai-status">
            <strong>连接状态：</strong>
            <span v-if="aiStatus?.network_enabled && aiStatus.credentials_configured">已配置联网开关与凭证（实际连通性以请求结果为准）</span>
            <span v-else-if="aiStatus?.network_enabled">联网开关已开启，但尚未检测到 API Key</span>
            <span v-else>服务器未开启模型联网</span>
            <small>{{ aiStatus?.provider || 'DeepSeek' }} · {{ aiStatus?.model_id || 'deepseek-chat' }}</small>
            <button type="button" @click="guard('检查模型状态', loadAIStatus)">刷新状态</button>
          </div>
          <p v-if="selected.ai_usage_level === 'unknown' || selected.ai_usage_level === 'A0'" class="warning">
            当前题目 AI 使用等级为 {{ selected.ai_usage_level }}，按规则不允许调用 AI。请先核对比赛规则并正确设置等级。
          </p>
          <label>向 AI 提问
            <textarea v-model="aiQuestion" maxlength="8000" rows="5" placeholder="例如：请分析这道 Web 题的入口、可能的漏洞点，并给出逐步验证思路。"></textarea>
          </label>
          <label class="consent">
            <input type="checkbox" v-model="aiConsent" />
            我确认将本题描述、已导入的文本文件、符合限制的二进制静态元数据/字符串及相关记录发送给配置的模型服务进行处理。
          </label>
          <p class="muted">不会发送二进制附件原文，也不会执行二进制文件。符合限制的小型 ELF/PE 等文件仅提取头部信息和可打印字符串。导入文件会先校验 SHA-256，并进行常见密钥格式脱敏；仍请勿上传密码、个人隐私或无权外传的材料。</p>
          <button class="primary" :disabled="aiBusy || !aiConsent || !aiQuestion.trim() || selected.ai_usage_level === 'unknown' || selected.ai_usage_level === 'A0' || !aiStatus?.network_enabled || !aiStatus?.credentials_configured" @click="askAI">
            {{ aiBusy ? '正在请求模型…' : '发送问题并获取分析' }}
          </button>
          <section v-if="aiHistory.length" class="ai-answer">
            <h4>本题 AI 对话记录（均为未验证建议）</h4>
            <article v-for="turn in aiHistory" :key="turn.event_id" class="ai-turn">
              <small>{{ turn.occurred_at }} · {{ turn.payload.model_id }}</small>
              <strong>你：</strong>
              <p>{{ turn.payload.question }}</p>
              <strong>AI：</strong>
              <pre>{{ turn.payload.answer }}</pre>
              <small>关联事件 #{{ turn.sequence }} · 未执行</small>
            </article>
            <p class="muted">请自行检查建议，手动执行后再将真实结果和证据补录到工作台。</p>
          </section>
        </section>
        <section v-show="tab === 'timeline'" class="panel">
          <div class="section-title">
            <h3>事件时间线</h3>
            <button :disabled="!!busy" @click="guard('校验事件链', verify)">
              校验事件链
            </button>
          </div>
          <p v-if="integrity" :class="integrity.valid ? 'success' : 'error'">
            {{
              integrity.valid
                ? "事件链一致（不证明操作或截图真实性）"
                : "事件链异常：" + integrity.earliest_affected_sequence
            }}
          </p>
          <p v-if="!events.length">
            尚无事件，未记录的操作不能作为已执行事实。
          </p>
          <article v-for="e in events" :key="e.event_id" class="event">
            <small
              >#{{ e.sequence }} · {{ e.occurred_at }} · {{ e.actor }}</small
            >
            <h4>{{ eventLabel(e) }}</h4>
            <p>{{ e.event_type }} · {{ e.event_id }}</p>
            <pre>{{ JSON.stringify(e.payload, null, 2) }}</pre>
            <p>关联证据：{{ e.artifact_ids.join(", ") || "无" }}</p>
            <code>{{ e.event_hash }}</code>
          </article>
        </section>
        <section v-show="tab === 'writeup'" class="panel writeup">
          <div class="no-print">
            <h3>Writeup 工作区</h3>
            <p>{{ status }}</p>
            <p class="muted">
              保存到服务器后，人工稿会成为 ZIP 的 writeup.md；服务器初稿另存
              writeup_generated.md。未保存修改仅在浏览器，请先保存或另存
              Markdown。人工内容不构成已验证执行事实。
            </p>
            <div class="actions">
              <button :disabled="!!busy" @click="guard('生成初稿', generate)">
                生成服务器初稿</button
              ><button :disabled="!!busy" @click="guard('读取人工稿', discard)">
                放弃本地修改</button
              ><button :disabled="!markdown" @click="downloadMarkdown">
                下载 Markdown</button
              ><button :disabled="!markdown" @click="print">
                打印 / 保存 PDF</button
              ><button :disabled="!!busy" @click="guard('导出档案', exportZip)">
                下载证据 ZIP
              </button>
            </div>
            <section v-if="draft" class="draft-state">
              <p class="save-status" role="status">
                {{
                  {
                    unsaved: "未保存",
                    saving: "正在保存",
                    saved: "已保存",
                    error: "保存失败",
                    conflict: "版本冲突",
                  }[draft.state]
                }}{{
                  draft.state === "saved"
                    ? "（版本 v" + draft.server?.version + "）"
                    : ""
                }}
              </p>
              <p v-if="draft.server" class="draft-metadata">
                服务器版本 v{{ draft.server.version }} ·
                {{ draft.server.saved_at }} ·
                {{ draft.server.size }} B<br /><code>{{
                  draft.server.sha256
                }}</code>
              </p>
              <p>
                当前稿 {{ draftBytes(markdown) }} / {{ MAX_DRAFT_BYTES }} UTF-8
                字节
              </p>
              <p v-if="draft.error" class="error" role="alert">
                {{ draft.error }}
              </p>
              <p v-if="draft.storageWarning" class="warning" role="alert">
                {{ draft.storageWarning }}
              </p>
              <div class="actions">
                <button
                  class="primary"
                  :disabled="
                    !!busy ||
                    !draft.canSave ||
                    draft.migration ||
                    draft.state === 'saved'
                  "
                  @click="guard('保存人工稿', saveDraft)"
                >
                  保存到服务器
                </button>
                <button
                  :disabled="!!busy"
                  @click="guard('读取人工稿', reloadDraft)"
                >
                  重新读取人工稿
                </button>
              </div>
              <div
                v-if="draft.migration && !draft.hasConflict"
                class="notice migration"
              >
                <p>发现本地未同步的人工稿，是否保存到服务器？</p>
                <button
                  :disabled="!!busy || !draft.canSave"
                  @click="guard('迁移人工稿', saveDraft)"
                >
                  确认迁移并保存
                </button>
              </div>
              <div
                v-if="draft.hasConflict"
                class="notice draft-conflict"
                role="alert"
              >
                <h4>服务器稿与本地稿不同，请选择或手动合并</h4>
                <div class="row">
                  <label
                    >服务器最新稿（只读）<textarea
                      :value="draft.current?.content ?? '服务器目前无人工稿'"
                      readonly
                    /></label
                  ><label
                    >本地稿（只读副本，主编辑器可修改）<textarea
                      :value="markdown"
                      readonly
                    />
                  </label>
                </div>
                <p>
                  服务器最新版本
                  {{
                    draft.current?.version ?? 0
                  }}。不会自动覆盖，也不会自动重试。
                </p>
                <button :disabled="!!busy" @click="draft.useServer()">
                  采用服务器稿（放弃本地修改）
                </button>
                <button :disabled="!!busy" @click="draft.keepLocalOnLatest()">
                  保留本地内容，按最新版本手动合并
                </button>
                <p>
                  保留后请在主编辑器完成合并，再明确点击保存；此按钮不会提交。
                </p>
              </div>
            </section>
            <details v-if="preview">
              <summary>查看服务器生成初稿（与人工稿分离）</summary>
              <pre>{{ preview.markdown }}</pre>
            </details>
            <ul v-if="preview">
              <li
                v-for="m in [
                  ...preview.missing_requirements,
                  ...preview.warnings,
                ]"
                :key="m"
                class="warning"
              >
                {{ m }}
              </li>
            </ul>
            <label
              >Markdown 人工编辑<textarea
                class="markdown-editor"
                v-model="markdown"
                spellcheck="false"
              />
            </label>
          </div>
          <div class="print-only">
            <h1>{{ selected.name }} · Writeup</h1>
            <p>{{ status }}</p>
            <pre>{{ markdown }}</pre>
          </div>
        </section>
      </template>
      <section v-else class="empty">
        <span class="eyebrow">YOUR NEXT CHALLENGE</span>
        <h2>每一个结论，都有证据可循。</h2>
        <p>配置规则，创建题目，导入附件。所有程序由你在本地手动运行。</p>
        <p>从左侧「＋ 创建题目」开始。</p>
      </section>
    </section>
    <aside class="inspector">
      <span class="eyebrow">PROCESS & PROVENANCE</span>
      <h3>分析与记录</h3>
      <div class="notice">
        <strong>人工执行模式</strong>
        <p>工具执行、模型联网和自动 Flag 提交均未启用。</p>
      </div>
      <div v-if="selected" class="notice">
        <strong>AI {{ selected.ai_usage_level || "unknown" }}</strong>
        <p
          v-if="
            !selected.ai_usage_level || selected.ai_usage_level === 'unknown'
          "
        >
          规则未确认，Agent 流程禁用。
        </p>
        <p v-else>等级不自动授予能力；当前仅展示已有建议。</p>
      </div>
      <p class="muted">
        {{ project?.ai_policy_summary || "规则概要尚未填写，请先核对规则。" }}
      </p>
      <h4>Agent 建议（非执行）</h4>
      <p v-if="!suggestions.length" class="muted">
        暂无已记录建议，不生成演示分析。
      </p>
      <article v-for="e in suggestions" :key="e.event_id" class="suggestion">
        <small>{{ e.occurred_at }} · {{ e.event_id }}</small>
        <pre>{{ JSON.stringify(e.payload, null, 2) }}</pre>
      </article>
      <template v-if="selected"
        ><h4>选手笔记 / 解题思路</h4>
        <form @submit.prevent="guard('保存笔记', addNote)">
          <fieldset :disabled="!!busy">
            <label
              >笔记类型<select v-model="noteKind" aria-label="笔记类型">
                <option value="note">普通笔记（不计为核心思路）</option>
                <option value="approach">核心解题思路（人工填写）</option>
              </select></label
            >
            <textarea
              aria-label="选手笔记"
              v-model="note"
              required
              maxlength="10000"
              placeholder="人工填写思路，保留事件与证据 ID"
            /><label class="checkbox"
              ><input
                type="checkbox"
                v-model="retrospective"
              />回溯补录（记录当前录入时间）</label
            ><button :disabled="!note">追加笔记</button>
          </fieldset>
        </form></template
      >
    </aside>
  </main>
</template>
