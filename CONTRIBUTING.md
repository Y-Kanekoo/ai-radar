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
