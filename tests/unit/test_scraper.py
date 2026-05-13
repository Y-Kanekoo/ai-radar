"""crawler/scraper.py と crawler/scrapers/* のユニットテスト (Phase 0.5).

各 per-source parser は実 HTML の縮小版 fixture で 1 件以上抽出できることを確認する.
DOM 構造の妥当性は WebFetch + curl での実物検証 (2026-05-13) で取られているため、
ここでは「parser が登録されている」「fixture HTML で要素抽出が破綻しない」までを担保.
"""

from __future__ import annotations

import httpx
import pytest

from ai_radar.crawler.scraper import (
    fetch_html,
    get_scraper,
    parse_html,
    register,
    registered_slugs,
)

# ---------------- レジストリ ----------------


def test_all_phase05_scrapers_registered() -> None:
    """Phase 0.5 で追加した 8 ソース全部が登録されている."""
    expected = {
        "anthropic-news",
        "hf-papers",
        "cursor-blog",
        "elyza-news",
        "ai2-blog",
        "kimi-blog",
        "luma-news",
        "bfl-news",
    }
    actual = registered_slugs()
    missing = expected - actual
    assert not missing, f"未登録 scraper: {missing}"


def test_get_scraper_unknown_returns_none() -> None:
    assert get_scraper("nonexistent-slug") is None


def test_register_duplicate_raises() -> None:
    """同一 slug の二重登録は ValueError."""

    @register("__dup_test__")
    def _p1(_content: bytes) -> list:
        return []

    with pytest.raises(ValueError, match="既に登録"):

        @register("__dup_test__")
        def _p2(_content: bytes) -> list:
            return []


# ---------------- parse_html ----------------


def test_parse_html_unknown_slug_is_bozo() -> None:
    """未登録 slug は bozo=True で空 items."""
    feed = parse_html(b"<html></html>", "nonexistent-slug")
    assert feed.bozo is True
    assert feed.items == []
    assert feed.bozo_exception is not None
    assert "nonexistent-slug" in feed.bozo_exception


def test_parse_html_parser_exception_is_caught() -> None:
    """parser が例外を投げても bozo に変換され、items は空になる."""

    @register("__raise_test__")
    def _p(_content: bytes) -> list:
        raise RuntimeError("boom")

    feed = parse_html(b"<html></html>", "__raise_test__")
    assert feed.bozo is True
    assert feed.items == []
    assert feed.bozo_exception is not None
    assert "boom" in feed.bozo_exception


def test_parse_html_empty_html_returns_empty_items() -> None:
    """空 HTML はどの parser でも空 items を返し、bozo=False."""
    for slug in (
        "anthropic-news",
        "hf-papers",
        "cursor-blog",
        "elyza-news",
        "ai2-blog",
        "kimi-blog",
        "luma-news",
        "bfl-news",
    ):
        feed = parse_html(b"<html><body></body></html>", slug)
        assert feed.bozo is False, f"{slug}: 空HTMLで bozo=True"
        assert feed.items == [], f"{slug}: 空HTMLで items 非空"


# ---------------- fetch_html ----------------


@pytest.mark.asyncio
async def test_fetch_html_200() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            content=b"<html>ok</html>",
            headers={"etag": "abc", "last-modified": "Wed, 13 May 2026 00:00:00 GMT"},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch_html("https://example.com/x", client=client)
    assert result.status_code == 200
    assert result.content == b"<html>ok</html>"
    assert result.etag == "abc"


@pytest.mark.asyncio
async def test_fetch_html_304_not_modified() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(304))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch_html(
            "https://example.com/x",
            etag="oldetag",
            client=client,
        )
    assert result.status_code == 304
    assert result.is_not_modified
    assert result.etag == "oldetag"


@pytest.mark.asyncio
async def test_fetch_html_4xx_records_error() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(403))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch_html("https://example.com/x", client=client)
    assert result.status_code == 403
    assert result.content is None
    assert result.error is not None
    assert "403" in result.error


@pytest.mark.asyncio
async def test_fetch_html_network_error_records_error() -> None:
    def _raise(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns fail")

    transport = httpx.MockTransport(_raise)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch_html("https://example.com/x", client=client)
    assert result.status_code == 0
    assert result.error is not None


# ---------------- per-source parser スモーク ----------------

# 縮小 HTML fixture. 実物 (2026-05-13 curl) の構造を 1 件だけ抜き出した最小例.
# 各 parser がタイトル/URL/日付を抽出できれば OK.

_HTML_ANTHROPIC = b"""<html><body>
<div>
  <a class="PublicationList-module__listItem" href="/news/claude-opus-4-7">
    <span class="PublicationList-module__title">Introducing Claude Opus 4.7</span>
    <time>Apr 16, 2026</time>
  </a>
</div>
</body></html>"""

_HTML_HF_PAPERS = b"""<html>
<head><link rel="canonical" href="https://huggingface.co/papers/date/2026-05-13"/></head>
<body>
<article>
  <h3><a href="/papers/2605.10730">Qwen-Image-2.0 Technical Report</a></h3>
  <div class="leading-none">73</div>
</article>
</body></html>"""

_HTML_CURSOR = b"""<html><body>
<article class="h-full">
  <a href="/blog/composer-2"></a>
  <p class="type-md">Introducing Composer 2</p>
  <p class="text-theme-text-sec">Frontier-level coding.</p>
  <time datetime="2026-03-19T00:00:00.000Z">Mar 19, 2026</time>
</article>
</body></html>"""

_HTML_ELYZA = """<html><body>
<div class="style__newsList">
  <a class="root" href="/news/2026/05/11/works_promotion_start">
    <p class="title">ELYZA Works with KDDI</p>
    <time class="publishedAt" datetime="2026.05.11">2026.05.11</time>
    <span class="label">プレスリリース</span>
  </a>
</div>
</body></html>""".encode()

_HTML_AI2 = b"""<html><body>
<div class="d_grid cg_8">
  <a href="/blog/emo">
    <span class="label"><h2>EMO: Mixture of experts</h2></span>
  </a>
  <div class="as_start">May 8, 2026</div>
  <span class="textStyle_wideCardBlurb">EMO is a new MoE model.</span>
</div>
</body></html>"""

_HTML_KIMI = b"""<html><body>
<a class="menu-card" href="/blog/kimi-k2-6">
  <div class="card-title">Kimi K2.6</div>
  <div class="card-date">2026/04/20</div>
  <div class="card-desc">Advancing Open-Source Coding</div>
</a>
<a class="menu-card menu-card-hero-mobile" href="/blog/kimi-k2-6">
  <div class="card-title">Kimi K2.6 (mobile duplicate)</div>
</a>
</body></html>"""

_HTML_LUMA = b"""<html><body>
<div class="group grid">
  <a class="card-link" href="/news/uni-1-1-api">Introducing the Uni-1.1 API</a>
  <span class="border-current">Product</span>
  <span class="typo-body-s text-secondary">May 5, 2026</span>
</div>
</body></html>"""

_HTML_BFL = b"""<html><body>
<article id="blog-post-1">
  <h2>FLUX.2 [klein]</h2>
  <time datetime="2026-01-15T15:00:00.000Z">January 15, 2026</time>
  <p class="text-bf-body-2-regular">Introducing FLUX.2.</p>
  <a href="/blog/flux2-klein"></a>
</article>
</body></html>"""

_FIXTURES = {
    "anthropic-news": (_HTML_ANTHROPIC, "Introducing Claude Opus 4.7", "/news/claude-opus-4-7"),
    "hf-papers": (_HTML_HF_PAPERS, "Qwen-Image-2.0 Technical Report", "/papers/2605.10730"),
    "cursor-blog": (_HTML_CURSOR, "Introducing Composer 2", "/blog/composer-2"),
    "elyza-news": (
        _HTML_ELYZA,
        "ELYZA Works with KDDI",
        "/news/2026/05/11/works_promotion_start",
    ),
    "ai2-blog": (_HTML_AI2, "EMO: Mixture of experts", "/blog/emo"),
    "kimi-blog": (_HTML_KIMI, "Kimi K2.6", "/blog/kimi-k2-6"),
    "luma-news": (_HTML_LUMA, "Introducing the Uni-1.1 API", "/news/uni-1-1-api"),
    "bfl-news": (_HTML_BFL, "FLUX.2 [klein]", "/blog/flux2-klein"),
}


@pytest.mark.parametrize("slug", list(_FIXTURES.keys()))
def test_each_parser_extracts_one_article(slug: str) -> None:
    """各 per-source parser が縮小 HTML から少なくとも 1 件抽出する."""
    html, expected_title, expected_path = _FIXTURES[slug]
    feed = parse_html(html, slug)
    assert feed.bozo is False, f"{slug}: {feed.bozo_exception}"
    assert len(feed.items) >= 1, f"{slug}: items が空"
    item = feed.items[0]
    assert item.title == expected_title, f"{slug}: title mismatch ({item.title!r})"
    assert expected_path in item.url, f"{slug}: url に {expected_path} が含まれない ({item.url})"
    # guid は url と同じ設計
    assert item.guid == item.url
    # 日付は parse できる場合と URL から推定する場合がある (hf-papers)
    assert item.published_struct is not None or slug == "hf-papers"


def test_kimi_skips_hero_mobile_duplicate() -> None:
    """kimi の hero-mobile 重複カードは除外される (同 URL の最初の 1 件のみ)."""
    feed = parse_html(_HTML_KIMI, "kimi-blog")
    assert len(feed.items) == 1
    assert "mobile duplicate" not in feed.items[0].title
