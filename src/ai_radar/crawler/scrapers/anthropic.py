"""Anthropic News (anthropic.com/news) HTML scraper.

DOM 構造は2系統が同居する:
  - PublicationList: メインの記事リスト (10件、snippet なし)
  - FeaturedGrid: 上部 Featured カード (3件、snippet あり)

CSS Modules ハッシュ付きクラス (`PublicationList-module-...__listItem`) のため、
完全一致は禁止. `[class*="..."]` の部分一致で吸収する.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from ai_radar.crawler.parse import ParsedItem
from ai_radar.crawler.scraper import register
from ai_radar.crawler.scrapers._util import absolute_url, parse_date_to_struct

BASE_URL = "https://www.anthropic.com"


@register("anthropic-news")
def parse_anthropic(content: bytes) -> list[ParsedItem]:
    """anthropic.com/news の HTML から記事リストを抽出."""
    soup = BeautifulSoup(content, "html.parser")
    items: list[ParsedItem] = []
    seen: set[str] = set()

    # メインリスト (PublicationList): タイトル span + time + subject
    for a in soup.select('a[class*="PublicationList-module"][href^="/news/"]'):
        url = absolute_url(BASE_URL, a.get("href", ""))
        if url in seen:
            continue
        seen.add(url)
        title_tag = a.select_one('span[class*="__title"]')
        time_tag = a.find("time")
        if not title_tag:
            continue
        items.append(
            ParsedItem(
                guid=url,
                url=url,
                title=title_tag.get_text(strip=True),
                body="",  # 一覧ページに snippet なし
                author=None,
                published_struct=parse_date_to_struct(
                    time_tag.get_text(strip=True) if time_tag else None
                ),
            )
        )

    # FeaturedGrid (3件、snippet あり)
    for a in soup.select('a[class*="FeaturedGrid-module"][href^="/news/"]'):
        url = absolute_url(BASE_URL, a.get("href", ""))
        if url in seen:
            continue
        seen.add(url)
        # Featured は h2 / h4 がタイトル
        title_tag = a.find(["h2", "h4"])
        time_tag = a.find("time")
        snippet_tag = a.select_one('p[class*="__body"]')
        if not title_tag:
            continue
        items.append(
            ParsedItem(
                guid=url,
                url=url,
                title=title_tag.get_text(strip=True),
                body=snippet_tag.get_text(strip=True) if snippet_tag else "",
                author=None,
                published_struct=parse_date_to_struct(
                    time_tag.get_text(strip=True) if time_tag else None
                ),
            )
        )

    return items
