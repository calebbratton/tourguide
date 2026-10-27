"""Default engine: run Claude through Claude Code (`claude -p`), so usage counts against a Claude
subscription instead of API credits. Needs the `claude` CLI installed and signed in."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from typing import Any, Callable, Iterator

from .prompts import SYSTEM_PROMPT, brief, fix_request
from .repo import Repo
from .schema import WALKTHROUGH_SCHEMA, validate

READ_ONLY_TOOLS = "Read,Grep,Glob"
FIX_ROUNDS = 3


class ClaudeCodeError(RuntimeError):
    pass


def _claude() -> str:
    exe = shutil.which("claude")
    if not exe:
        raise ClaudeCodeError("The `claude` CLI was not found. Install Claude Code and sign in, or use --engine api.")
    return exe


def _run_json(args: list[str], cwd: str) -> dict[str, Any]:
    proc = subprocess.run([_claude(), *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0 and not proc.stdout.strip():
        raise ClaudeCodeError(proc.stderr.strip() or f"claude exited with {proc.returncode}")
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ClaudeCodeError(f"Unexpected output from claude: {proc.stdout[:500]}") from exc
    if out.get("is_error"):
        raise ClaudeCodeError(str(out.get("result") or out))
    return out


def _walkthrough_from(out: dict[str, Any]) -> dict[str, Any]:
    if isinstance(out.get("structured_output"), dict):
        return out["structured_output"]
    text = str(out.get("result", ""))
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ClaudeCodeError("Claude did not return a walkthrough")
    return json.loads(text[start : end + 1])


def generate_cc(
    repo: Repo,
    *,
    repo_url: str | None = None,
    focus: str | None = None,
    scope: str | None = None,
    max_steps: int = 16,
    model: str | None = None,
    log: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr),
) -> dict[str, Any]:
    """Explore the repo with Claude Code's read-only tools and return a validated walkthrough."""
    session = str(uuid.uuid4())
    common = ["--output-format", "json", "--tools", READ_ONLY_TOOLS, "--allowedTools", READ_ONLY_TOOLS,
              "--json-schema", json.dumps(WALKTHROUGH_SCHEMA)]
    if model:
        common += ["--model", model]

    log("Claude is reading the repository (this takes a few minutes)...")
    out = _run_json(["-p", brief(max_steps, repo_url, focus, scope), "--session-id", session,
                     "--append-system-prompt", SYSTEM_PROMPT, *common], cwd=str(repo.root))
    for round_no in range(FIX_ROUNDS + 1):
        walkthrough = _walkthrough_from(out)
        problems = validate(walkthrough, repo, scope=scope)
        if not problems:
            cost = out.get("total_cost_usd")
            log(f"Done in {out.get('num_turns', '?')} turns" + (f" (about ${cost:.2f} at API prices; billed to your plan)" if cost else ""))
            return walkthrough
        if round_no == FIX_ROUNDS:
            break
        log(f"Fixing {len(problems)} problem(s), e.g. {problems[0]}")
        out = _run_json(["-p", fix_request(problems), "--resume", session, *common], cwd=str(repo.root))
    raise ClaudeCodeError("The walkthrough still has problems:\n- " + "\n- ".join(problems[:20]))


def ask_cc(prompt: str, *, quick: bool = False, model: str | None = None) -> Iterator[str]:
    """Stream a short answer with no tools and no saved session."""
    args = [_claude(), "-p", prompt, "--output-format", "stream-json", "--verbose", "--include-partial-messages",
            "--tools", "", "--no-session-persistence"]
    chosen = model or ("haiku" if quick else None)
    if chosen:
        args += ["--model", chosen]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    streamed = False
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "stream_event":
                delta = event.get("event", {}).get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    streamed = True
                    yield delta["text"]
            elif event.get("type") == "result":
                if event.get("is_error"):
                    raise ClaudeCodeError(str(event.get("result")))
                if not streamed and event.get("result"):
                    yield str(event["result"])
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
