# Contributing to alred

## Development workflow

変更前に[AGENTS.md](./AGENTS.md)と対象領域のinstructionを確認する。`main`へ直接pushせず、
`<type>/<short-name>`形式のworking branchからDraft Pull Requestを作成する。

```text
feature/<short-name>
fix/<short-name>
docs/<short-name>
refactor/<short-name>
test/<short-name>
chore/<short-name>
```

commitとPR titleはConventional Commit形式を推奨する。

```text
fix(network-ops): preserve incomplete rollback attempts
docs(containerlab): clarify startup config validation
```

## Local checks

通常の変更では次を実行する。

```bash
uv run --frozen pytest -m "not device"
uv run --frozen ruff check .
uv run --frozen python alred.py --help
```

Python code、dependency、package data、profile、schema、Jinja2、PyInstaller、packagingを変更した
場合はnative binaryも確認する。

```bash
uv sync --frozen --group dev --group build --python 3.11
uv run --python 3.11 --group build --frozen pyinstaller \
  --clean --noconfirm alred.spec
./dist/alred --version
./dist/alred --help
```

通常のCIで`device` markerを実行しない。labまたはhardware検証は、対象と許可を確認して別途実行し、
PRには対象、read-only／mutation、結果、未確認範囲だけを記載する。

## Documentation and compatibility

- 仕様変更では責務を持つ`docs/design/`と実装状況を更新する。
- 重要な判断理由は`docs/adr/`へ記録する。
- 既存CLI、schema、file formatの互換性を、廃止が合意されるまで維持する。
- secret、認証情報、未加工の機器ログ、`operations/`、support bundle、生成binaryをcommitしない。

## Pull Requests

[PR template](./.github/pull_request_template.md)の項目を記載する。AgentがPRを作成する場合も既定は
Draftとし、mergeとReleaseは別の明示承認を必要とする。

セキュリティ問題は公開Issueへ詳細を記載せず、[Security Policy](./SECURITY.md)に従う。
