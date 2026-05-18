"""Tests for query parsing, search execution, and result formatting."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tantivy_search.search import (
    ParsedQuery,
    SearchResult,
    _parse_time_value,
    format_results,
    parse_filters,
    search,
)


# --- parse_filters ---


def test_parse_plain_query():
    parsed = parse_filters("hello world")
    assert parsed.text == "hello world"
    assert parsed.lang_filter is None
    assert parsed.paths == ()


def test_parse_lang_filter():
    parsed = parse_filters("error handling lang:python")
    assert parsed.text == "error handling"
    assert parsed.lang_filter == "python"


def test_parse_multiple_filters():
    parsed = parse_filters("search lang:python")
    assert parsed.text == "search"
    assert parsed.lang_filter == "python"


def test_parse_filters_only():
    parsed = parse_filters("lang:rust")
    assert parsed.text == ""
    assert parsed.lang_filter == "rust"


def test_parse_negated_lang():
    parsed = parse_filters("error -lang:python")
    assert parsed.text == "error"
    assert parsed.lang_filter is None
    assert parsed.lang_excludes == ["python"]


def test_parse_multiple_excludes():
    parsed = parse_filters("-lang:python -lang:rust")
    assert parsed.text == ""
    assert parsed.lang_excludes == ["python", "rust"]


# --- time filter parsing ---


def test_parse_time_value_relative_hours():
    dt = _parse_time_value("24h")
    assert dt is not None
    assert (datetime.now(timezone.utc) - dt).total_seconds() == pytest.approx(
        24 * 3600, abs=5
    )


def test_parse_time_value_relative_days():
    dt = _parse_time_value("7d")
    assert dt is not None
    assert (datetime.now(timezone.utc) - dt).total_seconds() == pytest.approx(
        7 * 86400, abs=5
    )


def test_parse_time_value_relative_weeks():
    dt = _parse_time_value("2w")
    assert dt is not None
    assert (datetime.now(timezone.utc) - dt).total_seconds() == pytest.approx(
        14 * 86400, abs=5
    )


def test_parse_time_value_absolute_date():
    dt = _parse_time_value("2026-03-14")
    assert dt == datetime(2026, 3, 14, tzinfo=timezone.utc)


def test_parse_time_value_invalid():
    assert _parse_time_value("foo") is None


def test_parse_after_filter():
    parsed = parse_filters("ssh setup after:7d")
    assert parsed.text == "ssh setup"
    assert parsed.after is not None
    assert parsed.before is None


def test_parse_before_filter():
    parsed = parse_filters("docker before:2026-03-14")
    assert parsed.text == "docker"
    assert parsed.before == datetime(2026, 3, 14, tzinfo=timezone.utc)


def test_parse_after_and_before():
    parsed = parse_filters("config after:2026-03-01 before:2026-03-14")
    assert parsed.text == "config"
    assert parsed.after == datetime(2026, 3, 1, tzinfo=timezone.utc)
    assert parsed.before == datetime(2026, 3, 14, tzinfo=timezone.utc)


# --- format_results (JSON) ---


def test_format_empty():
    assert json.loads(format_results([])) == []


def test_format_single_result():
    result = SearchResult(
        file_path="/code/main.py",
        repo="myrepo",
        content="def hello():\n    return 'hi'",
        language="python",
        heading_path="",
        title="",
        line_start=10,
        line_end=12,
    )
    parsed = json.loads(format_results([result]))
    assert len(parsed) == 1
    r = parsed[0]
    assert r["file_path"] == "/code/main.py"
    assert r["repo"] == "myrepo"
    assert r["language"] == "python"
    assert r["lines"] == "10-12"
    assert "heading_path" not in r
    assert "title" not in r
    assert "snippet" not in r
    assert "def hello()" in r["content"]


def test_format_multiple_results():
    results = [
        SearchResult(
            file_path=f"/code/f{i}.py",
            repo="r",
            content=f"chunk {i}",
            language="python",
            heading_path="",
            title="",
            line_start=i,
            line_end=i + 5,
        )
        for i in range(3)
    ]
    parsed = json.loads(format_results(results))
    assert len(parsed) == 3
    assert [r["file_path"] for r in parsed] == [
        "/code/f0.py",
        "/code/f1.py",
        "/code/f2.py",
    ]


# --- Integration: index + search ---


@pytest.fixture
def indexed_repo(tmp_path: Path, sample_repo: Path, monkeypatch):
    """Create a temporary index with sample_repo indexed."""
    index_dir = tmp_path / "index"
    version_file = index_dir / ".schema_version"
    monkeypatch.setattr("tantivy_search.config.INDEX_DIR", index_dir)
    monkeypatch.setattr("tantivy_search.config.SCHEMA_VERSION_FILE", version_file)
    # Also patch the names imported into index.py's module namespace
    monkeypatch.setattr("tantivy_search.index.INDEX_DIR", index_dir)

    from tantivy_search.index import SearchIndex

    idx = SearchIndex()
    idx.index_repo(str(sample_repo), "sample-repo")
    return idx


def test_search_finds_python_content(indexed_repo):
    parsed = parse_filters("hello")
    results = search(indexed_repo, parsed, num_results=10)
    assert len(results) > 0
    assert any(
        "hello" in r.content.lower() or "hello" in r.file_path.lower() for r in results
    )


def test_search_finds_markdown_content(indexed_repo):
    parsed = parse_filters("Installation")
    results = search(indexed_repo, parsed, num_results=10)
    assert len(results) > 0


def test_search_lang_filter(indexed_repo):
    parsed = parse_filters("lang:python")
    results = search(indexed_repo, parsed, num_results=50)
    assert all(r.language == "python" for r in results)


def test_search_lang_alias_py(indexed_repo):
    parsed = parse_filters("lang:py")
    results = search(indexed_repo, parsed, num_results=50)
    assert len(results) > 0
    assert all(r.language == "python" for r in results)


def test_search_lang_alias_md(indexed_repo):
    parsed = parse_filters("lang:md")
    results = search(indexed_repo, parsed, num_results=50)
    assert len(results) > 0
    assert all(r.language == "markdown" for r in results)


def test_search_lang_filter_markdown(indexed_repo):
    parsed = parse_filters("lang:markdown")
    results = search(indexed_repo, parsed, num_results=50)
    assert len(results) > 0
    assert all(r.language == "markdown" for r in results)


def test_search_no_results(indexed_repo):
    parsed = parse_filters("xyznonexistenttermxyz")
    results = search(indexed_repo, parsed, num_results=10)
    assert len(results) == 0


def test_search_no_fuzzy(indexed_repo):
    parsed = parse_filters("hello")
    results = search(indexed_repo, parsed, num_results=10, fuzzy=False)
    # Should still work, just without fuzzy expansion
    assert isinstance(results, list)


def test_search_num_results_limit(indexed_repo):
    parsed = parse_filters("")  # match all
    results = search(indexed_repo, parsed, num_results=2)
    assert len(results) <= 2


def test_search_exclude_lang(indexed_repo):
    parsed = parse_filters("-lang:python")
    results = search(indexed_repo, parsed, num_results=50)
    assert len(results) > 0
    assert all(r.language != "python" for r in results)


def test_search_exclude_lang_alias(indexed_repo):
    parsed = parse_filters("-lang:py")
    results = search(indexed_repo, parsed, num_results=50)
    assert all(r.language != "python" for r in results)


def test_search_exclude_with_text(indexed_repo):
    # Search for something but exclude markdown results
    parsed = parse_filters("Installation -lang:markdown")
    results = search(indexed_repo, parsed, num_results=50)
    assert all(r.language != "markdown" for r in results)


# --- Integration: --path filter ---


def test_path_filter_descendants(indexed_repo, sample_repo: Path):
    """--path to a directory matches all files underneath it."""
    parsed = ParsedQuery(text="", paths=(str(sample_repo),))
    results = search(indexed_repo, parsed, num_results=50)
    assert len(results) > 0
    assert all(r.file_path.startswith(str(sample_repo)) for r in results)


def test_path_filter_exact_file(indexed_repo, sample_repo: Path):
    """--path to an exact file matches only chunks from that file."""
    main_py = str(sample_repo / "main.py")
    parsed = ParsedQuery(text="", paths=(main_py,))
    results = search(indexed_repo, parsed, num_results=50)
    assert len(results) > 0
    assert all("main.py" in r.file_path for r in results)
    assert all("README" not in r.file_path for r in results)


def test_path_filter_two_paths_or(indexed_repo, sample_repo: Path):
    """Two --path values are OR-joined; files outside both are excluded."""
    main_py = str(sample_repo / "main.py")
    src_dir = str(sample_repo / "src")
    parsed = ParsedQuery(text="", paths=(main_py, src_dir))
    results = search(indexed_repo, parsed, num_results=50)
    assert len(results) > 0
    assert all("main.py" in r.file_path or "/src/" in r.file_path for r in results)
    # README and CHANGELOG are outside both paths
    assert all("README" not in r.file_path for r in results)
    assert all("CHANGELOG" not in r.file_path for r in results)


def test_path_filter_with_text_query(indexed_repo, sample_repo: Path):
    """--path AND text are AND-joined: only matching chunks within the path."""
    src_dir = str(sample_repo / "src")
    parsed = ParsedQuery(text="add", paths=(src_dir,))
    results = search(indexed_repo, parsed, num_results=50)
    # Results must be from src/ and contain relevant content
    assert all("/src/" in r.file_path for r in results)


def test_path_no_leading_slash_error():
    """--path without leading '/' should cause an argparse error (exit 2)."""
    from unittest.mock import patch

    from tantivy_search.cli import main

    with patch("sys.argv", ["tantivy-search", "query", "--path", "relative/path"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code != 0


def test_path_metachar_escaped(tmp_path: Path, monkeypatch):
    """Regex metacharacters in path names are properly escaped."""
    index_dir = tmp_path / "index"
    version_file = index_dir / ".schema_version"
    monkeypatch.setattr("tantivy_search.config.INDEX_DIR", index_dir)
    monkeypatch.setattr("tantivy_search.config.SCHEMA_VERSION_FILE", version_file)
    monkeypatch.setattr("tantivy_search.index.INDEX_DIR", index_dir)

    # Directory name contains '.' and '+' — regex metacharacters
    special_dir = tmp_path / "my.special+dir"
    special_dir.mkdir()
    (special_dir / "a.py").write_text("x = 1\n")
    (special_dir / "b.py").write_text("y = 2\n")

    other_dir = tmp_path / "my_special_dir"
    other_dir.mkdir()
    (other_dir / "c.py").write_text("z = 3\n")

    from tantivy_search.index import SearchIndex

    idx = SearchIndex()
    idx.index_repo(str(special_dir), "special")
    idx.index_repo(str(other_dir), "other")

    parsed = ParsedQuery(text="", paths=(str(special_dir),))
    results = search(idx, parsed, num_results=50)
    assert len(results) > 0
    # Only files from special_dir (not other_dir) should match
    assert all(str(special_dir) in r.file_path for r in results)
    assert all(str(other_dir) not in r.file_path for r in results)


# --- Integration: timestamp search ---


@pytest.fixture
def indexed_sessions(tmp_path: Path, monkeypatch):
    """Create an index with session chunks that have timestamps."""
    index_dir = tmp_path / "index"
    version_file = index_dir / ".schema_version"
    monkeypatch.setattr("tantivy_search.config.INDEX_DIR", index_dir)
    monkeypatch.setattr("tantivy_search.config.SCHEMA_VERSION_FILE", version_file)
    monkeypatch.setattr("tantivy_search.index.INDEX_DIR", index_dir)

    from tantivy_search.chunking import Chunk
    from tantivy_search.index import SearchIndex

    idx = SearchIndex()

    # Add chunks with different timestamps
    old_chunk = Chunk(
        content="setting up ssh keys for deployment",
        language="session",
        heading_path="Turn 1: User > Assistant",
        title="SSH Setup Session",
        line_start=0,
        line_end=0,
        chunk_index=0,
        timestamp=datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc),
    )
    recent_chunk = Chunk(
        content="configuring docker containers for production",
        language="session",
        heading_path="Turn 1: User > Assistant",
        title="Docker Session",
        line_start=0,
        line_end=0,
        chunk_index=0,
        timestamp=datetime(2026, 3, 14, 10, 0, 0, tzinfo=timezone.utc),
    )
    no_ts_chunk = Chunk(
        content="some code without timestamp",
        language="python",
        heading_path="",
        title="",
        line_start=1,
        line_end=5,
        chunk_index=0,
    )

    idx.add_file_chunks(
        "/sessions/old.jsonl", "claude-sessions", "/sessions", [old_chunk]
    )
    idx.add_file_chunks(
        "/sessions/recent.jsonl", "claude-sessions", "/sessions", [recent_chunk]
    )
    idx.add_file_chunks("/code/main.py", "myrepo", "/code", [no_ts_chunk])
    return idx


def test_search_after_filter(indexed_sessions):
    parsed = parse_filters("after:2026-03-10")
    results = search(indexed_sessions, parsed, num_results=10)
    assert len(results) == 1
    assert "docker" in results[0].content


def test_search_before_filter(indexed_sessions):
    parsed = parse_filters("before:2026-03-10")
    results = search(indexed_sessions, parsed, num_results=10)
    assert len(results) == 1
    assert "ssh" in results[0].content


def test_search_after_and_before(indexed_sessions):
    parsed = parse_filters("after:2026-02-01 before:2026-03-31")
    results = search(indexed_sessions, parsed, num_results=10)
    assert len(results) == 2


def test_search_time_filter_with_text(indexed_sessions):
    parsed = parse_filters("docker after:2026-03-10")
    results = search(indexed_sessions, parsed, num_results=10)
    assert len(results) == 1
    assert "docker" in results[0].content


def test_search_time_filter_no_match(indexed_sessions):
    parsed = parse_filters("after:2026-04-01")
    results = search(indexed_sessions, parsed, num_results=10)
    assert len(results) == 0


def test_search_result_includes_timestamp(indexed_sessions):
    parsed = parse_filters("docker")
    results = search(indexed_sessions, parsed, num_results=10)
    assert len(results) >= 1
    docker_result = [r for r in results if "docker" in r.content][0]
    assert docker_result.timestamp != ""
