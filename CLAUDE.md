# konfig

Settings management, pluggable secrets and run-scoped logging for Python applications,
published to PyPI as `cognisn-konfig`. This file holds konfig's project configuration and
its own rules; process common to every project (branching, worktrees, commits, sessions)
comes from the developer's global working agreement.

# Project configuration
- Kvasir library: konfig
- Issue tracker: github (issues on Cognisn/konfig); releases, waves and workstreams are tracked in Skuld, project konfig
- GitHub repository: Cognisn/konfig
- Default branch: main
- Release branch style: release/v<version>
- Workstream branches: <kind>/<version>-<aspect>, cut from the release branch, version never prefixed with v (for example fix/0.5.0-body-field)
- Merge to main: merge (the release branch reaches main by pull request with a merge commit)
- Commit scopes: conventional types feat, fix, docs, test, chore, refactor, ci, build, security; scope optional, for example chore(dev)
- Shared modules: pyproject.toml, src/konfig/_version.txt, src/konfig/__init__.py, CHANGELOG.md, .github/workflows/, README.md, docs/configuration-reference.md

Shared modules are edited only by the session a kick-off prompt assigns them to; any other
session records the need as a Skuld decision or question instead.

## Versioning

- The single source of truth is `src/konfig/_version.txt`, read dynamically by hatchling and
  by `konfig.__version__`.
- It is set only by `scripts/bump-version.sh <version>`, on the release branch, by the
  integration session. Workstream branches never bump the version or create stamp commits.
- The script refuses anything but `MAJOR.MINOR.PATCH` with an optional `aN`, `bN` or `rcN`
  suffix. A pre-release stamp (`0.5.0a2`, `0.5.0rc1`) sets `_version.txt` only and leaves
  `CHANGELOG.md` alone, so `[Unreleased]` keeps collecting entries; the final stamp (`0.5.0`)
  rolls `[Unreleased]` into a dated section and opens a fresh `[Unreleased]`.
- `main` carries only final versions; pre-releases (`0.5.0a1`, `0.5.0rc1`) live on release
  branches.

## Changelog

Every user-visible change adds an entry under `## [Unreleased]` in `CHANGELOG.md`, in the same
commit as the change, using the Keep a Changelog headings (Added, Changed, Fixed, and so on).

## Development

```bash
pip install -e ".[dev,aws]"   # aws adds boto3 for the LocalStack suite
pytest
black --check src/ tests/
isort --check-only src/ tests/
mypy src/konfig
```

Lock files `requirements/dev.txt` and `requirements/build.txt` come from the `.in` files beside them; regenerate with the `uv pip compile` commands in the README's Development section.

Supported Python is 3.10 to 3.13; CI runs the suite on Linux, macOS and Windows. Run tests and
commit as separate steps.

## LocalStack integration suite

`tests/integration/test_aws_localstack.py` exercises the AWS Secrets Manager integrations
against LocalStack. It is marked `localstack` and skips itself when boto3 is missing or
LocalStack is unreachable, so it never affects the normal run.

- Plain clone: `docker compose up -d`, then `pytest -m localstack`, then `docker compose down`.
- Elsewhere (for example a per-worktree sandbox that publishes LocalStack on another loopback
  port): set `KONFIG_TEST_LOCALSTACK_URL=http://127.0.0.1:<port>` before `pytest -m localstack`.
  The default is `http://127.0.0.1:4566`.
- A running LocalStack stack is a heavy workload; respect the workstation's concurrency limit.

## Worktree recipe

`dev/worktree.json` (schema 1) and the Compose override template
`dev/worktree-compose.override.yml` let the workstation's worktree setup script create a
sandbox per worktree. Paths in the recipe are relative to the repository root. Every published
port in the template is bound to `127.0.0.1` and uses a `{{PORT_<NAME>}}` placeholder; never a
literal host port. The override needs Docker Compose 2.24.4 or later for `!override`.

## Public-repository hygiene

konfig is public. Never commit, or write into issues, commit messages or docs:

- hostnames, machine names, drive letters, internal paths or other workstation detail (those
  stay in the workstation registry and Skuld);
- credentials, keys or tokens, beyond obvious test values such as LocalStack's `test`;
- client information, commercial or legal discussion;
- details of an unreleased security defect (record those privately until fixed).

Test data is synthetic: `example.com`, `example.org`, `example.net`, the documentation IP
ranges and invented names. Australian English throughout, with no long dashes in prose.
