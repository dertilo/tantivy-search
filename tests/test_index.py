"""Tests for indexing and file collection."""

from pathlib import Path

import pytest

from tantivy_search.index import SearchIndex, _collect_supported_files, MAX_FILE_SIZE


@pytest.fixture
def search_index(tmp_path: Path, monkeypatch):
    """SearchIndex using a temporary directory."""
    index_dir = tmp_path / "index"
    monkeypatch.setattr("tantivy_search.config.INDEX_DIR", index_dir)
    monkeypatch.setattr(
        "tantivy_search.config.SCHEMA_VERSION_FILE", index_dir / ".schema_version"
    )
    # INDEX_DIR is also imported directly into index.py
    monkeypatch.setattr("tantivy_search.index.INDEX_DIR", index_dir)
    return SearchIndex()


# --- File collection ---


def test_collect_finds_supported_files(sample_repo: Path):
    files = _collect_supported_files(sample_repo)
    extensions = {f.suffix for f in files}
    assert ".py" in extensions
    assert ".md" in extensions
    assert ".sh" in extensions


def test_collect_skips_git_dir(sample_repo: Path):
    files = _collect_supported_files(sample_repo)
    assert not any(".git" in f.parts for f in files)


def test_collect_skips_node_modules(tmp_path: Path):
    nm = tmp_path / "node_modules"
    nm.mkdir()
    (nm / "pkg.js").write_text("module.exports = {}")
    (tmp_path / "app.js").write_text("console.log('hi')")

    files = _collect_supported_files(tmp_path)
    assert len(files) == 1
    assert files[0].name == "app.js"


def test_collect_skips_large_files(tmp_path: Path):
    big = tmp_path / "huge.py"
    big.write_text("x" * (MAX_FILE_SIZE + 1))
    small = tmp_path / "small.py"
    small.write_text("x = 1")

    files = _collect_supported_files(tmp_path)
    names = [f.name for f in files]
    assert "small.py" in names
    assert "huge.py" not in names


def test_collect_nonexistent_dir(tmp_path: Path):
    assert _collect_supported_files(tmp_path / "nope") == []


def test_collect_includes_nested_files(sample_repo: Path):
    files = _collect_supported_files(sample_repo)
    names = [f.name for f in files]
    assert "utils.py" in names


# --- Indexing ---


def test_index_repo(search_index, sample_repo: Path):
    stats = search_index.index_repo(str(sample_repo), "test-repo")
    assert stats.files_indexed > 0
    assert stats.chunks_total > 0
    assert stats.elapsed_seconds >= 0
    assert stats.errors == []
    assert search_index.num_docs == stats.chunks_total


def test_index_repo_replaces_on_reindex(search_index, sample_repo: Path):
    search_index.index_repo(str(sample_repo), "test-repo")
    stats2 = search_index.index_repo(str(sample_repo), "test-repo")
    # Re-indexing should produce the same doc count (delete + re-add)
    assert search_index.num_docs == stats2.chunks_total


def test_delete_repo(search_index, sample_repo: Path):
    search_index.index_repo(str(sample_repo), "test-repo")
    assert search_index.num_docs > 0

    search_index.delete_repo("test-repo")
    assert search_index.num_docs == 0


def test_delete_nonexistent_repo(search_index):
    count = search_index.delete_repo("nope")
    assert count == 0


def test_index_empty_dir(search_index, tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    stats = search_index.index_repo(str(empty), "empty-repo")
    assert stats.files_indexed == 0
    assert stats.chunks_total == 0


def test_index_handles_unreadable_file(search_index, tmp_path: Path):
    """Files that fail to chunk should be recorded as errors, not crash."""
    repo = tmp_path / "repo"
    repo.mkdir()
    bad = repo / "bad.py"
    bad.write_text("valid python")
    good = repo / "good.py"
    good.write_text("x = 1\n")

    # Make bad.py unreadable after collection (simulate chunking error)
    # Instead, test with a file that has encoding issues by writing raw bytes
    bad.write_bytes(b"\x80\x81\x82" * 100)

    stats = search_index.index_repo(str(repo), "test")
    # Should index at least the good file without crashing
    assert stats.files_indexed == 2  # both collected
    assert stats.chunks_total >= 1  # at least good.py chunked
