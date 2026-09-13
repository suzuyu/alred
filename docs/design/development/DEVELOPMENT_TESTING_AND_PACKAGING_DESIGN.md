# Development, Testing, and Packaging Design

## 1. 目的

本書はalredの開発環境、dependency、quality gate、package data、binary build、release artifactの設計を
定める。手順の詳細は[CONTRIBUTING.md](../../../CONTRIBUTING.md)と[BUILD.md](../../../BUILD.md)、現行構成の
観測記録は[Development and Packaging As-Is](../../as-is/DEVELOPMENT_AND_PACKAGING_AS_IS.md)を参照する。

GitHub上のbranch、PR、Release操作は本書のbuild責務に含めない。実行する場合はrepository instructionと該当
Skillに従い、外部変更ごとに明示的な依頼を必要とする。

## 2. Supported development environment

- projectの最小Pythonは3.11とする。
- 通常CIはPython 3.11と3.12を対象とする。
- dependency解決は`uv.lock`を正本とし、再現確認では`uv --frozen`を使用する。
- runtime、development、binary build dependencyをgroupで分離する。
- project metadata、version、console entry pointは`pyproject.toml`を正本とする。

source tree、wheel install、PyInstaller binaryの`alred --version`は同じproject versionを返さなければならない。
Release tagもPEP 440 versionと一致させる。

## 3. Quality gate

通常の変更では次を必須gateとする。

```text
uv run --frozen pytest -m "not device"
uv run --frozen ruff check .
uv run --frozen python alred.py --help
```

testは次の層に分ける。

| marker／種類 | 外部接続 | 通常CI |
|---|---:|---:|
| unit | なし | yes |
| integration | なし。複数component／CLIを結合 | yes |
| device | labまたは実機 | no |

device testは対象、credential、read-only／mutation、実行許可を確認した場合だけ実行する。fixtureに実機の未加工
出力やsecretを含めない。

Ruff ruleの拡張は既存codeへの影響を評価し、関連修正と同じ変更でgateを満たす。大量の無関係なformat変更を
混在させない。

## 4. Documentation and compatibility gate

CLI、schema、default path、artifact、NX-OS command、実装状況を変える場合は、同じ変更で責務を持つ設計書、
sample、help、testを更新する。Markdown link、design index、実装状況はdocumentation testで検証する。

設計と実装が不一致の場合は暗黙にどちらかへ合わせず、差分と影響を記録する。既存機能の観測結果は`docs/as-is/`
で正式仕様、推測、未確認事項から分離する。

## 5. Python distribution

wheelには実行に必要なPython moduleと次のpackage dataを必ず含める。

- health profileとcapability registry
- JSON schema
- Jinja2 template
- sample config
- 利用時に参照するREADME／CONFIG
- NTC Templatesを直接利用する場合のTextFSM templateと第三者ライセンス表示

resourceを追加・移動した場合はsource treeだけでなく、wheel installとPyInstaller binaryからも解決できるtestを
追加する。Hatchのinclude設定とPyInstaller specを同じ変更で更新する。

Route Diff の配布確認には [smoke runner](../../../scripts/smoke_route_diff.py) を使う。
source / install 済み wheel / native binary の起動 command を渡し、同じ合成 transcript から
standalone と Health の before / after を生成する。5 比較方式の期待件数、追加 profile、
Health 判定、全 report file の hash を照合する。実機接続は行わず、新規出力 directory に証跡を保存する。
検証 binary の build・実行は version 採番や Release 作成・公開とは区別する。

## 6. PyInstaller binary

PyInstallerはPython 3.11でone-file console binaryを作る。netmikoのdynamic importと全package dataをbundleし、
少なくとも次をsmoke testする。

- `--version`
- `--help`
- package dataを使うsample config生成
- schema、health profile、capability、templateのresource解決
- NTC Templatesを利用するparserのtemplate data解決
- `ntc_templates` と `textfsm` の distribution metadata 解決、および NTC Templates parser の実行

Python code、dependency、package data、schema、profile、template、spec、packagingを変更した場合はnative binary
testを行う。Docker buildが必要な変更では対象variantも確認する。

外部parser packageを直接importする場合は推移依存に依存せずruntime dependencyへ明示する。PyInstallerへ
package dataを同梱する場合は、対応する著作権表示とlicenseを第三者ライセンス一覧へ記録する。package が
`importlib.metadata` で version を取得する場合は、module と data に加えて distribution metadata も同梱する。

## 7. Linux compatibility variants

標準Release artifactはLinux x86_64の`glibc217` binaryとSHA-256 checksumとする。互換範囲を狭める
`glibc228`／`glibc234`は、配布先要件が明示された場合だけ追加する。

| variant | 最小glibcの意図 | Release default |
|---|---:|---:|
| `glibc217` | 2.17 | yes |
| `glibc228` | 2.28 | no |
| `glibc234` | 2.34 | no |

全variantは同一の固定requirementsを使用し、runtime dependencyとPyInstaller versionを`uv.lock`と同期する。
Dockerfile、lock export、build helperの整合はoffline testで検証する。

## 8. Artifactとsecurity

release artifact名にはOS、architecture、compatibility variantを含め、同名の`.sha256`を添付する。checksumは
公開前とdownload後に検証する。

次をrepositoryへcommitしない。

- `build/`、`dist/`、生成binary
- credential、secret、未加工の実機log
- `operations/`、support bundle

build中にmountしたrepositoryへ作業fileを書き戻すscriptは、対象を`build/`、`dist/alred`、`dist/alred.exe`へ
限定する。variant名付きartifactを暗黙に削除しない。

## 9. Release boundary

build完了はRelease公開を意味しない。標準flowは次を分離する。

1. test、lint、CLI smoke
2. binary buildとresource smoke
3. artifact名付けとchecksum生成
4. tag／Draft Release作成
5. asset、checksum、release noteの人手確認
6. 明示承認後の公開

alpha、beta、release candidateはpre-releaseとする。対応OS、architecture、glibc、既知の制約、checksumをrelease
noteへ記載する。

## 10. 現行との差分と将来拡張

- wheel／sdist install smokeを通常CIへ追加する余地がある。
- native binary smokeは`--version`、`--help`、sample config生成までであり、schema、health profile、
  capability、templateを個別に解決する包括的smokeは未実装である。Route Diff に限り、上記 runner で
  schema / profile / template を使う standalone / Health の一連の処理を検証できる。
- glibc Docker buildの定期検証は未実装である。
- SBOM、artifact署名、provenance attestationは未実装である。
- Linux x86_64以外は継続的なbuild pipelineがないため、正式な配布対象として扱う前にmatrixとtestを定義する。
