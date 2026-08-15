# CLI Framework As-Is

- Status: Integrated
- Last reviewed: 2026-08-09
- Scope: `alred/cli.py:build_parser`、`alred/cli.py:main`、`alred.py`

## Evidence

| 種別 | pathまたはcommand | 確認内容 |
|---|---|---|
| Code | `alred/cli.py` | argparse parser、subcommand、callback dispatch |
| Code | `alred.py` | package CLIへのentry point |
| CLI | `uv run python alred.py --help` | helpとtop-level command |
| Test | `tests/test_phase0_cli_baseline.py` | command一覧と終了code |

## Observed behavior

- `build_parser()`はrequired subparserを持つ`argparse.ArgumentParser`を返す。
- `main()`は`.env`を読み、引数をparseし、password prompt optionを解決した後、
  `args.func(args)`を呼ぶ。
- top-level `--help`は標準の`argparse`動作により終了code `0`となる。
- 未知のsubcommandは標準の`argparse`動作により終了code `2`となる。
- command一覧の回帰基準は`tests/fixtures/cli/top_level_commands.txt`で固定する。
- `__complete`は内部commandとしてparserに存在するが、通常helpでは非表示となる。

## Unknowns and conflicts

- 全subcommandの全optionとhelp文言はまだgolden化していない。文言全体のsnapshotは軽微な
  help改善も破壊的変更として扱うため、Phase 0ではtop-level command集合と終了codeを固定する。
- 全subcommandのoption catalogは未整備だが、`health-check`、`overlay-check`、`overlay-change`を含む
  現行top-level command集合はfixtureで固定されている。

## Recommended design disposition

現行`build_parser()`へ段階的にcommandを追加し、既存command名と終了codeを互換性policyに
従って維持する。共通CLI契約は用途別設計の`common`へ統合する。

## Integration

- Design document: [CLI, Configuration, and Resource Design](../design/common/CLI_CONFIGURATION_AND_RESOURCES_DESIGN.md)
- Integrated date: 2026-08-09
