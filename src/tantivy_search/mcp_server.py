"""Minimal MCP server exposing tantivy-search as a tool."""

from fastmcp import FastMCP

from tantivy_search.index import SearchIndex
from tantivy_search.search import format_results, parse_filters, search

mcp = FastMCP("tantivy-search")


@mcp.tool
def tantivy_search(query: str, num_results: int = 5, snippet: bool = True) -> str:
    """Search indexed code and markdown files using BM25 with fuzzy matching.

    Returns compact snippets by default; pass ``snippet=False`` for full chunks.

    Supports inline filters in the query string:
      lang:py, repo:myrepo, file:*.toml, after:7d, before:24h
    Prefix with - to exclude: -lang:python, -repo:vendor
    """
    parsed = parse_filters(query)
    idx = SearchIndex()
    results = search(
        idx,
        parsed,
        num_results=num_results,
        snippet_max_chars=300 if snippet else 0,
    )
    return format_results(results, snippet_mode=snippet)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
