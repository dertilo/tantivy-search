"""Shared fixtures for tantivy-search tests."""

import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    """Create a small sample repo with markdown and code files."""
    repo = tmp_path / "sample-repo"
    repo.mkdir()

    # Python file
    (repo / "main.py").write_text(
        textwrap.dedent("""\
        import os

        def hello(name: str) -> str:
            \"\"\"Greet someone.\"\"\"
            return f"Hello, {name}!"

        def goodbye(name: str) -> str:
            return f"Goodbye, {name}!"

        class Greeter:
            def __init__(self, prefix: str = "Hi"):
                self.prefix = prefix

            def greet(self, name: str) -> str:
                return f"{self.prefix}, {name}!"
    """)
    )

    # Markdown file with frontmatter
    (repo / "README.md").write_text(
        textwrap.dedent("""\
        ---
        title: Sample Project
        tags: [python, demo]
        ---

        # Sample Project

        This is a sample project for testing.

        ## Installation

        Run `pip install sample`.

        ## Usage

        ```python
        from sample import hello
        hello("world")
        ```

        ### Advanced Usage

        See the docs for more details.
    """)
    )

    # Markdown without frontmatter
    (repo / "CHANGELOG.md").write_text(
        textwrap.dedent("""\
        # Changelog

        ## v1.0.0

        - Initial release
        - Added hello function

        ## v0.1.0

        - Pre-release
    """)
    )

    # Shell script (no Language enum)
    (repo / "run.sh").write_text("#!/bin/bash\necho 'hello'\n")

    # Nested dir
    sub = repo / "src"
    sub.mkdir()
    (sub / "utils.py").write_text(
        textwrap.dedent("""\
        def add(a: int, b: int) -> int:
            return a + b
    """)
    )

    # File that should be skipped (inside .git)
    git_dir = repo / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("skip me")

    # Binary-like large file — not created (just skip dirs tested above)

    return repo
