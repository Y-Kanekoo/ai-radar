"""Kimi (Moonshot AI) Blog (kimi.com/blog) HTML scraper.

VitePress 静的サイト. `a.menu-card` がカードだが、`.menu-card-hero-mobile` は同一記事の
モバイル用重複表示なので必ず除外する.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from ai_radar.crawler.parse import ParsedItem
from ai_radar.crawler.scraper import register
from ai_radar.crawler.scrapers._util import absolute_url, parse_date_to_struct

BASE_URL = "https://www.kimi.com"


@register("kimi-blog")
def parse_kimi(content: bytes) -> list[ParsedItem]:
    """kimi.com/blog の HTML から記事リストを抽出."""
    soup = BeautifulSoup(content, "html.parser")
    items: list[ParsedItem] = []
    seen: set[str] = set()

    for a in soup.select("a.menu-card"):
        # hero-mobile は同一記事の重複表示
        if "menu-card-hero-mobile" in (a.get("class") or []):
            continue
        href = a.get("href", "")
        if not href:
            continue
        url = absolute_url(BASE_URL, href)
        if url in seen:
            continue
        seen.add(url)

        title_tag = a.select_one(".card-title")
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        if not title:
            continue

        date_tag = a.select_one(".card-date")
        # 形式 "2026/04/20" — dateutil は解釈可能
        date_str = date_tag.get_text(strip=True) if date_tag else ""

        snippet_tag = a.select_one(".card-desc")
        snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

        items.append(
            ParsedItem(
                guid=url,
                url=url,
                title=title,
                body=snippet,
                author=None,
                published_struct=parse_date_to_struct(date_str),
            )
        )

    return items
