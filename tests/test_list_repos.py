"""Tests for SearchIndex.list_paths() and _render_path_tree()."""

from pathlib import Path

import pytest

from tantivy_search.cli import _render_path_tree
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


def test_list_paths_collects_lcp(indexed_multi_path):
    idx, dir_alpha, dir_beta = indexed_multi_path
    paths = idx.list_paths()

    # Both partitions' LCPs should appear
    assert str(dir_alpha) in paths
    assert str(dir_beta) in paths

    # Counts match the number of indexed chunks (2 files per dir, likely 1 chunk each)
    assert paths[str(dir_alpha)] > 0
    assert paths[str(dir_beta)] > 0


def test_render_path_tree_format():
    repos = {
        "claudia": 4321,
        "chinomatico-monorepo": 2506,
        "chinomatico-monorepo/deps/foo": 6,
        "chinomatico-monorepo/deps/bar": 12,
        "conversation-history/old-laptop/2026-04-28": 512,
        "conversation-history/old-laptop/2026-04-29": 347,
    }
    output = _render_path_tree(repos)
    lines = output.splitlines()

    # Header present
    assert lines[0].startswith("Paths in index (6 roots,")

    # Every input name appears somewhere in the output
    for name in repos:
        leaf = name.split("/")[-1]
        assert any(leaf in line for line in lines), f"leaf {leaf!r} missing from output"

    # Prefix nodes appear exactly once (lines ending with /)
    prefix_lines = [line for line in lines if line.rstrip().endswith("/")]
    prefix_texts = [line.strip() for line in prefix_lines]
    assert prefix_texts.count("chinomatico-monorepo/") == 1
    assert prefix_texts.count("deps/") == 1
    assert prefix_texts.count("conversation-history/") == 1
    assert prefix_texts.count("old-laptop/") == 1

    # claudia is at depth 0 — no leading spaces
    claudia_line = next(line for line in lines if "claudia" in line and "/" not in line)
    assert not claudia_line.startswith(" ")

    # 2026-04-28 and 2026-04-29 are at depth 2 — 8 leading spaces (2 * 4)
    for date in ("2026-04-28", "2026-04-29"):
        date_line = next(line for line in lines if date in line)
        assert date_line.startswith("        "), f"{date} not indented at depth 2"
