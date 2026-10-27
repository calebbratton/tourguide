"""Command line entry point: generate, validate, render and serve walkthroughs."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from .repo import Repo
from .schema import validate


def _open_repo(source: str, workdir: Path) -> tuple[Repo, str, str | None, str | None]:
    """Accept a local path or a git URL. Returns (repo, name, web_url, commit)."""
    if re.match(r"^(https?://|git@)", source):
        dest = workdir / "repo"
        subprocess.run(["git", "clone", "--depth", "1", source, str(dest)], check=True)
        path, url = dest, re.sub(r"\.git$", "", source)
    else:
        path, url = Path(source), None
        if not url:
            try:
                remote = subprocess.run(["git", "-C", str(path), "remote", "get-url", "origin"],
                                        capture_output=True, text=True, check=True).stdout.strip()
                if remote.startswith("git@github.com:"):
                    remote = "https://github.com/" + remote.split(":", 1)[1]
                url = re.sub(r"\.git$", "", remote) if remote.startswith("http") else None
            except (subprocess.CalledProcessError, FileNotFoundError):
                url = None
    try:
        ref = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        ref = None
    name = "/".join(url.rstrip("/").split("/")[-2:]) if url else Path(path).resolve().name
    return Repo(path), name, url, ref


def cmd_generate(args: argparse.Namespace) -> int:
    from .render import bundle

    with tempfile.TemporaryDirectory() as tmp:
        repo, name, url, ref = _open_repo(args.repo, Path(tmp))
        if args.engine == "api":
            from .agent import generate_api

            kwargs = {"model": args.model} if args.model else {}
            walkthrough = generate_api(repo, repo_url=url, focus=args.focus, scope=args.scope, max_steps=args.steps, effort=args.effort, **kwargs)
        else:
            from .claude_code import generate_cc

            walkthrough = generate_cc(repo, repo_url=url, focus=args.focus, scope=args.scope, max_steps=args.steps, model=args.model)
        out = bundle(walkthrough, repo, name=name, url=url, ref=ref)
        out["scope"] = args.scope
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {args.output} ({len(out['steps'])} steps). Next: tourguide serve {args.output}", file=sys.stderr)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.walkthrough).read_text(encoding="utf-8"))
    problems = validate(data, Repo(args.repo))
    for p in problems:
        print(f"- {p}")
    print("OK" if not problems else f"{len(problems)} problem(s)", file=sys.stderr)
    return 1 if problems else 0


def cmd_bundle(args: argparse.Namespace) -> int:
    """Turn a hand-written walkthrough (no files embedded) into a viewer-ready bundle."""
    from .render import bundle

    data = json.loads(Path(args.walkthrough).read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        repo, name, url, ref = _open_repo(args.repo, Path(tmp))
        problems = validate(data, repo)
        if problems:
            print("\n".join(f"- {p}" for p in problems), file=sys.stderr)
            return 1
        out = bundle(data, repo, name=args.name or name, url=args.url or url, ref=ref)
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {args.output}", file=sys.stderr)
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    from .render import render_html

    data = json.loads(Path(args.walkthrough).read_text(encoding="utf-8"))
    Path(args.output).write_text(render_html(data, standalone=not args.fragment), encoding="utf-8")
    print(f"Wrote {args.output}", file=sys.stderr)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .render import render_html
    from .server import ENDPOINT, editor_config, serve

    data = json.loads(Path(args.walkthrough).read_text(encoding="utf-8"))
    editor = editor_config(args.editor, args.repo)
    page = render_html(data, live_endpoint=None if args.offline else ENDPOINT, editor=editor)
    serve(page, host=args.host, port=args.port, engine=args.engine, model=args.model, editor=args.editor, repo_root=args.repo)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tourguide", description="Adaptive guided walkthroughs of code repositories.")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="explore a repo with Claude and write a walkthrough bundle")
    g.add_argument("repo", help="local path or git URL")
    g.add_argument("-o", "--output", default="walkthrough.json")
    g.add_argument("--focus", help="what the tour should concentrate on, in plain words")
    g.add_argument("--scope", help="only tour files under this folder, e.g. src/sim")
    g.add_argument("--steps", type=int, default=16, help="target number of steps (default 16)")
    g.add_argument("--engine", default="claude-code", choices=["claude-code", "api"],
                   help="claude-code (default) uses your Claude plan via `claude -p`; api needs ANTHROPIC_API_KEY")
    g.add_argument("--model", help="model to use, e.g. sonnet or opus (default: your Claude Code default)")
    g.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"], help="api engine only")
    g.set_defaults(func=cmd_generate)

    v = sub.add_parser("validate", help="check a walkthrough's files and line numbers against a repo")
    v.add_argument("walkthrough")
    v.add_argument("repo")
    v.set_defaults(func=cmd_validate)

    b = sub.add_parser("bundle", help="embed repo files into a hand-written walkthrough")
    b.add_argument("walkthrough")
    b.add_argument("repo")
    b.add_argument("-o", "--output", default="walkthrough.json")
    b.add_argument("--name")
    b.add_argument("--url")
    b.set_defaults(func=cmd_bundle)

    r = sub.add_parser("render", help="write the viewer as a single HTML file")
    r.add_argument("walkthrough")
    r.add_argument("-o", "--output", default="walkthrough.html")
    r.add_argument("--fragment", action="store_true", help="omit the document head (for hosts that add their own)")
    r.set_defaults(func=cmd_render)

    s = sub.add_parser("serve", help="open the viewer locally with live answers and editor links")
    s.add_argument("walkthrough")
    s.add_argument("--repo", help="local checkout of the repo, for 'Open in editor' links")
    s.add_argument("--editor", help="vscode, cursor, windsurf, zed, or a command such as "
                   "\"nvim --server /tmp/nvim.sock --remote-send ':e +{line} {file}<CR>'\"")
    s.add_argument("--engine", default="claude-code", choices=["claude-code", "api"])
    s.add_argument("--model", help="model for live answers (default: your Claude Code default)")
    s.add_argument("--offline", action="store_true", help="no live answers; prepared explanations only")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
