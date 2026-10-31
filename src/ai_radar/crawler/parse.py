"""フィードパース層. feedparser を薄くラップしてデータクラスに変換."""

from __future__ import annotations

import feedparser
from radar_core.parse import ParsedFeed as ParsedFeed
from radar_core.parse import ParsedItem as ParsedItem


def parse_feed(content: bytes | str) -> ParsedFeed:
    """Atom/RSS バイト列をパースし、エントリを抽出する.

    feedparser は壊れたフィードでも可能な限りパースを続ける (bozo=True).
    items が1つでも取れていれば bozo=True でも正常扱いとする.

    Args:
        content: フィード本文. bytes 推奨 (encoding 自動判定が効く).

    Returns:
        ParsedFeed.
    """
    parsed = feedparser.parse(content)
    items: list[ParsedItem] = []
    for entry in parsed.entries:
        url = entry.get("link") or ""
        if not url:
            # 記事リンクのないポッドキャストは音声URLを参照先にする。音声は取得しない。
            url = next(
                (
                    enclosure.get("href")
                    for enclosure in entry.get("enclosures", [])
                    if enclosure.get("type", "").startswith("audio/") and enclosure.get("href")
                ),
                "",
            )
        guid = entry.get("id") or url
        title = entry.get("title") or "(no title)"

        body = ""
        if entry.get("content"):
            body = entry.content[0].get("value", "")
        if not body:
            body = entry.get("summary") or entry.get("description") or ""

        author = entry.get("author") or None

        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if published is not None:
            published_struct: tuple[int, ...] | None = tuple(published[:6])
        else:
            published_struct = None

        items.append(
            ParsedItem(
                guid=guid,
                url=url,
                title=title,
                body=body,
                author=author,
                published_struct=published_struct,
            )
        )

    bozo_exception: str | None = None
    if parsed.bozo and parsed.get("bozo_exception"):
        bozo_exception = str(parsed.bozo_exception)

    return ParsedFeed(
        items=items,
        bozo=bool(parsed.bozo),
        bozo_exception=bozo_exception,
    )
