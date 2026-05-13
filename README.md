# ai-radar

> AI/LLM news aggregator with public RSS feed, local MCP server, and Discord webhook.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

**ai-radar** collects articles, papers, and product releases from 11+ verified AI/LLM
sources (English + Japanese) and serves them through three channels:

1. **Public RSS feed** — hosted on GitHub Pages
2. **Local MCP server** — query the corpus from Claude Desktop / Claude Code
3. **Discord webhook** — push notifications for new articles

A sibling project of [qa-radar](https://github.com/Y-Kanekoo/qa-radar), built from
the same `crawler / publisher / tagger / summarizer` core but configured for AI/LLM
sources, 12 AI-specific tags, hype-filter, and trust-tier scoring.

For the Japanese readme, see [README.ja.md](README.ja.md).

## Status

🚧 Under active development (Phase 0 in progress, 2026-05-13 launch).

| Phase | Scope | Status |
|-------|-------|--------|
| 0. Foundation | Clone + 11 RSS sources + 12 AI tags + tests green + 1ch Discord | 🚧 |
| 1. Tag refinement + LLM fallback | Threading, reaction collection start | ⏳ |
| 2. Dedup 5-layer + trust-tier + hype-filter | URL/Levenshtein/body_hash/citation/temporal | ⏳ |
| 3. Benchmarks + GitHub Trending | LMArena / HF Leaderboard / MTEB / huchenme | ⏳ |
| 4. Personalization | Bayesian recommendation, A/B test | ⏳ |
| 5. JP sources + Podcast | Zenn / Qiita / Hatena / Cognitive Revolution etc. | ⏳ |
| 6. Core extraction | Reconsider qa-radar-core abstraction | ⏳ |

## Sources (Phase 0, RSS-first)

11 verified sources across 4 categories — all RSS feeds (no scraping required in
Phase 0). Scraping-only sources (Anthropic, HF Papers, Cursor, Sakana etc.) will
be added in Phase 0.5 once the scraper layer is implemented.

| Category | Sources |
|---|---|
| **Release (Tier 1)** | Hugging Face Blog, Google Research Blog, Microsoft AI News |
| **Paper** | arXiv cs.LG |
| **Newsletter** | TLDR AI, Ben's Bites, Latent Space |
| **Tool / Code Editor** | Windsurf, Replit |
| **Video / Image gen** | Midjourney (updates.midjourney.com) |
| **JP** | Stockmark |

See [config/sources.yaml](config/sources.yaml) for the full list with feed URLs
and license notes.

## Tags (12 AI-specific)

`llm` / `agent` / `multimodal` / `rag` / `fine-tuning` / `benchmark` / `safety` /
`regulation` / `paper` / `release` / `tool` / `opinion`

Configured in [config/tag_rules.yaml](config/tag_rules.yaml) with co-occurrence
rules, hype-keyword filter (Phase 2), and source-fixed tags.

## MCP server usage

The local MCP server exposes 5 tools you can call from Claude Desktop / Claude Code:

- `search_articles(query, tags?, date_from?, date_to?, limit, offset)` — full-text search via SQLite FTS5+BM25
- `list_recent(days, source?, tag?, limit)` — recent articles
- `get_article(article_id, include_body)` — article details
- `list_sources()` — aggregated sources with counts
- `list_tags(min_count, limit)` — tag occurrence counts

Register it in your MCP client config (`claude_desktop_config.json` or `.mcp.json`):

```json
{
  "mcpServers": {
    "ai-radar": {
      "command": "uv",
      "args": ["--directory", "/path/to/ai-radar", "run", "python", "-m", "ai_radar"]
    }
  }
}
```

DB path resolution order: `AI_RADAR_DB_PATH` env var > repo-local
`data/articles.db` > `~/Library/Caches/ai-radar/articles.db` (macOS).

## Development setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Y-Kanekoo/ai-radar.git
cd ai-radar
uv sync --dev
uv run pytest -v
uv run ruff check .

# Start the MCP server locally for manual testing
uv run python -m ai_radar
```

## Subscription-only policy

This project does **not** call LLM APIs. Summaries are computed interactively
via MCP from Claude Desktop / Claude Code (within Claude Pro/Max subscription).
The optional `[ai]` extra is left disabled by default and kept for backward
compatibility with qa-radar's `summarize_article` MCP tool.

## License

MIT — see [LICENSE](LICENSE). For data handling guidelines, see [NOTICE](NOTICE).
