// Plain-Node tests for the parts of the extension that don't need VS Code.
const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { Workspace, validate, referencedFiles } = require("../out/tour");
const { ClaudeCodeBackend, extractTour } = require("../out/claudeCode");

const fixtures = path.join(__dirname, "..", "..", "tests", "fixtures");
const mini = new Workspace(path.join(fixtures, "mini"));
const tour = () => JSON.parse(fs.readFileSync(path.join(fixtures, "mini_walkthrough.json"), "utf8"));

test("valid tour passes, like the Python validator", () => {
  assert.deepStrictEqual(validate(tour(), mini), []);
});

test("bad ranges, topics, links and scope are reported", () => {
  const t = tour();
  t.steps[1].highlights[0].end = 99;
  t.steps[2].topic = "nope";
  t.steps[1].links[0].url = "docs/x.md";
  const problems = validate(t, mini, "app/sub").join("\n");
  assert.match(problems, /outside app\/store.py \(1-16\)/);
  assert.match(problems, /'nope' is not one of/);
  assert.match(problems, /absolute http\(s\) URL/);
  assert.match(problems, /outside the tour's scope/);
});

test("referenced files include inline code links", () => {
  assert.deepStrictEqual(referencedFiles(tour()), ["app/agent.py", "app/store.py"]);
});

test("paths cannot escape the workspace", () => {
  assert.throws(() => mini.readText("../mini_walkthrough.json"));
});

test("extractTour prefers structured output", () => {
  assert.deepStrictEqual(extractTour({ structured_output: { title: "x" } }), { title: "x" });
  assert.deepStrictEqual(extractTour({ result: 'Here: {"title": "y"}' }), { title: "y" });
});

test("ask streams text from a claude-compatible CLI", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tg-"));
  const fake = path.join(dir, "claude");
  fs.writeFileSync(fake, `#!/usr/bin/env node
const ev = t => console.log(JSON.stringify({ type: "stream_event", event: { type: "content_block_delta", delta: { type: "text_delta", text: t } } }));
if (process.argv.includes("--version")) { console.log("1.0"); process.exit(0); }
ev("Hello "); ev("there"); console.log(JSON.stringify({ type: "result", is_error: false, result: "Hello there" }));`);
  fs.chmodSync(fake, 0o755);
  const backend = await ClaudeCodeBackend.detect(fake);
  assert.ok(backend);
  const seen = [];
  const text = await backend.ask("hi", { onText: t => seen.push(t) });
  assert.strictEqual(text, "Hello there");
  assert.deepStrictEqual(seen, ["Hello ", "Hello there"]);
  assert.strictEqual(await ClaudeCodeBackend.detect(path.join(dir, "missing")), null);
});
