"""Read-only access to a repository on disk, used by the agent's tools and the validator."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path

IGNORED_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "dist", "build", ".next", ".turbo", "target", ".idea", ".vscode", "coverage",
}
MAX_FILE_BYTES = 512_000
MAX_READ_LINES = 400
MAX_SEARCH_HITS = 80


class RepoError(Exception):
    """A tool call the agent can recover from (bad path, bad range, ...)."""


@dataclass
class Repo:
    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()
        if not self.root.is_dir():
            raise RepoError(f"{self.root} is not a directory")

    # ---- paths -------------------------------------------------------------

    def resolve(self, rel: str) -> Path:
        rel = (rel or ".").strip().lstrip("/")
        path = (self.root / rel).resolve()
        if path != self.root and self.root not in path.parents:
            raise RepoError(f"{rel!r} is outside the repository")
        return path

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix() or "."

    @staticmethod
    def _ignored(path: Path) -> bool:
        return any(part in IGNORED_DIRS for part in path.parts)

    def is_text_file(self, path: Path) -> bool:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return False
        with path.open("rb") as fh:
            return b"\0" not in fh.read(4096)

    def iter_files(self, under: str = "."):
        base = self.resolve(under)
        for path in sorted(base.rglob("*")):
            rel_parts = path.relative_to(self.root).parts
            if self._ignored(Path(*rel_parts)) or not path.is_file():
                continue
            yield path

    # ---- reads -------------------------------------------------------------

    def read_text(self, rel: str) -> str:
        path = self.resolve(rel)
        if not path.is_file():
            raise RepoError(f"{rel!r} is not a file")
        if not self.is_text_file(path):
            raise RepoError(f"{rel!r} is binary or larger than {MAX_FILE_BYTES} bytes")
        return path.read_text(encoding="utf-8", errors="replace")

    def line_count(self, rel: str) -> int:
        return len(self.read_text(rel).splitlines())

    # ---- agent tools -------------------------------------------------------

    def list_dir(self, path: str = ".", depth: int = 2) -> str:
        base = self.resolve(path)
        if not base.is_dir():
            raise RepoError(f"{path!r} is not a directory")
        depth = max(1, min(int(depth), 4))
        lines: list[str] = []

        def walk(d: Path, level: int) -> None:
            entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            for entry in entries:
                if entry.name in IGNORED_DIRS:
                    continue
                indent = "  " * level
                if entry.is_dir():
                    lines.append(f"{indent}{entry.name}/")
                    if level + 1 < depth:
                        walk(entry, level + 1)
                else:
                    size = entry.stat().st_size
                    n = ""
                    if self.is_text_file(entry):
                        n = f" ({len(entry.read_text(encoding='utf-8', errors='replace').splitlines())} lines)"
                    else:
                        n = f" ({size} bytes, binary/large)"
                    lines.append(f"{indent}{entry.name}{n}")
                if len(lines) > 600:
                    return

        walk(base, 0)
        if len(lines) > 600:
            lines = lines[:600] + ["... (truncated, list a subdirectory)"]
        return f"{self.rel(base)}/\n" + "\n".join(lines)

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> str:
        text = self.read_text(path)
        all_lines = text.splitlines()
        total = len(all_lines)
        start = max(1, int(start_line or 1))
        end = total if end_line is None else min(total, int(end_line))
        if start > max(total, 1):
            raise RepoError(f"{path} has only {total} lines")
        truncated = False
        if end - start + 1 > MAX_READ_LINES:
            end = start + MAX_READ_LINES - 1
            truncated = True
        width = len(str(end))
        body = "\n".join(f"{i:>{width}}  {all_lines[i - 1]}" for i in range(start, end + 1))
        header = f"{path} (lines {start}-{end} of {total})"
        footer = f"\n... (truncated; call again with start_line={end + 1})" if truncated else ""
        return f"{header}\n{body}{footer}"

    def search(self, pattern: str, glob: str | None = None, path: str = ".") -> str:
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            raise RepoError(f"invalid regex: {exc}") from exc
        hits: list[str] = []
        for file in self.iter_files(path):
            rel = self.rel(file)
            if glob and not (fnmatch.fnmatch(rel, glob) or fnmatch.fnmatch(file.name, glob)):
                continue
            if not self.is_text_file(file):
                continue
            for no, line in enumerate(file.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{no}: {line.strip()[:200]}")
                    if len(hits) >= MAX_SEARCH_HITS:
                        return "\n".join(hits) + "\n... (more matches; narrow the pattern or glob)"
        return "\n".join(hits) if hits else "No matches."


CODE_EXTENSIONS = {
    ".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".go", ".rs", ".rb", ".java", ".kt", ".cs", ".php",
    ".swift", ".c", ".h", ".cc", ".cpp", ".hpp", ".sh", ".sql", ".vue", ".svelte", ".lua", ".ex", ".exs", ".scala",
}


def source_files(repo: Repo) -> list[dict]:
    """Every code file with its line count, for the coverage map."""
    out = []
    for path in repo.iter_files():
        if path.suffix.lower() in CODE_EXTENSIONS and repo.is_text_file(path):
            out.append({"path": repo.rel(path), "lines": len(path.read_text(encoding="utf-8", errors="replace").splitlines())})
    return out
