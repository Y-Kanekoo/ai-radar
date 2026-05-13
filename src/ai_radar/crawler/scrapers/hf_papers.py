"""Hugging Face Papers Daily (huggingface.co/papers) HTML scraper.

一覧ページに日付要素は無いので、現在時刻 (UTC) を published に充てる. ソース URL は
`huggingface.co/papers` (今日の daily にリダイレクト) を想定. URL に日付を含む形式
`huggingface.co/papers/date/YYYY-MM-DD` を sources.yaml に指定した場合は、その日付を
扱うように `_extract_date_from_url` で補助する.

upvote (`div.leading-none`) も拾うが、現状の ParsedItem には格納先がない. Phase 2 で
スコアリング用の独立カラムを追加する想定. 今は body にメタとして残す.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ai_radar.crawler.parse import ParsedItem
from ai_radar.crawler.scraper import register
from ai_radar.crawler.scrapers._util import now_utc_struct, parse_date_to_struct

BASE_URL = "https://huggingface.co"
_DATE_IN_URL = re.compile(r"/papers/date/(\d{4}-\d{2}-\d{2})")
# Daily 一覧は数十件あるが、Top 10-15 で十分とする
_MAX_PAPERS = 15


@register("hf-papers")
def parse_hf_papers(content: bytes) -> list[ParsedItem]:
    """huggingface.co/papers の HTML から daily の paper リストを抽出."""
    soup = BeautifulSoup(content, "html.parser")
    items: list[ParsedItem] = []
    seen: set[str] = set()

    # URL に日付が埋まっているかを最初に確認 (sources.yaml で固定 URL を指定する場合)
    title_tag = soup.find("title")
    title_text = title_tag.get_text() if title_tag else ""
    canonical = soup.find("link", rel="canonical")
    href = canonical.get("href", "") if canonical else ""
    date_match = _DATE_IN_URL.search(href) or _DATE_IN_URL.search(title_text)
    published_struct = parse_date_to_struct(date_match.group(1)) if date_match else now_utc_struct()

    for a in soup.select('h3 a[href^="/papers/"]'):
        href = a.get("href", "")
        url = BASE_URL + href if href.startswith("/") else href
        if url in seen:
            continue
        seen.add(url)
        title = a.get_text(strip=True)
        if not title:
            continue

        # upvote が article 内の `div.leading-none` にある (parent をたどって取得)
        article = a.find_parent("article")
        upvote = ""
        if article is not None:
            upvote_tag = article.select_one("div.leading-none")
            if upvote_tag is not None:
                upvote = upvote_tag.get_text(strip=True)

        items.append(
            ParsedItem(
                guid=url,
                url=url,
                title=title,
                # snippet は abstract が一覧に無いので、upvote をメタとして残す
                body=f"upvotes={upvote}" if upvote else "",
                author=None,
                published_struct=published_struct,
            )
        )
        if len(items) >= _MAX_PAPERS:
            break

    return items
