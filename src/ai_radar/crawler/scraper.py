"""HTML スクレイピング層 (Phase 0.5).

RSS / Atom フィードを提供しないソース向け. 設計方針:
- `fetch_html`: httpx で HTML を取得. ETag / If-Modified-Since 対応で `fetch_feed` と
  ふるまいを揃え、`FetchResult` を共有する.
- `parse_html`: source slug でディスパッチ. 各 parser は ``ParsedItem`` のリストを返し、
  feedparser 経路と完全に同じ ``ParsedFeed`` 型に正規化する.
- per-source parser は `ai_radar.crawler.scrapers.{slug}` モジュールで `@register(slug)`
  デコレータで登録する.

これにより orchestrator は `source.fetch_kind` で fetch_* / parse_* を切り替えるだけで
dedup / tag / store の後段処理を一切変更せずに HTML ソースを扱える.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from ai_radar import __version__
from ai_radar.crawler.fetch import FetchResult
from ai_radar.crawler.parse import ParsedFeed, ParsedItem

# HTML 取得用は RSS 用とは別の UA / Accept を使う.
# ブラウザ系 UA は一部サイト (Cloudflare 配下等) で必須.
HTML_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    f"ai-radar/{__version__}"
)
HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
DEFAULT_TIMEOUT = 30.0

# 各 scraper モジュールが import 時に `register(slug)` で登録する
ScraperFn = Callable[[bytes], list[ParsedItem]]
_REGISTRY: dict[str, ScraperFn] = {}


def register(slug: str) -> Callable[[ScraperFn], ScraperFn]:
    """parser を slug で登録するデコレータ.

    重複登録は ``ValueError``. 各 scraper モジュールはトップレベルで使用すること.
    """

    def _decorator(fn: ScraperFn) -> ScraperFn:
        if slug in _REGISTRY:
            raise ValueError(f"scraper {slug!r} は既に登録されています")
        _REGISTRY[slug] = fn
        return fn

    return _decorator


def get_scraper(slug: str) -> ScraperFn | None:
    """登録済み parser を取得. 未登録時は ``None``."""
    _ensure_scrapers_loaded()
    return _REGISTRY.get(slug)


def registered_slugs() -> frozenset[str]:
    """登録済み slug 一覧. テストでカバレッジを検証するのに使う."""
    _ensure_scrapers_loaded()
    return frozenset(_REGISTRY)


_LOADED = False


def _ensure_scrapers_loaded() -> None:
    """scrapers パッケージを遅延 import して全 parser を登録する.

    循環 import を避けるため、scraper.py からは scrapers パッケージを直接 import せず
    最初のアクセス時に1回だけ読み込む.
    """
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    from ai_radar.crawler import scrapers  # noqa: F401  side-effect: parser を登録


async def fetch_html(
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    client: httpx.AsyncClient | None = None,
) -> FetchResult:
    """HTML を取得する. ふるまいは `fetch_feed` と同じ.

    Args:
        url: 対象 URL.
        etag: 前回取得時の ETag (あれば).
        last_modified: 前回取得時の Last-Modified (あれば).
        timeout: HTTP タイムアウト秒.
        client: 共有 httpx.AsyncClient. None なら関数内で生成する.

    Returns:
        FetchResult. ネットワーク例外は `error` フィールドに格納する.
    """
    headers = {"User-Agent": HTML_USER_AGENT, "Accept": HTML_ACCEPT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    own_client = client is None
    used_client = (
        client if client is not None else httpx.AsyncClient(timeout=timeout, follow_redirects=True)
    )
    try:
        try:
            resp = await used_client.get(url, headers=headers)
        except httpx.HTTPError as e:
            return FetchResult(
                url=url,
                status_code=0,
                content=None,
                etag=None,
                last_modified=None,
                error=str(e),
            )

        if resp.status_code == 304:
            return FetchResult(
                url=url,
                status_code=304,
                content=None,
                etag=etag,
                last_modified=last_modified,
            )

        if resp.status_code != 200:
            return FetchResult(
                url=url,
                status_code=resp.status_code,
                content=None,
                etag=None,
                last_modified=None,
                error=f"unexpected status: {resp.status_code}",
            )

        return FetchResult(
            url=url,
            status_code=200,
            content=resp.content,
            etag=resp.headers.get("etag"),
            last_modified=resp.headers.get("last-modified"),
        )
    finally:
        if own_client:
            await used_client.aclose()


def parse_html(content: bytes, source_slug: str) -> ParsedFeed:
    """source_slug に紐づく parser で HTML をパースする.

    feedparser 経路の `parse_feed` と同じ `ParsedFeed` を返す. 未登録 slug や parser
    例外は `bozo=True` + `bozo_exception` で示し、items は空リストになる.

    Args:
        content: HTML バイト列.
        source_slug: ソースの slug. 未登録なら bozo.

    Returns:
        ParsedFeed.
    """
    parser = get_scraper(source_slug)
    if parser is None:
        return ParsedFeed(
            items=[],
            bozo=True,
            bozo_exception=f"no scraper registered for {source_slug!r}",
        )
    try:
        items = parser(content)
    except Exception as e:
        return ParsedFeed(items=[], bozo=True, bozo_exception=str(e))
    return ParsedFeed(items=items, bozo=False, bozo_exception=None)
