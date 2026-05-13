"""Allen AI / AI2 Blog (allenai.org/blog) HTML scraper.

Next.js + Panda CSS (atomic class). クラス名は build 設定依存で不安定なので、構造を
起点に抽出する: `<h2>` を持つ `<a href^="/blog/">` を見つけ、その親カード div を
コンテナとして扱う.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from ai_radar.crawler.parse import ParsedItem
from ai_radar.crawler.scraper import register
from ai_radar.crawler.scrapers._util import absolute_url, parse_date_to_struct

BASE_URL = "https://allenai.org"


def _ascend_card(a: Tag) -> Tag | None:
    """`<a>` を起点に最近接の card div を見つける.

    Panda CSS の atomic class は安定しないので、深さ 6 までの祖先で最初に出会う
    `div` をカードとみなす. snippet と date が同じ祖先に含まれる構造を前提とする.
    """
    cur: Tag | None = a
    for _ in range(6):
        if cur is None:
            return None
        cur = cur.parent if isinstance(cur, Tag) else None
        if cur is None or cur.name != "div":
            continue
        # snippet または date のどちらかが含まれていれば card 候補
        if cur.select_one('span[class*="wideCardBlurb"]') or cur.select_one(
            'div[class*="as_start"]'
        ):
            return cur
    return None


@register("ai2-blog")
def parse_ai2(content: bytes) -> list[ParsedItem]:
    """allenai.org/blog の HTML から記事リストを抽出."""
    soup = BeautifulSoup(content, "html.parser")
    items: list[ParsedItem] = []
    seen: set[str] = set()

    for h2 in soup.find_all("h2"):
        a = h2.find_parent("a", href=True)
        if a is None:
            continue
        href = a.get("href", "")
        if not href.startswith("/blog/"):
            continue
        url = absolute_url(BASE_URL, href)
        if url in seen:
            continue
        seen.add(url)

        title = h2.get_text(strip=True)
        if not title:
            continue

        card = _ascend_card(a)
        snippet = ""
        date_str = ""
        if card is not None:
            blurb_tag = card.select_one('span[class*="wideCardBlurb"]')
            if blurb_tag:
                snippet = blurb_tag.get_text(strip=True)
            date_tag = card.select_one('div[class*="as_start"]')
            if date_tag:
                date_str = date_tag.get_text(strip=True)

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
