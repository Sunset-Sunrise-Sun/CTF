export type ModelServiceStatus = {
  provider: "deepseek";
  base_url: string;
  default_base_url: string;
  model_id: string;
  model_name: string;
  default_model_id: string;
  default_model_name: string;
  key_configured: boolean;
  key_source: "settings" | "environment" | null;
  key_storage_available: boolean;
  key_error: string | null;
  config_error: string | null;
  network_enabled: boolean;
  network_setting: boolean;
  network_env_override: boolean;
  env_key_custom_base_url_authorized: boolean;
  env_key_custom_base_url_authorization_required: boolean;
};

export const DEFAULT_MODEL_ID = "deepseek-flash";

export const MODEL_NAME_TO_ID: Record<string, string> = {
  "DeepSeek-V4.1-Flash": "deepseek-flash",
  "DeepSeek-V4-Pro": "deepseek-v4-pro",
};

export function modelIdFromInput(value: string): string {
  const cleaned = value.trim();
  if (!cleaned) return DEFAULT_MODEL_ID;
  return MODEL_NAME_TO_ID[cleaned] ?? cleaned;
}

export function modelDisplayName(status: ModelServiceStatus): string {
  return status.model_name || status.model_id;
}

export function keySourceLabel(status: ModelServiceStatus): string {
  if (!status.key_configured) return "未配置 API Key";
  if (status.key_source === "environment")
    return "使用服务器环境变量中的 API Key";
  if (status.key_source === "settings")
    return "已保存在本机（Windows DPAPI 加密）";
  return "已配置（来源未知）";
}

export function envKeyAuthorizationRequired(
  status: ModelServiceStatus,
): boolean {
  return (
    status.key_source === "environment" &&
    status.base_url.replace(/\/+$/, "") !==
      status.default_base_url.replace(/\/+$/, "") &&
    !status.env_key_custom_base_url_authorized
  );
}

export function canTestConnection(status: ModelServiceStatus): {
  allowed: boolean;
  reason: string;
} {
  if (status.config_error)
    return { allowed: false, reason: "配置损坏：请重新保存有效配置" };
  if (envKeyAuthorizationRequired(status))
    return {
      allowed: false,
      reason: "环境变量 API Key 用于自定义地址需要先明确授权",
    };
  if (!status.key_configured)
    return { allowed: false, reason: "请先保存 API Key" };
  if (!status.network_enabled)
    return { allowed: false, reason: "请先开启「联网调用」" };
  return { allowed: true, reason: "" };
}

export function networkSettingNote(status: ModelServiceStatus): string {
  if (status.network_env_override)
    return "服务器环境变量 CTF_MODEL_NETWORK_ENABLED 已强制开启；页面开关仍会保存，但不能覆盖该环境变量。";
  if (status.network_setting)
    return "已开启：保存配置不会自动改变该开关，需在此页面显式操作。";
  return "默认关闭；保存 API 配置不会自动开启联网。";
}

export function settingsErrorText(error: unknown): string {
  const text = String(error ?? "");
  if (text.includes("credential_store_unavailable"))
    return "当前系统凭证存储不可用，API Key 未保存。";
  if (text.includes("credential_store_error"))
    return "已保存的 API Key 无法读取（可能属于其他 Windows 用户）。";
  if (text.includes("invalid_base_url"))
    return "API 地址无效：必须为 HTTPS，或本机回环 HTTP 地址。";
  if (text.includes("invalid_model_id")) return "模型名称格式无效。";
  if (text.includes("invalid_api_key")) return "API Key 格式无效。";
  if (text.includes("api_key_conflict")) return "不能同时设置和清除 API Key。";
  if (text.includes("config_invalid"))
    return "配置文件损坏，模型调用已禁用；请重新保存有效配置。";
  if (text.includes("env_key_custom_base_url_not_authorized"))
    return "环境变量 API Key 尚未授权发送到当前自定义 API 地址。";
  return text || "设置操作失败。";
}
