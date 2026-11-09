<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { request } from "../../api";
import type { ModelServiceStatus } from "../../model-settings";
import {
  canTestConnection,
  envKeyAuthorizationRequired,
  keySourceLabel,
  modelDisplayName,
  modelIdFromInput,
  networkSettingNote,
  settingsErrorText,
} from "../../model-settings";

const emit = defineEmits<{ close: [] }>();
const status = ref<ModelServiceStatus>();
const loading = ref(false);
const busy = ref(false);
const testing = ref(false);
const error = ref("");
const notice = ref("");
const testResult = ref("");
const keyVisible = ref(false);
const authorizeEnvKey = ref(false);
const networkDraft = ref(false);
const form = reactive({
  base_url: "",
  model_name: "",
  api_key: "",
});

const testAvailability = computed(() =>
  status.value
    ? canTestConnection(status.value)
    : { allowed: false, reason: "正在加载配置" },
);
const keyHint = computed(() => {
  if (!status.value) return "";
  if (status.value.key_configured)
    return "已配置；留空保持不变。输入新 Key 可替换。";
  if (status.value.key_storage_available)
    return "输入 API Key 后保存；Key 只在后端加密保存。";
  return "当前系统凭证存储不可用，无法保存 API Key。";
});

const formBaseCustom = computed(() => {
  if (!status.value) return false;
  return (
    form.base_url.trim().replace(/\/+$/, "") !==
    status.value.default_base_url.replace(/\/+$/, "")
  );
});
const showEnvKeyAuthorization = computed(
  () => status.value?.key_source === "environment" && formBaseCustom.value,
);
const envKeyAuthorizationMissing = computed(
  () =>
    !!status.value &&
    envKeyAuthorizationRequired(status.value) &&
    !authorizeEnvKey.value,
);

// Editing the API address invalidates any previous env-key authorization;
// the user must explicitly re-check it for the new destination.
watch(
  () => form.base_url,
  () => {
    authorizeEnvKey.value = false;
  },
  { flush: "sync" },
);

function applyStatus(value: ModelServiceStatus) {
  status.value = value;
  form.base_url = value.base_url;
  form.model_name = modelDisplayName(value);
  networkDraft.value = value.network_setting;
  authorizeEnvKey.value = value.env_key_custom_base_url_authorized;
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    applyStatus(await request<ModelServiceStatus>("/model/settings"));
  } catch (e) {
    error.value = settingsErrorText(e);
  } finally {
    loading.value = false;
  }
}

async function save() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  testResult.value = "";
  try {
    const body: Record<string, unknown> = {
      base_url: form.base_url,
      model_id: modelIdFromInput(form.model_name),
      authorize_env_key_custom_base_url:
        showEnvKeyAuthorization.value && authorizeEnvKey.value,
    };
    if (form.api_key.trim()) body.api_key = form.api_key;
    applyStatus(await request<ModelServiceStatus>("/model/settings", body, "PUT"));
    form.api_key = "";
    keyVisible.value = false;
    notice.value = "模型服务配置已保存。联网调用开关未被自动修改。";
  } catch (e) {
    error.value = settingsErrorText(e);
  } finally {
    busy.value = false;
  }
}

async function clearKey() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  testResult.value = "";
  try {
    applyStatus(
      await request<ModelServiceStatus>(
        "/model/settings",
        {
          base_url: form.base_url,
          model_id: modelIdFromInput(form.model_name),
          clear_api_key: true,
        },
        "PUT",
      ),
    );
    form.api_key = "";
    keyVisible.value = false;
    notice.value = "已清除本机保存的 API Key。";
  } catch (e) {
    error.value = settingsErrorText(e);
  } finally {
    busy.value = false;
  }
}

async function saveNetwork() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    applyStatus(
      await request<ModelServiceStatus>(
        "/model/network",
        { network_enabled: networkDraft.value },
        "PUT",
      ),
    );
    notice.value = networkDraft.value
      ? "联网调用已开启；每次 AI 请求仍需单独确认。"
      : "联网调用已关闭；AI 请求会被拒绝。";
  } catch (e) {
    error.value = settingsErrorText(e);
  } finally {
    busy.value = false;
  }
}

async function testConnection() {
  if (testing.value || !testAvailability.value.allowed) return;
  testing.value = true;
  error.value = "";
  testResult.value = "";
  try {
    const result = await request<{
      success: boolean;
      provider: string;
      model_id: string;
      call_id: string;
      sent_synthetic_content_only: boolean;
    }>("/model/test", { confirm_synthetic_request: true }, "POST");
    testResult.value =
      "连接成功：仅发送固定合成提示，调用 ID " + result.call_id.slice(0, 8) + "…";
  } catch (e) {
    error.value = "连接测试失败：" + settingsErrorText(e);
  } finally {
    testing.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="model-settings" aria-labelledby="model-settings-title">
    <header class="settings-header">
      <div>
        <span class="eyebrow">模型服务</span>
        <h2 id="model-settings-title">模型服务设置</h2>
        <p class="muted">
          在这里配置本机的 DeepSeek API。API Key 只由后端保存和使用，页面永远不会显示完整 Key。
        </p>
      </div>
      <button type="button" class="close" @click="emit('close')">返回工作台</button>
    </header>

    <div v-if="error" class="banner error" role="alert">{{ error }}</div>
    <div v-if="notice" class="banner" role="status">{{ notice }}</div>
    <div v-if="loading" class="muted">正在加载模型服务配置…</div>

    <div v-if="status" class="settings-grid">
      <section class="settings-card">
        <h3>服务商与凭证</h3>
        <label>
          服务商
          <input :value="status.provider" disabled />
        </label>
        <label>
          API 地址
          <input v-model="form.base_url" placeholder="https://api.deepseek.com" />
          <small>默认：{{ status.default_base_url }}</small>
        </label>
        <p class="address-warning" role="note">
          API Key 将发送至当前填写的 API 地址，请确认该地址属于你信任的服务商。
        </p>
        <label>
          模型
          <input v-model="form.model_name" placeholder="DeepSeek-V4.1-Flash" />
          <small>默认：{{ status.default_model_name || status.default_model_id }}（API ID：{{ status.default_model_id }}）</small>
        </label>
        <label>
          API Key
          <span class="key-row">
            <input
              v-model="form.api_key"
              :type="keyVisible ? 'text' : 'password'"
              autocomplete="new-password"
              :placeholder="keyHint"
            />
            <button type="button" class="ghost" @click="keyVisible = !keyVisible">
              {{ keyVisible ? "隐藏" : "显示" }}
            </button>
          </span>
          <small>{{ keyHint }}</small>
        </label>
        <p class="key-state">
          状态：<strong>{{ keySourceLabel(status) }}</strong>
          <span v-if="status.key_error" class="warning">
            （{{ settingsErrorText(status.key_error) }}）
          </span>
        </p>
        <p v-if="status.config_error" class="warning">
          配置文件无法读取；模型调用已禁用。请重新保存有效配置。
        </p>
        <label v-if="showEnvKeyAuthorization" class="env-auth">
          <input v-model="authorizeEnvKey" type="checkbox" :disabled="busy" />
          我授权在此 API 地址使用服务器环境变量中的 API Key。地址变更后需重新授权。
        </label>
        <p v-if="envKeyAuthorizationMissing" class="warning">
          尚未授权环境变量 API Key 发送到当前自定义 API 地址；模型调用将被拒绝。
        </p>
        <div class="actions">
          <button type="button" class="primary" :disabled="busy" @click="save">
            保存配置
          </button>
          <button
            v-if="status.key_source === 'settings'"
            type="button"
            class="danger"
            :disabled="busy"
            @click="clearKey"
          >
            清除已保存 Key
          </button>
        </div>
      </section>

      <section class="settings-card">
        <h3>联网调用</h3>
        <p class="muted">{{ networkSettingNote(status) }}</p>
        <label class="switch-row">
          <input v-model="networkDraft" type="checkbox" :disabled="busy" />
          允许联网调用模型
        </label>
        <p class="key-state">
          当前有效状态：
          <strong>{{ status.network_enabled ? "已开启" : "已关闭" }}</strong>
        </p>
        <div class="actions">
          <button type="button" :disabled="busy" @click="saveNetwork">
            保存联网开关
          </button>
        </div>
        <hr />
        <h3>测试连接</h3>
        <p class="muted">
          只向配置的模型服务发送固定合成提示，不包含题目、附件、规则或聊天记录。
        </p>
        <button
          type="button"
          :disabled="testing || !testAvailability.allowed"
          @click="testConnection"
        >
          {{ testing ? "测试中…" : "测试连接" }}
        </button>
        <p v-if="!testAvailability.allowed" class="muted">
          {{ testAvailability.reason }}
        </p>
        <p v-if="testResult" class="success" role="status">{{ testResult }}</p>
      </section>
    </div>

    <footer class="settings-footer">
      <span class="muted">
        安全边界：单用户本地部署；Key 使用当前 Windows 用户 DPAPI 加密，其他 Windows 用户无法解密。
      </span>
    </footer>
  </section>
</template>

<style scoped>
.model-settings {
  max-width: 1080px;
  margin: 0 auto;
  padding: 24px;
  color: #17202d;
}
.settings-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.settings-header h2 {
  margin: 4px 0 8px;
}
.eyebrow {
  font-size: 11px;
  letter-spacing: 0.14em;
  color: #62708a;
}
.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}
.settings-card {
  border: 1px solid #d8dee9;
  border-radius: 12px;
  padding: 18px;
  background: #fff;
}
.settings-card h3 {
  margin: 0 0 12px;
}
label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
  font-size: 14px;
  font-weight: 600;
}
input {
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid #b9c2d0;
  border-radius: 8px;
  font: inherit;
}
input:disabled {
  background: #f3f5f9;
  color: #5b667a;
}
small,
.muted {
  color: #62708a;
  font-weight: 400;
}
.key-row {
  display: flex;
  gap: 8px;
}
.key-row input {
  flex: 1;
}
button {
  padding: 8px 14px;
  border: 1px solid #9aa7bd;
  border-radius: 8px;
  background: #fff;
  font: inherit;
  cursor: pointer;
}
button.primary {
  background: #1d5eff;
  border-color: #1d5eff;
  color: #fff;
}
button.danger {
  border-color: #c0392b;
  color: #a12a1e;
}
button.ghost {
  white-space: nowrap;
}
button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}
.key-state {
  margin: 8px 0;
  font-size: 14px;
}
.env-auth {
  flex-direction: row;
  align-items: flex-start;
  gap: 8px;
  margin: 8px 0;
  padding: 8px 9px;
  border: 1px solid #e3c36d;
  border-radius: 8px;
  background: #fffbf0;
  font-size: 12px;
  line-height: 1.45;
  font-weight: 400;
}
.env-auth input {
  flex: 0 0 auto;
  width: auto;
  margin-top: 2px;
}
.address-warning {
  margin: -4px 0 12px;
  padding: 7px 9px;
  border-left: 3px solid #c98a00;
  background: #fff8e6;
  color: #6d4b00;
  font-size: 12px;
  line-height: 1.45;
}
.switch-row {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
}
.switch-row input {
  flex: 0 0 auto;
  width: auto;
}
.success {
  color: #176b38;
}
.warning {
  color: #9a5a00;
}
.banner {
  padding: 10px 12px;
  margin: 10px 0;
  border-radius: 8px;
  background: #eef4ff;
}
.banner.error {
  background: #fff0ee;
  color: #8d2015;
}
.settings-footer {
  margin-top: 18px;
  font-size: 12px;
}
@media (max-width: 760px) {
  .model-settings {
    padding: 14px;
  }
  .settings-header {
    flex-direction: column;
  }
  .settings-grid {
    grid-template-columns: 1fr;
  }
}
</style>
