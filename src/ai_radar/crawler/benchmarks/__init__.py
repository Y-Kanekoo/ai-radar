"""Phase 3: ベンチマーク / Trending snapshot 取得層.

設計方針:
- 各ソース (LMArena / MTEB / GitHub Trending) は `@register(slug)` で登録された
  async fetcher を持ち、1 回呼ぶごとに ``BenchmarkSnapshot`` を返す.
- snapshot は (source_slug, captured_at, entries) の三組. DB v5 の
  ``benchmark_snapshots`` テーブルに JSON で保存される.
- 直前 snapshot との差分 (new / rank_up / rank_down / dropped) を
  ``diff.compute_diff`` で計算し、Discord に配信する.
- ベンチマーク (`category=benchmark`) と Trending (`category=trend`) は既存
  7ch Discord の per-category webhook (Phase 1 で確保済み) に流す.

レジストリパターンは HTML scrapers (`crawler/scraper.py`) と同型で、
各 fetcher モジュールはトップレベル import 時に ``register(slug)`` を呼ぶ.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

FETCH_TIMEOUT = 30.0


@dataclass(frozen=True)
class BenchmarkEntry:
    """1 snapshot 内の 1 行 (モデル or リポジトリ).

    Attributes:
        rank: 1-indexed 順位.
        identifier: 安定キー. LMArena/MTEB ではモデル名、GitHub Trending では
            ``"owner/repo"``. 差分計算でこの値を一致判定に使う.
        score: 数値スコア (ELO rating / average / stars 等). None 可.
        payload: その他のメタ情報 (organization, license, url, description, language).
    """

    rank: int
    identifier: str
    score: float | None
    payload: dict[str, str]


@dataclass(frozen=True)
class BenchmarkSnapshot:
    """1 fetch の結果. DB に 1 行として保存される.

    Attributes:
        source_slug: 一意 slug. 例: ``"lmarena_text"``, ``"mteb_overall"``,
            ``"github_trending_daily"``.
        category: Discord 配信先 channel を決める. ``"benchmark"`` か ``"trend"``.
        captured_at: 取得時刻 (unix秒).
        entries: 上位 N 件. rank 昇順.
        display_name: Discord embed の title に使う表示名 (例: "LMArena - Text").
    """

    source_slug: str
    category: str
    captured_at: int
    entries: tuple[BenchmarkEntry, ...]
    display_name: str


FetcherFn = Callable[[httpx.AsyncClient | None], Awaitable[BenchmarkSnapshot]]
_REGISTRY: dict[str, FetcherFn] = {}


def register(slug: str) -> Callable[[FetcherFn], FetcherFn]:
    """fetcher を slug で登録するデコレータ. 重複登録は ``ValueError``."""

    def _decorator(fn: FetcherFn) -> FetcherFn:
        if slug in _REGISTRY:
            raise ValueError(f"benchmark fetcher {slug!r} は既に登録されています")
        _REGISTRY[slug] = fn
        return fn

    return _decorator


_LOADED = False


def _ensure_fetchers_loaded() -> None:
    """fetchers パッケージを遅延 import. 循環 import 回避のため."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    from ai_radar.crawler.benchmarks import fetchers  # noqa: F401  side-effect: 登録


def get_fetcher(slug: str) -> FetcherFn | None:
    """登録済み fetcher を取得. 未登録なら None."""
    _ensure_fetchers_loaded()
    return _REGISTRY.get(slug)


def registered_slugs() -> frozenset[str]:
    """登録済み slug 一覧."""
    _ensure_fetchers_loaded()
    return frozenset(_REGISTRY)


__all__ = [
    "FETCH_TIMEOUT",
    "BenchmarkEntry",
    "BenchmarkSnapshot",
    "FetcherFn",
    "get_fetcher",
    "register",
    "registered_slugs",
]
