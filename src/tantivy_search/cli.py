import argparse
import logging
from pathlib import Path

from tantivy_search.config import (
    INDEX_DIR,
    SCHEMA_VERSION,
    check_schema_version,
    nuke_index,
    write_schema_version,
)
from tantivy_search.index import SearchIndex
from tantivy_search.search import (
    parse_filters,
    search,
    format_results,
    _parse_time_value,
)

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Local code and markdown search tool built on Tantivy.",
        epilog=(
            "inline filters (also supported inside the query string):\n"
            "  lang:<name>   filter by language (python, js, ts, cpp, rust, markdown, ...)\n"
            "                aliases: py, md, rb, rs, sh, cs, kt\n"
            "  -lang:<name>  exclude language (negation, works for all filters)\n"
            "\n"
            "examples:\n"
            '  tantivy-search "error handling" -l py\n'
            '  tantivy-search "config" -r myrepo -f "*.toml"\n'
            '  tantivy-search "ssh setup" -r claude-sessions --after 7d\n'
            '  tantivy-search "error handling" -s             # snippets\n'
            '  tantivy-search "error handling" -n 10 -e 2,5   # expand results 2 and 5\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "query", nargs="?", help="Search query (inline filters like lang:py also work)"
    )
    parser.add_argument(
        "-n", "--num-results", type=int, default=5, help="Max results (default: 5)"
    )
    parser.add_argument(
        "-r",
        "--repo",
        type=str,
        default=None,
        help="Filter by repository name (e.g. conversation-history, myrepo)",
    )
    parser.add_argument(
        "-l",
        "--lang",
        type=str,
        default=None,
        help="Filter by language (python, js, markdown, ... aliases: py, md, rs)",
    )
    parser.add_argument(
        "-f", "--file", type=str, default=None, help="Filter by file path substring"
    )
    parser.add_argument(
        "--after",
        type=str,
        default=None,
        help="Only results after time (relative: 24h, 7d, 2w or absolute: 2026-03-14)",
    )
    parser.add_argument(
        "--before",
        type=str,
        default=None,
        help="Only results before time (relative: 24h, 7d, 2w or absolute: 2026-03-14)",
    )
    parser.add_argument(
        "--no-fuzzy", action="store_true", help="Disable fuzzy matching"
    )
    parser.add_argument(
        "-s",
        "--snippet",
        action="store_true",
        help="Return snippets instead of full content",
    )
    parser.add_argument(
        "-e",
        "--expand",
        type=str,
        default=None,
        metavar="INDICES",
        help="Return full content for specific result indices (e.g. 0,2,5)",
    )
    parser.add_argument("--status", action="store_true", help="Show index stats")

    args = parser.parse_args()

    if args.status:
        cmd_status()
    elif args.query:
        cmd_search(args)
    else:
        parser.print_help()


def main_index() -> None:
    parser = argparse.ArgumentParser(
        description="Index directories for tantivy-search.",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Directories to index (repo name derived from basename)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not check_schema_version():
        logger.info("Schema version changed, rebuilding index...")
        nuke_index()

    idx = SearchIndex()
    for path in args.paths:
        repo_path = str(path.resolve())
        repo_name = path.resolve().name
        logger.info("Indexing %s ...", repo_name)
        stats = idx.index_repo(repo_path, repo_name)
        logger.info(
            "  %d files, %d chunks in %.1fs",
            stats.files_indexed,
            stats.chunks_total,
            stats.elapsed_seconds,
        )

    write_schema_version()


def cmd_search(args: argparse.Namespace) -> None:
    parsed = parse_filters(args.query)

    # CLI flags override/supplement inline filters
    if args.repo and not parsed.repo_filter:
        parsed.repo_filter = args.repo
    if args.lang and not parsed.lang_filter:
        parsed.lang_filter = args.lang
    if args.file and not parsed.file_filter:
        parsed.file_filter = args.file
    if args.after and not parsed.after:
        parsed.after = _parse_time_value(args.after)
    if args.before and not parsed.before:
        parsed.before = _parse_time_value(args.before)

    idx = SearchIndex()

    expand_indices = None
    if args.expand is not None:
        expand_indices = {int(i) for i in args.expand.split(",")}

    snippet_mode = args.snippet and expand_indices is None

    results = search(
        idx,
        parsed,
        num_results=args.num_results,
        fuzzy=not args.no_fuzzy,
        snippet_max_chars=300 if snippet_mode else 0,
    )

    if expand_indices is not None:
        results = [r for i, r in enumerate(results) if i in expand_indices]

    print(format_results(results, snippet_mode=snippet_mode))


def cmd_status() -> None:
    idx = SearchIndex()

    if INDEX_DIR.exists():
        size_bytes = sum(f.stat().st_size for f in INDEX_DIR.rglob("*") if f.is_file())
        if size_bytes > 1_000_000:
            size_str = f"{size_bytes / 1_000_000:.1f} MB"
        else:
            size_str = f"{size_bytes / 1_000:.1f} KB"
    else:
        size_str = "0 KB"

    print(f"Schema version: {SCHEMA_VERSION}")
    print(f"Index path:     {INDEX_DIR}")
    print(f"Index size:     {size_str}")
    print(f"Total docs:     {idx.num_docs}")


if __name__ == "__main__":
    main()
