import tantivy


def build_schema() -> tantivy.Schema:
    builder = tantivy.SchemaBuilder()

    # Identity / metadata — raw tokenizer for exact match filters and deletion
    builder.add_text_field("id", stored=True, tokenizer_name="raw", index_option="freq")
    builder.add_text_field(
        "file_path", stored=True, tokenizer_name="raw", index_option="freq"
    )
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
