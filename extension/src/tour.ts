// The tour format, validation against the workspace, and repository facts the viewer uses.
// Mirrors tourguide/schema.py.
import * as fs from "fs";
import * as path from "path";

export interface Highlight { start: number; end: number; label: string }
export interface Step {
  id: string;
  title: string;
  topic: string;
  file: string | null;
  highlights: Highlight[];
  explanation: { brief: string; standard: string; deep: string };
  links: { title: string; url: string }[];
  check: { question: string; answer: string } | null;
}
export interface Tour {
  title: string;
  summary: string;
  topics: { id: string; label: string; description: string; keywords: string[] }[];
  steps: Step[];
  repo?: { name: string; url: string | null; ref: string | null };
  scope?: string | null;
  files?: Record<string, string>;
  source_files?: { path: string; lines: number }[];
  [key: string]: unknown;
}

const SLUG = /^[a-z0-9][a-z0-9-]{0,47}$/;
const CODE_LINK = /\]\((?!https?:\/\/|#|mailto:)([^)\s#]+)(?:#L(\d+)(?:-L(\d+))?)?\)/g;

export class Workspace {
  constructor(readonly root: string, private readonly ignored: Set<string> = new Set([".git", "node_modules"])) {}

  resolve(rel: string): string {
    const full = path.resolve(this.root, rel.replace(/^\/+/, ""));
    if (full !== this.root && !full.startsWith(this.root + path.sep)) throw new Error(`${rel} is outside the workspace`);
    return full;
  }

  readText(rel: string): string {
    const full = this.resolve(rel);
    const stat = fs.statSync(full, { throwIfNoEntry: false });
    if (!stat || !stat.isFile()) throw new Error(`${rel} is not a file`);
    if (stat.size > 512_000) throw new Error(`${rel} is larger than 512 KB`);
    return fs.readFileSync(full, "utf8");
  }

  lineCount(rel: string): number {
    const text = this.readText(rel);
    if (!text) return 0;
    const lines = text.split(/\r\n|\r|\n/);
    return /(\r\n|\r|\n)$/.test(text) ? lines.length - 1 : lines.length;
  }

  *walk(dir = this.root): Generator<string> {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (this.ignored.has(entry.name)) continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) yield* this.walk(full);
      else if (entry.isFile()) yield path.relative(this.root, full).split(path.sep).join("/");
    }
  }

  sourceFiles(extensions: string[]): { path: string; lines: number }[] {
    const exts = new Set(extensions);
    const out: { path: string; lines: number }[] = [];
    for (const rel of this.walk()) {
      if (!exts.has(path.extname(rel).toLowerCase())) continue;
      try { out.push({ path: rel, lines: this.lineCount(rel) }); } catch { /* too large or unreadable */ }
    }
    return out;
  }
}

export function validate(tour: Tour, ws: Workspace, scope?: string): string[] {
  const errors: string[] = [];
  if (!tour || typeof tour !== "object") return ["walkthrough must be an object"];
  for (const key of ["title", "summary"] as const) if (typeof tour[key] !== "string" || !tour[key].trim()) errors.push(`\`${key}\` must be a non-empty string`);

  const topicIds = new Set<string>();
  if (!Array.isArray(tour.topics) || !tour.topics.length) errors.push("`topics` must be a non-empty list");
  for (const [i, t] of (tour.topics || []).entries()) {
    if (!t || typeof t.id !== "string" || !SLUG.test(t.id)) { errors.push(`topics[${i}].id must be a lowercase slug`); continue; }
    if (topicIds.has(t.id)) errors.push(`topic id '${t.id}' is duplicated`);
    topicIds.add(t.id);
    if (!t.label) errors.push(`topic '${t.id}' needs a label`);
  }
  if (!Array.isArray(tour.steps) || !tour.steps.length) return [...errors, "`steps` must be a non-empty list"];

  const seen = new Set<string>();
  tour.steps.forEach((s, i) => {
    let where = `steps[${i}]`;
    if (!s || typeof s !== "object") { errors.push(`${where} must be an object`); return; }
    if (typeof s.id !== "string" || !SLUG.test(s.id)) errors.push(`${where}.id must be a lowercase slug`);
    else if (seen.has(s.id)) errors.push(`${where}.id '${s.id}' is duplicated`);
    else { seen.add(s.id); where = `step '${s.id}'`; }
    if (!s.title) errors.push(`${where} needs a title`);
    if (!topicIds.has(s.topic)) errors.push(`${where}.topic '${s.topic}' is not one of ${[...topicIds].sort().join(", ")}`);

    for (const depth of ["brief", "standard", "deep"] as const) {
      const text = s.explanation && s.explanation[depth];
      if (typeof text !== "string" || !text.trim()) { errors.push(`${where}.explanation.${depth} is empty`); continue; }
      for (const m of text.matchAll(CODE_LINK)) {
        try {
          const total = ws.lineCount(m[1]);
          if (m[2]) {
            const a = +m[2], b = +(m[3] || m[2]);
            if (!(1 <= a && a <= b && b <= total)) errors.push(`${where}.explanation.${depth}: code link ${m[1]}#L${a}-L${b} is outside 1-${total}`);
          }
        } catch (e) { errors.push(`${where}.explanation.${depth}: code link (${m[1]}) - ${(e as Error).message}`); }
      }
    }

    const hl = s.highlights || [];
    if (scope && s.file && !s.file.startsWith(scope.replace(/^\/+|\/+$/g, "") + "/")) errors.push(`${where}.file '${s.file}' is outside the tour's scope \`${scope}\``);
    if (s.file == null) { if (hl.length) errors.push(`${where} has highlights but no file`); }
    else {
      let total: number | null = null;
      try { total = ws.lineCount(s.file); } catch (e) { errors.push(`${where}.file: ${(e as Error).message}`); }
      if (total !== null) {
        if (!hl.length) errors.push(`${where} names a file but highlights no lines`);
        for (const h of hl) {
          if (!(Number.isInteger(h.start) && Number.isInteger(h.end) && 1 <= h.start && h.start <= h.end && h.end <= total)) {
            errors.push(`${where}: highlight ${h.start}-${h.end} is outside ${s.file} (1-${total})`);
          }
        }
      }
    }
    for (const l of s.links || []) if (!/^https?:\/\//.test(l.url || "")) errors.push(`${where}: link '${l.url}' must be an absolute http(s) URL`);
    if (s.check != null && !(s.check.question && s.check.answer)) errors.push(`${where}.check needs a question and an answer, or null`);
  });
  return errors;
}

export function referencedFiles(tour: Tour): string[] {
  const files: string[] = [];
  for (const s of tour.steps || []) {
    if (s.file) files.push(s.file);
    for (const text of Object.values(s.explanation || {})) for (const m of String(text).matchAll(CODE_LINK)) files.push(m[1]);
  }
  return [...new Set(files)];
}

export function slugify(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48) || "tour";
}
