"""実CLIの設定ロード/拒否経路。合成disabledソース、通信を拒否して実行."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "provenance_sources.yaml"
# 子プロセスでも通信は禁止。CLIコードと引数処理はそのまま実行する。
OFFLINE_RUNNER = """
import runpy, socket, sys
def forbidden(*args, **kwargs):
    raise AssertionError('Network forbidden in offline CLI test')
socket.socket.connect = forbidden
socket.create_connection = forbidden
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""


def _run(tmp_path: Path, sources: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-c",
            OFFLINE_RUNNER,
            str(ROOT / "scripts" / "run_crawl.py"),
            "--sources-yaml",
            str(sources),
            "--db-path",
            str(tmp_path / "test.db"),
            "--blocked-yaml",
            str(tmp_path / "missing-blocked.yaml"),
        ],
        cwd=ROOT,
        env={
            **{k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")},
            "PYTHONPATH": str(ROOT / "src"),
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_cli_loads_backward_compatible_metadata_without_fetch(tmp_path: Path) -> None:
    result = _run(tmp_path, FIXTURE)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(tmp_path / "test.db") as conn:
        assert conn.execute("SELECT tier FROM sources ORDER BY id").fetchall() == [(2,), (2,), (1,)]
        assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0
        assert conn.execute("SELECT errors_json FROM crawl_runs").fetchone()[0] == "[]"


def test_cli_rejects_review_claim_without_evidence_before_db(tmp_path: Path) -> None:
    data = yaml.safe_load(FIXTURE.read_text())
    del data["sources"][1]["provenance"]["review_evidence_url"]
    sources = tmp_path / "invalid.yaml"
    sources.write_text(yaml.safe_dump(data))
    result = _run(tmp_path, sources)
    assert result.returncode != 0
    assert "provenance" in result.stderr
    assert not (tmp_path / "test.db").exists()
