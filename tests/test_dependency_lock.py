"""依存 lock の実行契約を、外部接続なしの fixture で検証する。"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_workflows_require_project_lock() -> None:
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        workflow = yaml.safe_load(path.read_text())
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                if step.get("uses", "").startswith("astral-sh/setup-uv@"):
                    assert step["with"]["version"] == "0.12.19", path
                    assert set(step["with"]["cache-dependency-glob"].split()) == {
                        "pyproject.toml",
                        "uv.lock",
                    }, path
                for line in step.get("run", "").splitlines():
                    if "uv sync " in line or "uv run " in line:
                        assert "--locked" in line, (path, line)
        if path.name == "pypi.yml":
            commands = "\n".join(s.get("run", "") for s in workflow["jobs"]["build"]["steps"])
            assert commands.index("uv lock --check") < commands.index("uv build")
    config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    assert config["updates"][0]["package-ecosystem"] == "uv"


@pytest.mark.parametrize("invalid", ["stale", "corrupt", "missing"])
def test_locked_run_rejects_invalid_lock_before_execution(tmp_path: Path, invalid: str) -> None:
    uv = shutil.which("uv")
    assert uv is not None, "uv is required to verify the actual lock contract"
    manifest = tmp_path / "pyproject.toml"
    manifest.write_text(
        '[project]\nname="lock-fixture"\nversion="0.1.0"\nrequires-python=">=3.11"\ndependencies=[]\n'
    )
    env = dict(os.environ, UV_CACHE_DIR=str(tmp_path / "cache"), UV_PYTHON_DOWNLOADS="never")

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [uv, *args, "--offline", "--python", sys.executable],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    assert run("lock").returncode == 0
    lock = tmp_path / "uv.lock"
    original = lock.read_bytes()
    command = [
        uv,
        "run",
        "--locked",
        "--offline",
        "--python",
        sys.executable,
        "python",
        "-c",
        "from pathlib import Path; Path('sentinel').touch()",
    ]
    valid = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert valid.returncode == 0, valid.stderr
    assert lock.read_bytes() == original
    (tmp_path / "sentinel").unlink()
    if invalid == "stale":
        manifest.write_text(manifest.read_text().replace('version="0.1.0"', 'version="0.2.0"'))
    elif invalid == "corrupt":
        lock.write_text("not valid toml [")
    else:
        lock.unlink()
    before = lock.read_bytes() if lock.exists() else None
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "lock" in result.stderr.lower()
    assert "cache" not in result.stderr.lower()
    assert not (tmp_path / "sentinel").exists()
    assert (lock.read_bytes() if lock.exists() else None) == before
