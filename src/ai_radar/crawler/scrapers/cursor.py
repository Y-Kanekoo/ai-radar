"""Cursor Blog (cursor.com/blog) HTML scraper.

Next.js SSR + Tailwind. `article.h-full` カードに3バリエーション (Featured / 通常 /
Customer Story) があり、タイトルクラスが少しずつ違うため Python 側で classes を見て
分岐する. 日付は `<time datetime="ISO8601">` がすべての article で揃っている.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from ai_radar.crawler.parse import ParsedItem
from ai_radar.crawler.scraper import register
from ai_radar.crawler.scrapers._util import absolute_url, parse_date_to_struct

BASE_URL = "https://cursor.com"


def _find_title(article: Tag) -> str:
    """カードバリエーションを吸収してタイトルを取得する.

    Featured は p.type-md-lg、通常 blog は p.type-md、customer story は
    p.type-base.text-theme-text. いずれも text-theme-text-sec は snippet なので除外.
    """
    for p in article.find_all("p"):
        classes = p.get("class") or []
        is_title_class = any(c in ("type-md", "type-md-lg", "type-base") for c in classes)
        is_snippet = any("text-theme-text-sec" in c for c in classes)
        if is_title_class and not is_snippet:
            text = p.get_text(strip=True)
            if text:
                return text
    return ""


@register("cursor-blog")
def parse_cursor(content: bytes) -> list[ParsedItem]:
    """cursor.com/blog の HTML から記事リストを抽出."""
    soup = BeautifulSoup(content, "html.parser")
    items: list[ParsedItem] = []
    seen: set[str] = set()

    for article in soup.select("article.h-full"):
        a = article.select_one('a[href^="/blog/"]')
        if a is None:
            continue
        href = a.get("href", "")
        url = absolute_url(BASE_URL, href)
        if url in seen:
            continue
        seen.add(url)

        title = _find_title(article)
        if not title:
            continue

        time_tag = article.find("time")
        date_str = ""
        if time_tag is not None:
            # datetime 属性が ISO8601、テキストは "Feb 26, 2026" 形式. ISO 優先.
            date_str = time_tag.get("datetime", "") or time_tag.get_text(strip=True)

        snippet_tag = article.select_one('p[class*="text-theme-text-sec"]')
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
