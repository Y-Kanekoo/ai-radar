"""公式 archive から検証済みの digest で、実行前に uv tool-cache を検査する。"""

import argparse
import hashlib
import shutil
import stat
from pathlib import Path

VERSION = "0.12.19"
ARCH = "x86_64"
DIGESTS = {
    "uv": "242e462a63f5a3c0421d68557006193ecbfb61321cba0fe8542213ac62d92563",
    "uvx": "34a435129d938dca2f22300764aca33e69e038485ee3e27ab62d321fc71e0a6c",
}


def verify_cache(root: Path, *, allow_missing: bool = False) -> None:
    """既存 cache を変更せず検証する。空 cache の許可は setup 前に限定する。"""
    version_dir = root / "uv" / VERSION
    directory = version_dir / ARCH
    marker = version_dir / f"{ARCH}.complete"
    for path in (root, root / "uv", version_dir, directory, marker):
        if path.is_symlink():
            raise ValueError("uv tool-cache contains a symlink")
    if not directory.exists() and not marker.exists() and allow_missing:
        print("uv tool-cache absent: archive checksum required during setup")
        return
    for name, expected in DIGESTS.items():
        path = directory / name
        try:
            mode = path.lstat().st_mode
            if not stat.S_ISREG(mode) or not mode & 0o111:
                raise ValueError("uv tool-cache entry must be a regular executable")
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
        except OSError as exc:
            raise ValueError("uv tool-cache entry is missing or unreadable") from exc
        if actual != expected:
            raise ValueError(f"uv tool-cache {name} checksum mismatch")
    print(f"uv tool-cache {VERSION}/{ARCH}: both executable checksums verified")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool-cache", type=Path, required=True)
    parser.add_argument("--allow-missing", action="store_true")
    parser.add_argument("--check-selected", action="store_true")
    parser.add_argument("--selected-uv")
    parser.add_argument("--selected-uvx")
    args = parser.parse_args()
    try:
        verify_cache(args.tool_cache, allow_missing=args.allow_missing)
        if args.check_selected:
            if args.allow_missing:
                raise ValueError("selected executables require an installed cache")
            for name, selected in (("uv", args.selected_uv), ("uvx", args.selected_uvx)):
                expected = args.tool_cache / "uv" / VERSION / ARCH / name
                if selected != str(expected) or shutil.which(name) != str(expected):
                    raise ValueError(f"selected {name} path differs from verified tool-cache")
            print("action outputs and PATH match verified executables")
    except ValueError as exc:
        print(f"Installer integrity check failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
