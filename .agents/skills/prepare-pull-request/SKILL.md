---
name: prepare-pull-request
description: Prepare and optionally create a safe, reviewable GitHub Pull Request for alred. Use when the user asks to prepare, commit, push, open, update, or check a PR, or asks for branch and PR workflow. Preserve unrelated worktree changes, run domain-appropriate checks, prevent secret and runtime-artifact commits, and create Draft PRs by default.
---

# Prepare Pull Request

## Establish authority

Read `../../../AGENTS.md` and every routed instruction relevant to the diff. Inspect the current branch,
worktree, remote, and requested scope before changing Git state.

Treat these as separate authorities:

- Review or propose: do not create a branch, commit, push, or PR.
- Prepare locally: create or reuse a working branch and commit only when explicitly requested.
- Create PR: push and run `gh pr create` only when explicitly requested.
- Merge or close: require a separate explicit request; never infer it from PR creation.

## Inspect safely

Run:

```bash
git status --short
git branch --show-current
git remote -v
git diff --check
```

Do not stash, discard, reset, rebase, squash, or include unrelated user changes. When the worktree is
dirty, identify the exact files owned by the requested change and stage them explicitly; never use a
broad `git add .` without proving every path belongs to the PR.

Use `<type>/<short-name>` with `feature`, `fix`, `docs`, `refactor`, `test`, or `chore`. Never commit or
push directly to `main`. Use Conventional Commit style for commit and PR titles, for example
`fix(network-ops): preserve incomplete rollback attempts`.

## Validate the change

Always run the narrow relevant tests, then the non-device suite when practical:

```bash
uv run --frozen pytest -m "not device"
uv run --frozen ruff check .
uv run --frozen python alred.py --help
```

For Python code, dependencies, package data, profiles, schemas, Jinja2, `alred.spec`, or packaging
changes, also build and smoke-test the native Python 3.11 binary:

```bash
uv sync --frozen --group dev --group build --python 3.11
uv run --python 3.11 --group build --frozen pyinstaller --clean --noconfirm alred.spec
./dist/alred --version
./dist/alred --help
```

Documentation-only and Agent-instruction-only PRs may skip the local binary build, but must state that
reason. Never run `device` tests in ordinary PR validation. Record lab or hardware evidence separately
without committing raw logs, operations, credentials, or support bundles.

## Review staged content

Before committing, run:

```bash
git diff --cached --check
git diff --cached --stat
git diff --cached
```

Check staged paths for credentials, tokens, private keys, `.env`, raw device logs, `operations/`,
support bundles, and generated binaries. Confirm design, manual, sample, schema, CLI help, and
`IMPLEMENTATION_STATUS.md` synchronization where required by `AGENTS.md`.

## Create a Draft PR

Write the PR body in Japanese using `.github/pull_request_template.md`. Preserve command, option,
path, version, and error-code spelling. Include scope, design impact, checks, binary build, lab/device
validation, compatibility, rollback, security, and remaining work.

After verifying `gh auth status`, create a Draft PR:

```bash
git push -u origin <branch>
gh pr create --draft --base main --title "<type>(<scope>): <summary>" --body-file <body-file>
```

Then inspect without merging:

```bash
gh pr view --web=false
gh pr checks
```

Do not enable auto-merge, merge, close, tag, or create a Release. Report the PR URL, pushed branch,
checks run, skipped checks with reasons, device verification status, and remaining manual actions.
