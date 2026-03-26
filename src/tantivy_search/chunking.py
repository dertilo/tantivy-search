from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import frontmatter
from langchain_text_splitters import (
    Language,
    RecursiveCharacterTextSplitter,
)

CHUNK_SIZE = 5000
CHUNK_OVERLAP = 100

MARKDOWN_EXTENSIONS = {".md", ".mdx", ".markdown"}

# Extension -> Language enum (None = no language-specific splitter, use generic)
EXTENSION_MAP: dict[str, Language | None] = {
    ".py": Language.PYTHON,
    ".js": Language.JS,
    ".ts": Language.TS,
    ".tsx": Language.TS,
    ".jsx": Language.JS,
    ".java": Language.JAVA,
    ".go": Language.GO,
    ".rs": Language.RUST,
    ".rb": Language.RUBY,
    ".php": Language.PHP,
    ".c": Language.C,
    ".cpp": Language.CPP,
    ".cc": Language.CPP,
    ".h": Language.C,
    ".hpp": Language.CPP,
    ".cs": Language.CSHARP,
    ".swift": Language.SWIFT,
    ".kt": Language.KOTLIN,
    ".scala": Language.SCALA,
    ".html": Language.HTML,
    ".htm": Language.HTML,
    ".proto": Language.PROTO,
    ".sol": Language.SOL,
    ".lua": Language.LUA,
    ".pl": Language.PERL,
    ".pm": Language.PERL,
    ".r": Language.R,
    ".sh": None,
    ".bash": None,
    ".zsh": None,
}

# Display name for extensions without a Language enum
_EXTENSION_NAMES: dict[str, str] = {".sh": "shell", ".bash": "shell", ".zsh": "shell"}

SUPPORTED_CODE_EXTENSIONS = set(EXTENSION_MAP.keys())
SUPPORTED_EXTENSIONS = SUPPORTED_CODE_EXTENSIONS | MARKDOWN_EXTENSIONS


@dataclass
class Chunk:
    content: str
    language: str
    heading_path: str
    title: str
    line_start: int
    line_end: int
    chunk_index: int
    timestamp: datetime | None = None


def chunk_file(file_path: Path) -> list[Chunk]:
    """Read file and split into chunks based on extension."""
    text = file_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return []

    ext = file_path.suffix.lower()
    if ext in MARKDOWN_EXTENSIONS:
        return _chunk_markdown(text)

    if ext in EXTENSION_MAP:
        lang = EXTENSION_MAP[ext]
        lang_name = lang.value if lang else _EXTENSION_NAMES.get(ext, "text")
        return _chunk_code(text, lang, lang_name)

    return []


def _chunk_markdown(text: str) -> list[Chunk]:
    """Split markdown using recursive character splitting with frontmatter extraction."""
    post = frontmatter.loads(text)
    title = str(post.get("title", ""))
    body = post.content

    if not title:
        title = _extract_h1_title(body)

    if not body.strip():
        return []

    heading_index = _build_heading_index(body)

    splitter = RecursiveCharacterTextSplitter.from_language(
        Language.MARKDOWN,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    sub_texts = splitter.split_text(body)

    line_tracker = _LineTracker(body)
    chunks: list[Chunk] = []
    for i, content in enumerate(sub_texts):
        line_start, line_end = line_tracker.find_lines(content)
        heading_path = _heading_path_at_line(heading_index, line_start)
        chunks.append(
            Chunk(
                content=content,
                language="markdown",
                heading_path=heading_path,
                title=title,
                line_start=line_start,
                line_end=line_end,
                chunk_index=i,
            )
        )
    return chunks


def _chunk_code(text: str, lang: Language | None, lang_name: str) -> list[Chunk]:
    """Split code file using language-aware recursive splitter."""
    if lang:
        splitter = RecursiveCharacterTextSplitter.from_language(
            lang,
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )
    else:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )

    sub_texts = splitter.split_text(text)
    line_tracker = _LineTracker(text)

    chunks: list[Chunk] = []
    for i, sub_text in enumerate(sub_texts):
        line_start, line_end = line_tracker.find_lines(sub_text)
        chunks.append(
            Chunk(
                content=sub_text,
                language=lang_name,
                heading_path="",
                title="",
                line_start=line_start,
                line_end=line_end,
                chunk_index=i,
            )
        )
    return chunks


class _LineTracker:
    """Track line positions for sequential chunk lookups in a source text.

    Assumes chunks are looked up in document order. Advances a cursor
    forward after each match to avoid O(n^2) re-scanning.
    """

    def __init__(self, full_text: str):
        self._text = full_text
        self._cursor = 0
        self._last_line_start = 1
        self._last_line_end = 1

    def find_lines(self, chunk: str) -> tuple[int, int]:
        """Return (line_start, line_end) for a chunk."""
        idx = self._text.find(chunk, self._cursor)
        if idx == -1:
            # Overlap chunks may repeat earlier content
            idx = self._text.find(chunk)
        if idx == -1:
            # Splitters may reformat text (e.g. add trailing spaces to headings).
            # Fall back to matching the first non-empty line of the chunk.
            for line in chunk.split("\n"):
                needle = line.strip()
                if needle:
                    idx = self._text.find(needle, self._cursor)
                    if idx == -1:
                        idx = self._text.find(needle)
                    break
        if idx == -1:
            return self._last_line_start, self._last_line_end

        self._last_line_start = self._text.count("\n", 0, idx) + 1
        self._last_line_end = self._last_line_start + chunk.count("\n")
        self._cursor = idx + 1
        return self._last_line_start, self._last_line_end


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)", re.MULTILINE)


def _build_heading_index(body: str) -> list[tuple[int, int, str]]:
    """Build a list of (line_number, level, heading_text) from markdown body."""
    index: list[tuple[int, int, str]] = []
    for match in _HEADING_RE.finditer(body):
        line_num = body.count("\n", 0, match.start()) + 1
        level = len(match.group(1))
        text = match.group(2).strip()
        index.append((line_num, level, text))
    return index


def _heading_path_at_line(heading_index: list[tuple[int, int, str]], line: int) -> str:
    """Return the heading breadcrumb active at a given line number.

    Walks the heading index up to `line`, maintaining a stack by level.
    Example: "## Foo > ### Bar"
    """
    # stack[level] = heading text; higher levels get cleared when a lower level appears
    stack: dict[int, str] = {}
    for h_line, level, text in heading_index:
        if h_line > line:
            break
        stack[level] = text
        # Clear deeper levels
        for k in [k for k in stack if k > level]:
            del stack[k]
    if not stack:
        return ""
    return " > ".join(f"{'#' * lvl} {stack[lvl]}" for lvl in sorted(stack))


def _extract_h1_title(text: str) -> str:
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("##"):
            return stripped[2:].strip()
    return ""
