# Phase 10 Progress Report

## 1. 目的

Phase 10「9000v適合性・運用受入とhardware文書確認」の実施済み証跡、未検証範囲、次の受入条件を分離して
管理する。機能仕様は[設計書一覧](../design/README.md)、全体の実装状態は
[Implementation Status](./IMPLEMENTATION_STATUS.md)を正本とする。

## 2. 現在の状態

Phase 10は`partial`である。Nexus 9000v C9300v 10.5(4)の受入、Linux x86_64上の
PyInstaller local binary、glibc 2.17および2.34 Docker binaryの検証、hardware 4機種の
文書・golden config確認は実施済みである。Nexus 9000v上のNX-OS 10.4(5)M、glibc 2.28
binary、実配布先OSでの起動は未完了であり、Phase完了とはしない。deviceの動作検証対象は
Nexus 9000vだけとし、hardware 4機種の実機受入はPhase完了条件に含めない。

## 3. 実施済み

### 3.1 Nexus 9000v

2026-07-30から2026-07-31に、C9300v 10.5(4)について次を確認した。

- 10台のread-only baseline / Overlay収集
- vPC VTEP leaf 2台のqualification apply、after `VERIFIED`、逆順rollback
- 通常のplan、approve、apply、after、save、rollback、rollback後検証、save-rollback
- rollback後のhealth、raw running-config、semantic configのbefore一致
- running/startup差分なしとstartup-config復元

2026-08-03にrelease candidate operation `RC-20260803-0.2.0A1`を追加実施した。10台の
beforeは、前回lab試験由来のsyslog警告を確認後、監査理由を記録してRC開始時刻からの
logging windowへ改訂し、`PASS=102`、`WARN=0`、`FAIL=0`、`UNKNOWN=0`となった。
`lfsw0103`、`lfsw0104`へのsaveなしapply後は共通health/compareが`PASS`、Overlayは
Configuration、Operational、Impactすべて`PASS`の`VERIFIED`となった。逆順rollback後も
healthが`PASS`で、対象2台のbefore running-configとのraw一致およびOverlay semantic一致を
確認し、`ROLLED_BACK_AND_VERIFIED`で終了した。startup-configは変更していない。

通常workflowの最終受入operationは、文書上`<save-rollback-operation-id>`として参照する。redacted
support bundleは
`support-bundles/phase8-complete/<save-rollback-operation-id>-all.tar.gz`、
SHA-256は
`0f889624ef8513909b60b1f91aff5db26ab741e51493b328c456f4b106f2dd52`である。

### 3.2 PyInstaller local binary

2026-07-31に次の環境で`alred.spec`から単体binaryを生成した。

| 項目 | 値 |
|---|---|
| build OS | Linux kernel `5.14.0-611.27.1.el9_7.x86_64` |
| architecture | `x86_64` |
| glibc | `2.34` |
| Python | `3.11.15` |
| PyInstaller | `6.21.0` |
| alred | `0.2.0a1` |
| binary SHA-256 | `6883190a80d1f48a2934580c2640491cb4d0088b3d7d3f64bc05356b414de084` |

次を実行し、終了code 0を確認した。

```sh
./dist/alred --version
./dist/alred --help
./dist/alred overlay-change save --help
./dist/alred overlay-change save-rollback --help
./dist/alred operation status --change-id <save-rollback-operation-id>
./dist/alred support-bundle verify \
  --manifest support-bundles/phase8-complete/<save-rollback-operation-id>-all.manifest.yaml
```

最後の2コマンドにより、CLI起動だけでなく、package内schema、operation artifact、
support bundle 232 filesの読み込みと検証まで確認した。

2026-08-03のPR前gateでもPython 3.11.15 / PyInstaller 6.21.0でnative binaryを再buildし、
`alred 0.2.0a1`、top-level help、同梱sample 19 filesの生成を確認した。再build時のSHA-256は
`8e63d4d65526556c18aedb741d8c3e0190cba565c42c263ab47d78c2f8596f02`である。このbinaryは
local glibc 2.34 buildであり、標準release assetは3.4のglibc 2.17 buildを使用する。

### 3.3 glibc 2.34 Docker binary

`scripts/build_binary_glibc234.sh`のrelease用経路を実行し、次を確認した。

| 項目 | 値 |
|---|---|
| base | `quay.io/pypa/manylinux_2_34_x86_64` |
| architecture | `x86_64` |
| Python | `3.11.11` |
| OpenSSL | `3.0.16` |
| PyInstaller | `6.21.0` |
| binary SHA-256 | `e0ea1a1af1654c154d6308bc4114d9ae7072f5831cf810f234fc241bbacfffc4` |

生成後に3.2と同じ6コマンドをホスト上で再実行し、終了code 0、operation読込、
support bundle 232 filesの検証成功を確認した。この証跡はglibc 2.17 / 2.28または別の
実配布先OSでの起動を保証しない。

### 3.4 glibc 2.17 Docker binary

2026-08-03に`scripts/build_release_artifacts_linux_x86_64.sh`の標準release経路を実行し、
manylinux2014環境で次を確認した。

| 項目 | 値 |
|---|---|
| build base | `quay.io/pypa/manylinux2014_x86_64` |
| architecture | `x86_64` |
| build glibc | `2.17` |
| Python | `3.11.11` |
| OpenSSL | `3.0.16` |
| PyInstaller | `6.21.0` |
| artifact | `alred-linux-x86_64-glibc217` |
| binary SHA-256 | `df81f5af9ee0c3ea7daa8c6c410ed47eb7c0b1490099cf9296d533cf68b595f4` |

ホスト上で`--version`、`--help`、SHA-256 checksum検証、同梱データからの
`generate-sample-config`を実行し、すべて終了code 0を確認した。ELFの動的
symbol参照では最大`GLIBC_2.14`であることも確認した。この証跡はbuild環境と
現行buildホストでの検証であり、実際のRHEL 7等の配布先OSでの受入を代替しない。

### 3.5 配布依存の再現性

PyInstallerを`pyproject.toml`の`build` dependency groupと`uv.lock`で固定した。
`packaging/linux/requirements-build.lock`は`uv.lock`から生成し、glibc 2.17、2.28、2.34の
Dockerfileで共用する。これにより、従来Dockerfileの手書き依存から欠落していた
`jsonschema`も配布binary buildへ含める。

固定requirementsの必須package、全Dockerfileからの参照、`alred.spec`のpackage dataと
Netmiko hidden importは`tests/test_packaging.py`で回帰確認する。

## 4. 未検証項目と文書確認結果

### 4.1 対象hardwareの文書確認（完了）

次は対応想定機種だが、device動作検証の対象外とする。実機または仮想labを準備せず、Cisco
公式資料と機種別golden configで静的に確認する。

| Model | 初期対象release | 文書確認 | 実行Level |
|---|---|---|---|
| Nexus 9336C-FX2 | 10.4(5)M | `DOCUMENT_REVIEWED` | `PLAN_ONLY`以下 |
| Nexus 93180YC-FX3 | 10.4(5)M | `DOCUMENT_REVIEWED` | `PLAN_ONLY`以下 |
| Nexus 9348GC-FX3 | 10.4(5)M | `DOCUMENT_REVIEWED` | `PLAN_ONLY`以下 |
| Nexus 9364C-H1 | 10.4(5)M | `DOCUMENT_REVIEWED` | `PLAN_ONLY`以下 |

各model/releaseについて、次を実施した。

1. Release Notesでexact PIDとNX-OS imageの対応を確認する。
2. VXLAN、Interfaces、BGP、IPv6、Scalability、Licenseの公式資料でcapabilityを確認する。
3. 最小構成とdual-stack構成のforward/rollback golden configを機種別に確認する。
4. 9000v/containerlab専用設定がhardware向けconfigへ混入しないことを確認する。
5. 未確認または非対応capabilityを`unknown`または`unsupported`として安全側で記録する。
6. 文書確認が完了してもCapability Registryへ`APPLY_VERIFIED` entryを登録しない。

詳細は[NX-OS Hardware Document Review](../design/network-ops/NXOS_HARDWARE_DOCUMENT_REVIEW.md)と
[`docs/compatibility/nxos/10.4.5M/`](../compatibility/nxos/10.4.5M/README.md)を参照する。

### 4.2 Releaseと配布先

- Nexus 9000v 10.4(5)M
- 10.4(5)Mより新しい未登録release
- glibc 2.28用Docker binaryのbuildと起動
- 実際の配布先OS、権限、temp filesystem、SSH transportでの起動
- WindowsおよびLinux aarch64（配布対象とする場合）

新しいNX-OS releaseは範囲指定で自動昇格せず、exact keyごとに確認する。

## 5. Next Action

1. glibc 2.17 artifactを実配布先OSで受入し、起動、temp filesystem、SSH transportを
   確認する。glibc 2.28 variantが必要になった場合だけ追加buildする。
2. Nexus 9000v 10.4(5)Mのimageとlabが利用可能になった場合にexact releaseの受入を実施する。
3. 実配布先OSが決まった時点でbinary acceptanceを実施し、artifact名、checksum、OS情報を
   本書へ追記する。
