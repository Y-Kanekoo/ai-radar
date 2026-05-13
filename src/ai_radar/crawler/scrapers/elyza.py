"""ELYZA News (elyza.ai/news) HTML scraper.

Next.js App Router + CSS Modules. クラス名は build ごとにハッシュ化されるため、
すべて `[class*="..."]` 部分一致で取る. 日付形式は `2026.05.11` のドット区切り.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from ai_radar.crawler.parse import ParsedItem
from ai_radar.crawler.scraper import register
from ai_radar.crawler.scrapers._util import absolute_url, parse_date_to_struct

BASE_URL = "https://elyza.ai"


@register("elyza-news")
def parse_elyza(content: bytes) -> list[ParsedItem]:
    """elyza.ai/news の HTML から記事リストを抽出."""
    soup = BeautifulSoup(content, "html.parser")
    items: list[ParsedItem] = []
    seen: set[str] = set()

    # newsList コンテナ直下の `<a>` が各記事
    for a in soup.select('div[class*="newsList"] a[href^="/news/"]'):
        href = a.get("href", "")
        url = absolute_url(BASE_URL, href)
        if url in seen:
            continue
        seen.add(url)

        title_tag = a.select_one('p[class*="title"]')
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        if not title:
            continue

        time_tag = a.find("time")
        date_str = ""
        if time_tag is not None:
            # datetime 属性は "2026.05.11" のドット区切り. dateutil は解釈不可なので
            # ドットをハイフンに置換してから渡す.
            raw = time_tag.get("datetime", "") or time_tag.get_text(strip=True)
            date_str = raw.replace(".", "-") if raw else ""

        # カテゴリラベル (プレスリリース / お知らせ / 技術ブログ) を body に残す
        label_tag = a.select_one('span[class*="label"]')
        label = label_tag.get_text(strip=True) if label_tag else ""

        items.append(
            ParsedItem(
                guid=url,
                url=url,
                title=title,
                body=label,
                author=None,
                published_struct=parse_date_to_struct(date_str),
            )
        )

    return items
