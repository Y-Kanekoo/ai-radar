"""Issue #8: 一時 DB + HTTP stub による CLI と workflow の契約."""

import logging
import sqlite3
from pathlib import Path

import httpx
import pytest
import yaml

import scripts.notify_discord as nd
from ai_radar.db import init_db
from ai_radar.publisher.discord import CATEGORY_ENV_PREFIX, FALLBACK_ENV
from tests.unit.test_notify_discord_message_id import _setup_article


@pytest.fixture
def setup(tmp_path, monkeypatch):
    for name in (*[CATEGORY_ENV_PREFIX + c.upper() for c in nd.KNOWN_CATEGORIES], FALLBACK_ENV):
        monkeypatch.delenv(name, raising=False)
    db = tmp_path / "articles.db"
    conn = init_db(db)
    conn.close()
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary"))
    return db


def test_missing_is_explicit_skip(setup, caplog):
    caplog.set_level(logging.INFO)
    assert nd.main(["--db-path", str(setup)]) == 0
    assert "status=unconfigured" in caplog.text
    assert "release: status=unconfigured" in caplog.text


def test_empty_is_distinct(setup, monkeypatch, caplog):
    monkeypatch.setenv(FALLBACK_ENV, "https://example.invalid/SECRET")
    caplog.set_level(logging.INFO)
    assert nd.main(["--db-path", str(setup)]) == 0
    assert "status=empty" in caplog.text
    assert "SECRET" not in caplog.text


@pytest.mark.parametrize("failure", [401, 429, 500, "timeout"])
def test_partial_failure_recovery_and_dedup(setup, monkeypatch, caplog, failure):
    conn = init_db(setup)
    _setup_article(conn, "a")
    _setup_article(conn, "b")
    conn.close()
    monkeypatch.setattr(nd, "should_deliver", lambda **kwargs: True)
    monkeypatch.setenv(FALLBACK_ENV, "https://example.invalid/SECRET")
    calls = []
    recovering = False

    def handler(request):
        calls.append(request)
        if not recovering and "title-b" in request.content.decode():
            if failure == "timeout":
                raise httpx.ReadTimeout("SECRET", request=request)
            return httpx.Response(failure, text="SECRET")
        return httpx.Response(200, json={"id": "message"})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        nd.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    caplog.set_level(logging.DEBUG)
    args = ["--db-path", str(setup), "--rate-delay", "0", "--verbose"]
    assert nd.main(args) == 2
    assert "status=partial_failure" in caplog.text
    assert "SECRET" not in caplog.text
    with sqlite3.connect(setup) as conn:
        assert conn.execute("SELECT COUNT(*) FROM article_notifications").fetchone()[0] == 1
    recovering = True
    calls.clear()
    assert nd.main(args) == 0
    assert len(calls) == 1
    calls.clear()
    assert nd.main(args) == 0
    assert calls == []


def test_dry_run_preserves_database_without_configuration(setup, monkeypatch, caplog):
    conn = init_db(setup)
    _setup_article(conn)
    conn.close()
    before = setup.read_bytes()
    monkeypatch.setattr(nd, "should_deliver", lambda **kwargs: False)
    monkeypatch.setattr(nd.httpx, "AsyncClient", lambda **kw: pytest.fail("dry-run HTTP"))
    caplog.set_level(logging.INFO)
    assert nd.main(["--db-path", str(setup), "--dry-run"]) == 0
    assert setup.read_bytes() == before
    assert "status=dry_run" in caplog.text
    assert "score閾値未満=1" in caplog.text


def test_workflow_preserves_failure_and_publication():
    workflow = yaml.safe_load(Path(".github/workflows/crawl.yml").read_text())
    jobs = workflow["jobs"]
    crawl = jobs["crawl-and-build"]
    notify = next(s for s in crawl["steps"] if s.get("id") == "notify")
    assert notify["continue-on-error"] is True
    assert "||" not in notify["run"]
    for c in nd.KNOWN_CATEGORIES:
        name = CATEGORY_ENV_PREFIX + c.upper()
        assert notify["env"][name] == "${{ secrets." + name + " }}"
    assert crawl["outputs"]["notify_outcome"] == "${{ steps.notify.outcome }}"
    gate = jobs["notification-result"]
    assert gate["needs"] == "crawl-and-build"
    assert "always()" in gate["if"]
    assert "notify_outcome == 'failure'" in gate["if"]
    assert "exit 1" in gate["steps"][0]["run"]
    assert jobs["deploy"]["needs"] == "crawl-and-build"
    assert "pull_request" not in workflow.get("on", workflow.get(True, {}))


def test_category_override_and_fallback(setup, monkeypatch, caplog):
    monkeypatch.setenv(FALLBACK_ENV, "https://fallback.invalid/secret")
    monkeypatch.setenv(CATEGORY_ENV_PREFIX + "RELEASE", "https://category.invalid/secret")
    seen = {}

    def dispatch(conn, category, webhook, *args):
        seen[category] = webhook
        return 1, 0, 0

    monkeypatch.setattr(nd, "_dispatch_category", dispatch)
    assert nd.main(["--db-path", str(setup)]) == 0
    assert seen.pop("release") == "https://category.invalid/secret"
    assert set(seen.values()) == {"https://fallback.invalid/secret"}


def test_partial_configuration_summary(setup, monkeypatch, caplog):
    monkeypatch.setenv(CATEGORY_ENV_PREFIX + "RELEASE", "https://category.invalid/secret")
    caplog.set_level(logging.INFO)
    assert nd.main(["--db-path", str(setup)]) == 0
    assert "release: status=empty" in caplog.text
    assert "paper: status=unconfigured" in caplog.text
    assert "status=partial_configuration" in caplog.text
    assert "configured=1/8" in caplog.text
    assert "status=partial_configuration" in (setup.parent / "summary").read_text()


def test_database_save_failure_is_not_success(setup, monkeypatch, caplog):
    conn = init_db(setup)
    _setup_article(conn)
    conn.close()
    monkeypatch.setattr(nd, "should_deliver", lambda **kw: True)
    monkeypatch.setenv(CATEGORY_ENV_PREFIX + "RELEASE", "https://example.invalid/SECRET")
    original = httpx.AsyncClient
    monkeypatch.setattr(
        nd.httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"id": "message"})),
            **kw,
        ),
    )

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("SECRET")

    monkeypatch.setattr(nd, "mark_notified_with_message_id", fail)
    caplog.set_level(logging.INFO)
    assert nd.main(["--db-path", str(setup)]) == 2
    assert "status=failed" in caplog.text
    assert "SECRET" not in caplog.text
    with sqlite3.connect(setup) as conn:
        assert conn.execute("SELECT COUNT(*) FROM article_notifications").fetchone()[0] == 0


def test_explicit_workflow_skip_and_no_push_notification():
    workflow = yaml.safe_load(Path(".github/workflows/crawl.yml").read_text())
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert triggers["schedule"] == [{"cron": "0 0,6,12 * * *"}]
    steps = workflow["jobs"]["crawl-and-build"]["steps"]
    notify = next(s for s in steps if s.get("id") == "notify")
    assert notify["if"] == "${{ inputs.skip_discord != true }}"
    for step in steps[steps.index(notify) + 1 :]:
        assert "notify" not in step.get("if", "")
    assert workflow["jobs"]["notification-result"]["permissions"] == {}


@pytest.mark.parametrize(
    "http_status, expected_exit, webhook",
    [
        (200, 0, "https://example.invalid/SECRET"),
        (401, 2, "https://example.invalid/SECRET"),
        (200, 2, "https://example.invalid:SECRET/webhook"),
    ],
)
def test_cli_process_exit_and_persistent_history(setup, http_status, expected_exit, webhook):
    """本物の CLI entrypoint を別プロセスで実行し HTTP のみ置換する."""
    import os
    import subprocess
    import sys
    import time

    conn = init_db(setup)
    _setup_article(conn, published_at=int(time.time()))
    conn.close()
    runner = """
import httpx, runpy, sys
original = httpx.AsyncClient
status = int(sys.argv[1])
httpx.AsyncClient = lambda **kw: original(
    transport=httpx.MockTransport(lambda r: httpx.Response(status, json={'id':'stub'})), **kw)
db = sys.argv[2]
sys.argv = ['scripts/notify_discord.py', '--db-path', db, '--rate-delay', '0', '--verbose']
runpy.run_path('scripts/notify_discord.py', run_name='__main__')
"""
    env = dict(os.environ, DISCORD_WEBHOOK_URL=webhook)
    result = subprocess.run(
        [sys.executable, "-c", runner, str(http_status), str(setup)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_exit, result.stderr
    assert "SECRET" not in result.stderr + result.stdout
    with sqlite3.connect(setup) as conn:
        count = conn.execute("SELECT COUNT(*) FROM article_notifications").fetchone()[0]
    assert count == (1 if expected_exit == 0 else 0)


@pytest.mark.parametrize("legacy", [False, True], ids=["current-schema", "pre-v4-schema"])
@pytest.mark.parametrize("deliver", [False, True], ids=["score-filtered", "eligible"])
def test_dry_run_migrates_only_memory_copy(setup, monkeypatch, caplog, legacy, deliver):
    """旧 schema もプレビュー可能で、元 DB の schema/bytes/履歴は不変."""
    conn = init_db(setup)
    _setup_article(conn)
    if legacy:
        conn.execute("ALTER TABLE articles DROP COLUMN is_hype")
        conn.execute("ALTER TABLE sources DROP COLUMN tier")
        conn.execute("DROP INDEX idx_notifications_discord_msg")
        conn.execute("ALTER TABLE article_notifications DROP COLUMN discord_message_id")
        conn.execute("ALTER TABLE article_notifications DROP COLUMN discord_channel_id")
        conn.execute("UPDATE schema_version SET version = 3")
        conn.commit()
    conn.close()
    before = setup.read_bytes()
    with sqlite3.connect(setup) as conn:
        before_dump = tuple(conn.iterdump())
    evaluated = []

    def score(**kwargs):
        evaluated.append(kwargs)
        return deliver

    monkeypatch.setattr(nd, "should_deliver", score)
    monkeypatch.setattr(nd.httpx, "AsyncClient", lambda **kw: pytest.fail("dry-run HTTP"))
    caplog.set_level(logging.INFO)
    assert nd.main(["--db-path", str(setup), "--dry-run"]) == 0
    assert len(evaluated) == 1
    assert evaluated[0]["tier"] == (3 if legacy else 1)
    assert evaluated[0]["is_hype"] is False
    assert "status=dry_run" in caplog.text
    assert "failure=0" in caplog.text
    if deliver:
        assert "[DRY release]" in caplog.text
    assert setup.read_bytes() == before
    with sqlite3.connect(setup) as conn:
        assert tuple(conn.iterdump()) == before_dump
        assert conn.execute("SELECT COUNT(*) FROM article_notifications").fetchone()[0] == 0
