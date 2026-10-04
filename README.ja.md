# ai-radar

> AI / LLM ニュースアグリゲーター（公開RSS + ローカルMCP + Discord webhook）

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

**ai-radar** は AI / LLM 領域の公式リリース、論文、ニュースレター、製品アップデートを
11 以上の検証済みソース（英語 + 日本語）から自動収集し、以下 3 形式で配信します:

1. **公開 RSS フィード** — GitHub Pages でホスト
2. **ローカル MCP サーバー** — Claude Desktop / Claude Code から自然言語で問い合わせ
3. **Discord webhook** — 新着記事を category 別チャンネルにプッシュ通知（Phase 2 で 7ch 化予定）

姉妹プロジェクト [qa-radar](https://github.com/Y-Kanekoo/qa-radar) と同一の
`crawler / publisher / tagger / summarizer` コアを共有していますが、AI/LLM 用に
ソース・タグ・ハイプフィルタ・信頼度Tierを差し替えています。

## 開発状況

🚧 Phase 1 進行中（2026-05-13 起動、20 ソース + dedup 5層 + 7ch Discord 完了）。

| Phase | スコープ | 状態 |
|-------|---------|------|
| 0. 基盤 | Clone + RSS 11ソース + AI 12タグ + テスト緑化 + Discord 1ch | ✅ |
| 0.5. スクレイパー | +9 ソース (HTML scraper layer) | ✅ |
| 1. 重複排除 5層 + 7ch Discord | URL正規化/Levenshtein/body_hash/引用元/時系列 + category 別 webhook | ✅ |
| 2. 信頼度Tier + ハイプフィルタ + LLM fallback | Source tier scoring, hype detection, MCP tagging | ✅ |
| 3. ベンチマーク + GitHub Trending | LMArena / HF Leaderboard / MTEB / huchenme | ⏳ |
| 4. パーソナライゼーション | Bayesian推薦、A/B test、リアクション学習 | ⏳ |
| 5. 日本語 + Podcast | Zenn / Qiita / はてブ / Cognitive Revolution 等 | ⏳ |
| 6. core 抽出 | qa-radar-core 抽出の再検討 | ⏳ |

詳細は [README.md](README.md) の Dedup 5-layer / Discord 7-channel webhook セクション参照。

## 集約ソース（Phase 0、RSS 優先）

11 ソース（カテゴリ別）。Phase 0 は RSS 直取りのみ。スクレイピング対象
（Anthropic / HF Papers / Cursor / Sakana 等）は scraper レイヤー実装後の
Phase 0.5 で追加します。

| カテゴリ | ソース |
|---|---|
| **公式リリース (Tier 1)** | Hugging Face Blog, Google Research Blog, Microsoft AI News |
| **論文** | arXiv cs.LG |
| **ニュースレター** | TLDR AI, Ben's Bites, Latent Space |
| **ツール / Code Editor** | Windsurf, Replit |
| **動画 / 画像生成** | Midjourney (updates.midjourney.com) |
| **日本語** | Stockmark |

詳細は [config/sources.yaml](config/sources.yaml) を参照。

## AI 12タグ

`llm` / `agent` / `multimodal` / `rag` / `fine-tuning` / `benchmark` / `safety` /
`regulation` / `paper` / `release` / `tool` / `opinion`

[config/tag_rules.yaml](config/tag_rules.yaml) で定義。共起ルール、
ハイプキーワードフィルタ（Phase 2）、ソース固定タグに対応。

## サブスク内完結方針

このプロジェクトは **LLM API を呼び出しません**。要約は MCP 経由で
Claude Desktop / Claude Code から対話的に実行します（Claude Pro/Max サブスク内）。

オプションの `[ai]` extra（anthropic SDK 同梱）は qa-radar 互換性のため残して
ありますが、デフォルトで無効化されています。

## 開発環境

Python 3.11+ と [uv](https://docs.astral.sh/uv/) が必要です。

```bash
git clone https://github.com/Y-Kanekoo/ai-radar.git
cd ai-radar
uv sync --dev
uv run pytest -v
uv run ruff check .

# MCP サーバーをローカルで起動
uv run python -m ai_radar
```

## ライセンス

MIT — [LICENSE](LICENSE) 参照。データ取扱いガイドラインは [NOTICE](NOTICE) を参照。

## 通知結果と運用

カテゴリ別 Webhook → 共通 fallback → 未設定 skip の順序は維持します。未設定は
exit 0 の運用保留で、正常な空結果や送信成功とは区別してログ・Actions summary に
記録します。設定済みの送信・保存失敗は exit 2 です。通知に失敗しても成功分の履歴を
含む DB 公開・Pages は継続し、別 job が workflow 全体に失敗を残します。
main マージでは通知せず、次の既存定期実行から適用されます。

`--dry-run` は設定不要で全カテゴリを確認し、DB のメモリコピーを使用して送信も
履歴保存もしません。通常実行の score 未満の抑制履歴は維持します。Discord 受領後の
保存失敗や timeout、DB 公開失敗では再送重複があり得ます。台帳の再設計は含みません。
詳細な状態・互換性・限界は [README の通知契約](README.md#discord-7-channel-webhook-phase-1)
を参照してください。実認証設定と実通知の到達はオフライン検証の対象外です。
