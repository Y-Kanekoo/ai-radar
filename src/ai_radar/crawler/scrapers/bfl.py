"""Black Forest Labs (bfl.ai/blog) HTML scraper.

Next.js App Router + Sanity CMS. 構造化が最も整っており、`<article id="blog-post-...">`
内にタイトル (h2), ISO8601 datetime, snippet, リンクが揃う.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from ai_radar.crawler.parse import ParsedItem
from ai_radar.crawler.scraper import register
from ai_radar.crawler.scrapers._util import absolute_url, parse_date_to_struct

BASE_URL = "https://bfl.ai"


@register("bfl-news")
def parse_bfl(content: bytes) -> list[ParsedItem]:
    """bfl.ai/blog の HTML から記事リストを抽出."""
    soup = BeautifulSoup(content, "html.parser")
    items: list[ParsedItem] = []
    seen: set[str] = set()

    for article in soup.select('article[id^="blog-post-"]'):
        h2 = article.find("h2")
        a = article.select_one('a[href^="/blog/"]')
        if not h2 or not a:
            continue
        href = a.get("href", "")
        url = absolute_url(BASE_URL, href)
        if url in seen:
            continue
        seen.add(url)

        title = h2.get_text(strip=True)
        if not title:
            continue

        time_tag = article.find("time")
        # ISO8601 が datetime 属性にそのまま入っている
        date_str = ""
        if time_tag is not None:
            date_str = time_tag.get("datetime", "") or time_tag.get_text(strip=True)

        snippet_tag = article.select_one("p.text-bf-body-2-regular")
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
