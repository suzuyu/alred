---
name: release-alred
description: Build, verify, and optionally create a Draft GitHub Release for alred. Use when the user asks to prepare release assets, tag a version, create or update a GitHub Release, upload binaries, or publish a release. Default to the Linux x86_64 glibc 2.17 binary and checksum; build glibc 2.28 or 2.34 only when explicitly requested. Separate Draft creation from publication approval.
---

# Release Alred

## Establish authority

Read `../../../AGENTS.md`, `../../../BUILD.md`, `../../../SECURITY.md`, and relevant domain instructions.
Require an explicit version and requested extent. Treat build, tag push, Draft Release creation, asset
upload, and publication as separate actions.

- Build-only authority does not permit Git tag or GitHub changes.
- Draft Release authority permits tag push and Draft creation only when explicitly requested.
- Publishing requires a separate explicit request naming the version.
- Never publish directly from an unmerged feature branch or a dirty worktree.

## Verify version and source

Use the existing tag convention without a `v` prefix. Require the Git tag, `pyproject.toml` version,
binary `--version`, and Release title to match exactly. Treat PEP 440 `a`, `b`, and `rc` versions as
GitHub pre-releases.

Before release work, confirm:

```bash
git status --short
git branch --show-current
git remote -v
git fetch --tags origin
git tag --list <version>
```

Require the release commit to be merged into `main`, unless the user explicitly defines a different
release branch policy. Do not move or overwrite an existing tag or replace an existing asset without
explicit approval.

## Run release gates

Run:

```bash
uv run --frozen pytest -m "not device"
uv run --frozen ruff check .
uv run --frozen python alred.py --help
```

Review implementation status, supported NX-OS scope, unresolved limitations, and release notes. Do not
claim unverified hardware support. Ensure release notes contain no secret, raw device data, placeholder,
or PR-only review section.

## Build standard assets

Build glibc 2.17 by default:

```bash
./scripts/build_release_artifacts_linux_x86_64.sh
./dist/alred-linux-x86_64-glibc217 --version
./dist/alred-linux-x86_64-glibc217 --help
(cd dist && sha256sum --check alred-linux-x86_64-glibc217.sha256)
```

Build another variant only when explicitly requested:

```bash
./scripts/build_release_artifacts_linux_x86_64.sh --variant glibc228
./scripts/build_release_artifacts_linux_x86_64.sh --variant glibc234
./scripts/build_release_artifacts_linux_x86_64.sh --all-variants
```

Do not commit `dist/` or `build/`. Upload only the requested binary and its matching `.sha256` file.

## Create tag and Draft Release

After all gates pass and the user has authorized Draft creation:

```bash
git tag -a <version> -m "Release <version>"
git push origin <version>
gh release create <version> --verify-tag --draft --title "<version>" \
  --notes-file <release-notes> \
  dist/alred-linux-x86_64-glibc217 \
  dist/alred-linux-x86_64-glibc217.sha256
```

Add `--prerelease` for `a`, `b`, or `rc` versions. Use `gh release upload` only for an existing Draft
and only after checking asset names with `gh release view <version> --json assets,isDraft`.

Inspect the Draft, asset names, sizes, and checksums. Report the Draft URL and stop. Do not publish it.

## Publish only after separate approval

When the user explicitly asks to publish the named Draft, re-check the tag, notes, assets, checksum,
pre-release flag, and Draft state. Then run:

```bash
gh release edit <version> --draft=false
```

Do not alter the pre-release flag unless the user approved that classification. After publication,
verify the public Release and asset list and report any download verification not performed.
