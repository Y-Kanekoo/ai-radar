"""AlpacaEval leaderboard fetcher (Phase 3.5).

データソース: ``tatsu-lab/alpaca_eval`` GitHub repo の
``src/alpaca_eval/leaderboards/data_AlpacaEval/alpaca_eval_gpt4_leaderboard.csv``
を raw URL で取得. License: Apache-2.0 (リポジトリ全体).

CSV ヘッダ (2026-05 時点):
    (model 名は index 列、ヘッダ無し), win_rate, standard_error, n_wins,
    n_wins_base, n_draws, n_total, mode, avg_length,
    discrete_win_rate, length_controlled_winrate

primary metric は ``length_controlled_winrate`` (LC win rate). 通常 win_rate より
モデル間の比較ノイズを抑えた指標で、AlpacaEval 2.0 から公式. 空セルがある行は
末尾に並ぶ. これを score として上位 N を snapshot 化する.

注: 最終更新が 2024-12 で半年程度停滞しているが、leaderboard 自体は
頻繁にコミットされる. 増分は本 fetcher の cron 実行で検出する.
"""

from __future__ import annotations

import csv
import io
import logging
import time

import httpx

from ai_radar.crawler.benchmarks import BenchmarkEntry, BenchmarkSnapshot, register
from ai_radar.crawler.benchmarks._util import fetch_text_with_retry

logger = logging.getLogger("ai_radar.benchmarks.alpaca_eval")

LEADERBOARD_URL = (
    "https://raw.githubusercontent.com/tatsu-lab/alpaca_eval/main/"
    "src/alpaca_eval/leaderboards/data_AlpacaEval/alpaca_eval_gpt4_leaderboard.csv"
)
TOP_N = 25
SLUG = "alpaca_eval"
DISPLAY_NAME = "AlpacaEval (length-controlled win rate)"


def _parse_csv(text: str) -> list[BenchmarkEntry]:
    """CSV を BenchmarkEntry リストに変換 (length_controlled_winrate 降順上位 N).

    1 列目はヘッダ無しのモデル名 index. ``csv.reader`` で読み、列名を後付けする.
    """
    reader = csv.reader(io.StringIO(text))
    rows_iter = iter(reader)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        return []

    # 期待ヘッダ: 1 列目空, 以降 col 名
    # 互換性のため index で参照 (列順が変わる可能性は低いが、列名でも探す)
    col_map: dict[str, int] = {name.strip(): i for i, name in enumerate(header_row)}

    def _col(row: list[str], name: str) -> str:
        i = col_map.get(name)
        if i is None or i >= len(row):
            return ""
        return row[i].strip()

    candidates: list[tuple[str, float, dict[str, str]]] = []
    for row in rows_iter:
        if not row:
            continue
        model = row[0].strip()
        if not model:
            continue
        lc_raw = _col(row, "length_controlled_winrate")
        # LC が空欄なら旧来の win_rate にフォールバック
        score_raw = lc_raw or _col(row, "win_rate")
        try:
            score = float(score_raw)
        except ValueError:
            continue

        payload: dict[str, str] = {}
        for key in ("win_rate", "n_total", "mode", "avg_length"):
            v = _col(row, key)
            if v:
                payload[key] = v
        candidates.append((model, score, payload))

    # length_controlled_winrate 降順
    candidates.sort(key=lambda t: -t[1])

    entries: list[BenchmarkEntry] = []
    for i, (model, score, payload) in enumerate(candidates[:TOP_N], start=1):
        entries.append(
            BenchmarkEntry(
                rank=i,
                identifier=model,
                score=score,
                payload=payload,
            )
        )
    return entries


@register(SLUG)
async def fetch_alpaca_eval(client: httpx.AsyncClient | None = None) -> BenchmarkSnapshot:
    """AlpacaEval leaderboard を取得して snapshot を返す."""
    text = await fetch_text_with_retry(LEADERBOARD_URL, client=client)
    if not text:
        logger.warning("AlpacaEval CSV 取得失敗 url=%s", LEADERBOARD_URL)
        return BenchmarkSnapshot(
            source_slug=SLUG,
            category="benchmark",
            captured_at=int(time.time()),
            entries=(),
            display_name=DISPLAY_NAME,
        )

    entries = _parse_csv(text)
    return BenchmarkSnapshot(
        source_slug=SLUG,
        category="benchmark",
        captured_at=int(time.time()),
        entries=tuple(entries),
        display_name=DISPLAY_NAME,
    )
