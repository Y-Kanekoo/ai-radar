"""ネットワークも実行可能ファイルの起動も不要な tool-cache guard の回帰。"""

import hashlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify_uv_tool_cache.py"
spec = importlib.util.spec_from_file_location("uv_guard", SCRIPT)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "uv/0.12.19/x86_64"
    directory.mkdir(parents=True)
    data = b"fixture executable; never run"
    for name in ("uv", "uvx"):
        (directory / name).write_bytes(data)
        (directory / name).chmod(0o755)
    (directory.parent / "x86_64.complete").touch()
    monkeypatch.setattr(
        guard, "DIGESTS", dict.fromkeys(("uv", "uvx"), hashlib.sha256(data).hexdigest())
    )
    return tmp_path


def test_valid_warm_cache_is_read_only(cache: Path) -> None:
    guard.verify_cache(cache)
    guard.verify_cache(cache, allow_missing=True)


def test_absent_cache_only_allowed_before_setup(tmp_path: Path) -> None:
    guard.verify_cache(tmp_path, allow_missing=True)
    with pytest.raises(ValueError):
        guard.verify_cache(tmp_path)


@pytest.mark.parametrize(
    "case", ["uv", "uvx", "partial", "marker-only", "symlink", "parent-link", "marker-link"]
)
def test_existing_bad_cache_is_never_a_cold_miss(cache: Path, case: str) -> None:
    directory = cache / "uv/0.12.19/x86_64"
    if case in ("uv", "uvx"):
        (directory / case).write_bytes(b"modified")
    elif case in ("partial", "marker-only"):
        (directory / "uv").unlink()
        if case == "marker-only":
            (directory / "uvx").unlink()
            directory.rmdir()
    elif case == "symlink":
        (directory / "uv").unlink()
        (directory / "uv").symlink_to(directory / "uvx")
    elif case == "parent-link":
        directory.rename(directory.with_name("original"))
        directory.symlink_to(directory.with_name("original"))
    else:
        marker = directory.parent / "x86_64.complete"
        marker.unlink()
        marker.symlink_to(directory / "uv")
    with pytest.raises(ValueError):
        guard.verify_cache(cache, allow_missing=True)


def test_cli_rejects_modified_warm_cache_without_execution(tmp_path: Path) -> None:
    directory = tmp_path / "uv/0.12.19/x86_64"
    directory.mkdir(parents=True)
    marker = tmp_path / "executed"
    for name in ("uv", "uvx"):
        (directory / name).write_text(f"#!/bin/sh\ntouch '{marker}'\n")
        (directory / name).chmod(0o755)
    (directory.parent / "x86_64.complete").touch()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--tool-cache", str(tmp_path), "--allow-missing"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1 and "checksum mismatch" in result.stdout
    assert not marker.exists()


def test_action_output_and_path_must_match_verified_cache(
    cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = cache / "uv/0.12.19/x86_64"
    args = [
        str(SCRIPT),
        "--tool-cache",
        str(cache),
        "--check-selected",
        "--selected-uv",
        str(directory / "uv"),
        "--selected-uvx",
        str(directory / "uvx"),
    ]
    monkeypatch.setattr(sys, "argv", args)
    monkeypatch.setenv("PATH", str(directory) + os.pathsep + os.environ["PATH"])
    assert guard.main() == 0
    monkeypatch.setattr(sys, "argv", [*args[:-1], "/different/uvx"])
    assert guard.main() == 1
    monkeypatch.setattr(sys, "argv", args)
    monkeypatch.setenv("PATH", "/nonexistent")
    assert guard.main() == 1
