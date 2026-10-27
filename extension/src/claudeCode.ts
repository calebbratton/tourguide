// Claude Code backend: runs `claude -p`, so usage counts against the user's Claude plan.
// Kept free of the vscode module so it can be tested with plain Node.
import { spawn } from "child_process";
import { randomUUID } from "crypto";
import { brief, fixRequest, Shared } from "./shared";
import { Tour, validate, Workspace } from "./tour";

export interface AskOptions { quick?: boolean; signal?: AbortSignal; onText?: (text: string) => void }
export interface GenerateOptions { focus?: string; scope?: string; steps: number; repoUrl?: string; log: (msg: string) => void; signal?: AbortSignal }

export interface Backend {
  readonly name: string;
  readonly canGenerate: boolean;
  ask(prompt: string, opts: AskOptions): Promise<string>;
  generate?(ws: Workspace, shared: Shared, opts: GenerateOptions): Promise<Tour>;
}

export class BackendError extends Error {
  constructor(message: string, readonly code = "upstream_error") { super(message); }
}


export class ClaudeCodeBackend implements Backend {
  readonly name = "Claude Code";
  readonly canGenerate = true;
  constructor(private readonly exe: string, private readonly model?: string) {}

  static async detect(exe: string, model?: string): Promise<ClaudeCodeBackend | null> {
    const ok = await new Promise<boolean>(resolve => {
      const p = spawn(exe, ["--version"], { stdio: "ignore" });
      p.on("error", () => resolve(false));
      p.on("exit", code => resolve(code === 0));
    });
    return ok ? new ClaudeCodeBackend(exe, model) : null;
  }

  ask(prompt: string, opts: AskOptions): Promise<string> {
    const args = ["-p", prompt, "--output-format", "stream-json", "--verbose", "--include-partial-messages",
      "--tools", "", "--no-session-persistence"];
    if (opts.quick) args.push("--model", "haiku");
    return new Promise((resolve, reject) => {
      const proc = spawn(this.exe, args, { stdio: ["ignore", "pipe", "pipe"] });
      let text = "", buf = "", finished = false;
      const done = (fn: () => void) => { if (!finished) { finished = true; fn(); } };
      opts.signal?.addEventListener("abort", () => { proc.kill(); done(() => reject(new BackendError("cancelled", "cancelled"))); });
      proc.on("error", e => done(() => reject(new BackendError(e.message))));
      proc.stdout.setEncoding("utf8");
      proc.stdout.on("data", (chunk: string) => {
        buf += chunk;
        const lines = buf.split("\n"); buf = lines.pop() || "";
        for (const line of lines) {
          let ev: any;
          try { ev = JSON.parse(line); } catch { continue; }
          if (ev.type === "stream_event" && ev.event?.delta?.type === "text_delta") {
            text += ev.event.delta.text; opts.onText?.(text);
          } else if (ev.type === "result") {
            if (ev.is_error) done(() => reject(new BackendError(String(ev.result))));
            else { if (!text && ev.result) { text = String(ev.result); opts.onText?.(text); } done(() => resolve(text)); }
          }
        }
      });
      proc.on("exit", code => done(() => (text ? resolve(text) : reject(new BackendError(`claude exited with ${code}`)))));
    });
  }

  private runJson(args: string[], cwd: string, signal?: AbortSignal): Promise<any> {
    return new Promise((resolve, reject) => {
      const proc = spawn(this.exe, args, { cwd, stdio: ["ignore", "pipe", "pipe"] });
      let out = "", err = "";
      signal?.addEventListener("abort", () => { proc.kill(); reject(new BackendError("cancelled", "cancelled")); });
      proc.stdout.on("data", d => (out += d));
      proc.stderr.on("data", d => (err += d));
      proc.on("error", e => reject(new BackendError(e.message)));
      proc.on("exit", code => {
        try {
          const json = JSON.parse(out);
          if (json.is_error) return reject(new BackendError(String(json.result)));
          resolve(json);
        } catch { reject(new BackendError(err.trim() || `claude exited with ${code}`)); }
      });
    });
  }

  async generate(ws: Workspace, shared: Shared, opts: GenerateOptions): Promise<Tour> {
    const session = randomUUID();
    const tools = "Read,Grep,Glob";
    const common = ["--output-format", "json", "--tools", tools, "--allowedTools", tools, "--json-schema", JSON.stringify(shared.schema)];
    if (this.model) common.push("--model", this.model);
    opts.log("Claude is reading the repository…");
    let out = await this.runJson(["-p", brief(opts.steps, opts.repoUrl, opts.focus, opts.scope), "--session-id", session,
      "--append-system-prompt", shared.systemPrompt, ...common], ws.root, opts.signal);
    for (let round = 0; ; round++) {
      const tour = extractTour(out);
      const problems = validate(tour, ws, opts.scope);
      if (!problems.length) return tour;
      if (round === 3) throw new BackendError("The tour still has problems:\n- " + problems.slice(0, 10).join("\n- "));
      opts.log(`Fixing ${problems.length} problem(s) in the tour…`);
      out = await this.runJson(["-p", fixRequest(problems), "--resume", session, ...common], ws.root, opts.signal);
    }
  }
}

export function extractTour(out: any): Tour {
  if (out && typeof out.structured_output === "object" && out.structured_output) return out.structured_output as Tour;
  const text = String(out?.result ?? "");
  const a = text.indexOf("{"), b = text.lastIndexOf("}");
  if (a < 0 || b < a) throw new BackendError("Claude did not return a tour");
  return JSON.parse(text.slice(a, b + 1)) as Tour;
}

