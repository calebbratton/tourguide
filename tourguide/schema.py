"""The walkthrough format, and checks that tie it to the real repository."""

from __future__ import annotations

import re
from typing import Any

from .repo import Repo, RepoError

DEPTHS = ("brief", "standard", "deep")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
# Markdown links inside explanations that point at code: [text](src/app.py#L10-L20)
CODE_LINK = re.compile(r"\]\((?!https?://|#|mailto:)([^)\s#]+)(?:#L(\d+)(?:-L(\d+))?)?\)")

_highlight = {
    "type": "object",
    "properties": {
        "start": {"type": "integer", "description": "First highlighted line, 1-based."},
        "end": {"type": "integer", "description": "Last highlighted line, inclusive."},
        "label": {"type": "string", "description": "A few words naming what these lines do."},
    },
    "required": ["start", "end", "label"],
    "additionalProperties": False,
}

_explanation = {
    "type": "object",
    "description": "The same step written at three depths. All markdown.",
    "properties": {
        "brief": {"type": "string", "description": "1-3 sentences for someone who already knows this kind of code."},
        "standard": {"type": "string", "description": "A clear explanation for a working developer new to this repo."},
        "deep": {"type": "string", "description": "Internals, design trade-offs, edge cases and how it connects to the rest of the system."},
    },
    "required": list(DEPTHS),
    "additionalProperties": False,
}

WALKTHROUGH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string", "description": "Markdown. What the repository is for and how the tour is organised."},
        "topics": {
            "type": "array",
            "description": "3-8 subject areas the steps belong to. The viewer sets a depth per topic.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "lowercase-slug"},
                    "label": {"type": "string"},
                    "description": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"},
                                 "description": "Words a learner might use for this topic, e.g. crud, database, sql."},
                },
                "required": ["id", "label", "description", "keywords"],
                "additionalProperties": False,
            },
        },
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "lowercase-slug, unique"},
                    "title": {"type": "string"},
                    "topic": {"type": "string", "description": "One of the topic ids."},
                    "file": {"type": ["string", "null"], "description": "Repo-relative path, or null for an overview step."},
                    "highlights": {"type": "array", "items": _highlight},
                    "explanation": _explanation,
                    "links": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"title": {"type": "string"}, "url": {"type": "string"}},
                            "required": ["title", "url"],
                            "additionalProperties": False,
                        },
                    },
                    "check": {
                        "type": ["object", "null"],
                        "description": "A quick question that tests understanding of this step, with a short answer.",
                        "properties": {"question": {"type": "string"}, "answer": {"type": "string"}},
                        "required": ["question", "answer"],
                        "additionalProperties": False,
                    },
                },
                "required": ["id", "title", "topic", "file", "highlights", "explanation", "links", "check"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "summary", "topics", "steps"],
    "additionalProperties": False,
}


def validate(walkthrough: dict[str, Any], repo: Repo, scope: str | None = None) -> list[str]:
    """Return a list of human-readable problems; empty means valid."""
    errors: list[str] = []
    if not isinstance(walkthrough, dict):
        return ["walkthrough must be an object"]

    for key in ("title", "summary"):
        if not isinstance(walkthrough.get(key), str) or not walkthrough[key].strip():
            errors.append(f"`{key}` must be a non-empty string")

    topics = walkthrough.get("topics")
    topic_ids: set[str] = set()
    if not isinstance(topics, list) or not topics:
        errors.append("`topics` must be a non-empty list")
        topics = []
    for i, topic in enumerate(topics):
        tid = topic.get("id") if isinstance(topic, dict) else None
        if not isinstance(tid, str) or not SLUG.match(tid):
            errors.append(f"topics[{i}].id must be a lowercase slug")
            continue
        if tid in topic_ids:
            errors.append(f"topic id {tid!r} is duplicated")
        topic_ids.add(tid)
        if not topic.get("label"):
            errors.append(f"topic {tid!r} needs a label")

    steps = walkthrough.get("steps")
    if not isinstance(steps, list) or not steps:
        return errors + ["`steps` must be a non-empty list"]

    seen: set[str] = set()
    for i, step in enumerate(steps):
        where = f"steps[{i}]"
        if not isinstance(step, dict):
            errors.append(f"{where} must be an object")
            continue
        sid = step.get("id")
        if not isinstance(sid, str) or not SLUG.match(sid):
            errors.append(f"{where}.id must be a lowercase slug")
        elif sid in seen:
            errors.append(f"{where}.id {sid!r} is duplicated")
        else:
            seen.add(sid)
            where = f"step {sid!r}"
        if not step.get("title"):
            errors.append(f"{where} needs a title")
        if step.get("topic") not in topic_ids:
            errors.append(f"{where}.topic {step.get('topic')!r} is not one of {sorted(topic_ids)}")

        expl = step.get("explanation")
        if not isinstance(expl, dict):
            errors.append(f"{where}.explanation must have brief, standard and deep")
        else:
            for depth in DEPTHS:
                text = expl.get(depth)
                if not isinstance(text, str) or not text.strip():
                    errors.append(f"{where}.explanation.{depth} is empty")
                else:
                    errors.extend(_check_code_links(text, repo, f"{where}.explanation.{depth}"))

        file = step.get("file")
        highlights = step.get("highlights") or []
        if scope and file and not file.startswith(scope.strip("/") + "/"):
            errors.append(f"{where}.file {file!r} is outside the tour's scope `{scope}`")
        if file is None:
            if highlights:
                errors.append(f"{where} has highlights but no file")
        else:
            try:
                total = repo.line_count(file)
            except RepoError as exc:
                errors.append(f"{where}.file: {exc}")
                total = None
            if total is not None:
                if not highlights:
                    errors.append(f"{where} names a file but highlights no lines")
                for h in highlights:
                    s, e = h.get("start"), h.get("end")
                    if not (isinstance(s, int) and isinstance(e, int)) or not 1 <= s <= e <= total:
                        errors.append(f"{where}: highlight {s}-{e} is outside {file} (1-{total})")

        for link in step.get("links") or []:
            url = link.get("url", "") if isinstance(link, dict) else ""
            if not url.startswith(("https://", "http://")):
                errors.append(f"{where}: link {url!r} must be an absolute http(s) URL")

        check = step.get("check")
        if check is not None and not (isinstance(check, dict) and check.get("question") and check.get("answer")):
            errors.append(f"{where}.check needs a question and an answer, or null")
    return errors


def _check_code_links(text: str, repo: Repo, where: str) -> list[str]:
    errors = []
    for m in CODE_LINK.finditer(text):
        path, start, end = m.group(1), m.group(2), m.group(3)
        try:
            total = repo.line_count(path)
        except RepoError as exc:
            errors.append(f"{where}: code link ({path}) - {exc}")
            continue
        if start:
            s, e = int(start), int(end or start)
            if not 1 <= s <= e <= total:
                errors.append(f"{where}: code link {path}#L{s}-L{e} is outside 1-{total}")
    return errors


def referenced_files(walkthrough: dict[str, Any]) -> list[str]:
    """Every repo file the viewer needs to show: step files plus code links in explanations."""
    files: list[str] = []
    for step in walkthrough.get("steps", []):
        if step.get("file"):
            files.append(step["file"])
        for text in (step.get("explanation") or {}).values():
            files.extend(m.group(1) for m in CODE_LINK.finditer(text or ""))
    return list(dict.fromkeys(files))
