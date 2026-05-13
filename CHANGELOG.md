# Changelog

All notable changes to ai-radar will be documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
