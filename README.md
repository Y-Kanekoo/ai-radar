# ai-radar

> AI/LLM news aggregator with public RSS feed, local MCP server, and Discord webhook.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

**ai-radar** collects articles, papers, and product releases from 20+ verified AI/LLM
sources (English + Japanese) and serves them through three channels:

1. **Public RSS feed** — hosted on GitHub Pages
2. **Local MCP server** — query the corpus from Claude Desktop / Claude Code
3. **Discord webhook (7-channel)** — push notifications per category

A sibling project of [qa-radar](https://github.com/Y-Kanekoo/qa-radar), built from
the same `crawler / publisher / tagger / summarizer` core but configured for AI/LLM
sources, 12 AI-specific tags, hype-filter, and trust-tier scoring.

For the Japanese readme, see [README.ja.md](README.ja.md).

## Status

🚧 Under active development (Phase 1 in progress, 2026-05-13 launch).

| Phase | Scope | Status |
|-------|-------|--------|
| 0. Foundation | Clone + 11 RSS sources + 12 AI tags + tests green + 1ch Discord | ✅ |
| 0.5. Scrapers | +9 sources (HTML scraper layer for Anthropic / HF Papers / Cursor etc.) | ✅ |
| 1. Dedup 5-layer + 7-channel Discord | URL/Levenshtein/body_hash/thread/cluster + category webhooks | ✅ |
| 2. Trust-tier + hype-filter + LLM fallback | Source tier scoring, hype detection, MCP-based tagging | ✅ |
| 3. Benchmarks + GitHub Trending | LMArena + MTEB + GitHub Trending (scraping) + DB v5 snapshots | ✅ |
| 3.5. Benchmark expansion | BigCodeBench + AlpacaEval added. Open LLM v2 / HELM deferred. | ✅ |
| 4. Personalization | Bayesian recommendation, A/B test, reaction learning | ⏳ |
| 5. JP sources + Podcast | Zenn / Qiita / Hatena / Cognitive Revolution etc. | ⏳ |
| 6. Core extraction | Reconsider qa-radar-core abstraction | ⏳ |

## Sources (20 total, Phase 0 + 0.5)

20 verified sources: 12 RSS direct + 8 HTML scraper. Each source declares
`fetch_kind: rss | scraper` in `config/sources.yaml`.

| Category | Sources |
|---|---|
| **Release (Tier 1, RSS)** | Hugging Face Blog, Google Research Blog, Microsoft AI News |
| **Release (Tier 1, scraper)** | Anthropic News, Cursor Blog, Luma News, BFL Blog, Sakana AI, Kimi Blog (Moonshot) |
| **Paper (RSS)** | arXiv cs.LG |
| **Paper (scraper)** | Hugging Face Papers (Daily), Allen AI Blog |
| **Newsletter** | TLDR AI, Ben's Bites, Latent Space |
| **Tool / Code Editor** | Windsurf, Replit, Cursor |
| **Video / Image gen** | Midjourney (RSS), Luma AI, Black Forest Labs |
| **JP** | Stockmark (RSS), ELYZA News (scraper) |

See [config/sources.yaml](config/sources.yaml) for the full list with feed URLs
and license notes.

## Tags (12 AI-specific)

`llm` / `agent` / `multimodal` / `rag` / `fine-tuning` / `benchmark` / `safety` /
`regulation` / `paper` / `release` / `tool` / `opinion`

Configured in [config/tag_rules.yaml](config/tag_rules.yaml) with co-occurrence
rules, hype-keyword filter (Phase 2), and source-fixed tags.

## Trust-tier scoring (Phase 2)

Each article receives a delivery score before Discord notification:

```
score = source_tier_score(tier) × time_decay(category, age) × user_interest
        × (1 - hype_penalty if is_hype else 1.0)
```

| Tier | Source kind | Score weight |
|---|---|---|
| 1 | Official (Anthropic, arXiv, Google Research) | 1.0 |
| 2 | Peer-reviewed (arxiv preprints, MIT TR) | 0.8 |
| 3 | Curation (TLDR AI, Ben's Bites, Latent Space) | 0.7 |
| 4 | Personal blog (Substack, Medium, HN) | 0.5 |
| 5 | SNS / aggregators / auto-translation | 0.3 |

Time decay λ per category: `release=0.5` (half-life 1.4d), `benchmark=0.3` (2.3d),
`paper=0.05` (14d), `tutorial=0.01` (70d). Delivery threshold = 0.5.

Articles below threshold are marked as notified (skipped from re-evaluation).

## Hype filter (Phase 2)

Articles from Tier 4-5 sources with hype keywords (`revolutionary`, `breakthrough`,
`AGI achieved`, `革命的`, etc.) get `is_hype=true`. Discord embed titles are prefixed
with **⚠️** and the score is halved (`HYPE_PENALTY=0.5`).

## Anti-tag filter (Phase 2)

Articles whose title or body matches `anti_tags` (hiring / careers / sponsored / 採用 etc.)
are skipped during crawl, never reaching Discord or RSS.

## MCP LLM fallback (Phase 2)

`get_untagged_articles(days, limit)` MCP tool returns articles with empty tag arrays.
Use it from Claude Desktop / Code to manually request tag suggestions:

```
@ai-radar Get the untagged articles from the last 7 days and suggest tags
from the 12 AI taxonomy.
```

ai-radar does **not** call any LLM API — Claude (yours) does the reasoning within
the Pro/Max subscription.

## Dedup 5-layer (Phase 1)

Each crawled article is checked against the existing corpus in 5 layers before
insertion. Layers 1–3 reject duplicates; layers 4–5 assign clustering IDs.

| Layer | Check | Threshold | Implementation |
|---|---|---|---|
| ① URL normalized | Same `normalized_url` (utm/fbclid stripped, arXiv version stripped, trailing slash unified) | exact match | `is_known_by_normalized_url` |
| ② Title similarity | `SequenceMatcher.ratio()` over 24 h window | ≥ 0.85 | `find_similar_title` |
| ③ Body hash cross-source | Same `body_hash` in another source | exact match | `find_cross_source_duplicate` |
| ④ Citation thread | Same `thread_id` via title similarity over 24 h window | ≥ 0.90 | `find_thread_id` |
| ⑤ Temporal cluster | Same `cluster_id` via title similarity over 24 h window | ≥ 0.80 | `find_cluster_id` |

Threshold defaults are tunable per call. DB stores `normalized_url`, `thread_id`,
`cluster_id` columns added in schema v3 (auto-migrated from v2).

## Discord 7-channel webhook (Phase 1)

`scripts/notify_discord.py` dispatches articles per `source.category`. Configure
one webhook URL per channel via env var, or use a single `DISCORD_WEBHOOK_URL`
as fallback for all categories.

| Env var | Channel example | Categories |
|---|---|---|
| `AI_RADAR_DISCORD_WEBHOOK_RELEASE` | `#ai-radar-release` | Anthropic, OpenAI, HF Blog, Google Research, MS AI, Sakana, BFL, Luma, Kimi, Midjourney |
| `AI_RADAR_DISCORD_WEBHOOK_PAPER` | `#ai-radar-paper` | arXiv cs.LG, HF Papers, AI2 |
| `AI_RADAR_DISCORD_WEBHOOK_NEWSLETTER` | `#ai-radar-newsletter` | TLDR AI, Ben's Bites, Latent Space |
| `AI_RADAR_DISCORD_WEBHOOK_TOOL` | `#ai-radar-tool` | Windsurf, Replit, Cursor |
| `AI_RADAR_DISCORD_WEBHOOK_JP` | `#ai-radar-jp` | Stockmark, ELYZA |
| `AI_RADAR_DISCORD_WEBHOOK_BENCHMARK` | `#ai-radar-benchmark` | reserved for Phase 3 |
| `AI_RADAR_DISCORD_WEBHOOK_TREND` | `#ai-radar-trend` | reserved for Phase 3 |
| `AI_RADAR_DISCORD_WEBHOOK_PODCAST` | `#ai-radar-podcast` | reserved for Phase 5 |
| `DISCORD_WEBHOOK_URL` | (legacy / fallback) | any category without a specific webhook |

Resolution order: per-category env > `DISCORD_WEBHOOK_URL` fallback > skip.
Each category has an independent notification record (`channel=discord_<category>`),
so the same article is delivered only once per category.

Configure these as **GitHub Actions secrets** for the `crawl.yml` workflow.

## Benchmark snapshots (Phase 3)

Phase 3 introduces a *snapshot + diff* infrastructure for tracking leaderboards
and trending repositories. A separate GitHub Actions workflow (`benchmarks.yml`,
22:00 JST daily) fetches each registered source, stores the ranked entries as
JSON in DB v5's `benchmark_snapshots` table, computes a diff against the previous
snapshot, and posts changes to per-category Discord channels.

| Source | Slug | Data origin | Category |
|---|---|---|---|
| LMArena (Chatbot Arena, text style-controlled) | `lmarena_text` | HF `lmarena-ai/leaderboard-dataset` via Datasets Server `rows` API | `benchmark` |
| MTEB (registered models) | `mteb_models` | HF `mteb/results/paths.json` | `benchmark` |
| BigCodeBench (Complete) | `bigcodebench` | HF `bigcode/bigcodebench-results` via Datasets Server | `benchmark` |
| AlpacaEval (length-controlled win rate) | `alpaca_eval` | GitHub raw CSV from `tatsu-lab/alpaca_eval` | `benchmark` |
| GitHub Trending (daily, AI-keyword filtered) | `github_trending_daily` | scraping `github.com/trending` (AI keyword: `llm` / `agent` / `gpt` / `rag` / `diffusion` / etc.) | `trend` |

The diff bucket is one of: 🆕 new rank-in, 📈 rank up (≥2 positions), 📉 rank down
(≥2 positions), ❌ dropped. The CLI is:

```bash
uv run python scripts/track_benchmarks.py            # all registered fetchers
uv run python scripts/track_benchmarks.py --source lmarena_text --dry-run
```

`Open LLM Leaderboard v2` and `HELM lite` were investigated in Phase 3.5 but
deferred again: v2 candidate datasets (`HuggingFaceH4/open_llm_leaderboard_v2`,
`open-llm-leaderboard/contents-v2`) all return 401, suggesting deprecation /
consolidation; HELM has no documented public raw data URL.

## Discord reaction collector (Phase 4a)

Phase 4a wires the Discord reactions feedback loop *infrastructure*:

1. `scripts/notify_discord.py` now posts each item with `?wait=true` and stores
   `discord_message_id` / `discord_channel_id` into `article_notifications`.
2. A separate Bot user (env `AI_RADAR_DISCORD_BOT_TOKEN`) reads reactions via
   `GET /channels/{cid}/messages/{mid}` on a 23:00 JST daily cron
   (`scripts/collect_reactions.py`, `.github/workflows/collect-reactions.yml`).
3. Aggregated `reactions(emoji, user_count, collected_at)` rows are stored in
   the v6 `reactions` table for later scoring use.

The scoring layer (`crawler/scoring.user_interest_for`) has the data path wired
but **returns the default 1.0** until Phase 4.5, when a Beta posterior over
`user_interest_for(slug)` is applied to `should_deliver`. Reaction data needs
2–4 weeks of accumulation before the posterior is meaningful.

The Bot token must have **Read Messages / View Channels** permission in the 7
ai-radar channels. Webhooks alone cannot read reactions (write-only).

> ⚠️ `?wait=true` makes Discord block until the message is delivered (~1–2s per
> request) instead of fire-and-forget (~50ms). If `notify_discord.py` hits
> timeouts during peak batches, raise `--rate-delay` (default 1.0s) accordingly.

## MCP server usage

The local MCP server exposes 6 tools you can call from Claude Desktop / Claude Code:

- `search_articles(query, tags?, date_from?, date_to?, limit, offset)` — full-text search via SQLite FTS5+BM25
- `list_recent(days, source?, tag?, limit)` — recent articles
- `get_article(article_id, include_body)` — article details
- `list_sources()` — aggregated sources with counts
- `list_tags(min_count, limit)` — tag occurrence counts
- `get_untagged_articles(days, limit)` — Phase 2 LLM-fallback helper (untagged articles for manual classification)

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
