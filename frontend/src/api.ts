import type { ImportRecord } from "./domain";
export async function loadImportDetails(
  records: ImportRecord[],
  getDetail: (id: string) => Promise<ImportRecord>,
): Promise<ImportRecord[]> {
  return Promise.all(
    records.map(async (record) => {
      if (record.manifest_verified !== true)
        return {
          ...record,
          files: [],
          manifest_verified: false,
          integrity_error: record.integrity_error || "导入清单未通过校验",
        };
      try {
        const detail = await getDetail(record.import_id);
        return detail.manifest_verified === true
          ? detail
          : {
              ...detail,
              files: [],
              manifest_verified: false,
              integrity_error: detail.integrity_error || "导入详情未通过校验",
            };
      } catch (error) {
        return {
          ...record,
          files: [],
          manifest_verified: false,
          integrity_error: String(error),
        };
      }
    }),
  );
}
export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: string, structuredDetail?: unknown) {
    super(`${status} · ${detail}`);
    this.status = status;
    this.detail = structuredDetail;
  }
}
async function detail(r: Response) {
  try {
    const j = await r.json();
    return typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
  } catch {
    return "请求失败";
  }
}
export async function request<T>(
  path: string,
  body?: unknown,
  method = "GET",
  base = "/api",
  timeoutMs = 30000,
): Promise<T> {
  const r = await fetch(base + path, {
    method,
    signal: AbortSignal.timeout(timeoutMs),
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    const payload = await r.json().catch(() => undefined);
    throw new ApiError(
      r.status,
      typeof payload?.detail === "string"
        ? payload.detail
        : JSON.stringify(payload?.detail ?? "请求失败"),
      payload?.detail,
    );
  }
  return r.json();
}
export function upload<T>(
  path: string,
  file: File,
  fields: Record<string, string>,
  progress: (n: number | null) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest(),
      data = new FormData();
    data.append("file", file);
    Object.entries(fields).forEach(([k, v]) => {
      if (v) data.append(k, v);
    });
    x.open("POST", "/api" + path);
    x.timeout = 120000;
    x.upload.onprogress = (e) =>
      progress(
        e.lengthComputable ? Math.round((e.loaded / e.total) * 100) : null,
      );
    x.upload.onload = () => progress(100);
    x.onerror = () =>
      reject(new Error("连接中断，结果未知；请刷新核对记录后再重试。"));
    x.ontimeout = () =>
      reject(new Error("上传超时，结果未知；请刷新核对记录。"));
    x.onload = () => {
      try {
        const j = JSON.parse(x.responseText);
        x.status >= 200 && x.status < 300
          ? resolve(j)
          : reject(
              new ApiError(
                x.status,
                typeof j.detail === "string"
                  ? j.detail
                  : JSON.stringify(j.detail),
              ),
            );
      } catch {
        reject(new Error("无效服务器响应，请刷新核对结果。"));
      }
    };
    x.send(data);
  });
}
export async function limitedBlob(path: string, maxBytes = 1048576) {
  const r = await fetch("/api" + path);
  if (!r.ok) throw new ApiError(r.status, await detail(r));
  if (Number(r.headers.get("content-length")) > maxBytes) {
    await r.body?.cancel();
    throw new Error("预览上限 1 MiB，请下载原件。");
  }
  const reader = r.body?.getReader();
  if (!reader) throw new Error("浏览器不支持流式预览");
  const parts: Uint8Array<ArrayBuffer>[] = [];
  let n = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      n += value.byteLength;
      if (n > maxBytes) {
        await reader.cancel();
        throw new Error("预览上限 1 MiB，请下载原件。");
      }
      parts.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  return new Blob(parts, {
    type: r.headers.get("content-type") || "application/octet-stream",
  });
}
export function saveBlob(b: Blob, name: string) {
  const url = URL.createObjectURL(b),
    a = document.createElement("a");
  a.href = url;
  a.download = name.replace(/[\\/:*?"<>|\x00-\x1f]/g, "_");
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
