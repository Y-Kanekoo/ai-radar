"""benchmark fetcher の parse ロジック (Phase 3)."""

from __future__ import annotations

from ai_radar.crawler.benchmarks.fetchers.alpaca_eval import _parse_csv as _alpaca_parse
from ai_radar.crawler.benchmarks.fetchers.bigcodebench import _parse_rows as _bcb_parse
from ai_radar.crawler.benchmarks.fetchers.github_trending import (
    _is_ai_related,
    _parse_int_with_commas,
    _parse_trending,
)
from ai_radar.crawler.benchmarks.fetchers.lmarena import _parse_rows
from ai_radar.crawler.benchmarks.fetchers.mteb import _parse_paths

# ---------------- LMArena ----------------


def test_lmarena_parse_rows_filters_category_overall() -> None:
    """``category=='overall'`` のみ採用される."""
    rows = [
        {"row": {"model_name": "X", "rank": 1, "rating": 1300, "category": "overall"}},
        {"row": {"model_name": "Y", "rank": 1, "rating": 1100, "category": "coding"}},
        {"row": {"model_name": "Z", "rank": 2, "rating": 1280, "category": "overall"}},
    ]
    entries = _parse_rows(rows)
    ids = [e.identifier for e in entries]
    assert "X" in ids
    assert "Z" in ids
    assert "Y" not in ids


def test_lmarena_parse_rows_sorted_by_rank() -> None:
    """戻り値は rank 昇順."""
    rows = [
        {"row": {"model_name": "B", "rank": 2, "rating": 1280, "category": "overall"}},
        {"row": {"model_name": "A", "rank": 1, "rating": 1300, "category": "overall"}},
        {"row": {"model_name": "C", "rank": 3, "rating": 1260, "category": "overall"}},
    ]
    entries = _parse_rows(rows)
    assert [e.rank for e in entries] == [1, 2, 3]
    assert [e.identifier for e in entries] == ["A", "B", "C"]


def test_lmarena_parse_rows_attaches_payload_fields() -> None:
    """organization / license / vote_count / publish_date が payload に入る."""
    rows = [
        {
            "row": {
                "model_name": "M",
                "organization": "OpenAI",
                "license": "Proprietary",
                "rating": 1300.5,
                "vote_count": 12345,
                "rank": 1,
                "category": "overall",
                "leaderboard_publish_date": "2026-05-01",
            }
        }
    ]
    entries = _parse_rows(rows)
    assert len(entries) == 1
    e = entries[0]
    assert e.score == 1300.5
    assert e.payload["organization"] == "OpenAI"
    assert e.payload["license"] == "Proprietary"
    assert e.payload["leaderboard_publish_date"] == "2026-05-01"
    assert e.payload["vote_count"] == "12345"


def test_lmarena_parse_rows_skips_missing_model_name() -> None:
    """model_name が空の行は skip."""
    rows = [
        {"row": {"model_name": "", "rank": 1, "rating": 1300, "category": "overall"}},
        {"row": {"model_name": "X", "rank": 2, "rating": 1280, "category": "overall"}},
    ]
    entries = _parse_rows(rows)
    assert [e.identifier for e in entries] == ["X"]


def test_lmarena_parse_rows_empty_input_yields_empty() -> None:
    """空入力なら空."""
    assert _parse_rows([]) == []


# ---------------- MTEB ----------------


def test_mteb_parse_paths_counts_files_per_model() -> None:
    """ファイル数を score として保持する."""
    paths = {
        "ModelA": ["results/ModelA/a.json", "results/ModelA/b.json"],
        "ModelB": ["results/ModelB/c.json"],
    }
    entries = _parse_paths(paths)
    by_id = {e.identifier: e for e in entries}
    assert by_id["ModelA"].score == 2.0
    assert by_id["ModelB"].score == 1.0


def test_mteb_parse_paths_sorted_by_count_desc() -> None:
    """ファイル数降順. 同点は名前昇順."""
    paths = {
        "B": ["x.json", "y.json"],
        "A": ["p.json", "q.json"],
        "C": ["z.json"],
    }
    entries = _parse_paths(paths)
    assert [e.identifier for e in entries] == ["A", "B", "C"]
    assert [e.rank for e in entries] == [1, 2, 3]


def test_mteb_parse_paths_skips_non_string_keys() -> None:
    """文字列でないキーは skip (broken JSON 対策)."""
    paths: dict[str, list[str]] = {"A": ["x.json"]}
    entries = _parse_paths(paths)
    assert len(entries) == 1


# ---------------- GitHub Trending ----------------


def test_is_ai_related_picks_up_llm_keyword() -> None:
    """description に "llm" を含むと AI 関連."""
    assert _is_ai_related("foo/bar", "A simple llm wrapper") is True


def test_is_ai_related_picks_up_repo_name_keyword() -> None:
    """リポ名に "agent" を含むと AI 関連."""
    assert _is_ai_related("foo/awesome-agent", "Not described") is True


def test_is_ai_related_rejects_unrelated() -> None:
    """関係ないリポは False."""
    assert _is_ai_related("foo/web-framework", "PHP framework") is False


def test_parse_int_with_commas_handles_thousand_separator() -> None:
    """カンマ区切り数値が int になる."""
    assert _parse_int_with_commas("1,234") == 1234
    assert _parse_int_with_commas("123 stars today") == 123
    assert _parse_int_with_commas("") == 0


def test_parse_trending_extracts_ai_repos_only() -> None:
    """AI フィルタで関係リポだけ抽出される."""
    html = """
    <html><body>
      <article class="Box-row">
        <h2 class="h3"><a href="/foo/llm-tool">llm-tool</a></h2>
        <p>An LLM agent framework</p>
        <span itemprop="programmingLanguage">Python</span>
        <a href="/foo/llm-tool/stargazers">1,234</a>
        <span class="float-sm-right">56 stars today</span>
      </article>
      <article class="Box-row">
        <h2 class="h3"><a href="/bar/web-framework">web-framework</a></h2>
        <p>A PHP web framework</p>
        <span itemprop="programmingLanguage">PHP</span>
        <a href="/bar/web-framework/stargazers">500</a>
        <span class="float-sm-right">10 stars today</span>
      </article>
      <article class="Box-row">
        <h2 class="h3"><a href="/baz/agent-os">agent-os</a></h2>
        <p>OS for AI agents</p>
        <span itemprop="programmingLanguage">Rust</span>
        <a href="/baz/agent-os/stargazers">789</a>
        <span class="float-sm-right">42 stars today</span>
      </article>
    </body></html>
    """
    entries = _parse_trending(html)
    ids = [e.identifier for e in entries]
    assert "foo/llm-tool" in ids
    assert "baz/agent-os" in ids
    assert "bar/web-framework" not in ids


def test_parse_trending_extracts_stars_and_language() -> None:
    """stars / stars_today / language が payload に入る."""
    html = """
    <article class="Box-row">
      <h2 class="h3"><a href="/foo/llm-tool">llm-tool</a></h2>
      <p>An LLM agent</p>
      <span itemprop="programmingLanguage">Python</span>
      <a href="/foo/llm-tool/stargazers">1,234</a>
      <span class="float-sm-right">56 stars today</span>
    </article>
    """
    entries = _parse_trending(html)
    assert len(entries) == 1
    e = entries[0]
    assert e.payload["language"] == "Python"
    assert e.payload["stars"] == "1234"
    assert e.payload["stars_today"] == "56"
    assert e.payload["url"] == "https://github.com/foo/llm-tool"
    assert e.score == 56.0


def test_parse_trending_empty_html_yields_empty() -> None:
    """空 HTML は空."""
    assert _parse_trending("<html></html>") == []


# ---------------- BigCodeBench (Phase 3.5) ----------------


def test_bigcodebench_parse_rows_sorted_by_complete_desc() -> None:
    """complete score 降順で rank が振られる."""
    rows = [
        {"row": {"model": "B", "complete": 30.0, "instruct": 20.0, "type": "🟢"}},
        {"row": {"model": "A", "complete": 50.0, "instruct": 40.0, "type": "🟢"}},
        {"row": {"model": "C", "complete": 10.0, "instruct": 5.0, "type": "🔶"}},
    ]
    entries = _bcb_parse(rows)
    assert [e.identifier for e in entries] == ["A", "B", "C"]
    assert [e.rank for e in entries] == [1, 2, 3]
    assert entries[0].score == 50.0


def test_bigcodebench_parse_rows_skips_null_complete() -> None:
    """complete が null のモデルは順位対象外."""
    rows = [
        {"row": {"model": "X", "complete": None, "instruct": 30.0}},
        {"row": {"model": "Y", "complete": 25.0, "instruct": 15.0}},
    ]
    entries = _bcb_parse(rows)
    assert [e.identifier for e in entries] == ["Y"]


def test_bigcodebench_parse_rows_attaches_payload() -> None:
    """link / instruct / size / date / type が payload に入る."""
    rows = [
        {
            "row": {
                "model": "M",
                "link": "https://hf.co/m",
                "complete": 47.6,
                "instruct": 36.2,
                "size": 6.7,
                "act_param": 6.7,
                "type": "🔶",
                "date": "2024-12-04",
            }
        }
    ]
    entries = _bcb_parse(rows)
    e = entries[0]
    assert e.payload["link"] == "https://hf.co/m"
    assert e.payload["type"] == "🔶"
    assert e.payload["date"] == "2024-12-04"
    assert e.payload["instruct"] == "36.2"
    assert e.payload["size"] == "6.7"


def test_bigcodebench_parse_rows_skips_blank_model_name() -> None:
    """model が空文字の行は skip."""
    rows = [
        {"row": {"model": "  ", "complete": 50.0}},
        {"row": {"model": "Z", "complete": 40.0}},
    ]
    entries = _bcb_parse(rows)
    assert [e.identifier for e in entries] == ["Z"]


# ---------------- AlpacaEval (Phase 3.5) ----------------


_ALPACA_CSV = (
    ",win_rate,standard_error,n_wins,n_wins_base,n_draws,n_total,mode,avg_length,"
    "discrete_win_rate,length_controlled_winrate\n"
    "gpt4_1106_preview,97.7,0.5,783,16,5,804,minimal,2049,97.7,89.9\n"
    "claude-3-opus,95.0,0.7,765,35,1,801,community,1775,95.0,92.0\n"
    "mistral-medium,96.8,0.6,779,25,1,805,minimal,1500,96.8,91.5\n"
    "broken-row-empty-lc,90.0,0.7,700,100,5,805,minimal,1500,90.0,\n"
)


def test_alpaca_parse_csv_sorts_by_length_controlled_winrate_desc() -> None:
    """length_controlled_winrate 降順で rank. LC 欠損行は win_rate にフォールバックして混在."""
    entries = _alpaca_parse(_ALPACA_CSV)
    # 並び:
    #   claude-3-opus (LC=92.0)
    #   mistral-medium (LC=91.5)
    #   broken-row-empty-lc (LC 空 → win_rate 90.0 fallback)
    #   gpt4_1106_preview (LC=89.9)
    ids = [e.identifier for e in entries]
    assert ids[0] == "claude-3-opus"
    assert ids[1] == "mistral-medium"
    assert ids[2] == "broken-row-empty-lc"
    assert ids[3] == "gpt4_1106_preview"


def test_alpaca_parse_csv_falls_back_to_win_rate_when_lc_empty() -> None:
    """LC 列が空欄なら win_rate を score に使う (broken-row-empty-lc は 90.0 として残る)."""
    entries = _alpaca_parse(_ALPACA_CSV)
    found = [e for e in entries if e.identifier == "broken-row-empty-lc"]
    assert len(found) == 1
    assert found[0].score == 90.0


def test_alpaca_parse_csv_attaches_payload() -> None:
    """win_rate / n_total / mode / avg_length が payload."""
    entries = _alpaca_parse(_ALPACA_CSV)
    by_id = {e.identifier: e for e in entries}
    e = by_id["claude-3-opus"]
    assert e.payload["win_rate"] == "95.0"
    assert e.payload["n_total"] == "801"
    assert e.payload["mode"] == "community"
    assert e.payload["avg_length"] == "1775"


def test_alpaca_parse_csv_empty_input_yields_empty() -> None:
    """空入力なら空."""
    assert _alpaca_parse("") == []


def test_alpaca_parse_csv_skips_unparseable_score() -> None:
    """LC も win_rate も空なら skip."""
    csv = ",win_rate,length_controlled_winrate\nvalid,80.0,75.0\nbroken,,\n"
    entries = _alpaca_parse(csv)
    assert [e.identifier for e in entries] == ["valid"]
