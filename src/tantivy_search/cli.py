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
    _parse_time_value,
    format_results,
    parse_filters,
    search,
)

logger = logging.getLogger(__name__)


def _validate_path(value: str) -> str:
    if not value.startswith("/"):
        raise argparse.ArgumentTypeError(
            f"--path must be an absolute filesystem path starting with '/': {value!r}"
        )
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Local code and markdown search tool built on Tantivy.",
        epilog=(
            "inline filters (also supported inside the query string):\n"
            "  lang:<name>   filter by language (python, js, ts, cpp, rust, markdown, ...)\n"
            "                aliases: py, md, rb, rs, sh, cs, kt\n"
            "  -lang:<name>  exclude language (negation)\n"
            "\n"
            "examples:\n"
            '  tantivy-search "error handling" -l py\n'
            '  tantivy-search "config" --path /home/user/code/myrepo\n'
            '  tantivy-search "ssh setup" --path /home/user/Documents/notes --after 7d\n'
            '  tantivy-search "error handling" -n 10 -e 2,5  # expand results 2 and 5 to full content\n'
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
        "--path",
        type=_validate_path,
        action="append",
        default=None,
        metavar="PATH",
        help=(
            "Absolute filesystem path. Repeat to OR multiple paths. "
            "Matches the path itself or any descendant."
        ),
    )
    parser.add_argument(
        "-l",
        "--lang",
        type=str,
        default=None,
        help="Filter by language (python, js, markdown, ... aliases: py, md, rs)",
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
        "-e",
        "--expand",
        type=str,
        default=None,
        metavar="INDICES",
        help="Return full content for specific result indices (e.g. 0,2,5). Without -e, results are snippets.",
    )
    parser.add_argument("--status", action="store_true", help="Show index stats")
    parser.add_argument(
        "--list-paths",
        action="store_true",
        help="Print all indexed filesystem paths as a tree with doc counts",
    )

    args = parser.parse_args()

    if args.status:
        cmd_status()
    elif args.list_paths:
        cmd_list_paths(args)
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


def _render_path_tree(paths: dict[str, int]) -> str:
    if not paths:
        return "Paths in index (0 roots, 0 docs)"
    total = sum(paths.values())
    lines = [f"Paths in index ({len(paths)} roots, {total} docs)", ""]
    seen_prefixes: set[str] = set()
    name_width = 48
    for name in sorted(paths):
        parts = name.split("/")
        for i in range(len(parts) - 1):
            prefix = "/".join(parts[: i + 1]) + "/"
            if prefix not in seen_prefixes:
                seen_prefixes.add(prefix)
                indent = "    " * i
                lines.append(f"{indent}{parts[i]}/")
        leaf_indent = "    " * (len(parts) - 1)
        leaf = parts[-1]
        # Pad leaf+indent column to name_width, then right-align count
        label = f"{leaf_indent}{leaf}"
        pad = max(1, name_width - len(label))
        lines.append(f"{label}{' ' * pad}{paths[name]:>8,}")
    return "\n".join(lines)


def cmd_list_paths(args: argparse.Namespace) -> int:
    idx = SearchIndex()
    paths = idx.list_paths()
    print(_render_path_tree(paths))
    return 0


def cmd_search(args: argparse.Namespace) -> None:
    parsed = parse_filters(args.query)

    # CLI flags supplement inline filters
    if args.lang and not parsed.lang_filter:
        parsed.lang_filter = args.lang
    if args.after and not parsed.after:
        parsed.after = _parse_time_value(args.after)
    if args.before and not parsed.before:
        parsed.before = _parse_time_value(args.before)
    if args.path:
        parsed.paths = tuple(args.path)

    idx = SearchIndex()

    expand_indices = None
    if args.expand is not None:
        expand_indices = {int(i) for i in args.expand.split(",")}

    # Snippets by default; full content only for indices listed via -e/--expand.
    snippet_mode = expand_indices is None

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
