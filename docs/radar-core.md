# radar-core の段階的導入

依存は `radar-core @ git+https://github.com/Y-Kanekoo/radar-core@v0.1.0` に固定する。
`uv.lock` はタグの参照先コミット
`d4301e178c1fd17e1c4688e9442f4ddd0c2ebe02` も固定する。
Hatchling の `allow-direct-references = true` は、この git 依存を含む
編集可能インストール・配布物のビルドに必要。

## 第1段階の実装範囲

| 対象 | 委譲する範囲 | 互換性の維持方法 |
|---|---|---|
| `crawler/normalize.py` | URL・日時・HTML除去・本文ハッシュ、`max_chars > 0` の抜粋 | 既存の公開関数を薄いラッパーとして維持。`TRACKING_PARAMS` は再エクスポート |
| `crawler/fetch.py` | `FetchResult` | 既存モジュールから同じフィールド・既定値・プロパティを持つ型を再エクスポート。HTTP取得は従来処理を維持 |
| `crawler/parse.py` | `ParsedItem` / `ParsedFeed` | 既存モジュールから同じフィールドを持つ型を再エクスポート。feedparser 呼び出し・抽出は従来処理を維持 |
| `publisher/discord.py` | 今回は委譲なし | 通知内容・HTTP要求・再試行・ログ文言を維持するため従来処理を使用 |

既存の import パスと公開関数のシグネチャは維持する。
データクラスの定義元は `radar_core` になるが、旧モジュール名の pickle 参照も解決できる。
`make_snippet(max_chars <= 0)` は radar-core で拒否されるため、従来のスライス処理を残す。

**意図した差分（セキュリティ強化）:** radar-core の import 時に登録されるフィルターで、
httpx/httpcore ログ中の Discord Webhook URL をマスクする。互換アダプターからフィルターは外さない。

`tests/unit/test_radar_core_compat.py` で正規化の境界値・例外・シグネチャ、
再エクスポートした型、HTTP要求回数・ヘッダ・タイムアウト、解析入力・抽出値、
Discord の文字数・空値・ペイロード・waitクエリ・ID・429待機・ログとマスクを検証する。
既存テストは変更・削除・skip化しない。追加テストは MockTransport とフィクスチャのみで完結する。

## 次の段階の候補

公開関数・モジュールパス・CLI・出力・ログ文言・DB形式・通知内容を維持するため、
次の差分がある処理はそのまま置き換えられない。

| 対象 | ai-radar の現行動作 | radar-core v0.1.0 の差分と見送り理由 |
|---|---|---|
| `make_snippet` | `max_chars <= 0` もスライス処理する | `ValueError` を送出するため、その入力範囲のみ従来処理を残す |
| `fetch_feed` | 既存クライアントのタイムアウト設定を使用。HTTPError は元の例外文字列を返し、InvalidURL は捕捉しない | 毎回 `timeout` を指定し、エラー文字列を変更、InvalidURL も結果に変換する。通信設定・例外・保存されるエラーが変わる |
| `RobotsCache` | robots.txt の取得・判定に ai-radar の User-Agent を使う | radar-core の User-Agent 固定。サイトごとの許可判定や取得内容が変わり得る |
| `parse_feed` | 文字列を feedparser に直接渡す。抽出値は型を変換せず採用する | 文字列を UTF-8 バイト列に変換し、文字列以外の抽出値を除外、日時要素を整数化する。文字列のエンコーディング・パス入力・例外の互換性を要確認 |
| Discord embed | Python の文字数で title/footer を切り、省略記号は description のみ。空フィールドも保持 | UTF-16 単位で省略記号込みの切り詰め・空フィールド除去・合計6000単位の制限を適用。絵文字や長文・空値を含む通知内容が変わる |
| Discord payload・送信 | 既存 payload と送信先クエリを維持。2xx は ID がなくても成功、整数 ID も文字列化 | `allowed_mentions` の追加、分割、wait クエリ上書き、ID 確認の条件が異なる |
| Discord 429 再試行 | ヘッダ優先、最低0.5秒、既定1回再試行 | JSON 優先、最低0秒、既定2回再試行。送信タイミング・既存ログも異なる |

DB・スコアリング・ハイプ判定・カテゴリ別 webhook 解決・通知履歴は引き続き
ai-radar が担当する。

### 既存ドキュメントと実装の食い違い

- `normalize.py` の「必ず100字以下」という説明に対し、実装・既存テストは
  本文100字に `…` を追加した最大101字を許容する。今回この動作は変更しない。
- 切り出し前の追跡パラメータのコメント（上流にも残存）は19個とするが、
  実際の集合は20個。再エクスポート後も集合の内容を維持する。

## インストールと workflow

GitHub Actions は引き続き `uv sync --locked --all-extras --dev` を使用する。
レジストリ配布物のハッシュ検証と git 依存のコミット固定は両立し、
`--require-hashes` は指定していない。公開 GitHub リポジトリの取得に追加の
シークレットは不要。workflow の変更は不要。

ローカルでは workflow と同じ uv 0.12.19 と Python 3.11 / 3.12 を使い、
通常の同期と、保存済みキャッシュから別の仮想環境への
`uv sync --locked --offline --all-extras --dev` を確認する。
GitHub Actions 自体は無料枠切れのため実行しない。

### ローカル検証結果（2026-11-01）

uv 0.12.19、Python 3.11.15 / 3.12.13 で最終実装を検証した。
キャッシュ・仮想環境・一時ファイルは worktree 内の `.uv-cache` / `.venv` に配置した。
`PATH` の先頭に `.uv-cache/ci-uv/bin` を追加し、`UV_CACHE_DIR` / `TMPDIR` も
worktree 内に設定した。`.python-version` は3.11固定なので、3.12検証時は
`UV_PYTHON=3.12` と別の `UV_PROJECT_ENVIRONMENT` を指定した。
カバレッジは版ごとに順次計測し、3.12では別の `COVERAGE_FILE` を使用した。

| コマンド | 結果 |
|---|---|
| `uv lock --check` | 成功 |
| `uv sync --locked --all-extras --dev` | 両 Python 版で成功。空の専用キャッシュから GitHub の固定コミット取得・ビルドも成功 |
| `uv sync --locked --offline --all-extras --dev` | 両 Python 版で、キャッシュを使った別の新規環境へのインストール成功。import・ラッパー動作も確認 |
| `uv run ruff check .` | 成功 |
| `uv run ruff format --check .` | 109ファイルで成功 |
| `uv run ruff format --check src/ai_radar/crawler/normalize.py src/ai_radar/crawler/fetch.py src/ai_radar/crawler/parse.py tests/unit/test_radar_core_compat.py` | 変更・追加4ファイルで成功 |
| `uv run --locked --with mypy --with types-PyYAML --with types-python-dateutil mypy --follow-imports=silent --ignore-missing-imports src/ai_radar/crawler/normalize.py src/ai_radar/crawler/fetch.py src/ai_radar/crawler/parse.py src/ai_radar/publisher/discord.py tests/unit/test_radar_core_compat.py` | 対象4モジュールと追加テストでエラーなし |
| `uv run pytest` | 580件成功。従来の外部通信の統合テスト2件は既存設定どおり実行対象外 |
| `uv run pytest --cov=ai_radar` | 580件成功、同2件は実行対象外、カバレッジ87% |
| `uv run --locked pytest -v --cov=ai_radar --cov-report=term-missing` | Python 3.12で workflow 同等の580件成功、同2件は実行対象外、カバレッジ87% |
| `uv run coverage report --fail-under=80` | 両 Python 版で成功（87%） |
| `uv run --locked pytest tests/test_dependency_lock.py tests/test_uv_installer.py tests/test_uv_tool_cache.py` | 既存の依存・インストール関連23件すべて成功 |
| `uv build` | sdist / wheel のビルド成功。キャッシュ混入なし、タグ固定依存のメタデータも確認 |

追加の互換性テストは31件。既存テスト・workflow は変更していない。
GitHub Actions の Linux runner 自体は実行しておらず、ローカルmacOS上で
両 Python 版の同等コマンドと installer の既存フィクスチャを検証した。

整形の既存事象は変更対象外とし、除外設定も追加しない。
今回の開始時点では、workflow と同じ固定版環境で `ruff format --check .` が
108ファイルすべて成功し、既存の整形違反は再現しなかった。

### PyPI 公開の制限

依存インストールと配布物ビルドは通るが、PyPI は直接 URL 参照の依存を持つ
パッケージを受け付けない（[公式ドキュメント](https://setuptools.pypa.io/en/stable/userguide/dependency_management.html#direct-url-dependencies)）。
指定のタグ固定形式を維持しているため、`pypi.yml` の公開ジョブを実行する前に
配布方針の判断が必要。アップロード・workflow の無効化は行わない。
