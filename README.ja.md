# ai-radar

> AI / LLM ニュースアグリゲーター（公開RSS + ローカルMCP + Discord webhook）

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

**ai-radar** は AI / LLM 領域の公式リリース、論文、ニュースレター、製品アップデートを
26 の設定済みソース（英語 + 日本語）から自動収集し、以下 3 形式で配信します:

1. **公開 RSS フィード** — GitHub Pages でホスト
2. **ローカル MCP サーバー** — Claude Desktop / Claude Code から自然言語で問い合わせ
3. **Discord webhook** — 新着記事を category 別チャンネルにプッシュ通知（Phase 1 で 7ch 化済み）

姉妹プロジェクト [qa-radar](https://github.com/Y-Kanekoo/qa-radar) と同一の
`crawler / publisher / tagger / summarizer` コアを共有していますが、AI/LLM 用に
ソース・タグ・ハイプフィルタ・信頼度Tierを差し替えています。

## 開発状況

🚧 開発中（Phase 0〜4a・5 実装済み・DB スキーマ v6。Phase 6 は第1段階の利用開始済み。Phase 4.5 は未着手。2026-05-13 起動）。

| Phase | スコープ | 状態 |
|-------|---------|------|
| 0. 基盤 | Clone + RSS 11ソース + AI 12タグ + テスト緑化 + Discord 1ch | ✅ |
| 0.5. スクレイパー | +9 ソース (HTML scraper layer) | ✅ |
| 1. 重複排除 5層 + 7ch Discord | URL正規化/Levenshtein/body_hash/引用元/時系列 + category 別 webhook | ✅ |
| 2. 信頼度Tier + ハイプフィルタ + LLM fallback | Source tier scoring, hype detection, MCP tagging | ✅ |
| 3. ベンチマーク + GitHub Trending | LMArena + MTEB + GitHub Trending（スクレイピング）+ DB v5 スナップショット | ✅ |
| 3.5. ベンチマーク拡充 | BigCodeBench + AlpacaEval 追加。Open LLM v2 / HELM は見送り | ✅ |
| 4a. リアクション収集 | Discord message_id 保存 + Bot API でリアクション収集 + DB v6 `reactions` テーブル（スコアへの反映は no-op で 1.0 固定） | ✅ |
| 4.5. パーソナライゼーション | リアクションからの Bayesian（Beta 事後分布）推薦、A/B test、Trending キーワード動的化 | ⏳ |
| 5. 日本語 + Podcast | Zenn / Qiita / はてブ / Cognitive Revolution | ✅ |
| 6. core 抽出 | radar-core v0.1.0 を切り出し、第1段階で正規化・取得/解析データ型の利用開始 | 🚧 |

共有ライブラリ `radar-core` は v0.1.0 タグと lockfile のコミットで固定しています。
正規化処理と取得・解析のデータ型を共有化し、挙動差のある取得・解析本体と Discord 通知は維持します。
import 時の Webhook URL マスクは、意図したセキュリティ強化として適用します。
差分と次の段階の候補は [段階的導入メモ](docs/radar-core.md) を参照してください。

詳細は [README.md](README.md) の Dedup 5-layer / Discord 7-channel webhook セクション参照。

## 集約ソース（26 ソース、Phase 0 + 0.5 + 5）

全26ソースが有効（RSS/Atom 18 + HTML scraper 8）。Phase 5 の追加6本は
2026-10-31 に curl で HTTP 200、RSS/Atomのパース、robots.txt と公開規約を確認。
既存20本の確認日は2026-05-13のままです。`fetch_kind: rss` はAtom・RSS 1.0（RDF）を含みます。

| カテゴリ | ソース |
|---|---|
| **公式リリース（RSS）** | Hugging Face Blog, Google Research Blog, Microsoft AI News, Midjourney Updates, Sakana AI |
| **公式リリース（scraper）** | Anthropic News, Kimi Blog (Moonshot), Luma AI News, Black Forest Labs |
| **論文（RSS）** | arXiv cs.LG |
| **論文（scraper）** | Hugging Face Papers (Daily), Allen AI Blog |
| **ニュースレター（RSS）** | TLDR AI, Ben's Bites, Latent Space |
| **ポッドキャスト（RSS、category: newsletter）** | The Cognitive Revolution |
| **ツール / Code Editor（RSS）** | Windsurf, Replit |
| **ツール / Code Editor（scraper）** | Cursor |
| **日本語（RSS/Atom）** | Stockmark, Zenn LLM, Zenn 生成AI, Qiita LLM, Qiita 生成AI, はてなブックマーク AI |
| **日本語（scraper）** | ELYZA News |

Cognitive Revolution は既存の `newsletter` カテゴリ・Tier 3 とし、同カテゴリの
Discord webhook に配信します。記事リンクのないエピソードは音声enclosureのURLを参照先に
使います。音声の取得・再配信は行いません。Zenn・Qiita はTier 4、はてブはTier 5です。
トピック・タグの重複記事には既存のソース横断重複排除が適用されます。

URL・取得間隔・確認日・利用条件は [config/sources.yaml](config/sources.yaml) を参照。

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

`--dry-run` は設定不要で全カテゴリを確認し、DB のメモリコピーにのみ通常実行と同じ migration を適用し、送信も
元 DB への履歴保存・スキーマ変更もしません。通常実行の score 未満の抑制履歴は維持します。Discord 受領後の
保存失敗や timeout、DB 公開失敗では再送重複があり得ます。台帳の再設計は含みません。
詳細な状態・互換性・限界は [README の通知契約](README.md#discord-7-channel-webhook-phase-1)
を参照してください。実認証設定と実通知の到達はオフライン検証の対象外です。
