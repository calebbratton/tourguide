// The tour panel: the shared viewer in a webview, driving real editor tabs and highlights.
import * as crypto from "crypto";
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { Backend, BackendError } from "./backends";
import { Highlight, referencedFiles, Tour, Workspace } from "./tour";

const CDN = "https://cdnjs.cloudflare.com/ajax/libs/";
const LIBS: Record<string, string> = {
  [CDN + "highlight.js/11.9.0/highlight.min.js"]: "highlight.min.js",
  [CDN + "marked/12.0.2/marked.min.js"]: "marked.min.js",
  [CDN + "dompurify/3.1.6/purify.min.js"]: "purify.min.js",
};

export class TourPanel {
  static current: TourPanel | undefined;

  private readonly panel: vscode.WebviewPanel;
  private readonly highlight: vscode.TextEditorDecorationType;
  private readonly label: vscode.TextEditorDecorationType;
  private readonly calls = new Map<number, AbortController>();
  private readonly disposables: vscode.Disposable[] = [];
  private readonly status: vscode.StatusBarItem;
  private shown: { path: string; ranges: Highlight[] } | null = null;

  static open(ctx: vscode.ExtensionContext, ws: Workspace, tourFile: string, tour: Tour, backend: Backend | null) {
    TourPanel.current?.dispose();
    TourPanel.current = new TourPanel(ctx, ws, tourFile, tour, backend);
  }

  private constructor(
    private readonly ctx: vscode.ExtensionContext,
    private readonly ws: Workspace,
    private readonly tourFile: string,
    private readonly tour: Tour,
    private readonly backend: Backend | null,
  ) {
    this.panel = vscode.window.createWebviewPanel("tourguide.tour", tour.title, { viewColumn: vscode.ViewColumn.Beside, preserveFocus: false }, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [vscode.Uri.joinPath(ctx.extensionUri, "media")],
    });
    this.highlight = vscode.window.createTextEditorDecorationType({
      isWholeLine: true,
      backgroundColor: "rgba(255, 214, 10, 0.16)",
      borderColor: "rgba(224, 180, 0, 0.9)",
      borderStyle: "solid",
      borderWidth: "0 0 0 3px",
      overviewRulerColor: "rgba(224, 180, 0, 0.9)",
      overviewRulerLane: vscode.OverviewRulerLane.Full,
    });
    this.label = vscode.window.createTextEditorDecorationType({
      after: { margin: "0 0 0 2em", color: new vscode.ThemeColor("editorCodeLens.foreground"), fontStyle: "italic" },
    });
    this.status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
    this.status.command = "tourguide.next";

    this.panel.webview.html = this.html();
    this.panel.onDidDispose(() => this.dispose(), null, this.disposables);
    this.panel.webview.onDidReceiveMessage(m => this.onMessage(m), null, this.disposables);
    this.panel.onDidChangeViewState(e => vscode.commands.executeCommand("setContext", "tourguide.active", e.webviewPanel.visible), null, this.disposables);
    vscode.window.onDidChangeTextEditorSelection(e => this.onSelection(e), null, this.disposables);
    vscode.window.onDidChangeVisibleTextEditors(() => this.redecorate(), null, this.disposables);
    vscode.commands.executeCommand("setContext", "tourguide.active", true);
  }

  goto(dir: 1 | -1) { this.panel.webview.postMessage({ type: "goto", dir }); }

  askAboutSelection() {
    this.panel.reveal(undefined, false);
    this.post({ type: "focusAsk" });
  }

  dispose() {
    if (TourPanel.current === this) TourPanel.current = undefined;
    for (const c of this.calls.values()) c.abort();
    this.clearDecorations();
    this.highlight.dispose(); this.label.dispose(); this.status.dispose();
    vscode.commands.executeCommand("setContext", "tourguide.active", false);
    while (this.disposables.length) this.disposables.pop()?.dispose();
    this.panel.dispose();
  }

  // ---------------------------------------------------------------- webview

  private html(): string {
    const webview = this.panel.webview;
    const media = vscode.Uri.joinPath(this.ctx.extensionUri, "media");
    const nonce = crypto.randomBytes(16).toString("base64");
    const data: Tour = { ...this.tour, files: { ...(this.tour.files || {}) }, live: null, editor: null };
    for (const rel of referencedFiles(this.tour)) {
      try { data.files![rel] = this.ws.readText(rel); } catch { /* keep any embedded copy */ }
    }
    if (!data.repo) data.repo = { name: path.basename(this.ws.root), url: null, ref: null };
    let page = fs.readFileSync(path.join(media.fsPath, "viewer.html"), "utf8");
    page = page.replace(/<link[^>]+fonts\.(googleapis|gstatic)\.com[^>]*>\n?/g, "");
    for (const [cdn, file] of Object.entries(LIBS)) page = page.replace(cdn, webview.asWebviewUri(vscode.Uri.joinPath(media, "libs", file)).toString());
    page = page.replace(/<script(?=[ >])/g, `<script nonce="${nonce}"`);
    page = page.replace("__TITLE__", escapeHtml(this.tour.title)).replace("__DATA__", () => JSON.stringify(data).replace(/</g, "\\u003c"));
    const csp = `default-src 'none'; img-src ${webview.cspSource} data:; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';`;
    return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}">` +
      `<meta name="viewport" content="width=device-width,initial-scale=1"></head><body>${page}</body></html>`;
  }

  private post(msg: unknown) { this.panel.webview.postMessage(msg); }

  private async onMessage(m: any) {
    switch (m?.type) {
      case "ready":
        this.post({ type: "init", live: !!this.backend, backend: this.backend?.name,
          profile: this.ctx.workspaceState.get("tourguide.profile:" + this.tourFile) });
        break;
      case "show":
        await this.show(m.path, m.ranges || []);
        break;
      case "reveal":
        if (m.path) await this.reveal(m.path, m.line, true);
        break;
      case "clear":
        this.shown = null; this.clearDecorations(); this.status.hide();
        break;
      case "step":
        this.status.text = `$(book) ${m.position}/${m.total} ${m.title}`;
        this.status.tooltip = "Tour Guide: next step";
        this.status.show();
        break;
      case "profile":
        await this.ctx.workspaceState.update("tourguide.profile:" + this.tourFile, m.profile);
        break;
      case "ask":
        await this.ask(m.id, String(m.prompt), !!m.quick);
        break;
      case "cancel":
        this.calls.get(m.id)?.abort();
        break;
    }
  }

  private async ask(id: number, prompt: string, quick: boolean) {
    if (!this.backend) return this.post({ type: "error", id, code: "not_granted", message: "No AI backend" });
    const ctl = new AbortController();
    this.calls.set(id, ctl);
    try {
      const text = await this.backend.ask(prompt, { quick, signal: ctl.signal, onText: t => this.post({ type: "chunk", id, text: t }) });
      this.post({ type: "done", id, text });
    } catch (e) {
      const code = e instanceof BackendError ? e.code : "upstream_error";
      if (code !== "cancelled") this.post({ type: "error", id, code, message: (e as Error).message });
    } finally { this.calls.delete(id); }
  }

  // ---------------------------------------------------------------- editor

  private async show(rel: string, ranges: Highlight[]) {
    this.shown = { path: rel, ranges };
    const first = ranges[0];
    await this.reveal(rel, first ? first.start : 1, false);
  }

  private async reveal(rel: string, line: number, select: boolean) {
    let uri: vscode.Uri;
    try { uri = vscode.Uri.file(this.ws.resolve(rel)); } catch { return; }
    const doc = await vscode.workspace.openTextDocument(uri);
    const column = this.panel.viewColumn === vscode.ViewColumn.One ? vscode.ViewColumn.Two : vscode.ViewColumn.One;
    const editor = await vscode.window.showTextDocument(doc, { viewColumn: column, preserveFocus: true, preview: true });
    this.decorate(editor);
    const ln = Math.max(0, Math.min(doc.lineCount - 1, line - 1));
    const range = this.shown && this.shown.path === rel ? this.shown.ranges.find(r => r.start === line) : undefined;
    const end = range ? Math.min(doc.lineCount - 1, range.end - 1) : ln;
    editor.revealRange(new vscode.Range(ln, 0, end, 0), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
    if (select) editor.selection = new vscode.Selection(ln, 0, ln, 0);
  }

  private decorate(editor: vscode.TextEditor) {
    const rel = path.relative(this.ws.root, editor.document.uri.fsPath).split(path.sep).join("/");
    if (!this.shown || this.shown.path !== rel) { editor.setDecorations(this.highlight, []); editor.setDecorations(this.label, []); return; }
    const last = editor.document.lineCount - 1;
    const clamp = (n: number) => Math.max(0, Math.min(last, n - 1));
    editor.setDecorations(this.highlight, this.shown.ranges.map(r => new vscode.Range(clamp(r.start), 0, clamp(r.end), 0)));
    editor.setDecorations(this.label, this.shown.ranges.filter(r => r.label).map(r => ({
      range: new vscode.Range(clamp(r.start), Number.MAX_SAFE_INTEGER, clamp(r.start), Number.MAX_SAFE_INTEGER),
      renderOptions: { after: { contentText: "◀ " + r.label } },
    })));
  }

  private redecorate() { for (const e of vscode.window.visibleTextEditors) this.decorate(e); }

  private clearDecorations() {
    for (const e of vscode.window.visibleTextEditors) { e.setDecorations(this.highlight, []); e.setDecorations(this.label, []); }
  }

  private onSelection(e: vscode.TextEditorSelectionChangeEvent) {
    if (e.textEditor.document.uri.scheme !== "file") return;
    const rel = path.relative(this.ws.root, e.textEditor.document.uri.fsPath);
    if (rel.startsWith("..") || path.isAbsolute(rel)) return;
    const sel = e.selections[0];
    if (!sel || sel.isEmpty) return this.post({ type: "selection", path: null });
    const file = rel.split(path.sep).join("/");
    this.post({ type: "selection", path: file, start: sel.start.line + 1, end: sel.end.line + (sel.end.character === 0 && sel.end.line > sel.start.line ? 0 : 1),
      text: e.textEditor.document.getText(new vscode.Range(sel.start.line, 0, sel.end.line, Number.MAX_SAFE_INTEGER)) });
  }
}

function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}
