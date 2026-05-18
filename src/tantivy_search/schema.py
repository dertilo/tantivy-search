import tantivy


def build_schema() -> tantivy.Schema:
    builder = tantivy.SchemaBuilder()

    # Identity / metadata — raw tokenizer for exact match filters and deletion
    builder.add_text_field("id", stored=True, tokenizer_name="raw", index_option="freq")
    builder.add_text_field(
        "file_path", stored=True, tokenizer_name="raw", index_option="freq"
    )
    # ``repo`` is a logical index partition (a.k.a. "sub-repo"). It may be a bare
    # name (``"claudia"``) or a ``/``-delimited hierarchy (e.g.
    # ``"conversation-history/old-laptop/<conv-id>"``). The value is chosen by
    # whoever calls ``SearchIndex.index_repo()`` / ``add_file_chunks()`` and is not
    # required to be a git repository. Hierarchical names enable
    # multi-granularity filtering via the prefix arm of ``_repo_query``.
    builder.add_text_field(
        "repo", stored=True, tokenizer_name="raw", index_option="freq"
    )
    builder.add_text_field(
        "language", stored=True, tokenizer_name="raw", index_option="freq"
    )
    # Searchable text — default tokenizer (lowercase + split) with positions for phrase queries
    builder.add_text_field(
        "content", stored=True, tokenizer_name="default", index_option="position"
    )
    builder.add_text_field(
        "heading_path", stored=True, tokenizer_name="default", index_option="position"
    )
    builder.add_text_field(
        "title", stored=True, tokenizer_name="default", index_option="position"
    )

    # Timestamp — indexed + fast for range queries
    builder.add_date_field("timestamp", stored=True, indexed=True, fast=True)

    # Numeric — stored only
    builder.add_integer_field("line_start", stored=True, indexed=False)
    builder.add_integer_field("line_end", stored=True, indexed=False)

    return builder.build()
