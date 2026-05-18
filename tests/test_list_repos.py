"""Tests for SearchIndex.list_repos() and _render_repo_tree()."""

from pathlib import Path

import pytest

from tantivy_search.cli import _render_repo_tree
from tantivy_search.index import SearchIndex


@pytest.fixture
def indexed_multi_name_repo(tmp_path: Path, sample_repo: Path, monkeypatch):
    """Index the same sample_repo under three different logical repo names."""
    index_dir = tmp_path / "index"
    version_file = index_dir / ".schema_version"
    monkeypatch.setattr("tantivy_search.config.INDEX_DIR", index_dir)
    monkeypatch.setattr("tantivy_search.config.SCHEMA_VERSION_FILE", version_file)
    monkeypatch.setattr("tantivy_search.index.INDEX_DIR", index_dir)

    idx = SearchIndex()
    idx.index_repo(str(sample_repo), "alpha")
    idx.index_repo(str(sample_repo), "beta")
    idx.index_repo(str(sample_repo), "gamma")
    return idx


def test_list_repos_collects_distinct_repos(
    indexed_multi_name_repo: SearchIndex, sample_repo: Path
):
    repos = indexed_multi_name_repo.list_repos()
    assert set(repos.keys()) == {"alpha", "beta", "gamma"}
    # Each repo was indexed from the same sample_repo so counts should match
    assert repos["alpha"] == repos["beta"] == repos["gamma"]
    assert repos["alpha"] > 0


def test_render_repo_tree_format():
    repos = {
        "claudia": 4321,
        "chinomatico-monorepo": 2506,
        "chinomatico-monorepo/deps/foo": 6,
        "chinomatico-monorepo/deps/bar": 12,
        "conversation-history/old-laptop/2026-04-28": 512,
        "conversation-history/old-laptop/2026-04-29": 347,
    }
    output = _render_repo_tree(repos)
    lines = output.splitlines()

    # Header present
    assert lines[0].startswith("Repos in index (6 partitions,")

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
