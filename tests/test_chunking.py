"""Tests for markdown and code file chunking."""

import textwrap
from pathlib import Path

from tantivy_search.chunking import (
    _extract_h1_title,
    _LineTracker,
    chunk_file,
)


# --- Markdown chunking ---


def test_md_basic_headings(tmp_path: Path):
    md = tmp_path / "doc.md"
    md.write_text(
        textwrap.dedent("""\
        # Title

        Intro paragraph.

        ## Section A

        Content A.

        ## Section B

        Content B.
    """)
    )
    chunks = chunk_file(md)
    assert len(chunks) >= 1
    assert all(c.language == "markdown" for c in chunks)


def test_md_frontmatter_extraction(tmp_path: Path):
    md = tmp_path / "doc.md"
    md.write_text(
        textwrap.dedent("""\
        ---
        title: My Doc
        ---

        # Heading

        Some content.
    """)
    )
    chunks = chunk_file(md)
    assert len(chunks) >= 1
    assert chunks[0].title == "My Doc"


def test_md_title_from_h1_when_no_frontmatter(tmp_path: Path):
    md = tmp_path / "doc.md"
    md.write_text("# My Title\n\nContent here.\n")
    chunks = chunk_file(md)
    assert chunks[0].title == "My Title"


def test_md_heading_path_breadcrumb(tmp_path: Path):
    """heading_path contains the heading breadcrumb at the chunk's position."""
    # Make two chunks by exceeding CHUNK_SIZE so we can test breadcrumb at different positions
    md = tmp_path / "doc.md"
    md.write_text(
        "# Top\n\nIntro.\n\n"
        "## Sub\n\n" + "word " * 1200 + "\n\n"  # >5000 chars → forces a split
        "## Other\n\nMore content here.\n"
    )
    chunks = chunk_file(md)
    assert len(chunks) >= 2
    # First chunk starts at # Top
    assert "# Top" in chunks[0].heading_path
    # Second chunk should be under ## Sub or ## Other
    assert "##" in chunks[1].heading_path


def test_md_empty_file(tmp_path: Path):
    md = tmp_path / "empty.md"
    md.write_text("")
    assert chunk_file(md) == []


def test_md_whitespace_only(tmp_path: Path):
    md = tmp_path / "blank.md"
    md.write_text("   \n\n  \n")
    assert chunk_file(md) == []


def test_md_no_headings_fallback(tmp_path: Path):
    md = tmp_path / "plain.md"
    md.write_text("Just some plain text without any headings.\n\nAnother paragraph.\n")
    chunks = chunk_file(md)
    assert len(chunks) >= 1
    assert chunks[0].heading_path == ""


def test_md_code_fence_preserved(tmp_path: Path):
    md = tmp_path / "doc.md"
    md.write_text(
        textwrap.dedent("""\
        # Example

        Here is code:

        ```python
        def foo():
            return 42
        ```

        After code.
    """)
    )
    chunks = chunk_file(md)
    all_content = " ".join(c.content for c in chunks)
    assert "def foo()" in all_content


def test_md_oversized_doc_gets_split(tmp_path: Path):
    md = tmp_path / "big.md"
    big_content = "# Big Doc\n\n" + ("word " * 500 + "\n\n") * 20
    md.write_text(big_content)
    chunks = chunk_file(md)
    assert len(chunks) >= 2


# --- Code chunking ---


def test_code_python_file(tmp_path: Path):
    py = tmp_path / "example.py"
    py.write_text(
        textwrap.dedent("""\
        def foo():
            return 1

        def bar():
            return 2
    """)
    )
    chunks = chunk_file(py)
    assert len(chunks) >= 1
    assert all(c.language == "python" for c in chunks)


def test_code_shell_uses_generic_splitter(tmp_path: Path):
    sh = tmp_path / "run.sh"
    sh.write_text("#!/bin/bash\necho hello\necho world\n")
    chunks = chunk_file(sh)
    assert len(chunks) >= 1
    assert chunks[0].language == "shell"


def test_code_unsupported_extension_returns_empty(tmp_path: Path):
    txt = tmp_path / "data.xyz"
    txt.write_text("some random data")
    assert chunk_file(txt) == []


def test_code_line_numbers(tmp_path: Path):
    py = tmp_path / "lines.py"
    py.write_text("line1\nline2\nline3\nline4\nline5\n")
    chunks = chunk_file(py)
    assert chunks[0].line_start == 1
    assert chunks[0].line_end >= 1


def test_code_chunk_index_sequential(tmp_path: Path):
    py = tmp_path / "multi.py"
    funcs = "\n\n".join(
        f"def func_{i}():\n    " + "\n    ".join(f"x{j} = {j}" for j in range(30))
        for i in range(20)
    )
    py.write_text(funcs)
    chunks = chunk_file(py)
    if len(chunks) > 1:
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))


# --- _extract_h1_title ---


def test_extract_h1_title():
    assert _extract_h1_title("# Hello\n## Sub\n") == "Hello"


def test_extract_h1_ignores_h2():
    assert _extract_h1_title("## Not a title\n") == ""


def test_extract_h1_empty():
    assert _extract_h1_title("") == ""


def test_extract_h1_strips_whitespace():
    assert _extract_h1_title("#  Spaced  \n") == "Spaced"


# --- _LineTracker ---


def test_line_tracker_sequential():
    text = "aaa\nbbb\nccc\nddd\n"
    tracker = _LineTracker(text)
    assert tracker.find_lines("bbb") == (2, 2)
    assert tracker.find_lines("ddd") == (4, 4)


def test_line_tracker_multiline_chunk():
    text = "a\nb\nc\nd\ne\n"
    tracker = _LineTracker(text)
    assert tracker.find_lines("b\nc\nd") == (2, 4)


def test_line_tracker_not_found_returns_last():
    text = "hello\nworld\n"
    tracker = _LineTracker(text)
    tracker.find_lines("hello")
    start, _end = tracker.find_lines("MISSING")
    assert start == 1  # falls back to last known
