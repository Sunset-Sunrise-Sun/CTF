import { test } from "node:test";
import assert from "node:assert/strict";
import {
  canTestConnection,
  envKeyAuthorizationRequired,
  keySourceLabel,
  modelDisplayName,
  modelIdFromInput,
  networkSettingNote,
  settingsErrorText,
} from "../src/model-settings.ts";

const base = {
  provider: "deepseek",
  base_url: "https://api.deepseek.com",
  default_base_url: "https://api.deepseek.com",
  model_id: "deepseek-flash",
  model_name: "DeepSeek-V4.1-Flash",
  default_model_id: "deepseek-flash",
  default_model_name: "DeepSeek-V4.1-Flash",
  key_configured: true,
  key_source: "settings",
  key_storage_available: true,
  key_error: null,
  config_error: null,
  network_enabled: false,
  network_setting: false,
  network_env_override: false,
  env_key_custom_base_url_authorized: false,
  env_key_custom_base_url_authorization_required: false,
};

test("public model name maps to the official DeepSeek API id", () => {
  assert.equal(modelIdFromInput("DeepSeek-V4.1-Flash"), "deepseek-flash");
  assert.equal(modelIdFromInput("DeepSeek-V4-Pro"), "deepseek-v4-pro");
  assert.equal(modelIdFromInput("deepseek-chat"), "deepseek-chat");
  assert.equal(modelIdFromInput("custom-model-v1"), "custom-model-v1");
  assert.equal(modelIdFromInput(""), "deepseek-flash");
  assert.equal(modelDisplayName(base), "DeepSeek-V4.1-Flash");
  assert.equal(modelDisplayName({ ...base, model_name: "" }), "deepseek-flash");
});

test("key status describes settings/environment/missing without exposing a value", () => {
  assert.equal(keySourceLabel({ ...base, key_configured: false, key_source: null }), "未配置 API Key");
  assert.match(keySourceLabel(base), /DPAPI/);
  assert.match(
    keySourceLabel({ ...base, key_source: "environment" }),
    /环境变量/,
  );
});

test("connection test requires both a configured key and explicit network opt-in", () => {
  assert.deepEqual(canTestConnection({ ...base, key_configured: false }), {
    allowed: false,
    reason: "请先保存 API Key",
  });
  assert.deepEqual(canTestConnection(base), {
    allowed: false,
    reason: "请先开启「联网调用」",
  });
  assert.deepEqual(canTestConnection({ ...base, network_enabled: true }), {
    allowed: true,
    reason: "",
  });
});

test("network note distinguishes default-off, enabled and environment override", () => {
  assert.match(networkSettingNote(base), /默认关闭/);
  assert.match(networkSettingNote({ ...base, network_setting: true }), /已开启/);
  assert.match(
    networkSettingNote({ ...base, network_env_override: true }),
    /CTF_MODEL_NETWORK_ENABLED/,
  );
});

test("environment key on a custom address needs explicit authorization", () => {
  const envCustom = {
    ...base,
    key_source: "environment",
    base_url: "https://trusted.example",
    network_enabled: true,
  };
  assert.equal(envKeyAuthorizationRequired(envCustom), true);
  assert.deepEqual(canTestConnection(envCustom), {
    allowed: false,
    reason: "环境变量 API Key 用于自定义地址需要先明确授权",
  });
  const authorized = {
    ...envCustom,
    env_key_custom_base_url_authorized: true,
  };
  assert.equal(envKeyAuthorizationRequired(authorized), false);
  assert.equal(canTestConnection(authorized).allowed, true);
  // Default DeepSeek address with an env key needs no extra authorization.
  assert.equal(
    envKeyAuthorizationRequired({
      ...envCustom,
      base_url: base.default_base_url,
    }),
    false,
  );
});

test("settings errors are mapped to safe user messages", () => {
  assert.match(settingsErrorText("credential_store_unavailable"), /凭证存储不可用/);
  assert.match(settingsErrorText("credential_store_error"), /其他 Windows 用户/);
  assert.match(settingsErrorText("invalid_base_url"), /HTTPS/);
  assert.match(settingsErrorText("invalid_model_id"), /模型名称/);
  assert.match(settingsErrorText("invalid_api_key"), /API Key 格式/);
  assert.match(settingsErrorText("config_invalid"), /配置文件损坏/);
  assert.match(
    settingsErrorText("env_key_custom_base_url_not_authorized"),
    /尚未授权/,
  );
  assert.equal(settingsErrorText(""), "设置操作失败。");
});

test("corrupted config disables connection testing", () => {
  assert.deepEqual(canTestConnection({ ...base, config_error: "invalid_config" }), {
    allowed: false,
    reason: "配置损坏：请重新保存有效配置",
  });
});
