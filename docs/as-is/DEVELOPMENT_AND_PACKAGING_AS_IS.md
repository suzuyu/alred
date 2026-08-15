# Development and Packaging As-Is

## 1. 文書の位置づけ

- Status: Reviewed
- Last reviewed: 2026-08-09
- 対象: Python package、dependency lock、test/lint、PyInstaller、Linux binary、release artifact
- 根拠: `pyproject.toml`、`uv.lock`、`alred.spec`、`.github/workflows/quality.yml`、`packaging/`、
  `scripts/`、`tests/test_packaging.py`、`BUILD.md`、`CONTRIBUTING.md`
- 統合先:
  [Development, Testing, and Packaging Design](../design/development/DEVELOPMENT_TESTING_AND_PACKAGING_DESIGN.md)

本書はrepository内で確認できる現行状態を記録する。実際の各Linux distributionでのbinary互換性やGitHub
Release公開結果を保証するものではない。

## 2. Python project

- package名とconsole scriptは`alred`である。
- Python要件は`>=3.11`で、classifierとCIは3.11／3.12を対象とする。
- build backendはHatchlingである。
- runtime dependencyはJinja2、jsonschema、netmiko、PyYAML、python-dotenvである。
- dev groupはpytestとRuff、build groupはPyInstallerを含む。
- `uv.lock`をdependencyの再現可能な正本として使い、CIは`--frozen`で同期・実行する。

versionは原則installed distribution metadataから取得し、source tree実行時は`pyproject.toml`へfallbackする。
どちらもない場合は`0.0.0`となる。

## 3. Package data

wheelは`alred` packageと次のdataを含める設定である。

- health profile YAML
- capability YAML
- JSON schema
- Jinja2 template
- sample config
- repository rootの`README.md`と`CONFIG.md`

PyInstallerは`collect_data_files("alred")`でpackage dataを収集し、netmikoのdynamic importに対応するため
`collect_submodules("netmiko")`をhidden importへ追加する。`pyproject.toml`もbinaryへ含める。

## 4. Testとquality gate

pytest markerは`unit`、`integration`、`device`で、strict markerを有効にしている。通常CIはdeviceを除外する。

```text
uv run --frozen pytest -m "not device"
uv run --frozen ruff check .
uv run --frozen python alred.py --help
```

Ruffは現在、実行時障害につながる`E9`、`F63`、`F7`、`F82`だけを有効にするbaselineである。CIはPython
3.11と3.12をmatrix実行する。

別jobでPython 3.11のnative PyInstaller binaryをbuildし、`--version`、`--help`、sample config生成をsmoke
testする。Docker/glibc各variantのbuildは通常CIでは実行していない。

## 5. Linux binary

`alred.spec`はone-file console binary `dist/alred`を生成する。LinuxのDocker buildは次の3variantを持つ。

| variant | base | 扱い |
|---|---|---|
| `glibc217` | manylinux2014 x86_64 | 標準Releaseの既定 |
| `glibc228` | manylinux_2_28 x86_64 | 明示指定時だけ |
| `glibc234` | manylinux_2_34 x86_64 | 明示指定時だけ |

3variantは同じ`packaging/linux/requirements-build.lock`をinstallする。Docker image内でOpenSSLとshared
library付きPython 3.11をbuildし、repositoryをmountしてPyInstallerを実行する。

build scriptは`build/`と`dist/alred`／`dist/alred.exe`を作業用outputとして置換する。一方、variant名付きの
既存release artifactは削除しない。生成binaryとbuild directoryはcommit対象ではない。

## 6. Release artifact

helperの既定flowは`glibc217`をbuildし、binary smoke test後に次を作る。

```text
dist/alred-linux-x86_64-glibc217
dist/alred-linux-x86_64-glibc217.sha256
```

`--variant`または`--all-variants`で2.28／2.34を追加できる。checksumは`sha256sum`で生成する。
tagは`pyproject.toml`のPEP 440 versionと一致し、先頭`v`を付けない運用が文書化されている。

Releaseの作成・公開、tag、pushはrepository内のbuild処理とは別の外部操作であり、明示的な依頼を必要とする。

## 7. 未確認・制約

- wheel/sdist buildとinstall smokeは通常quality workflowにない。
- Docker glibc variantは通常CIでbuildされず、定期的な互換性検証は確認できない。
- READMEに例示された非x86_64／Windows artifactを継続生成するCIはない。
- binaryのsoftware bill of materials、署名、provenance attestationはない。
- 実配布先OSでのSSH、NX-API、template、schema resource読込はrelease前の別検証が必要である。
