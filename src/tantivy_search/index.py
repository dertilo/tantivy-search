from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import tantivy

if TYPE_CHECKING:
    from tantivy_search.chunking import Chunk

from tantivy_search.config import (
    INDEX_DIR,
    check_schema_version,
    nuke_index,
    write_schema_version,
)
from tantivy_search.schema import build_schema

logger = logging.getLogger(__name__)

WRITER_HEAP_SIZE = 50_000_000

# Directories to skip when walking
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".eggs",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "target",
    ".gradle",
}

MAX_FILE_SIZE = 1_000_000  # 1MB


@dataclass
class IndexStats:
    files_indexed: int = 0
    chunks_total: int = 0
    errors: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


class SearchIndex:
    def __init__(self):
        self._schema = build_schema()
        self._index = self._open_or_create()

    def _open_or_create(self) -> tantivy.Index:
        if INDEX_DIR.exists() and not check_schema_version():
            logger.info("Schema version mismatch, rebuilding index")
            nuke_index()

        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        index = tantivy.Index(self._schema, path=str(INDEX_DIR), reuse=True)
        write_schema_version()
        return index

    @property
    def schema(self) -> tantivy.Schema:
        return self._schema

    @property
    def index(self) -> tantivy.Index:
        return self._index

    def searcher(self) -> tantivy.Searcher:
        self._index.reload()
        return self._index.searcher()

    @property
    def num_docs(self) -> int:
        return self.searcher().num_docs

    def has_repo(self, repo_name: str) -> bool:
        """Check if the index contains any docs for a repo."""
        searcher = self.searcher()
        q = tantivy.Query.term_query(
            self._schema, "repo", repo_name, index_option="freq"
        )
        return searcher.search(q, limit=1, count=True).count > 0

    def delete_repo(self, repo_name: str) -> int:
        """Delete all docs for a repo. Returns approximate doc count before deletion."""
        searcher = self.searcher()
        q = tantivy.Query.term_query(
            self._schema, "repo", repo_name, index_option="freq"
        )
        count = searcher.search(q, limit=1, count=True).count
        if count > 0:
            with self._index.writer(
                heap_size=WRITER_HEAP_SIZE, num_threads=1
            ) as writer:
                writer.delete_documents("repo", repo_name)
        return count

    def delete_file_chunks(self, file_path: str) -> None:
        """Delete all chunks for a single file."""
        with self._index.writer(heap_size=WRITER_HEAP_SIZE, num_threads=1) as writer:
            writer.delete_documents("file_path", file_path)

    def _write_chunks(
        self,
        writer: tantivy.IndexWriter,
        file_path: str,
        repo_name: str,
        chunks: list[Chunk],
    ) -> None:
        """Write chunk documents using an existing writer."""
        for i, chunk in enumerate(chunks):
            doc = tantivy.Document()
            doc.add_text("id", f"{file_path}:{i}")
            doc.add_text("file_path", file_path)
            doc.add_text("repo", repo_name)
            doc.add_text("content", chunk.content)
            doc.add_text("language", chunk.language)
            doc.add_text("heading_path", chunk.heading_path)
            doc.add_text("title", chunk.title)
            if chunk.timestamp is not None:
                doc.add_date("timestamp", chunk.timestamp)
            doc.add_integer("line_start", chunk.line_start)
            doc.add_integer("line_end", chunk.line_end)
            writer.add_document(doc)

    def add_file_chunks(
        self, file_path: str, repo_name: str, chunks: list[Chunk]
    ) -> None:
        """Add documents for a single file."""
        with self._index.writer(heap_size=WRITER_HEAP_SIZE, num_threads=1) as writer:
            self._write_chunks(writer, file_path, repo_name, chunks)

    def index_repo(self, repo_path: str, repo_name: str) -> IndexStats:
        """Delete all existing docs for repo, then re-chunk and re-index all files."""
        from tantivy_search.chunking import chunk_file

        start = time.time()
        stats = IndexStats()

        self.delete_repo(repo_name)

        file_paths = _collect_supported_files(Path(repo_path))
        stats.files_indexed = len(file_paths)

        with self._index.writer(heap_size=WRITER_HEAP_SIZE, num_threads=1) as writer:
            for fpath in file_paths:
                try:
                    chunks = chunk_file(fpath)
                except Exception as e:
                    logger.warning("Failed to chunk %s: %s", fpath, e)
                    stats.errors.append(f"{fpath}: {e}")
                    continue
                self._write_chunks(writer, str(fpath), repo_name, chunks)
                stats.chunks_total += len(chunks)

        stats.elapsed_seconds = time.time() - start
        return stats


def is_skippable_dir(name: str) -> bool:
    """Return True if a directory should be skipped during indexing/watching."""
    return name in SKIP_DIRS or (name.startswith(".") and name != ".")


def _collect_supported_files(root: Path) -> list[Path]:
    """Walk directory tree, return sorted list of files with supported extensions."""
    from tantivy_search.chunking import SUPPORTED_EXTENSIONS

    files: list[Path] = []
    if not root.is_dir():
        return files

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not is_skippable_dir(d)]
        dirnames.sort()

        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            try:
                if fpath.stat().st_size <= MAX_FILE_SIZE:
                    files.append(fpath)
            except OSError:
                continue

    files.sort()
    return files
