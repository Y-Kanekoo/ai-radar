# Changelog

All notable changes to ai-radar will be documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
