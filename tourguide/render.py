"""Bundle a walkthrough with the code it shows and render the viewer page."""

from __future__ import annotations

import html
import json
from importlib import resources
from typing import Any

from .repo import Repo, source_files
from .schema import referenced_files

STANDALONE_HEAD = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
    "</head><body>"
)


def bundle(walkthrough: dict[str, Any], repo: Repo, *, name: str, url: str | None, ref: str | None) -> dict[str, Any]:
    """Attach repo metadata and the text of every file the tour shows."""
    out = dict(walkthrough)
    out["version"] = 1
    out["repo"] = {"name": name, "url": url, "ref": ref}
    out["files"] = {path: repo.read_text(path) for path in referenced_files(walkthrough)}
    out["source_files"] = source_files(repo)
    return out


def render_html(bundled: dict[str, Any], *, standalone: bool = True, live_endpoint: str | None = None,
                editor: dict[str, Any] | None = None) -> str:
    """Fill the viewer template. `standalone` adds a document head for opening the file directly."""
    data = dict(bundled)
    data["live"] = {"endpoint": live_endpoint} if live_endpoint else None
    data["editor"] = editor
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    template = resources.files("tourguide.viewer").joinpath("template.html").read_text(encoding="utf-8")
    page = template.replace("__TITLE__", html.escape(data.get("title", "Repo tour")), 1).replace("__DATA__", payload, 1)
    return STANDALONE_HEAD + page + "</body></html>" if standalone else page
