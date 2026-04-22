import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Self

import tantivy

from tantivy_search.index import SearchIndex

SEARCH_FIELDS = ["content", "title", "heading_path"]
FIELD_BOOSTS = {"title": 3.0, "heading_path": 2.0, "content": 1.0}
EXACT_BOOST = 5.0

# Maps filter key aliases to (ParsedQuery field name, schema field name)
FILTER_KEYS: dict[str, tuple[str, str]] = {
    "lang": ("lang_filter", "language"),
    "file": ("file_filter", "file_path"),
    "f": ("file_filter", "file_path"),
    "repo": ("repo_filter", "repo"),
    "r": ("repo_filter", "repo"),
}

FILTER_RE = re.compile(r"(-?)(lang|file|f|repo|r):(\S+)")
TIME_FILTER_RE = re.compile(r"(after|before):(\S+)")

# Relative time units for after:/before: filters
_TIME_UNITS = {"h": "hours", "d": "days", "w": "weeks"}
_RELATIVE_RE = re.compile(r"^(\d+)([hdw])$")

# Shorthand aliases for lang: filter values → stored language name
LANG_ALIASES: dict[str, str] = {
    "py": "python",
    "rb": "ruby",
    "rs": "rust",
    "md": "markdown",
    "sh": "shell",
    "cs": "csharp",
    "kt": "kotlin",
}


@dataclass
class SearchResult:
    file_path: str
    repo: str
    content: str
    language: str
    heading_path: str
    title: str
    line_start: int
    line_end: int
    timestamp: str = ""
    snippet: str = ""

    @classmethod
    def from_doc(cls, doc: tantivy.Document) -> Self:
        ts = doc.get_first("timestamp")
        return cls(
            file_path=doc.get_first("file_path") or "",
            repo=doc.get_first("repo") or "",
            content=doc.get_first("content") or "",
            language=doc.get_first("language") or "",
            heading_path=doc.get_first("heading_path") or "",
            title=doc.get_first("title") or "",
            line_start=doc.get_first("line_start") or 0,
            line_end=doc.get_first("line_end") or 0,
            timestamp=str(ts) if ts else "",
        )

    def to_dict(self, snippet_mode: bool = False, index: int | None = None) -> dict:
        """Convert to dict, omitting empty optional fields.

        If snippet_mode is True and a snippet exists, replace content with
        the snippet for compact output.  If index is set, include it as the
        first field (for expand workflow).
        """
        d: dict = {}
        if index is not None:
            d["index"] = index
        raw = asdict(self)
        if snippet_mode and raw["snippet"]:
            raw["content"] = raw["snippet"]
        for key in ("file_path", "repo", "content", "language"):
            d[key] = raw[key]
        for key in ("heading_path", "title", "timestamp"):
            if raw[key]:
                d[key] = raw[key]
        d["lines"] = f"{self.line_start}-{self.line_end}"
        return d


@dataclass
class ParsedQuery:
    text: str
    lang_filter: str | None = None
    file_filter: str | None = None
    repo_filter: str | None = None
    after: datetime | None = None
    before: datetime | None = None
    lang_excludes: list[str] | None = None
    file_excludes: list[str] | None = None
    repo_excludes: list[str] | None = None


def _parse_time_value(value: str) -> datetime | None:
    """Parse a time value: relative (24h, 7d, 2w) or absolute (2026-03-14)."""
    m = _RELATIVE_RE.match(value)
    if m:
        amount, unit = int(m.group(1)), _TIME_UNITS[m.group(2)]
        return datetime.now(timezone.utc) - timedelta(**{unit: amount})
    # Try absolute date (YYYY-MM-DD)
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    # Try absolute datetime (YYYY-MM-DDTHH:MM:SS)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def parse_filters(raw_query: str) -> ParsedQuery:
    """Extract lang:, file:, repo:, after:, before: filters from query string.

    Supports negation: ``-lang:python`` excludes Python results.
    """
    parsed = ParsedQuery(text="")
    remaining = raw_query

    for match in TIME_FILTER_RE.finditer(raw_query):
        key, value = match.group(1), match.group(2)
        remaining = remaining.replace(match.group(0), "", 1)
        dt = _parse_time_value(value)
        if dt is not None:
            setattr(parsed, key, dt)

    for match in FILTER_RE.finditer(remaining):
        negated, key, value = match.group(1), match.group(2), match.group(3)
        remaining = remaining.replace(match.group(0), "", 1)
        attr_name, _ = FILTER_KEYS[key]

        if negated:
            exclude_attr = attr_name.replace("_filter", "_excludes")
            lst = getattr(parsed, exclude_attr) or []
            lst.append(value)
            setattr(parsed, exclude_attr, lst)
        else:
            setattr(parsed, attr_name, value)

    parsed.text = remaining.strip()
    return parsed


def _build_text_query(index: tantivy.Index, text: str, fuzzy: bool) -> tantivy.Query:
    """Build hybrid exact (boosted) + fuzzy text query."""
    exact_q = index.parse_query(
        text, default_field_names=SEARCH_FIELDS, field_boosts=FIELD_BOOSTS
    )
    boosted_exact = tantivy.Query.boost_query(exact_q, EXACT_BOOST)

    if not fuzzy:
        return boosted_exact

    fuzzy_q = index.parse_query(
        text,
        default_field_names=SEARCH_FIELDS,
        field_boosts=FIELD_BOOSTS,
        fuzzy_fields={field: (True, 1, True) for field in SEARCH_FIELDS},
    )
    return tantivy.Query.boolean_query(
        [
            (tantivy.Occur.Should, boosted_exact),
            (tantivy.Occur.Should, fuzzy_q),
        ]
    )


def _repo_query(schema: tantivy.Schema, value: str) -> tantivy.Query:
    """Build a repo filter query — matches exact name and any sub-path.

    repo:myproject       -> myproject, myproject/deps/foo, ...
    repo:myproject/deps  -> myproject/deps/foo, myproject/deps/bar, ...
    """
    escaped = re.escape(value.rstrip("/"))
    # Use boolean OR: exact match OR prefix match (with /)
    exact = tantivy.Query.term_query(
        schema, "repo", value.rstrip("/"), index_option="freq"
    )
    prefix = tantivy.Query.regex_query(schema, "repo", escaped + "/.*")
    return tantivy.Query.boolean_query(
        [
            (tantivy.Occur.Should, exact),
            (tantivy.Occur.Should, prefix),
        ]
    )


def _build_filter_clauses(
    schema: tantivy.Schema, parsed: ParsedQuery, index: tantivy.Index | None = None
) -> list[tuple[tantivy.Occur, tantivy.Query]]:
    """Build Must/MustNot clauses for each active filter."""
    clauses: list[tuple[tantivy.Occur, tantivy.Query]] = []

    # --- positive (include) filters ---

    if parsed.lang_filter:
        lang = LANG_ALIASES.get(parsed.lang_filter, parsed.lang_filter)
        clauses.append(
            (
                tantivy.Occur.Must,
                tantivy.Query.term_query(schema, "language", lang, index_option="freq"),
            )
        )

    if parsed.repo_filter:
        repos = [r.strip() for r in parsed.repo_filter.split(",")]
        if len(repos) == 1:
            repo_q = _repo_query(schema, repos[0])
        else:
            repo_q = tantivy.Query.boolean_query(
                [(tantivy.Occur.Should, _repo_query(schema, r)) for r in repos]
            )
        clauses.append((tantivy.Occur.Must, repo_q))

    if parsed.file_filter:
        pattern = f".*{re.escape(parsed.file_filter)}.*"
        clauses.append(
            (
                tantivy.Occur.Must,
                tantivy.Query.regex_query(schema, "file_path", pattern),
            )
        )

    # --- time range filters ---

    if (parsed.after or parsed.before) and index is not None:
        after_str = parsed.after.strftime("%Y-%m-%dT%H:%M:%SZ") if parsed.after else "*"
        before_str = (
            parsed.before.strftime("%Y-%m-%dT%H:%M:%SZ") if parsed.before else "*"
        )
        range_q = index.parse_query(f"timestamp:[{after_str} TO {before_str}]")
        clauses.append((tantivy.Occur.Must, range_q))

    # --- default: exclude dep repos unless explicitly targeting them ---

    _targets_deps = (parsed.repo_filter and "/deps" in parsed.repo_filter) or any(
        "/deps" in r for r in (parsed.repo_excludes or [])
    )
    if not _targets_deps:
        clauses.append(
            (
                tantivy.Occur.MustNot,
                tantivy.Query.regex_query(schema, "repo", ".*/deps/.*"),
            )
        )

    # --- negation (exclude) filters ---

    for lang in parsed.lang_excludes or []:
        resolved = LANG_ALIASES.get(lang, lang)
        clauses.append(
            (
                tantivy.Occur.MustNot,
                tantivy.Query.term_query(
                    schema, "language", resolved, index_option="freq"
                ),
            )
        )

    for repo in parsed.repo_excludes or []:
        clauses.append(
            (
                tantivy.Occur.MustNot,
                _repo_query(schema, repo),
            )
        )

    for file_pat in parsed.file_excludes or []:
        pattern = f".*{re.escape(file_pat)}.*"
        clauses.append(
            (
                tantivy.Occur.MustNot,
                tantivy.Query.regex_query(schema, "file_path", pattern),
            )
        )

    return clauses


def build_query(
    idx: SearchIndex, parsed: ParsedQuery, fuzzy: bool = True
) -> tantivy.Query:
    """Combine text query and filter clauses into a single query."""
    clauses: list[tuple[tantivy.Occur, tantivy.Query]] = []

    if parsed.text:
        text_q = _build_text_query(idx.index, parsed.text, fuzzy)
        clauses.append((tantivy.Occur.Must, text_q))

    clauses.extend(_build_filter_clauses(idx.schema, parsed, index=idx.index))

    if not clauses:
        return tantivy.Query.all_query()

    # MustNot-only queries need a base all_query to exclude from
    has_positive = any(occur != tantivy.Occur.MustNot for occur, _ in clauses)
    if not has_positive:
        clauses.insert(0, (tantivy.Occur.Must, tantivy.Query.all_query()))

    if len(clauses) == 1:
        return clauses[0][1]
    return tantivy.Query.boolean_query(clauses)


def search(
    idx: SearchIndex,
    parsed: ParsedQuery,
    num_results: int = 20,
    fuzzy: bool = True,
    snippet_max_chars: int = 0,
) -> list[SearchResult]:
    """Execute search and return results with full chunk content.

    If snippet_max_chars > 0, generates a snippet for each result using
    tantivy's SnippetGenerator and stores it in result.snippet.
    """
    query = build_query(idx, parsed, fuzzy=fuzzy)
    searcher = idx.searcher()
    result = searcher.search(query, limit=num_results, count=True)

    snippet_gen = None
    if snippet_max_chars > 0:
        snippet_gen = tantivy.SnippetGenerator.create(
            searcher, query, idx.schema, "content"
        )
        snippet_gen.set_max_num_chars(snippet_max_chars)

    results: list[SearchResult] = []
    for _score, doc_addr in result.hits:
        doc = searcher.doc(doc_addr)
        sr = SearchResult.from_doc(doc)
        if snippet_gen:
            snippet = snippet_gen.snippet_from_doc(doc)
            sr.snippet = snippet.fragment()
        results.append(sr)

    return results


def format_results(results: list[SearchResult], snippet_mode: bool = False) -> str:
    """Format search results as JSON."""
    return json.dumps(
        [
            r.to_dict(snippet_mode=snippet_mode, index=i if snippet_mode else None)
            for i, r in enumerate(results)
        ],
        indent=2,
    )
