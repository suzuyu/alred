# CLI, Configuration, and Resources As-Is

- Status: Reviewed
- Last reviewed: 2026-08-09
- Scope: `alred/cli.py`、`alred/constants.py`、`alred/resources.py`、`alred/utils.py`、`alred.py`

## Evidence

| 種別 | pathまたはcommand | 確認内容 |
|---|---|---|
| Code | `alred/cli.py:build_parser`、`alred/cli.py:main` | parser構築、callback dispatch、例外処理 |
| Code | `alred/constants.py` | device対応、既定path、command、生成filename |
| Code | `alred/utils.py` | 環境変数、YAML、出力path、logging |
| Code | `alred/resources.py` | source／installed／PyInstallerのresource root |
| Packaging | `pyproject.toml`、`alred.spec` | console entry pointとbundle対象resource |
| Test | `tests/test_phase0_cli_baseline.py` | top-level command集合、help、終了code |
| Test | `tests/test_packaging.py` | runtime resourceとNetmikoのbundle |
| User doc | `README.md`、`CONFIG.md` | install、設定優先順位、公開入力形式 |

## Observed behavior

### CLI

- `alred` console scriptと`python alred.py`は、どちらも`alred.cli:main`へ到達する。
- `argparse`のtop-level subparserは必須であり、未知commandは終了code `2`、`--help`は`0`となる。
- `__complete`はparse可能だが通常helpから隠され、`completion bash|zsh`から利用される。
- `main()`は`.env`を読み、password prompt optionを解決してからcallbackを呼ぶ。
- `OperationError`と`ProfileResolutionError`は共通CLI errorへ変換される。それ以外の例外を
  top-levelで包括的に捕捉しない。
- callbackが非zeroの整数を返した場合、その値をprocess終了codeにする。

### 設定とpath

- raw、links、topologyの既定pathは、それぞれ`ALRED_RAW_DIR`、`ALRED_LINKS_DIR`、
  `ALRED_TOPOLOGY_DIR`を優先し、`ALRED_OUTPUT_DIR`と`NW_TOOL_*`へfallbackする。
- log directoryは`ALRED_LOG_DIR`、次に`NW_TOOL_LOG_DIR`、最後に`logs`を使う。
- `hosts.yaml`、`roles.yaml`、`sites.yaml`、`description_rules.yaml`、`show_commands.txt`は、
  option省略時にcurrent working directoryの既定filenameを探索する機能がある。
- `generate-clab`はinventory option省略時に`hosts.lab.yaml`、`hosts.yaml`の順で探索する。
- YAMLは`yaml.safe_load`／`safe_dump`を使用する。汎用loaderはtop-level型を強制しない。

### Resourceとlogging

- source／wheel環境では`alred/`、PyInstaller環境では`sys._MEIPASS/alred`をpackage resource
  rootとする。
- wheelはPython moduleに加えてprofile、capability、schema、Jinja2 template、sample config、
  `README.md`、`CONFIG.md`を含める。
- logger名は`alred`で、consoleは通常`INFO`、`--verbose`時`DEBUG`、file handlerは常に
  `DEBUG`である。logger再構築時は既存handlerをclearする。

## Documented but not verified

- READMEに記載するすべてのinstall方式と全配布先OSで、同じresource探索結果になることは
  今回の解析では実行確認していない。
- 旧`NW_TOOL_*`環境変数の完全な利用実績と廃止時期は確認できていない。

## Inferred behavior

- `alred/cli.py`がparser構築と多くのworkflow実装を同時に所有しているため、公開CLI互換性の
  変更影響が複数用途へ広がりやすい。
- 汎用YAML loaderの型制約は各利用側で補完する前提だが、すべての旧commandで一貫しているとは
  限らない。

## Unknowns and conflicts

- 全subcommandの全option、alias、defaultを固定するmachine-readable catalogはない。
- 共通Error Catalogと、legacy commandが直接送出する`ValueError`／`FileNotFoundError`の対応は
  完了していない。
- 設定fileと環境変数の廃止policyは、schema major versionのようには明文化されていない。

## Recommended design disposition

- top-level command名、既存option alias、入力filename、環境変数fallbackは互換性契約として
  維持する。
- CLI、設定優先順位、resource探索、loggingの責務を共通設計へ統合する。
- 旧commandの例外を一括で隠さず、利用者が修正可能な既知errorだけを段階的にError Catalogへ
  接続する。

## Integration

- Design document: [CLI, Configuration, and Resource Design](../design/common/CLI_CONFIGURATION_AND_RESOURCES_DESIGN.md)
- ADR: Not required
- Integrated date: 2026-08-09
