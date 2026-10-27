"""`tourguide serve`: the viewer on localhost, with live answers and "Open in editor" links.

Live answers go through Claude Code (`claude -p`, billed to your Claude plan) by default,
or the Claude API with --engine api."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Iterator

ENDPOINT = "/api/sample"
OPEN_ENDPOINT = "/api/open"

# URL schemes the browser can follow directly. Anything else is treated as a command template.
EDITOR_URLS = {
    "vscode": "vscode://file/{file}:{line}",
    "cursor": "cursor://file/{file}:{line}",
    "windsurf": "windsurf://file/{file}:{line}",
    "zed": "zed://file/{file}:{line}",
}


def _api_asker(model: str | None) -> Callable[[str, bool], Iterator[str]]:
    import anthropic

    from .agent import MODEL

    client = anthropic.Anthropic()

    def ask(prompt: str, quick: bool) -> Iterator[str]:
        with client.beta.messages.stream(
            model=model or MODEL,
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "low" if quick else "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            yield from stream.text_stream

    return ask


def _cc_asker(model: str | None) -> Callable[[str, bool], Iterator[str]]:
    from .claude_code import ask_cc

    return lambda prompt, quick: ask_cc(prompt, quick=quick, model=model)


def editor_config(editor: str | None, repo_root: str | None) -> dict | None:
    """What the viewer needs to show an "Open in editor" link."""
    if not editor or not repo_root:
        return None
    root = str(Path(repo_root).resolve())
    if editor in EDITOR_URLS:
        return {"name": editor, "url": EDITOR_URLS[editor], "root": root}
    return {"name": shlex.split(editor)[0], "endpoint": OPEN_ENDPOINT, "root": root}


def serve(page_html: str, *, host: str = "127.0.0.1", port: int = 8765, engine: str = "claude-code",
          model: str | None = None, editor: str | None = None, repo_root: str | None = None) -> None:
    ask = _api_asker(model) if engine == "api" else _cc_asker(model)
    page = page_html.encode("utf-8")
    root = Path(repo_root).resolve() if repo_root else None
    command = editor if editor and editor not in EDITOR_URLS else None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            pass

        def _json_body(self) -> dict:
            return json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")

        def do_GET(self) -> None:
            if self.path.split("?")[0] not in ("/", "/index.html"):
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def do_POST(self) -> None:
            if self.path == OPEN_ENDPOINT:
                return self._open()
            if self.path != ENDPOINT:
                self.send_error(404)
                return
            try:
                body = self._json_body()
                prompt = str(body["prompt"])[:250_000]
            except (ValueError, KeyError):
                self.send_error(400, "expected JSON with a prompt")
                return
            self.send_response(200)
            self.send_header("content-type", "text/plain; charset=utf-8")
            self.send_header("cache-control", "no-store")
            self.end_headers()
            try:
                for chunk in ask(prompt, bool(body.get("quick"))):
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass  # the viewer pressed Stop
            except Exception as exc:  # report and end the stream; the viewer shows a retry message
                print(f"Live answer failed: {exc}", file=sys.stderr)

        def _open(self) -> None:
            if not (command and root):
                self.send_error(404)
                return
            try:
                body = self._json_body()
                target = (root / str(body["path"])).resolve()
                line = int(body.get("line") or 1)
                if root not in target.parents or not target.is_file():
                    raise ValueError("path outside the repository")
            except (ValueError, KeyError):
                self.send_error(400)
                return
            argv = [part.format(file=str(target), line=line) for part in shlex.split(command)]
            subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Tour Guide is running at http://{host}:{port}  (Ctrl+C to stop)", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
