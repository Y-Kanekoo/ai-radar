# ai-radar ソース一覧と利用規約状況

> 最終更新: 2026-05-09 / 全URLは WebFetch で200応答を実物確認済み

## TDR-001: 発見元・掲載先・査読状態・人気を分離する

- 日付: 2026-10-02
- 状態: 提案（実装・オフライン検証済み、マージ前レビュー待ち）
- 対象: `config/sources.yaml` と `SourceConfig` の出所情報

### 背景と決定

従来の Tier 2 の説明「査読」は arXiv と Kimi の登録実態と一致せず、
HF Papers の「コミュニティ投票で品質保証」も人気と品質を混同していた。
`tier` は既存の配信優先度として数値・スコア式を維持し、査読ラベルに使わない。
arXiv の掲載だけでは各論文の査読有無を判断できず、HF の投票も査読の証拠ではない。

任意の `provenance` mapping を追加する（旧 YAML と既存呼び出しは互換）。

| フィールド | 意味・既定値 |
|---|---|
| `source_type` | 発見元の種別。`unknown`（既定）/ `blog` / `preprint_repository` / `research_aggregator` / `journal` / `proceedings` / `newsletter` |
| `publication_venue` | 確認済み掲載先。不明は `null`。発見用サイト名では代用しない |
| `review_status` | `unknown`（既定）/ `not_peer_reviewed` / `peer_reviewed` |
| `review_evidence_url` | 根拠の HTTP(S) URL。不明は `null` |
| `popularity_signal` | `none`（既定）/ `community_upvotes`。品質証拠ではない |

`peer_reviewed` は掲載先と明示的な根拠URLがなければ拒否する。掲載先名・
記事タイトル・source type・Tier・投票数だけで昇格させない。
URL検証は形式のみで、内容の真偽や適用範囲の確認は設定者が行う。
不明値・不正な型・未知のキーは拒否し、誤記を黙って無視しない。

現在の arXiv は `preprint_repository`、HF Papers は `research_aggregator` とし、
双方の掲載先は `null`、査読状態は `unknown`。HF の人気指標だけを
`community_upvotes` と明示する。他のソースは未確認を表す既定値とする。

### 境界と互換性

これは**発見元について確認した情報**であり、個々の記事の査読判定ではない。
たとえば査読方針のある会議にも序文があり得る。ソースの査読状態や掲載先を
記事に暗黙継承しない。SQLite、MCP、RSS、Pages の記事スキーマを変更せず、
記事単位の査読済みバッジは生成しない。記事ごとの証拠保存・照合は将来の別設計とする。

ソースの追加/削除、有効状態、URL、カテゴリ、取得頻度、Tier とスコア式、
通知先、依存関係、権限は変更しない。HF parser の `body` 内の投票メタデータも
互換維持し、スコアには加えない。`version: 1` は任意フィールドの後方互換拡張で維持。

### 機能別の検証

- Unit: preprint / 確認済み掲載先 / 根拠不足 / 型・空値・誤記 / 人気と査読の分離 / 旧設定互換 / 既存重み
- Offline integration: 合成HTML（0・1・999999票）→ parser → 一時DB、合成会議feedの序文に査読情報を継承しない
- CLI: `scripts/run_crawl.py` の設定ロードと不正設定拒否。合成disabledソースのみ、socket接続禁止、一時DBのみ

```bash
uv run pytest tests/unit/test_source_provenance.py
uv run pytest tests/offline_integration/test_source_provenance_offline.py
uv run pytest tests/cli/test_source_provenance_cli.py
```

実サイト通信・通知送信・有料API・記事品質の検証を行うテストではない。
`tests/integration/` は既存の opt-in 実通信用なので、常時実行する合成テストとは分離した。

この文書の下部に残る旧QAソース一覧と英日README全体の同期は別作業。
[既存 Issue #6](https://github.com/Y-Kanekoo/ai-radar/issues/6) のドキュメント同期範囲として追跡し、
今回の出所ラベル修正で現行ソース全体を再分類したとは扱わない。

## 法的フレームワーク

本プロジェクトは日本国著作権法 **第47条の5（情報所在検索サービスの軽微利用）**
および **第32条（引用）** の範囲内で運用します。

**軽微利用の境界**:
- タイトル（事実情報、引用要件不要）
- スニペット（≤100字、本文の5〜10%以内）
- 元記事URL（必須、誘導目的）
- 出所明示（配信元名・著者名）
- 自動生成タグ（自社著作物）

## ソース一覧

### Tool releases（9）

| Slug | ソース | 言語 | 規約 |
|---|---|---|---|
| `playwright-releases` | [Playwright](https://github.com/microsoft/playwright/releases.atom) | en | GitHub ToS、再配信OK |
| `cypress-releases` | [Cypress](https://github.com/cypress-io/cypress/releases.atom) | en | GitHub ToS、再配信OK |
| `selenium-releases` | [Selenium](https://github.com/SeleniumHQ/selenium/releases.atom) | en | GitHub ToS、再配信OK |
| `jest-releases` | [Jest](https://github.com/jestjs/jest/releases.atom) | en | GitHub ToS、再配信OK |
| `vitest-releases` | [Vitest](https://github.com/vitest-dev/vitest/releases.atom) | en | GitHub ToS、再配信OK |
| `pytest-releases` | [pytest](https://github.com/pytest-dev/pytest/releases.atom) | en | GitHub ToS、再配信OK |
| `appium-releases` | [Appium](https://github.com/appium/appium/releases.atom) | en | GitHub ToS、再配信OK |
| `k6-releases` | [k6 (Grafana)](https://github.com/grafana/k6/releases.atom) | en | GitHub ToS、再配信OK |
| `allure-releases` | [Allure 2](https://github.com/allure-framework/allure2/releases.atom) | en | GitHub ToS、再配信OK |

### Vendor blogs（4）

| Slug | ソース | 言語 | 規約 |
|---|---|---|---|
| `google-testing-blog` | [Google Testing Blog](http://feeds.feedburner.com/blogspot/RLXA) | en | Blogger標準、引用可 |
| `mabl-blog` | [mabl Blog](https://www.mabl.com/blog/rss.xml) | en | 公開RSS、引用+リンクバック |
| `applitools-blog` | [Applitools Blog](https://applitools.com/blog/feed/) | en | 公開RSS、引用+リンクバック |
| `browserstack-blog` | [BrowserStack Blog](https://www.browserstack.com/blog/feed/) | en | 公開RSS、引用+リンクバック |

### Community feeds（3）

| Slug | ソース | 言語 | 規約 |
|---|---|---|---|
| `mot-club` | [Ministry of Testing Club](https://club.ministryoftesting.com/latest.rss) | en | Discourse latest.rss、フォーラム標準で公衆配信 |
| `devto-qa` | [DEV.to /tag/qa](https://dev.to/feed/tag/qa) | en | 公開RSS、再投稿NGだがリンクバック運用OK |
| `medium-test-automation` | [Medium /tag/test-automation](https://medium.com/feed/tag/test-automation) | en | 公開RSS、本文転載NG・抜粋+リンクバックで運用 |

### Japanese tech-company blogs（5）

| Slug | ソース | 言語 | 規約 |
|---|---|---|---|
| `cybozu-tech` | [Cybozu Inside Out](https://blog.cybozu.io/feed) | ja | はてなブログ、引用+リンクバックで運用 |
| `m3-tech` | [m3 Tech Blog](https://www.m3tech.blog/feed) | ja | はてなブログ、QAカテゴリ年20-25本 |
| `sansan-builders-box` | [Sansan Builders Box](https://buildersbox.corp-sansan.com/feed) | ja | はてなブログ、QAカテゴリ年12本 |
| `kakehashi-tech` | [KAKEHASHI Tech Blog](https://kakehashi-dev.hatenablog.com/feed) | ja | はてなブログ、QAカテゴリ19本 |
| `base-product` | [BASE Product Team Blog](https://devblog.thebase.in/feed) | ja | はてなブログ、性能QA連載 |

### Japanese individual blogs（3）

| Slug | ソース | 言語 | 規約 |
|---|---|---|---|
| `nihonbuson` | [ブロッコリーのブログ](https://nihonbuson.hatenadiary.jp/feed) | ja | 個人、引用+出所+リンクバック |
| `kawaguti` | [kawaguti's diary](https://kawaguti.hateblo.jp/feed) | ja | 個人、引用+出所+リンクバック |
| `goyoki` | [千里霧中 (goyoki)](https://goyoki.hatenablog.com/feed) | ja | 個人、QA記事密度高 |

### note.com 個人（4）

| Slug | ソース | 言語 | 規約 |
|---|---|---|---|
| `akiyama924-note` | [秋山浩一 note](https://note.com/akiyama924/rss) | ja | note公開RSS、抜粋+リンクバック必須 |
| `tarappo-note` | [tarappo note](https://note.com/tarappo/rss) | ja | note公開RSS、抜粋+リンクバック必須 |
| `yumotsuyo-note` | [湯本剛 note](https://note.com/yumotsuyo/rss) | ja | note公開RSS、抜粋+リンクバック必須 |
| `qa-tpen-note` | [QAを楽しむ者 note](https://note.com/qa_tpen/rss) | ja | note公開RSS、抜粋+リンクバック必須 |

### Zenn Publication（1）

| Slug | ソース | 言語 | 規約 |
|---|---|---|---|
| `mybest-zenn` | [マイベスト (Zenn)](https://zenn.dev/p/mybest_dev/feed) | ja | Zenn公開、本文転載NG・抜粋+リンクバックで運用 |

### Academic papers（1）

| Slug | ソース | 言語 | 規約 |
|---|---|---|---|
| `arxiv-cs-se` | [arxiv cs.SE](https://rss.arxiv.org/rss/cs.SE) | en | arxiv公式RSS、メタデータはCC0で再配信OK |

## 明示的にブロックしているソース

| ドメイン | 理由 |
|---|---|
| `jiji.com` | RSS規約で「プログラムによる再配信を禁止」明示 |

詳細は [`config/blocked.yaml`](../config/blocked.yaml) を参照。

## 削除依頼への対応

著者・配信元から削除依頼を受けた場合、7日以内に以下の対応を行います:

1. `config/sources.yaml` の `enabled: false` 化（即時）
2. DB から該当ソースの全記事を削除
3. 公開済み RSS / Pages から該当エントリを除外
4. `config/blocked.yaml` の `blocked_domains` に追加（再発防止）

依頼窓口: <https://github.com/Y-Kanekoo/ai-radar/issues> (`takedown` ラベル)
