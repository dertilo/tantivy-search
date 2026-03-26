"""Tests for config and schema versioning."""

from pathlib import Path

from tantivy_search.config import (
    check_schema_version,
    nuke_index,
    write_schema_version,
)


# --- Schema versioning ---


def test_write_and_check_schema_version(tmp_path: Path, monkeypatch):
    index_dir = tmp_path / "index"
    monkeypatch.setattr("tantivy_search.config.INDEX_DIR", index_dir)
    monkeypatch.setattr(
        "tantivy_search.config.SCHEMA_VERSION_FILE", index_dir / ".schema_version"
    )

    write_schema_version()
    assert check_schema_version() is True


def test_schema_version_mismatch(tmp_path: Path, monkeypatch):
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    version_file = index_dir / ".schema_version"
    version_file.write_text("0")

    monkeypatch.setattr("tantivy_search.config.INDEX_DIR", index_dir)
    monkeypatch.setattr("tantivy_search.config.SCHEMA_VERSION_FILE", version_file)

    assert check_schema_version() is False


def test_schema_version_missing_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("tantivy_search.config.SCHEMA_VERSION_FILE", tmp_path / "nope")
    assert check_schema_version() is False


def test_nuke_index(tmp_path: Path, monkeypatch):
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    (index_dir / "somefile").write_text("data")

    monkeypatch.setattr("tantivy_search.config.INDEX_DIR", index_dir)
    nuke_index()
    assert not index_dir.exists()
