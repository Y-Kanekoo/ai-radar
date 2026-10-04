"""固定 installer と runner の組合せを、ネットワークなしで検証する。"""

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION = "astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7"
CHECKSUM = "23bf5552d220e0842b65c862097b2ebaeba0064b74eda5e565e77fd25969d8c8"


def check_installer(job: dict, step: dict) -> None:
    assert job["runs-on"] == "ubuntu-latest", "checksum is for Linux x86_64 GNU"
    assert step["uses"] == ACTION, "review the immutable official release"
    assert step["with"]["version"] == "0.12.19"
    assert step["with"]["checksum"] == CHECKSUM, "official artifact checksum is mandatory"
    assert "RUNNER_TOOL_CACHE" not in step.get("env", {}), "runner reserved env is not a control"
    assert step["with"]["python-version"] in {"3.11", "${{ matrix.python-version }}"}
    assert "manifest-file" not in step["with"]


def test_all_workflows_verify_installer() -> None:
    count = 0
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        workflow = yaml.safe_load(path.read_text())
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                if step.get("uses", "").startswith("astral-sh/setup-uv@"):
                    check_installer(job, step)
                    count += 1
    assert count == 8


@pytest.mark.parametrize("change", ["missing", "wrong", "tag", "tool-cache", "runner"])
def test_installer_policy_rejects_incompatible_configuration(change: str) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = deepcopy(workflow["jobs"]["lint-and-test"])
    step = next(s for s in job["steps"] if s.get("uses", "").startswith("astral-sh/setup-uv@"))
    check_installer(job, step)
    if change == "missing":
        del step["with"]["checksum"]
    elif change == "wrong":
        step["with"]["checksum"] = "0" * 64
    elif change == "tag":
        step["uses"] = "astral-sh/setup-uv@v10"
    elif change == "tool-cache":
        step["env"] = {"RUNNER_TOOL_CACHE": "/tmp/ineffective-override"}
    else:
        job["runs-on"] = "ubuntu-24.04-arm"
    with pytest.raises((AssertionError, KeyError)):
        check_installer(job, step)


def test_cache_consumer_isolated_and_requires_producer() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    producer = workflow["jobs"]["cache-seed"]
    normal = workflow["jobs"]["lint-and-test"]
    consumer = workflow["jobs"]["cache-restore"]
    assert consumer["needs"] == "cache-seed"
    assert producer["needs"] == "lint-and-test"
    assert producer["strategy"]["matrix"] == normal["strategy"]["matrix"]
    assert consumer["strategy"]["matrix"] == producer["strategy"]["matrix"]
    steps = [next(s for s in j["steps"] if s.get("id") == "uv") for j in [producer, consumer]]
    for key in [
        "version",
        "checksum",
        "python-version",
        "cache-dependency-glob",
        "cache-suffix",
        "prune-cache",
    ]:
        assert steps[0]["with"][key] == steps[1]["with"][key]
    assert steps[1]["with"]["save-cache"] is False
    assert steps[0]["with"]["save-cache"] is True
    assert steps[0]["with"]["cache-suffix"] == (
        "acceptance-${{ github.run_id }}-${{ github.run_attempt }}-${{ matrix.python-version }}"
    )
    normal_setup = next(s for s in normal["steps"] if s.get("id") == "uv")
    assert normal_setup["with"]["cache-suffix"] == "installer-v10-${{ matrix.python-version }}"
    seed_commands = "\n".join(s.get("run", "") for s in producer["steps"])
    assert 'test "$CACHE_HIT" = "false"' in seed_commands
    assert "test ! -d .venv" in seed_commands
    assert "uv sync --locked --all-extras --dev" in seed_commands
    assert steps[0]["with"]["prune-cache"] is False
    commands = "\n".join(s.get("run", "") for s in consumer["steps"])
    assert 'test "$CACHE_HIT" = "true"' in commands
    assert "test ! -d .venv" in commands
    assert "uv sync --locked --offline --all-extras --dev" in commands
    assert workflow["permissions"] == {"contents": "read"}


def test_cache_guard_runs_before_and_after_every_setup() -> None:
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        workflow = yaml.safe_load(path.read_text())
        for job in workflow["jobs"].values():
            steps = job.get("steps", [])
            for index, step in enumerate(steps):
                if not step.get("uses", "").startswith("astral-sh/setup-uv@"):
                    continue
                before, after = steps[index - 1], steps[index + 1]
                for guard in [before, after]:
                    assert guard["env"]["UV_INSTALLER_TOOL_CACHE"] == "${{ runner.tool_cache }}"
                    assert "python3 scripts/verify_uv_tool_cache.py" in guard["run"]
                    assert '"$UV_INSTALLER_TOOL_CACHE"' in guard["run"]
                    assert "if" not in guard and "continue-on-error" not in guard
                assert "--allow-missing" in before["run"]
                assert "--allow-missing" not in after["run"]
                assert "--check-selected" in after["run"]
                assert after["env"]["SELECTED_UV"] == "${{ steps.uv.outputs.uv-path }}"
                assert after["env"]["SELECTED_UVX"] == "${{ steps.uv.outputs.uvx-path }}"
                assert step["with"]["activate-environment"] is False
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    steps = ci["jobs"]["lint-and-test"]["steps"]
    assert any("python3 tests/installer/check_warm_cache.py" in s.get("run", "") for s in steps)
