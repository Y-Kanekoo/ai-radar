"""hosted CI の検証済み binary をコピーし、warm cache の改変拒否を確認する。"""

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GUARD = Path(__file__).resolve().parents[2] / "scripts/verify_uv_tool_cache.py"


def check_warm_cache(source: Path) -> None:
    """fixture のみを書き換え、runner の実 cache は読み取りだけ行う。"""

    def run(root: Path, *, allow_missing: bool = False) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(GUARD), "--tool-cache", str(root)]
        if allow_missing:
            command.append("--allow-missing")
        return subprocess.run(command, capture_output=True, text=True, check=False)

    valid = run(source)
    assert valid.returncode == 0, valid.stdout + valid.stderr
    binaries = source / "uv/0.12.19/x86_64"
    original = {
        name: hashlib.sha256((binaries / name).read_bytes()).hexdigest() for name in ("uv", "uvx")
    }
    with tempfile.TemporaryDirectory(prefix="uv-warm-cache-") as temp:
        directory = Path(temp)
        for case in ("valid", "uv", "uvx", "missing", "symlink"):
            root = directory / case
            target = root / "uv/0.12.19/x86_64"
            target.mkdir(parents=True)
            for name in ("uv", "uvx"):
                shutil.copy2(binaries / name, target / name)
            (target.parent / "x86_64.complete").touch()
            marker = root / "executed"
            if case in ("uv", "uvx"):
                # 実行されると marker を残す偽 binary。検証処理は実行しない。
                (target / case).write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 0\n")
                (target / case).chmod(0o755)
            elif case == "missing":
                (target / "uvx").unlink()
            elif case == "symlink":
                (target / "uv").unlink()
                (target / "uv").symlink_to(binaries / "uv")
            result = run(root, allow_missing=True)
            assert result.returncode == (0 if case == "valid" else 1), result.stdout + result.stderr
            if case in ("uv", "uvx"):
                assert "checksum mismatch" in result.stdout, result.stdout
            assert not marker.exists()
            print(f"warm tool-cache fixture {case}: expected result verified")
    assert original == {
        name: hashlib.sha256((binaries / name).read_bytes()).hexdigest() for name in original
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool-cache", type=Path, required=True)
    check_warm_cache(parser.parse_args().tool_cache)
