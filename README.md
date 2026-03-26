# tantivy-search

Local code and markdown search tool built on [Tantivy](https://github.com/quickwit-oss/tantivy). Indexes directories for fast BM25 keyword search across code and markdown files.

## Features

- **BM25 search** with hybrid exact (5x boosted) + fuzzy matching
- **Field boosts**: title (3x), heading_path (2x), content (1x)
- **Language-aware chunking** for 30+ programming languages and markdown
- **Inline filters**: `lang:py`, `repo:myrepo`, `file:*.toml`, `after:7d` (with negation)
- **Snippet mode** for compact output, with selective expansion of individual results

## Usage

```bash
# Index directories (repo name derived from directory basename)
tantivy-index ~/code/my-project ~/Documents/notes

# Search
tantivy-search "error handling lang:py"
tantivy-search "config repo:my-project f:*.toml"
tantivy-search "README lang:md"
tantivy-search "error -lang:python"          # exclude a language
tantivy-search "ssh setup after:7d"          # recent results only

# Snippet mode
tantivy-search "error handling" -s           # compact output
tantivy-search "error handling" -n 10 -e 2,5 # expand results 2 and 5

# Index stats
tantivy-search --status
```

### Inline filters

| Filter | Description |
|--------|-------------|
| `lang:<name>` | Filter by language (python, js, ts, rust, markdown, ...) |
| `file:<pat>` / `f:<pat>` | Filter by file path substring |
| `repo:<name>` / `r:<name>` | Filter by repository name |
| `after:<time>` / `before:<time>` | Timestamp filter (24h, 7d, 2w, or 2026-03-14) |
| `-lang:<name>` | Exclude a language (negation works for all filters) |

Language aliases: `py`, `md`, `rb`, `rs`, `sh`, `cs`, `kt`.

## Keeping the index up to date

`tantivy-index` does a full reindex of the given directories each time. For periodic reindexing, a systemd timer works well:

```ini
# ~/.config/systemd/user/tantivy-index.service
[Unit]
Description=Reindex tantivy-search

[Service]
Type=oneshot
ExecStart=%h/.local/bin/tantivy-index %h/code/my-project %h/Documents/notes
```

```ini
# ~/.config/systemd/user/tantivy-index.timer
[Unit]
Description=Reindex every 5 minutes

[Timer]
OnBootSec=30
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

For live reindexing (e.g. git-based change detection), see the Python API: `SearchIndex.index_repo(repo_path, repo_name)`.

## MCP server

`pip install tantivy-search[mcp]` adds an optional [MCP](https://modelcontextprotocol.io/) server. Add to your Claude Desktop / Claude Code config:

```json
{
  "mcpServers": {
    "tantivy-search": {
      "command": "tantivy-search-mcp"
    }
  }
}
```