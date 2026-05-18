"""Tests for SearchIndex.list_paths() and the --list-paths CLI output."""

from pathlib import Path

import pytest

from tantivy_search.index import SearchIndex


@pytest.fixture
def indexed_multi_path(tmp_path: Path, monkeypatch):
    """Index two distinct directories under separate repo partitions."""
    index_dir = tmp_path / "index"
    version_file = index_dir / ".schema_version"
    monkeypatch.setattr("tantivy_search.config.INDEX_DIR", index_dir)
    monkeypatch.setattr("tantivy_search.config.SCHEMA_VERSION_FILE", version_file)
    monkeypatch.setattr("tantivy_search.index.INDEX_DIR", index_dir)

    dir_alpha = tmp_path / "proj-alpha"
    dir_alpha.mkdir()
    (dir_alpha / "main.py").write_text("def hello(): pass\n")
    (dir_alpha / "utils.py").write_text("def util(): pass\n")

    dir_beta = tmp_path / "proj-beta"
    dir_beta.mkdir()
    (dir_beta / "app.py").write_text("def app(): pass\n")
    (dir_beta / "models.py").write_text("class Foo: pass\n")

    idx = SearchIndex()
    idx.index_repo(str(dir_alpha), "alpha")
    idx.index_repo(str(dir_beta), "beta")
    return idx, dir_alpha, dir_beta


def test_list_paths_returns_original_root(indexed_multi_path):
    """list_paths() returns the exact root_path passed to index_repo, not a heuristic."""
    idx, dir_alpha, dir_beta = indexed_multi_path
    paths = idx.list_paths()

    assert str(dir_alpha) in paths
    assert str(dir_beta) in paths
    assert paths[str(dir_alpha)] > 0
    assert paths[str(dir_beta)] > 0


def test_list_paths_single_file_repo(tmp_path: Path, monkeypatch):
    """A repo with one file still returns its root_path, not the file path."""
    index_dir = tmp_path / "index"
    version_file = index_dir / ".schema_version"
    monkeypatch.setattr("tantivy_search.config.INDEX_DIR", index_dir)
    monkeypatch.setattr("tantivy_search.config.SCHEMA_VERSION_FILE", version_file)
    monkeypatch.setattr("tantivy_search.index.INDEX_DIR", index_dir)

    repo_dir = tmp_path / "solo-repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# Solo\n")

    idx = SearchIndex()
    idx.index_repo(str(repo_dir), "solo")
    paths = idx.list_paths()

    assert str(repo_dir) in paths, f"Expected {repo_dir!s} in {paths}"
    # The key must be the directory, not the file path
    assert str(repo_dir / "README.md") not in paths


def test_list_paths_add_file_chunks_root(tmp_path: Path, monkeypatch):
    """root_path is respected when add_file_chunks is called directly."""
    from tantivy_search.chunking import Chunk

    index_dir = tmp_path / "index"
    version_file = index_dir / ".schema_version"
    monkeypatch.setattr("tantivy_search.config.INDEX_DIR", index_dir)
    monkeypatch.setattr("tantivy_search.config.SCHEMA_VERSION_FILE", version_file)
    monkeypatch.setattr("tantivy_search.index.INDEX_DIR", index_dir)

    idx = SearchIndex()
    chunk = Chunk(
        content="session data",
        language="json",
        heading_path="",
        title="",
        line_start=1,
        line_end=1,
        chunk_index=0,
    )
    root = "/home/tilo/.claude/projects"
    idx.add_file_chunks(
        "/home/tilo/.claude/projects/p1/session.jsonl", "sessions", root, [chunk]
    )

    paths = idx.list_paths()
    assert root in paths
    assert paths[root] == 1


def test_list_paths_cli_flat_sorted(tmp_path: Path, monkeypatch, capsys):
    """--list-paths prints one absolute path per line, sorted, no tree characters."""
    import argparse

    from tantivy_search.cli import cmd_list_paths

    index_dir = tmp_path / "index"
    version_file = index_dir / ".schema_version"
    monkeypatch.setattr("tantivy_search.config.INDEX_DIR", index_dir)
    monkeypatch.setattr("tantivy_search.config.SCHEMA_VERSION_FILE", version_file)
    monkeypatch.setattr("tantivy_search.index.INDEX_DIR", index_dir)

    dir_a = tmp_path / "aaa"
    dir_a.mkdir()
    (dir_a / "x.py").write_text("x = 1\n")
    dir_b = tmp_path / "bbb"
    dir_b.mkdir()
    (dir_b / "y.py").write_text("y = 2\n")

    idx = SearchIndex()
    idx.index_repo(str(dir_a), "aaa")
    idx.index_repo(str(dir_b), "bbb")

    # Patch SearchIndex() inside cmd_list_paths to return our pre-built idx
    monkeypatch.setattr("tantivy_search.cli.SearchIndex", lambda: idx)

    cmd_list_paths(argparse.Namespace())
    captured = capsys.readouterr().out
    lines = [ln for ln in captured.splitlines() if ln.strip()]

    # Must be sorted
    assert lines == sorted(lines)
    # No tree decoration characters
    for line in lines:
        assert not any(c in line for c in ("|", "├", "└", "─", "│"))
    # Both paths present
    assert any(str(dir_a) in line for line in lines)
    assert any(str(dir_b) in line for line in lines)


# ---------------------------------------------------------------------------
# _collapse_paths unit tests
# ---------------------------------------------------------------------------


def test_collapse_paths_three_siblings_collapsed():
    """≥3 siblings under a parent not in the listing → single summary line."""
    from tantivy_search.cli import _collapse_paths

    paths = ["/data/a", "/data/b", "/data/c"]
    result = _collapse_paths(paths)
    assert result == ["/data/* (3 entries)"]


def test_collapse_paths_two_siblings_stay():
    """<3 siblings under the same parent → not collapsed."""
    from tantivy_search.cli import _collapse_paths

    paths = ["/data/a", "/data/b"]
    result = _collapse_paths(paths)
    assert result == ["/data/a", "/data/b"]


def test_collapse_paths_parent_present_no_collapse():
    """If the parent directory is itself in the listing, children are NOT collapsed."""
    from tantivy_search.cli import _collapse_paths

    paths = sorted(["/data", "/data/a", "/data/b", "/data/c"])
    result = _collapse_paths(paths)
    assert "/data" in result
    assert "/data/a" in result
    assert "/data/b" in result
    assert "/data/c" in result
    assert all("/* " not in p for p in result)
