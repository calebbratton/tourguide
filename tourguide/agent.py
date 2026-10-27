"""API engine: a manual tool-use loop on the Claude API (needs ANTHROPIC_API_KEY).

The default engine is claude_code.py, which runs on a Claude subscription instead."""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

import anthropic

from .repo import Repo, RepoError
from .prompts import SYSTEM_PROMPT, brief, fix_request
from .schema import WALKTHROUGH_SCHEMA, validate

MODEL = "claude-opus-5-5"
MAX_TURNS = 80




def _tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "list_dir",
            "description": "List a directory of the repository as a tree with line counts. Returns text.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Repo-relative directory, default '.'"},
                    "depth": {"type": "integer", "description": "Levels to show, 1-4, default 2"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "read_file",
            "description": "Read a text file with line numbers (at most 400 lines per call).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "search",
            "description": "Regex search across the repository. Returns path:line: text for each match.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Python regular expression"},
                    "glob": {"type": "string", "description": "Optional filename filter like '*.py' or 'src/**'"},
                    "path": {"type": "string", "description": "Optional directory to search under"},
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
        },
        {
            "name": "submit_walkthrough",
            "description": "Submit the finished walkthrough. Returns 'accepted' or a list of problems to fix.",
            "input_schema": WALKTHROUGH_SCHEMA,
            "eager_input_streaming": True,
        },
    ]


def _run_tool(repo: Repo, name: str, args: dict[str, Any]) -> str:
    if name == "list_dir":
        return repo.list_dir(args.get("path", "."), args.get("depth", 2))
    if name == "read_file":
        return repo.read_file(args["path"], args.get("start_line", 1), args.get("end_line"))
    if name == "search":
        return repo.search(args["pattern"], args.get("glob"), args.get("path", "."))
    raise RepoError(f"unknown tool {name!r}")


def generate_api(
    repo: Repo,
    *,
    repo_url: str | None = None,
    focus: str | None = None,
    scope: str | None = None,
    max_steps: int = 16,
    model: str = MODEL,
    effort: str = "high",
    log: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr),
    client: anthropic.Anthropic | None = None,
) -> dict[str, Any]:
    """Run the agent until it submits a walkthrough that passes validation."""
    client = client or anthropic.Anthropic()
    messages: list[dict[str, Any]] = [{"role": "user", "content": brief(max_steps, repo_url, focus, scope)}]

    for turn in range(1, MAX_TURNS + 1):
        with client.beta.messages.stream(
            model=model,
            max_tokens=64000,
            system=SYSTEM_PROMPT + "\n\nIn this session, deliver the walkthrough by calling the submit_walkthrough tool.",
            tools=_tools(),
            messages=messages,
            output_config={"effort": effort},
            cache_control={"type": "ephemeral"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            response = stream.get_final_message()

        if response.stop_reason == "refusal":
            raise RuntimeError(f"Claude declined to continue: {response.stop_details}")
        messages.append({"role": "assistant", "content": response.content})

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason == "max_tokens":
            # A cut-off tool call cannot be trusted; ask for a smaller submission.
            results = [
                {"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                 "content": "Your response hit the output limit before this call finished. Retry with shorter text."}
                for b in tool_uses
            ]
            messages.append({"role": "user", "content": results or "You hit the output limit. Continue, more concisely."})
            continue
        if not tool_uses:
            messages.append({"role": "user", "content": "Keep going. When the tour is ready, call submit_walkthrough."})
            continue

        results = []
        accepted: dict[str, Any] | None = None
        for block in tool_uses:
            args = block.input if isinstance(block.input, dict) else {}
            if block.name == "submit_walkthrough":
                problems = validate(args, repo, scope=scope)
                if problems:
                    log(f"[turn {turn}] submission had {len(problems)} problem(s); sending them back")
                    results.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                    "content": fix_request(problems)})
                else:
                    accepted = args
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": "accepted"})
                continue
            log(f"[turn {turn}] {block.name} {json.dumps(args)[:120]}")
            try:
                output = _run_tool(repo, block.name, args)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
            except (RepoError, KeyError, ValueError, TypeError) as exc:
                results.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True, "content": str(exc)})
        if accepted is not None:
            return accepted
        messages.append({"role": "user", "content": results})

    raise RuntimeError(f"No valid walkthrough after {MAX_TURNS} turns")
