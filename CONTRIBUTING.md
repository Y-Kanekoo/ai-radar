# Contributing to ai-radar

Thank you for your interest!

## Adding a new RSS source

1. **Verify** the feed URL is publicly accessible (no auth required) by
   `curl -I <feed-url>` and confirm 200 status.
2. **Verify ToS** permits aggregation in the form of *title + ≤100 char
   snippet + link-back*. Sites that explicitly forbid re-distribution
   (e.g. Jiji Press) must NOT be added.
3. Add an entry to `config/sources.yaml` following the existing schema.
4. Open a PR. Include in the PR description:
   - The feed URL you verified
   - The ToS URL and a quoted excerpt covering aggregation
   - Estimated post frequency

## Reporting copyright concerns

If you are a content author or publisher and would like content excluded:

- Open an issue: <https://github.com/Y-Kanekoo/ai-radar/issues>
- Tag with `takedown`
- We aim to respond and act within 7 days

## Development setup

```bash
git clone https://github.com/Y-Kanekoo/ai-radar.git
cd ai-radar
uv sync --locked --all-extras --dev
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
```

## Branch policy

- `main` is protected. Direct pushes are not allowed.
- Create `feature/phase-N-<short-name>` branches per phase.
- One PR per phase, with the phase acceptance criteria checklist filled in.
- Squash merge with commit message format `[type] Phase N: <summary>`
  where type ∈ {feat, fix, refactor, docs, test, chore, ops}.

## Coding standards

- Python 3.11+ syntax (no compat with 3.10)
- All comments in Japanese, but identifiers (variable/function/class names) in English
- Type hints required for public functions; no `Any` allowed
- ruff (E, F, I, B, UP, N, SIM, RUF) must pass with line length 100
- pytest coverage target: ≥80%

## Dependency updates

`uv.lock` is the canonical project dependency graph. Use uv 0.12.19 (the
workflow version) and the existing Python 3.11/3.12 CI matrix. Workflows record
actual uv and Python versions; Python patch versions are not pinned.

Normal development and CI use `uv sync --locked` and `uv run --locked`:
manifest/lock mismatch, a missing lock, or an invalid lock must stop execution.
`--frozen` skips freshness validation and is not a substitute for this gate.
For an intentional dependency change, update the manifest if needed, run
`uv lock --upgrade-package <name>`, and review and commit the resulting lock.
Avoid blanket upgrades in unrelated changes. Cache keys include both files;
a restored cache never replaces lock validation.

Dependabot uses the native `uv` ecosystem to update the lock weekly. Review
normal updates individually, handle major upgrades in separate PRs, and
prioritize security fixes. Merge only after CI and review; no automatic merge
or new publishing permissions are introduced. Dependency updates do not promise
compatibility merely because a newer version exists. The current lock was also
read successfully with uv 0.11.0, matching GitHub's documented supported uv
series; this does not prove that a future hosted Dependabot PR will succeed.
Confirm the first generated PR and its manifest/lock diff operationally.

References: [uv Dependabot integration](https://docs.astral.sh/uv/guides/integration/dependabot/),
[lock freshness semantics](https://docs.astral.sh/uv/concepts/projects/sync/), and
[GitHub supported ecosystems](https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories).

### Installer integrity and cache acceptance (Issue #17)

All setup-uv steps use the official v10.2.0 release commit
`c18668ad3cf93ea998bef934396af7bb5c839dc7` (Node 24). This is supported by
our GitHub-hosted Ubuntu runners; changing to a self-hosted runner requires
checking its Node 24 support first. The explicit SHA-256 is for **uv 0.12.19,
Linux x86_64 GNU only**:
`23bf5552d220e0842b65c862097b2ebaeba0064b74eda5e565e77fd25969d8c8`.
It was checked against both the [official checksum file](https://github.com/astral-sh/uv/releases/download/0.12.19/uv-x86_64-unknown-linux-gnu.tar.gz.sha256)
and downloaded archive on 2026-10-04. Other platforms require separately
verified checksums. Workflow policy tests reject an absent/changed checksum,
a mutable action tag, or an incompatible runner.

The action validates downloads before extraction, but a warm tool-cache hit
bypasses its checksum path. GitHub's [Node action handler](https://github.com/actions/runner/blob/v2.337.0/src/Runner.Worker/Handlers/NodeScriptActionHandler.cs)
sets reserved runner variables from runtime context: the previous step-level
`RUNNER_TOOL_CACHE` override did **not** isolate that cache. PR #18's first cold
run is download evidence only; it did not prove warm-cache integrity.

Every setup is now bracketed by `scripts/verify_uv_tool_cache.py`, invoked with
standard Python and the actual `runner.tool_cache` context. Before setup, a
completely absent target is allowed; existing `uv` and `uvx` must match these
SHA-256 values derived from the verified official archive:

- `uv`: `242e462a63f5a3c0421d68557006193ecbfb61321cba0fe8542213ac62d92563`
- `uvx`: `34a435129d938dca2f22300764aca33e69e038485ee3e27ab62d321fc71e0a6c`

Partial entries, executable/parent/marker symlinks, and modified binaries fail
before setup. The guard never executes, removes or repairs cached binaries.
After setup, both binaries must exist and match; action output paths and PATH
resolution must identify those same verified binaries. Explicit Python inputs
and `activate-environment: false` avoid uv execution within setup before this
second guard. The pinned vendor has `post-if: success()`, so a failed guard
also prevents post-save/pruning. This protects this workflow's execution order;
it does not defend against a concurrent process with the same permissions
changing files after verification. No reserved environment override is used.

`tests/installer/check_warm_cache.py` runs in hosted CI after verification. It
copies real verified binaries into temporary, populated caches with completion
markers, then exercises correct, modified uv/uvx, missing and symlink cases via
the guard CLI. Modified scripts would leave a sentinel if executed; rejection
must leave it absent. The actual runner tool-cache is only read and remains
unchanged. Offline unit tests also cover missing entries, parent/marker links,
and action-output/PATH mismatch. The former test requiring the ineffective
reserved-variable override was replaced by guard-order and override-rejection
contracts; retaining that assertion would preserve the reported bug.

The vendor [checksum implementation](https://github.com/astral-sh/setup-uv/blob/c18668ad3cf93ea998bef934396af7bb5c839dc7/src/download/checksum/checksum.ts)
and [download order](https://github.com/astral-sh/setup-uv/blob/c18668ad3cf93ea998bef934396af7bb5c839dc7/src/download/download-version.ts)
were separately exercised with the shipped Node bundle and loopback fixtures:
correct archive accepted; wrong/missing checksum and altered archive rejected.
That direct-process experiment is not a simulation of GitHub's Node handler.

CI records the producer's `cache-hit` and primary `cache-key` without skipping
locked sync on a miss. Its stable, Python-specific suffix permits reuse across
runs; do not add a permanent run-ID suffix that forces all builds cold. CI keeps
unpruned dependency artifacts so a fresh consumer job, after the producer's
post-save, must report a hit and install with `uv sync --locked --offline` into
an absent `.venv`. Python installation itself is outside that offline command.
The consumer does not save caches. Scheduled/publishing workflows retain cache
pruning and their existing triggers, permissions and notification behavior.

Cache acceptance is distinct from installer acceptance. PR #18 run
`37210130791` already demonstrated producer miss → save → exact-key hit →
offline sync for both Python versions. Preserve that evidence at its revision.
For a later revision/retry, record whether the producer is warm or cold, compare
producer/consumer primary keys, and require consumer hit plus offline sync.
A stable key may correctly restore an earlier run; do not call that a new cold
round trip. Testing an additional cold cycle would require a separately scoped
fixture key and independent evidence, not disabling normal cache reuse. A producer's cold-install success, or a generic
"cache saved" message alongside an HTTP error, is not restoration proof.
If the cache service is unavailable, normal producer checks still run, while
the consumer gate fails; report that failure rather than claiming Issue #17
resolved. Do not dispatch notification workflows to exercise this test.
See the vendor [cache contract](https://github.com/astral-sh/setup-uv/blob/c18668ad3cf93ea998bef934396af7bb5c839dc7/docs/caching.md).

When updating uv or setup-uv, review the immutable official release, verify the
new platform-specific archive digest, update the workflow pins and policy tests
together, and repeat cold good/bad installer and cache checks. Dependabot PR #4
proposed only the older v7 tag in four files; this change supersedes that proposal
on current main with six production/CI workflows and the integrity acceptance
criteria. PR #4 is not edited or merged by this work. Hosted Dependabot PR
creation and real notification delivery remain separate operational checks.
