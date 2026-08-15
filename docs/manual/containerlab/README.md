# Containerlab Manual

商用ネットワークの収集結果から検証用 lab を生成する運用者と、結線表から新規 lab を作成する利用者向けの
manual である。仕様の正本は [Containerlab Workflow Design](../../design/containerlab/CONTAINERLAB_WORKFLOW_DESIGN.md)、
実装状況は[Implementation Status](../../implementation/IMPLEMENTATION_STATUS.md)を参照する。

## 読む順序

| 文書 | 対象 |
|---|---|
| [Preparation](00_PREPARATION.md) | 共通前提、入力、credential、安全確認 |
| [Evidence Package Quick Start](01_QUICK_START.md) | Evidence Package の準備、再現用 lab 生成、起動、config 投入の最短 workflow |
| [Existing Network to Lab](02_EXISTING_NETWORK_TO_LAB.md) | 商用環境の Operation から Evidence Package を作成する詳細手順 |
| [External Config to Lab](02_EXTERNAL_CONFIG_TO_LAB.md) | alred 非依存の show run／config folder から生成 |
| [Direct Collection to Lab](02_DIRECT_COLLECTION_TO_LAB.md) | lab 生成環境から実機を直接収集（商用では非推奨） |
| [結線表から新規 Lab を生成](03_TABLE_DRIVEN_LAB.md) | 実環境を前提とせず、`hosts.txt` と cable CSV から一から設計・生成 |
| [Config Transformation](04_CONFIG_TRANSFORMATION.md) | inventory、管理 IP、NX-OS boot 後投入用 config 変換 |
| [Topology Generation](05_TOPOLOGY_GENERATION.md) | link 正規化、topology 生成、外部 runtime 境界 |
| [NX-OS Boot and Config Push](05_NXOS_BOOT_AND_CONFIG_PUSH.md) | 9000v 起動後の config 投入 |
| [Startup Config Verification](06_STARTUP_CONFIG_VERIFICATION.md) | lab起動後のread-only比較 |
| [Output Guide](07_OUTPUT_GUIDE.md) | 入出力と成果物 |
| [Security and Data Transfer](08_SECURITY_AND_DATA_TRANSFER.md) | 商用raw、credential、隔離環境への移送 |
| [Troubleshooting](09_TROUBLESHOOTING.md) | 不足file、候補link、既知制約 |

## 入力経路の選択

| パターン | 主な入力 | 推奨度 | 使用する手順 |
|---|---|---:|---|
| A | `digital-twin` Evidence Package | 推奨 | [Quick Start](01_QUICK_START.md)／[Existing Network to Lab](02_EXISTING_NETWORK_TO_LAB.md) |
| B | 外部 show run／config folder | 条件付き | [External Config to Lab](02_EXTERNAL_CONFIG_TO_LAB.md) |
| C | lab 生成環境からの直接収集 | 商用では非推奨 | [Direct Collection to Lab](02_DIRECT_COLLECTION_TO_LAB.md) |
| D | `hosts.txt` と cable CSV | 新規 lab 設計用 | [結線表から新規 Lab を生成](03_TABLE_DRIVEN_LAB.md) |

Pattern A は商用環境と隔離 lab の境界を archive と Manifest で固定できるため、既定とする。
Pattern D は商用環境の再現経路ではなく、再現元が存在しない新規 lab を一から設計する独立経路である。

## 実装済みと将来構成

`health-check before --purpose inspection --collect`、既存 `operations/` の再利用、`collect-clab` 互換収集、config 変換、
link 正規化、topology 生成、`init-clab`、起動後確認は現行 CLI として利用できる。Collection Manifest を source とする
`digital-twin`／`ai-analysis` の `protected-preserve` または `pseudonymized` Portable Evidence Package は、
create／inspect／verify／import と Containerlab config 変換に利用できる。明示 acknowledgement 付き `verbatim` も実装済みである。

source option 省略時の最新 current before 自動選択、`--change-id` による Operation 固定、
Canonical Link Evidence 同梱、隔離 lab での link 再生成一致 gate、外部 running config import、
`clab-set-cmds` の Evidence Package 包括経路は実装済みである。任意 phase／attempt の選択、
`support` profile、開示 policy file は将来拡張とする。

`cisco_n9kv` の `startup-config` は既定で出力しない。boot 後は `clab-apply-config` または `push-config-dir` で投入する。
merge／lab profile で明示した `startup-config` は維持されるため、生成 YAML を確認してから deploy する。
