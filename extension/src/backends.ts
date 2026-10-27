// AI backends. A backend answers live questions and (where it can) generates tours.
// Tours themselves never need a backend: prepared tours play with none.
import * as vscode from "vscode";
import { AskOptions, Backend, BackendError, ClaudeCodeBackend } from "./claudeCode";

export { Backend, BackendError } from "./claudeCode";

// ------------------------------------------------------------------ chat models the editor provides

export class EditorModelBackend implements Backend {
  readonly canGenerate = false;
  constructor(private readonly model: vscode.LanguageModelChat) {}
  get name() { return this.model.name || this.model.vendor; }

  static async detect(): Promise<EditorModelBackend | null> {
    if (!vscode.lm || typeof vscode.lm.selectChatModels !== "function") return null;
    try {
      const models = await vscode.lm.selectChatModels({});
      return models.length ? new EditorModelBackend(models[0]) : null;
    } catch { return null; }
  }

  async ask(prompt: string, opts: AskOptions): Promise<string> {
    const cts = new vscode.CancellationTokenSource();
    opts.signal?.addEventListener("abort", () => cts.cancel());
    try {
      const res = await this.model.sendRequest([vscode.LanguageModelChatMessage.User(prompt)], {}, cts.token);
      let text = "";
      for await (const part of res.text) { text += part; opts.onText?.(text); }
      return text;
    } catch (e) {
      if (cts.token.isCancellationRequested) throw new BackendError("cancelled", "cancelled");
      if (e instanceof vscode.LanguageModelError && e.code === vscode.LanguageModelError.NoPermissions.name) throw new BackendError(e.message, "not_granted");
      throw new BackendError((e as Error).message);
    } finally { cts.dispose(); }
  }
}

export async function pickBackend(): Promise<Backend | null> {
  const cfg = vscode.workspace.getConfiguration("tourguide");
  const choice = cfg.get<string>("backend", "auto");
  const exe = cfg.get<string>("claudePath", "claude") || "claude";
  const model = cfg.get<string>("model", "") || undefined;
  if (choice === "none") return null;
  if (choice === "claude-code" || choice === "auto") {
    const cc = await ClaudeCodeBackend.detect(exe, model);
    if (cc || choice === "claude-code") return cc;
  }
  return EditorModelBackend.detect();
}
