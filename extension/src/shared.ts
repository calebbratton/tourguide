// Prompt, schema and file rules shared with the Python package (copied into media/ by scripts/assets.mjs).
import * as fs from "fs";
import * as path from "path";

export interface Shared {
  systemPrompt: string;
  schema: Record<string, unknown>;
  codeExtensions: string[];
  ignoredDirs: string[];
}

let cached: Shared | undefined;

export function shared(extensionRoot: string): Shared {
  if (!cached) cached = JSON.parse(fs.readFileSync(path.join(extensionRoot, "media", "shared.json"), "utf8")) as Shared;
  return cached;
}

export function brief(maxSteps: number, repoUrl?: string, focus?: string, scope?: string): string {
  const lines = [`Write a walkthrough of the repository in the current directory (about ${maxSteps} steps, at most ${maxSteps + 4}).`];
  if (repoUrl) lines.push(`The repository is published at ${repoUrl}; use it for links to the repo's own docs.`);
  if (focus) lines.push(`The person who asked for this tour wants it to focus on: ${focus}`);
  if (scope) {
    lines.push(`This is a focused tour of \`${scope}\`: every step's file must be under \`${scope}\`. ` +
      "Read other parts of the repo only for context, and go deeper on this area than a whole-repo tour would.");
  }
  return lines.join("\n");
}

export function fixRequest(problems: string[]): string {
  return "The walkthrough has problems. Fix them and deliver the whole walkthrough again:\n- " + problems.slice(0, 60).join("\n- ");
}
