# Changelog

All notable changes to ai-radar will be documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Phase 4a — Discord reactions collector + DB v6 (2026-05-13)

#### Added

- **DB スキーマ v6**: `article_notifications` に `discord_message_id` /
  `discord_channel_id` カラムを追加 (`_premigrate_columns_if_needed` で ALTER).
  `reactions` テーブル + index 2 個 (article_id, collected_at) を新設.
  v5→v6 を `_migrate` で自動マイグレーション.
- **`publisher/discord_bot.py`**: Discord Bot API クライアント
  (`Bot {token}` 認証で `/channels/{cid}/messages/{mid}` を叩いて `reactions` を
  取得). 429 は `Retry-After` で再試行、5xx は指数バックオフ、404/403 は再試行せず
  None を返す. カスタム絵文字は `name:id` 形式に正規化.
- **`publisher/reactions_store.py`**: `ReactionEntry` frozen dataclass + I/O 層.
  `insert_reactions` (`INSERT OR IGNORE`), `aggregate_reactions_by_source`
  (since_unix で時間窓フィルタ), `latest_collected_at`.
- **`publisher/notification_state.py` 拡張**:
  - `mark_notified_with_message_id`: 既存行を `ON CONFLICT UPDATE` で更新する
    際、None 渡しでは既存値を保持する `COALESCE` 動作 (再送時に NULL で上書き
    しない).
  - `fetch_notifications_with_message_id`: `discord_message_id` が NULL の行は
    返さず、reaction 収集対象だけを抽出.
- **`publisher/discord.py` 拡張**: `send_notification_with_message_id` を追加.
  webhook URL に `?wait=true` を付与して 200 レスポンスから `id` /
  `channel_id` を回収.
- **`scripts/collect_reactions.py`**: 過去 N 日 (既定 14 日) の通知済みメッセージ
  に対し Bot API で reactions を取得して DB に保存する CLI.
  `AI_RADAR_DISCORD_BOT_TOKEN` 未設定なら exit 0 でスキップ.
- **`.github/workflows/collect-reactions.yml`**: 23:00 JST daily cron.
  `workflow_dispatch` で `days` / `dry_run` 入力可能. concurrency group で多重実行
  を防止.
- **`crawler/scoring.py` 拡張**: `user_interest_for(slug, conn)` を追加.
  **Phase 4a 時点は no-op で default 1.0 を返す** (DB 経路だけ確立). Phase 4.5 で
  Beta posterior に置き換え予定.
- **`scripts/notify_discord.py` 変更**: `send_batch` → per-item dispatch
  (`_send_per_item_and_mark`) に切替. 成功した item のみ `message_id` を保存し、
  失敗は mark せず次回 cron で再試行可能にする (重複送信防止と再送可能性を両立).

#### Deferred (Phase 4.5 以降)

- **Bayesian Beta posterior**: 反応データが 2〜4 週間貯まってから. 現状は配線のみ.
- **A/B 配信実験**: 配信閾値の動的調整. ROC 比較用ロガーは未実装.
- **動的 GitHub Trending キーワード**: ユーザー興味から AI キーワード集合を更新.

#### Tests

- 455 passed / 2 skipped (Phase 3.5 比 +37)、ruff format + check 緑化.
  内訳: discord_bot 11 / reactions_store 8 / user_interest 5 /
  notification_state_message_id 4 / publisher_discord_message_id 5 /
  notify_discord_message_id 3 (orchestration) / db v6 migration 3.

### Phase 3.5 — BigCodeBench + AlpacaEval fetchers (2026-05-13)

#### Added

- **`fetchers/bigcodebench.py`**: `bigcode/bigcodebench-results` HF dataset から
  `complete` (Complete subset) 降順上位 25 を snapshot 化. `instruct` / `size` /
  `link` / `date` / `type` は payload に同梱.
- **`fetchers/alpaca_eval.py`**: tatsu-lab/alpaca_eval GitHub raw CSV
  (`alpaca_eval_gpt4_leaderboard.csv`) を csv 標準ライブラリで parse.
  primary metric は `length_controlled_winrate`, 空欄は `win_rate` にフォールバック.
- fetchers/__init__.py に 2 fetcher を追加し registry で公開.

#### Deferred (再び Phase 3.5+ へ)

- **Open LLM Leaderboard v2**: `HuggingFaceH4/open_llm_leaderboard_v2` も
  `open-llm-leaderboard/contents-v2` も 401 で取得不可 → 廃止 / 統合された可能性.
- **HELM lite**: 公開 raw データ URL 不明、追加調査要.

#### Verified

- production URL に対する初回 fetch 成功 (advisor 助言遵守):
  - BigCodeBench: 25 entries, top = GPT-4o-2024-05-13 (complete=61.1)
  - AlpacaEval: 25 entries, top = xwinlm-70b-v0.1 (win_rate fallback)

#### Tests

- 418 passed / 2 skipped (Phase 3 比 +10)、ruff format + check 緑化.
  内訳: registry 1 / BigCodeBench parse 4 / AlpacaEval parse 5.

### Phase 3 — Benchmark snapshots + GitHub Trending (2026-05-13)

#### Added

- **DB スキーマ v5**: `benchmark_snapshots` テーブル + index 2 個を追加.
  v4→v5 を `_premigrate_columns_if_needed` / `_migrate` で自動 ALTER.
- **`crawler/benchmarks/` パッケージ** (registry + fetcher 3 個):
  - `BenchmarkEntry` / `BenchmarkSnapshot` の frozen dataclass.
  - `@register(slug)` デコレータで lazy import. scrapers 層と同形.
  - `_util.py`: HF Datasets Server URL 組み立て + JSON/text retry helper
    (501 LockedDatasetTimeoutError を指数バックオフで吸収).
  - `fetchers/lmarena.py`: `lmarena-ai/leaderboard-dataset` の `text_style_control`
    から `category=="overall"` 上位 20 を取得.
  - `fetchers/mteb.py`: `mteb/results/paths.json` からモデル → 評価ファイル数を
    score として、上位 30 を取得 (登録モデル snapshot).
  - `fetchers/github_trending.py`: `github.com/trending` (daily) を BeautifulSoup
    でスクレイプ + AI キーワードフィルタ. 上位 25 を取得.
  - `diff.py`: 直前 snapshot との差分 (new / rank_up / rank_down / dropped) を
    `min_rank_delta=2` で計算. 1 位の揺らぎはノイズとして除外.
  - `store.py`: snapshot 保存・取得・notified フラグ管理.
- **`publisher/benchmark_discord.py`**: snapshot diff を 1 embed で配信する層.
  category=`benchmark` (緑) / `trend` (橙) で色分け. 47条の5境界遵守 (identifier と
  公開数値のみ, body は含めない).
- **`scripts/track_benchmarks.py`**: CLI. 全 fetcher 並列実行 → diff 計算 → 配信 →
  `notified=1` セット. ``--source`` / ``--dry-run`` / ``--min-rank-delta`` 対応.
- **`.github/workflows/benchmarks.yml`**: 22:00 JST cron (UTC 13:00). crawl.yml と
  別時間帯にずらし、同じ release DB を read/write.

#### Changed

- 7-channel Discord webhook 構成 (Phase 1) の ``benchmark`` / ``trend`` channel が
  実装対象に. `AI_RADAR_DISCORD_WEBHOOK_BENCHMARK` / `AI_RADAR_DISCORD_WEBHOOK_TREND`
  を GitHub Actions secrets として登録すれば配信される.

#### Deferred to Phase 3.5

- Open LLM Leaderboard: v1 contents が 2024 年で更新停止、Space は runtime error.
  v2 の存在を確認できず一旦保留.
- HELM / BigCodeBench / AlpacaEval: 追加スコープ.

#### Tests

- 404 passed / 2 skipped (Phase 2 比 +54)、ruff format + check 緑化.
  内訳: registry 4 / diff 8 / fetchers parse 12 / store 8 / discord embed 8 /
  util retry 8 / DB v5 migration 3 / 既存 test_db.py 等 v5 assert 3.

### Phase 2 — Trust-tier scoring + Hype filter + LLM fallback (2026-05-13)

#### Added

- **DB スキーマ v4**: `articles.is_hype INTEGER` + `sources.tier INTEGER` を追加.
  v3→v4 を `_premigrate_columns_if_needed` で自動 ALTER TABLE.
- **`SourceConfig.tier`**: yaml の `tier:` を読み込み (1-5、未指定なら 3、範囲外は ValueError).
  全 20 ソースに tier 明示.
- **`TaggerConfig.anti_tags` / `.hype_keywords`**: tag_rules.yaml から読込.
- **`tagger.engine.is_blocked_by_anti_tag`**: anti_tags (hiring/careers/sponsored/採用 等) ヒット
  記事を配信対象外として扱う.
- **`tagger.engine.detect_hype`**: Tier 4-5 + `hype_keywords` ヒット記事に `is_hype=True`.
- **`crawler/scoring.py` 新設**: `compute_score(tier, category, age_seconds, is_hype)` +
  `should_deliver(...)`. プラン §5 のスコアリング式を実装.
- **配信スコアフィルタ**: `scripts/notify_discord.py` で score >= 0.5 のみ送信.
  閾値未満は通知済みマークして再評価しない.
- **Discord embed ⚠️ マーク**: `build_embed(item, is_hype=True)` で title 先頭に ⚠️.
  `send_batch(items, hype_flags=...)` で並列リストとして渡す.
- **MCP tool `get_untagged_articles`**: タグ未付与記事を返す (Phase 2 LLM fallback の助走).
  API 不使用方針に沿い、Claude Desktop/Code から手動でタグ提案させる窓口.

#### Changed

- `UnnotifiedArticle` に `tier: int = 3` と `is_hype: bool = False` を追加.
- `fetch_unnotified` の SQL に `s.tier` + `a.is_hype` を含める.
- `upsert_source` で `tier` も書く.

#### Tests

- 350 passed / 2 skipped (Phase 1 比 +51)、ruff format + check 緑化.

### Phase 1 — Dedup 5-layer + 7-channel Discord (2026-05-13)

#### Added

- **DB スキーマ v3**: `articles` に `normalized_url` / `thread_id` / `cluster_id` カラム
  + 3 個の INDEX を追加. 既存 v2 DB は ALTER TABLE で自動 upgrade.
- **dedup 5層**: 既存 (source_id, guid) UNIQUE + body_hash の 2 系統に加えて、
  - 層1: `is_known_by_normalized_url` — `normalized_url` 完全一致
  - 層2: `find_similar_title` — 24h 窓 + `SequenceMatcher.ratio() >= 0.85`
  - 層3: `find_cross_source_duplicate` — body_hash 完全一致 (別ソース)
  - 層4: `find_thread_id` — 24h 窓 + title 類似 >= 0.9 で同 thread に統合
  - 層5: `find_cluster_id` — 24h 窓 + title 類似 >= 0.8 で同 cluster に統合
- **URL 正規化拡張**: utm_*, fbclid, mc_*, msclkid, twclid, igshid, _hsenc, spm,
  dclid を除去. arXiv URL の version suffix (`v1`/`v2` 等) と末尾スラッシュを統一.
- **7チャンネル Discord 配信**: `scripts/notify_discord.py` を category 別 dispatch に
  改修. 環境変数 `AI_RADAR_DISCORD_WEBHOOK_<CATEGORY>` で per-category webhook を
  解決し、`DISCORD_WEBHOOK_URL` を fallback として残す (後方互換).
- **publisher**: `resolve_webhook(category, env)` を新規追加.
  `discord_channel_for_category(category)` で category 別 channel 名を採番.
- **テスト**: dedup 5層 + Discord 7ch + DB v3 migration の 36 件追加 (Phase 0.5 比 +36).

#### Changed

- `SourceConfig` は `fetch_kind` に加えて (Phase 0.5 で追加済み) 互換性のみ.
- `is_cross_source_duplicate` (bool 戻り値) は薄いラッパとして残し、内部実装は
  ID を返す `find_cross_source_duplicate` に置き換え.

### Phase 0.5 — HTML scrapers + 9 sources (2026-05-13)

#### Added

- **HTML スクレイパー基盤**: `crawler/scraper.py` (`@register(slug)` で per-source parser を登録) +
  `crawler/scrapers/_util.py` (URL 結合 + 日付正規化)
- **8 per-source parser**: anthropic / hf_papers / cursor / elyza / ai2 / kimi / luma / bfl
- **Sakana AI 追加 (RSS)**: Phase 0 検証で見落としていた `feed.xml` を採用
- **SourceConfig.fetch_kind**: `"rss"` (デフォルト) / `"scraper"` 切替. yaml 不正値で ValueError
- **依存追加**: `beautifulsoup4>=4.12`, `python-dateutil>=2.9`

### Phase 0 — Foundation (2026-05-13〜)

ai-radar を [qa-radar](https://github.com/Y-Kanekoo/qa-radar) からフォークし、
AI/LLM 領域専用のニュースアグリゲーターとして再構築開始.

#### Added

- リポジトリ初期化 (qa-radar 0.1.0 ベースの crawler / publisher / tagger / summarizer / MCP server)
- AI 12 タグ体系 (`llm` / `agent` / `multimodal` / `rag` / `fine-tuning` /
  `benchmark` / `safety` / `regulation` / `paper` / `release` / `tool` / `opinion`)
- 11 ソース (Phase 0、RSS 直取りのみ):
  - **Release (Tier 1)**: Hugging Face Blog, Google Research Blog, Microsoft AI News
  - **Paper**: arXiv cs.LG
  - **Newsletter**: TLDR AI, Ben's Bites, Latent Space
  - **Tool / Code Editor**: Windsurf, Replit
  - **Video / Image gen**: Midjourney (updates.midjourney.com)
  - **JP**: Stockmark
- API 不使用方針: 要約は MCP 経由で Claude Desktop / Code から対話的に実行

#### Changed

- パッケージ名: `qa_radar` → `ai_radar`
- 配布名: `qa-radar` → `ai-radar`
- description / keywords / classifiers を AI/LLM 領域用に変更
- DB 環境変数: `QA_RADAR_DB_PATH` → `AI_RADAR_DB_PATH` (qa-radar からの移行ユーザーは設定変更が必要)

#### Roadmap (Phase 1-6, 8週で完了予定)

- Phase 1: タグ拡張 + スレッド化 + Discord リアクション収集 (28h)
- Phase 2: 重複排除 5層 + 信頼度Tier (5段階) + ハイプフィルタ (24h)
- Phase 3: ベンチマーク追跡 (LMArena / HF Leaderboard / MTEB) + GitHub Trending (30h)
- Phase 4: Bayesian 推薦 + A/B test + リアクション学習自動化 (30h)
- Phase 5: 日本語ソース (Zenn / Qiita / はてブ / note) + Podcast 7本 (23h)
- Phase 6: qa-radar-core 抽出の再検討 (継続課題、45h)

詳細プラン: `~/.claude/plans/ai-radar-launch-plan.md`

[Unreleased]: https://github.com/Y-Kanekoo/ai-radar/compare/HEAD...HEAD
