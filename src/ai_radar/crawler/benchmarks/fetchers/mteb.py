"""MTEB results dataset fetcher.

データソース: ``mteb/results`` (HuggingFace dataset). ``paths.json`` がモデル名 →
評価結果ファイルパス配列のインデックス. Phase 3 では以下の簡易 snapshot を取る:

- entries: モデル名一覧. identifier = モデル名 (``"Alibaba-NLP__gte-Qwen2-7B-instruct"``).
- score: モデル当たりの評価ファイル件数 (= カバレッジ指標、増えるほど多くのタスクで評価済み).
- rank: モデル名の安定ソート (cumulative file count 降順 → name 昇順) 上位 N.

注: 真の "MTEB ランキング" は個別 JSON を全部集計する必要があり Phase 3 のスコープ
を超える. ここでは「どのモデルが MTEB に登録されたか」の **登録 snapshot** を取る.
これだけでも "新規モデルが MTEB に提出された" イベントとして十分価値がある.
将来 Phase 3.5 で個別 JSON 集計に進化させる予定.
"""

from __future__ import annotations

import logging
import time

import httpx

from ai_radar.crawler.benchmarks import BenchmarkEntry, BenchmarkSnapshot, register
from ai_radar.crawler.benchmarks._util import fetch_json_with_retry, hf_resolve_url

logger = logging.getLogger("ai_radar.benchmarks.mteb")

DATASET = "mteb/results"
PATHS_FILE = "paths.json"
TOP_N = 30  # 上位 N (file count 降順)
SLUG = "mteb_models"
DISPLAY_NAME = "MTEB - registered models"


def _parse_paths(paths: dict) -> list[BenchmarkEntry]:
    """paths.json (model_name → [paths]) を BenchmarkEntry リストに変換."""
    items: list[tuple[str, int]] = []
    for model_name, paths_list in paths.items():
        if not isinstance(model_name, str) or not model_name:
            continue
        count = len(paths_list) if isinstance(paths_list, list) else 0
        items.append((model_name, count))

    # file count 降順, 同点はモデル名昇順 (再現性)
    items.sort(key=lambda x: (-x[1], x[0]))

    entries: list[BenchmarkEntry] = []
    for i, (name, count) in enumerate(items[:TOP_N], start=1):
        entries.append(
            BenchmarkEntry(
                rank=i,
                identifier=name,
                score=float(count),
                payload={"file_count": str(count)},
            )
        )
    return entries


@register(SLUG)
async def fetch_mteb(client: httpx.AsyncClient | None = None) -> BenchmarkSnapshot:
    """MTEB ``paths.json`` を取得して snapshot を返す."""
    url = hf_resolve_url(DATASET, path=PATHS_FILE)
    data = await fetch_json_with_retry(url, client=client)
    if not isinstance(data, dict):
        logger.warning("MTEB paths.json が dict ではありません url=%s", url)
        return BenchmarkSnapshot(
            source_slug=SLUG,
            category="benchmark",
            captured_at=int(time.time()),
            entries=(),
            display_name=DISPLAY_NAME,
        )

    entries = _parse_paths(data)
    return BenchmarkSnapshot(
        source_slug=SLUG,
        category="benchmark",
        captured_at=int(time.time()),
        entries=tuple(entries),
        display_name=DISPLAY_NAME,
    )
