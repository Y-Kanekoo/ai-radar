"""Luma AI News (lumalabs.ai/news) HTML scraper.

Next.js App Router (RSC). `a.card-link[href^="/news/"]` がカードのリンク. 日付は
カードコンテナ内の `span.typo-body-s.text-secondary` にある (DOM の祖先方向).
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from ai_radar.crawler.parse import ParsedItem
from ai_radar.crawler.scraper import register
from ai_radar.crawler.scrapers._util import absolute_url, parse_date_to_struct

BASE_URL = "https://lumalabs.ai"


def _find_date_in_ancestors(a: Tag) -> str:
    """祖先方向に最大 6 階層遡って日付 span を探す."""
    cur: Tag | None = a
    for _ in range(6):
        if cur is None or not isinstance(cur, Tag):
            return ""
        date_span = cur.select_one("span.typo-body-s.text-secondary")
        if date_span is not None:
            return date_span.get_text(strip=True)
        cur = cur.parent
    return ""


@register("luma-news")
def parse_luma(content: bytes) -> list[ParsedItem]:
    """lumalabs.ai/news の HTML から記事リストを抽出."""
    soup = BeautifulSoup(content, "html.parser")
    items: list[ParsedItem] = []
    seen: set[str] = set()

    for a in soup.select('a.card-link[href^="/news/"]'):
        href = a.get("href", "")
        url = absolute_url(BASE_URL, href)
        if url in seen:
            continue
        seen.add(url)

        title = a.get_text(strip=True)
        if not title:
            continue

        date_str = _find_date_in_ancestors(a)

        # カテゴリラベル ("Product" / "Company" / "Research" 等) を body に残す
        category = ""
        # `a` の親方向にカード root があり、その中に category span がある
        card_root = a.parent
        if isinstance(card_root, Tag):
            cat_tag = card_root.select_one("span.border-current")
            if cat_tag is not None:
                category = cat_tag.get_text(strip=True)

        items.append(
            ParsedItem(
                guid=url,
                url=url,
                title=title,
                body=category,
                author=None,
                published_struct=parse_date_to_struct(date_str),
            )
        )

    return items
