import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { pickBackend } from "./backends";
import { TourPanel } from "./panel";
import { shared } from "./shared";
import { slugify, Tour, validate, Workspace } from "./tour";

const TOURS_DIR = ".tours";

export function activate(ctx: vscode.ExtensionContext) {
  ctx.subscriptions.push(
    vscode.commands.registerCommand("tourguide.openTour", (uri?: vscode.Uri) => openTour(ctx, uri)),
    vscode.commands.registerCommand("tourguide.generateTour", () => generateTour(ctx)),
    vscode.commands.registerCommand("tourguide.next", () => TourPanel.current?.goto(1)),
    vscode.commands.registerCommand("tourguide.previous", () => TourPanel.current?.goto(-1)),
    vscode.commands.registerCommand("tourguide.askAboutSelection", () => TourPanel.current?.askAboutSelection()),
    { dispose: () => TourPanel.current?.dispose() },
  );
}

export function deactivate() { TourPanel.current?.dispose(); }

function workspace(ctx: vscode.ExtensionContext): Workspace | null {
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder || folder.uri.scheme !== "file") {
    vscode.window.showWarningMessage("Open a folder first. Tour Guide works on the files of a local workspace.");
    return null;
  }
  return new Workspace(folder.uri.fsPath, new Set(shared(ctx.extensionPath).ignoredDirs));
}

async function openTour(ctx: vscode.ExtensionContext, uri?: vscode.Uri) {
  const ws = workspace(ctx);
  if (!ws) return;
  let file = uri?.fsPath;
  if (!file) {
    const found = await vscode.workspace.findFiles(`${TOURS_DIR}/*.json`);
    const items = found.map(u => {
      let title = path.basename(u.fsPath);
      try { title = (JSON.parse(fs.readFileSync(u.fsPath, "utf8")) as Tour).title || title; } catch { /* show the file name */ }
      return { label: title, description: vscode.workspace.asRelativePath(u), uri: u };
    });
    const generate = { label: "$(sparkle) Generate a new tour…", description: "", uri: undefined as vscode.Uri | undefined };
    const pick = await vscode.window.showQuickPick([...items, generate], { placeHolder: items.length ? "Pick a tour" : "No tours in .tours/ yet" });
    if (!pick) return;
    if (!pick.uri) return generateTour(ctx);
    file = pick.uri.fsPath;
  }
  let tour: Tour;
  try { tour = JSON.parse(fs.readFileSync(file, "utf8")); } catch (e) {
    vscode.window.showErrorMessage(`Couldn't read ${path.basename(file)}: ${(e as Error).message}`);
    return;
  }
  const problems = validate(tour, ws);
  if (problems.length) {
    const choice = await vscode.window.showWarningMessage(
      `This tour doesn't match the code any more (${problems.length} problem(s), e.g. ${problems[0]}). The code may have changed since it was written.`,
      "Open anyway", "Regenerate");
    if (choice === "Regenerate") return generateTour(ctx, tour.scope || undefined);
    if (choice !== "Open anyway") return;
  }
  TourPanel.open(ctx, ws, file, tour, await pickBackend());
}

async function generateTour(ctx: vscode.ExtensionContext, presetScope?: string) {
  const ws = workspace(ctx);
  if (!ws) return;
  const backend = await pickBackend();
  if (!backend || !backend.canGenerate || !backend.generate) {
    const more = "How to set up Claude Code";
    const choice = await vscode.window.showWarningMessage(
      "Generating a tour needs the Claude Code CLI (`claude`), installed and signed in. Prepared tours in .tours/ play without it.", more);
    if (choice === more) vscode.env.openExternal(vscode.Uri.parse("https://docs.claude.com/en/docs/claude-code/setup"));
    return;
  }
  const scope = presetScope ?? await vscode.window.showInputBox({
    title: "Generate a tour (1/2)", prompt: "Limit the tour to one folder, or leave empty for the whole repository", placeHolder: "e.g. src/sim",
  });
  if (scope === undefined) return;
  const focus = await vscode.window.showInputBox({
    title: "Generate a tour (2/2)", prompt: "Anything the tour should focus on? (optional)", placeHolder: "e.g. the LangGraph agent and how tools are called",
  });
  if (focus === undefined) return;
  const cfg = vscode.workspace.getConfiguration("tourguide");
  const s = shared(ctx.extensionPath);

  await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "Tour Guide", cancellable: true }, async (progress, token) => {
    const ctl = new AbortController();
    token.onCancellationRequested(() => ctl.abort());
    try {
      const tour = await backend.generate!(ws, s, {
        scope: scope.trim().replace(/^\/+|\/+$/g, "") || undefined,
        focus: focus.trim() || undefined,
        steps: cfg.get<number>("steps", 16),
        log: msg => progress.report({ message: msg }),
        signal: ctl.signal,
      });
      tour.scope = scope.trim() || null;
      tour.source_files = ws.sourceFiles(s.codeExtensions);
      tour.repo = { name: path.basename(ws.root), url: null, ref: null };
      const dir = path.join(ws.root, TOURS_DIR);
      fs.mkdirSync(dir, { recursive: true });
      let file = path.join(dir, slugify(scope.trim() || tour.title) + ".json");
      for (let n = 2; fs.existsSync(file); n++) file = path.join(dir, `${slugify(scope.trim() || tour.title)}-${n}.json`);
      fs.writeFileSync(file, JSON.stringify(tour, null, 2));
      TourPanel.open(ctx, ws, file, tour, backend);
      vscode.window.showInformationMessage(`Saved the tour to ${path.relative(ws.root, file)}. Commit it so others can take it too.`);
    } catch (e) {
      if (!ctl.signal.aborted) vscode.window.showErrorMessage(`Couldn't generate the tour: ${(e as Error).message}`);
    }
  });
}
