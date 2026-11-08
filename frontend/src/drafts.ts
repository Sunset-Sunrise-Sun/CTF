/** Human drafts are editing state, never execution evidence. No automatic PUTs. */
export interface HumanDraft {
  challenge_id: string;
  content: string;
  version: number;
  sha256: string;
  size: number;
  saved_at: string;
  is_human_draft: true;
}
export interface DraftIO {
  read(): Promise<HumanDraft>;
  write(body: { content: string; base_version: number }): Promise<HumanDraft>;
  getLocal(): string | null;
  setLocal(content: string): void;
  clearLocal(): void;
  getBase(): number | null;
  setBase(version: number | null): void;
}
export const MAX_DRAFT_BYTES = 1048576;
type CacheStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;
// Keep the original localStorage key readable. A per-window session copy also
// survives reload when another window saves and clears the shared legacy key.
export function createDraftCache(
  key: string,
  shared: CacheStorage,
  tab: CacheStorage,
) {
  return {
    getLocal: () => tab.getItem(key) ?? shared.getItem(key),
    setLocal: (content: string) => {
      tab.setItem(key, content);
      shared.setItem(key, content);
    },
    clearLocal: () => {
      const own = tab.getItem(key) ?? shared.getItem(key);
      tab.removeItem(key);
      if (shared.getItem(key) === own) shared.removeItem(key);
    },
    getBase: () => {
      const value = JSON.parse(
        tab.getItem(key + ":server-version") ??
          shared.getItem(key + ":server-version") ??
          "null",
      );
      return Number.isSafeInteger(value) && value >= 0 ? value : null;
    },
    setBase: (version: number | null) => {
      const value = JSON.stringify(version);
      tab.setItem(key + ":server-version", value);
      shared.setItem(key + ":server-version", value);
    },
  };
}
export function draftBytes(content: string) {
  return new TextEncoder().encode(content).byteLength;
}
export class DraftSession {
  content = "";
  server: HumanDraft | null = null;
  current: HumanDraft | null = null;
  baseVersion: number | null = null;
  state: "unsaved" | "saving" | "saved" | "error" | "conflict" = "unsaved";
  loadState: "loading" | "ready" | "unavailable" = "loading";
  origin: "empty" | "generated" | "local" | "human" = "empty";
  migration = false;
  hasConflict = false;
  memoryLocal = false;
  error = "";
  storageWarning = "";
  io: DraftIO;
  constructor(io: DraftIO) {
    this.io = io;
  }
  get canSave() {
    return (
      this.loadState === "ready" &&
      this.baseVersion !== null &&
      !this.hasConflict &&
      this.state !== "saving"
    );
  }
  persist() {
    try {
      this.io.setLocal(this.content);
      this.io.setBase(this.baseVersion);
      this.storageWarning = "";
    } catch {
      this.storageWarning =
        "浏览器存储失败，编辑内容仍在内存，请立即下载 Markdown 备份。";
    }
  }
  edit(content: string) {
    this.content = content;
    this.origin = "local";
    this.memoryLocal = true;
    if (!this.hasConflict && this.state !== "saving") this.state = "unsaved";
    this.persist();
  }
  async load() {
    this.loadState = "loading";
    this.error = "";
    let local: string | null = this.memoryLocal ? this.content : null;
    try {
      if (local === null) local = this.io.getLocal();
    } catch {
      this.storageWarning = "无法读取浏览器草稿；请保留当前内容并下载备份。";
    }
    if (local !== null) {
      this.content = local;
      this.origin = "local";
      this.memoryLocal = true;
    }
    try {
      const server = await this.io.read();
      this.server = server;
      this.current = null;
      this.baseVersion = server.version;
      this.migration = false;
      this.loadState = "ready";
      if (local !== null && local !== server.content) {
        try {
          this.baseVersion = this.io.getBase() ?? server.version;
        } catch {}
        this.current = server;
        this.hasConflict = true;
        this.state = "conflict";
      } else {
        this.content = server.content;
        this.origin = "human";
        this.state = "saved";
        this.hasConflict = false;
      }
    } catch (e) {
      if ((e as { status?: number }).status === 404) {
        this.server = null;
        this.baseVersion = 0;
        this.current = null;
        this.hasConflict = false;
        this.loadState = "ready";
        this.state = "unsaved";
        this.migration = local !== null;
        if (local === null && !this.memoryLocal) {
          this.content = "";
          this.origin = "empty";
        }
      } else {
        this.loadState = "unavailable";
        this.baseVersion = null;
        this.state = "error";
        this.error = "读取服务器人工稿失败；未清空本地编辑内容。" + String(e);
      }
    }
  }
  useGenerated(content: string) {
    if (this.origin !== "empty" && this.origin !== "generated") return false;
    this.content = content;
    this.origin = "generated";
    this.state = "unsaved";
    return true;
  }
  async save() {
    if (!this.canSave) return;
    this.persist();
    if (!this.content.trim()) {
      this.state = "error";
      this.error = "人工稿不能为空（422 内容规则）";
      return;
    }
    if (draftBytes(this.content) > MAX_DRAFT_BYTES) {
      this.state = "error";
      this.error = "人工稿超过 1 MiB UTF-8 字节上限（413 内容规则），未发送。";
      return;
    }
    const sent = this.content,
      version = this.baseVersion!;
    this.state = "saving";
    this.error = "";
    try {
      const saved = await this.io.write({
        content: sent,
        base_version: version,
      });
      this.server = saved;
      this.baseVersion = saved.version;
      this.current = null;
      this.hasConflict = false;
      this.migration = false;
      if (this.content === sent) {
        this.content = saved.content;
        this.origin = "human";
        this.state = "saved";
        this.memoryLocal = false;
        try {
          this.io.clearLocal();
          this.io.setBase(saved.version);
        } catch {
          this.storageWarning = "服务器已保存，但浏览器缓存清理失败。";
        }
      } else {
        this.state = "unsaved";
        this.persist();
      }
    } catch (e) {
      const problem = e as { status?: number; detail?: unknown };
      if (
        problem.status === 409 &&
        problem.detail &&
        typeof problem.detail === "object" &&
        Object.hasOwn(problem.detail, "current")
      ) {
        this.current = (
          problem.detail as { current: HumanDraft | null }
        ).current;
        this.hasConflict = true;
        this.state = "conflict";
        this.error =
          "版本冲突，编辑内容已保留。请明确选择或合并，不会自动重试。";
      } else {
        this.state = "error";
        this.error =
          "保存失败，结果可能未知；本地草稿已保留。重新读取服务器核对后再保存。" +
          String(e);
      }
    }
  }
  // Explicit user actions: neither method issues a PUT.
  keepLocalOnLatest() {
    if (!this.hasConflict) return;
    this.server = this.current;
    this.baseVersion = this.current?.version ?? 0;
    this.hasConflict = false;
    this.current = null;
    this.state = "unsaved";
    this.migration = false;
    this.error = "";
    this.persist();
  }
  useServer() {
    if (!this.hasConflict) return;
    this.server = this.current;
    this.baseVersion = this.current?.version ?? 0;
    this.content = this.current?.content ?? "";
    this.origin = this.current ? "human" : "empty";
    this.state = this.current ? "saved" : "unsaved";
    this.hasConflict = false;
    this.current = null;
    this.memoryLocal = false;
    this.migration = false;
    this.error = "";
    try {
      this.io.clearLocal();
      this.io.setBase(this.baseVersion);
    } catch {
      this.storageWarning = "浏览器缓存清理失败，请下载服务器稿备份。";
    }
  }
}
