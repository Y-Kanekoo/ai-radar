"""BigCodeBench leaderboard fetcher (Phase 3.5).

データソース: ``bigcode/bigcodebench-results`` (HF dataset, MIT/Apache-2.0).
HF Datasets Server `rows` API で取得し、Complete score 降順上位 N を snapshot とする.

スキーマ (2026-05 時点):
    model (str), link (str), moe (bool), size (float),
    act_param (float), type (str), complete (float, %), instruct (float, %),
    date (str), prefill (bool)

評価種別はコード生成 (Complete) と instruction-following code (Instruct).
score として primary な ``complete`` を使い、``instruct`` は payload に同梱する.
``complete`` が null のモデルは除外する.
"""

from __future__ import annotations

import logging
import time

import httpx

from ai_radar.crawler.benchmarks import BenchmarkEntry, BenchmarkSnapshot, register
from ai_radar.crawler.benchmarks._util import fetch_json_with_retry, hf_rows_url

logger = logging.getLogger("ai_radar.benchmarks.bigcodebench")

DATASET = "bigcode/bigcodebench-results"
CONFIG = "default"
SPLIT = "train"
TOP_N = 25
SLUG = "bigcodebench"
DISPLAY_NAME = "BigCodeBench (Complete)"


def _parse_rows(rows: list[dict]) -> list[BenchmarkEntry]:
    """rows API の戻りを BenchmarkEntry リストに変換 (complete 降順上位 N)."""
    candidates: list[dict] = []
    for r in rows:
        row = r.get("row") or {}
        model = row.get("model")
        complete = row.get("complete")
        if not isinstance(model, str) or not model.strip():
            continue
        # complete が None / NaN なら順位対象から外す
        if not isinstance(complete, int | float):
            continue
        candidates.append(row)

    candidates.sort(key=lambda d: -float(d["complete"]))

    entries: list[BenchmarkEntry] = []
    for i, row in enumerate(candidates[:TOP_N], start=1):
        payload: dict[str, str] = {}
        link = row.get("link")
        if isinstance(link, str):
            payload["link"] = link
        for k in ("type", "date"):
            v = row.get(k)
            if v is not None:
                payload[k] = str(v)
        for k in ("size", "act_param", "instruct"):
            v = row.get(k)
            if isinstance(v, int | float):
                payload[k] = f"{v:g}"

        entries.append(
            BenchmarkEntry(
                rank=i,
                identifier=str(row["model"]).strip(),
                score=float(row["complete"]),
                payload=payload,
            )
        )
    return entries


@register(SLUG)
async def fetch_bigcodebench(client: httpx.AsyncClient | None = None) -> BenchmarkSnapshot:
    """BigCodeBench leaderboard を取得して snapshot を返す."""
    url = hf_rows_url(DATASET, config=CONFIG, split=SPLIT, offset=0, length=100)
    data = await fetch_json_with_retry(url, client=client)
    rows: list[dict] = []
    if isinstance(data, dict):
        rows_obj = data.get("rows")
        if isinstance(rows_obj, list):
            rows = rows_obj
    if not rows:
        logger.warning("BigCodeBench fetch から行が取れませんでした url=%s", url)
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
