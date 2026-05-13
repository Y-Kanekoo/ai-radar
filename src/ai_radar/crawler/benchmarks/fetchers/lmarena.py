"""LMArena (Chatbot Arena) leaderboard fetcher.

データソース: ``lmarena-ai/leaderboard-dataset`` (HuggingFace dataset, CC-BY-4.0).
config: ``text_style_control`` の ``latest`` split を取得し、``category=="overall"``
の rating 降順上位 N を snapshot とする.

スキーマ (2025-11 時点):
    model_name (str), organization (str), license (str), rating (float),
    rating_lower (float), rating_upper (float), variance (float),
    vote_count (int), rank (int), category (str), leaderboard_publish_date (str)

API 仕様上 length 上限は 100. 内部で先頭 100 行 → category フィルタ → 上位 N.
auto-conversion 中の 501 LockedDatasetTimeoutError は `fetch_json_with_retry`
が吸収する.
"""

from __future__ import annotations

import logging
import time

import httpx

from ai_radar.crawler.benchmarks import BenchmarkEntry, BenchmarkSnapshot, register
from ai_radar.crawler.benchmarks._util import fetch_json_with_retry, hf_rows_url

logger = logging.getLogger("ai_radar.benchmarks.lmarena")

DATASET = "lmarena-ai/leaderboard-dataset"
CONFIG = "text_style_control"
SPLIT = "latest"
TARGET_CATEGORY = "overall"
TOP_N = 20
SLUG = "lmarena_text"
DISPLAY_NAME = "LMArena - Text (style-controlled, overall)"


def _parse_rows(rows: list[dict]) -> list[BenchmarkEntry]:
    """HF rows API の戻り値から ``BenchmarkEntry`` リストを作る.

    rows 形式: ``[{"row_idx": 0, "row": {"model_name": ..., ...}, ...}, ...]``
    ``category=="overall"`` のみ採用. rank 昇順で TOP_N 件返す.
    """
    overall: list[dict] = []
    for r in rows:
        row = r.get("row") or {}
        if row.get("category") != TARGET_CATEGORY:
            continue
        overall.append(row)

    # rank が無い場合があるので rating 降順でも安定にソート
    def _sort_key(d: dict) -> tuple[int, float]:
        rank = d.get("rank")
        rating = d.get("rating")
        return (
            rank if isinstance(rank, int) and rank > 0 else 10**6,
            -float(rating) if isinstance(rating, int | float) else 0.0,
        )

    overall.sort(key=_sort_key)
    entries: list[BenchmarkEntry] = []
    for i, row in enumerate(overall[:TOP_N], start=1):
        rank_raw = row.get("rank")
        rank = rank_raw if isinstance(rank_raw, int) and rank_raw > 0 else i
        rating = row.get("rating")
        score = float(rating) if isinstance(rating, int | float) else None

        identifier = str(row.get("model_name") or "").strip()
        if not identifier:
            continue  # skip 異常行

        payload: dict[str, str] = {}
        for k in ("organization", "license", "leaderboard_publish_date"):
            v = row.get(k)
            if v is not None:
                payload[k] = str(v)
        vote_count = row.get("vote_count")
        if isinstance(vote_count, int):
            payload["vote_count"] = str(vote_count)

        entries.append(
            BenchmarkEntry(rank=rank, identifier=identifier, score=score, payload=payload)
        )
    return entries


@register(SLUG)
async def fetch_lmarena(client: httpx.AsyncClient | None = None) -> BenchmarkSnapshot:
    """LMArena leaderboard を取得して snapshot を返す.

    取得失敗時は ``entries=()`` の空 snapshot を返す (呼び出し側で skip 判定).
    """
    url = hf_rows_url(DATASET, config=CONFIG, split=SPLIT, offset=0, length=100)
    data = await fetch_json_with_retry(url, client=client)
    rows: list[dict] = []
    if isinstance(data, dict):
        rows_obj = data.get("rows")
        if isinstance(rows_obj, list):
            rows = rows_obj
    if not rows:
        logger.warning("LMArena fetch から行が取れませんでした url=%s", url)
        return BenchmarkSnapshot(
            source_slug=SLUG,
            category="benchmark",
            captured_at=int(time.time()),
            entries=(),
            display_name=DISPLAY_NAME,
        )

    entries = _parse_rows(rows)
    return BenchmarkSnapshot(
        source_slug=SLUG,
        category="benchmark",
        captured_at=int(time.time()),
        entries=tuple(entries),
        display_name=DISPLAY_NAME,
    )
