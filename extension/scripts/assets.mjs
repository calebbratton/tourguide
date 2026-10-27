// Copies the shared viewer, prompt and schema from the Python package, plus the viewer's
// libraries from node_modules, into media/. The Python package is the single source of truth.
import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const pkg = join(root, "..", "tourguide");
mkdirSync(join(root, "media", "libs"), { recursive: true });

copyFileSync(join(pkg, "viewer", "template.html"), join(root, "media", "viewer.html"));
const shared = execFileSync("python3", ["-c",
  "import json,sys; sys.path.insert(0, sys.argv[1]);" +
  "from tourguide.prompts import SYSTEM_PROMPT; from tourguide.schema import WALKTHROUGH_SCHEMA;" +
  "from tourguide.repo import CODE_EXTENSIONS, IGNORED_DIRS;" +
  "print(json.dumps({'systemPrompt': SYSTEM_PROMPT, 'schema': WALKTHROUGH_SCHEMA," +
  " 'codeExtensions': sorted(CODE_EXTENSIONS), 'ignoredDirs': sorted(IGNORED_DIRS)}))",
  join(pkg, "..")], { encoding: "utf8" });
writeFileSync(join(root, "media", "shared.json"), shared);

const libs = {
  "highlight.min.js": "@highlightjs/cdn-assets/highlight.min.js",
  "marked.min.js": "marked/marked.min.js",
  "purify.min.js": "dompurify/dist/purify.min.js",
};
for (const [name, from] of Object.entries(libs)) copyFileSync(join(root, "node_modules", from), join(root, "media", "libs", name));
console.log("assets ready");
