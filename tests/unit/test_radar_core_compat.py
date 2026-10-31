"""radar-core の委譲境界と、利用側に残す互換動作を検証する。"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import pickle
from dataclasses import asdict, replace

import feedparser
import httpx
import pytest
from radar_core import fetch as core_fetch
from radar_core import normalize as core_normalize
from radar_core import parse as core_parse

from ai_radar.crawler import fetch, normalize, parse
from ai_radar.publisher import discord
from ai_radar.publisher.rss import FeedItem


@pytest.mark.parametrize(
    ("name", "signature"),
    [
        ("normalize_url", "(url: 'str') -> 'str'"),
        ("normalize_published", "(struct_time: 'tuple[int, ...] | None') -> 'int'"),
        ("strip_html", "(text: 'str') -> 'str'"),
        ("make_snippet", "(body: 'str', max_chars: 'int' = 100) -> 'str'"),
        ("compute_body_hash", "(body: 'str') -> 'str'"),
    ],
)
def test_normalize_signatures(name: str, signature: str) -> None:
    assert str(inspect.signature(getattr(normalize, name))) == signature


def test_url_keeps_existing_tracking_and_query_rules() -> None:
    assert normalize.TRACKING_PARAMS == core_normalize.TRACKING_PARAMS
    assert len(normalize.TRACKING_PARAMS) == 20
    assert (
        normalize.normalize_url(
            "HTTPS://Example.COM/path///?UTM_SOURCE=rss&src=feed&source=site&empty=&id=1&id=2#top"
        )
        == "https://example.com/path?src=feed&source=site&id=1&id=2"
    )
    with pytest.raises(TypeError):
        normalize.normalize_url("https://example.com", extra_tracking_params={"src"})  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        normalize.normalize_url("https://[invalid")


def test_html_hash_and_date_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    body = "<p>こんにちは &amp; 世界</p>\n\t続き"
    assert normalize.strip_html(body) == "こんにちは & 世界\n\t続き"
    assert (
        normalize.compute_body_hash(body)
        == hashlib.sha256("こんにちは & 世界 続き".encode()).hexdigest()
    )
    monkeypatch.setattr(core_normalize.time, "time", lambda: 1705321845.9)
    assert normalize.normalize_published(None) == 1705321845
    assert normalize.normalize_published((2024, 1, 15)) == 1705276800
    with pytest.raises(ValueError):
        normalize.normalize_published((2024, 13, 15))


@pytest.mark.parametrize(
    ("body", "limit", "expected"),
    [
        ("<p>あ</p>" * 200, 100, "あ" * 100 + "…"),
        ("abcdefgh ijkl", 10, "abcdefgh…"),
        ("abc", 1, "a…"),
        ("abc", 0, "…"),
        ("", 0, ""),
        ("abc", -1, "ab…"),
        ("abc", -3, "…"),
        ("", -1, "…"),
        ("<p>a  b</p>", -1, "a…"),
    ],
)
def test_snippet_preserves_nonpositive_limits(body: str, limit: int, expected: str) -> None:
    assert normalize.make_snippet(body, limit) == expected


def test_reexports_keep_data_and_old_import_paths() -> None:
    assert fetch.FetchResult is core_fetch.FetchResult
    assert parse.ParsedItem is core_parse.ParsedItem
    assert parse.ParsedFeed is core_parse.ParsedFeed
    result = fetch.FetchResult("https://example.com", 200, b"", None, None)
    assert asdict(result) == {
        "url": "https://example.com",
        "status_code": 200,
        "content": b"",
        "etag": None,
        "last_modified": None,
        "error": None,
    }
    assert result.is_modified and not result.is_not_modified
    assert not replace(result, content=None).is_modified
    cached = replace(result, status_code=304, content=None)
    assert cached.is_not_modified and not cached.is_modified
    item = parse.ParsedItem("id", "url", "題", "本文", None, (2024, 1, 15))
    parsed = parse.ParsedFeed([item], False, None)
    assert asdict(parsed) == {
        "items": [
            {
                "guid": "id",
                "url": "url",
                "title": "題",
                "body": "本文",
                "author": None,
                "published_struct": (2024, 1, 15),
            }
        ],
        "bozo": False,
        "bozo_exception": None,
    }
    # 旧モジュール名で保存された pickle のクラス参照も解決できる。
    for module, name in [
        (fetch, "FetchResult"),
        (parse, "ParsedItem"),
        (parse, "ParsedFeed"),
    ]:
        assert pickle.loads(f"c{module.__name__}\n{name}\n.".encode()) is getattr(module, name)
    assert pickle.loads(pickle.dumps(parsed)) == parsed


@pytest.mark.parametrize("status", [200, 304, 500])
async def test_fetch_keeps_headers_timeout_and_single_request(status: int) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, content=b"<feed/>", headers={"etag": "new"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=7) as client:
        result = await fetch.fetch_feed(
            "https://example.com/feed",
            etag="cached",
            last_modified="date",
            timeout=1,
            client=client,
        )
        assert not client.is_closed
    assert len(requests) == 1
    assert requests[0].headers["user-agent"] == fetch.USER_AGENT
    assert requests[0].headers["accept"] == fetch.ACCEPT_HEADER
    assert requests[0].headers["if-none-match"] == "cached"
    assert requests[0].headers["if-modified-since"] == "date"
    assert requests[0].extensions["timeout"] == dict.fromkeys(
        ("connect", "read", "write", "pool"), 7
    )
    assert isinstance(result, fetch.FetchResult)
    assert result.status_code == status
    assert result.content == (b"<feed/>" if status == 200 else None)
    assert result.etag == {200: "new", 304: "cached", 500: None}[status]
    assert result.error == ("unexpected status: 500" if status == 500 else None)


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.InvalidURL])
async def test_fetch_preserves_errors(error_type: type[Exception]) -> None:
    error = error_type("取得失敗")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise error

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        if error_type is httpx.InvalidURL:
            with pytest.raises(httpx.InvalidURL) as raised:
                await fetch.fetch_feed("https://example.com/feed", client=client)
            assert raised.value is error
        else:
            result = await fetch.fetch_feed("https://example.com/feed", client=client)
            assert result == fetch.FetchResult(
                "https://example.com/feed", 0, None, None, None, "取得失敗"
            )
        assert not client.is_closed
    assert len(requests) == 1


async def test_robots_keeps_ai_radar_identity_and_cache() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="User-agent: ai-radar\nDisallow: /private\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cache = fetch.RobotsCache()
        assert not await cache.is_allowed("https://example.com/private", client)
        assert await cache.is_allowed("https://example.com/public", client)
    assert len(requests) == 1
    assert str(requests[0].url) == "https://example.com/robots.txt"
    assert requests[0].headers["user-agent"] == fetch.USER_AGENT


@pytest.mark.parametrize(
    "content", [b"<feed/>", "<?xml version='1.0' encoding='shift_jis'?><feed/>"]
)
def test_parse_preserves_input_and_uncoerced_values(
    content: bytes | str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs: list[bytes | str] = []

    def stub(value: bytes | str) -> feedparser.FeedParserDict:
        inputs.append(value)
        return feedparser.FeedParserDict(
            entries=[
                feedparser.FeedParserDict(
                    link="https://example.com",
                    title=123,
                    author=456,
                    content=[{"value": 789}],
                    published_parsed=[2024, 1, 15, "12", 0, 0],
                )
            ],
            bozo=True,
            bozo_exception=ValueError("壊れたフィード"),
        )

    monkeypatch.setattr(parse.feedparser, "parse", stub)
    result = parse.parse_feed(content)
    assert inputs == [content]
    assert inputs[0] is content
    assert type(result) is parse.ParsedFeed
    assert type(result.items[0]) is parse.ParsedItem
    assert result.items[0].title == 123
    assert result.items[0].author == 456
    assert result.items[0].body == 789
    assert result.items[0].published_struct == (2024, 1, 15, "12", 0, 0)
    assert result.bozo and result.bozo_exception == "壊れたフィード"


def _item() -> FeedItem:
    return FeedItem("id", "https://example.com", "😀" * 257, "", "", None, 0, ())


def test_discord_keeps_character_limits_and_empty_fields() -> None:
    assert discord.build_payload(_item()) == {
        "embeds": [
            {
                "title": "😀" * 256,
                "url": "https://example.com",
                "description": "",
                "color": 0x0969DA,
                "footer": {"text": ""},
                "timestamp": "1970-01-01T00:00:00+00:00",
            }
        ]
    }


async def test_discord_keeps_retry_query_payload_ids_and_log(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"retry-after": "0.1"}, json={"retry_after": 9})
        return httpx.Response(200, json={"id": 123, "channel_id": 456})

    monkeypatch.setattr(discord.asyncio, "sleep", sleep)
    caplog.set_level(logging.INFO, logger="ai_radar.discord")
    url = "https://discord.invalid/api/webhooks/fixture/placeholder?wait=false&thread_id=7"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await discord.send_notification_with_message_id(_item(), url, client=client) == (
            True,
            "123",
            "456",
        )
        assert not client.is_closed
    assert sleeps == [0.5]
    assert len(requests) == 2
    assert [str(request.url) for request in requests] == [url + "&wait=true"] * 2
    assert [json.loads(request.content) for request in requests] == [
        discord.build_payload(_item())
    ] * 2
    assert [
        record.getMessage() for record in caplog.records if record.name == "ai_radar.discord"
    ] == ["Discord rate limited, 0.5s 待機して再試行"]


@pytest.mark.parametrize("name", ["httpx", "httpcore.http11", "httpcore.http2", "httpcore.proxy"])
def test_import_masks_only_webhook_log_urls(name: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=name)
    logger = logging.getLogger(name)
    logger.info("POST %s", "https://discord.invalid/api/webhooks/fixture/placeholder?wait=true")
    logger.info("GET %s", "https://example.com/feed?source=rss")
    assert [record.getMessage() for record in caplog.records] == [
        "POST https://discord.invalid/api/webhooks/***/***",
        "GET https://example.com/feed?source=rss",
    ]
