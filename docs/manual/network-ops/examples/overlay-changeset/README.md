# Overlay ChangeSet examples

[Overlay ChangeSet作成ガイド](../../07_OVERLAY_CHANGESET_GUIDE.md)および
[alred による VNI 設定投入](../../08_ALRED_OVERLAY_CHANGE_APPLY.md)で使用する Single-site Fabric
サンプルです。`after` は
[Containerlab Single-site Fabric sample](../../../containerlab/examples/single-site-fabric/README.md)と
同じ状態です。

| ファイル | 実際の用途 |
|---|---|
| [desired-changes.yaml](./desired-changes.yaml) | 外部groupを参照する標準ChangeSet |
| [device-groups.fabric.yaml](./device-groups.fabric.yaml) | 2 組の vPC pair と全 VTEP Leaf を定義する共通 group |
| [desired-changes.minimal.yaml](./desired-changes.minimal.yaml) | 外部 group を参照し、既定値を省略した ChangeSet |
| [desired-changes.inline.yaml](./desired-changes.inline.yaml) | 外部ファイルを使わない一ファイル形式 |
| [adc-lfsw0101.cfg](./adc-lfsw0101.cfg) | vPC pair 1 で plan が生成する forward config の代表例 |
| [adc-lfsw0101-rollback.cfg](./adc-lfsw0101-rollback.cfg) | vPC pair 1 の rollback config 代表例 |
| [adc-lfsw0103.cfg](./adc-lfsw0103.cfg) | vPC pair 2 で plan が生成する forward config の代表例 |
| [adc-lfsw0103-rollback.cfg](./adc-lfsw0103-rollback.cfg) | vPC pair 2 の rollback config 代表例 |

基本方針は、Fabricで共通の所属を`device-groups.fabric.yaml`へ分離し、作業ごとに変わるVNI、
VLAN、VRF、SVIと対象groupを`desired-changes.yaml`へ記載することです。単発利用などで
一ファイルにまとめたい場合は`desired-changes.inline.yaml`を使用できます。3つのChangeSet例は
表現方法だけが異なり、同じ対象とconfigへ解決されます。

サンプルは、既存 VRF `tenant1-vpc1`／L3VNI 19001 に L2VNI 10100 と Gateway SVI を
2 組の vPC Leaf pair へ追加します。vPC pair 内は同一設定とし、pair ごとの VLAN を ChangeSet の
group override で表現します。

| logical group | vPC group | devices | VLAN | configの関係 |
|---|---|---|---:|---|
| `adc-vpc-pair-01` | `adc-vpc-pair-01` | `adc-lfsw0101`, `adc-lfsw0102` | 100 | `adc-lfsw0101.cfg` と pair device の config は host comment 以外同一 |
| `adc-vpc-pair-02` | `adc-vpc-pair-02` | `adc-lfsw0103`, `adc-lfsw0104` | 10 | `adc-lfsw0103.cfg` と pair device の config は host comment 以外同一 |

生成 config 内の BGP AS は before Snapshot から解決されるため、実環境ではサンプルの 65001 と
異なる場合があります。実行前にforward configとrollback configの両方をレビューしてください。

同じ generator が合成 before evidence、現行 Single-site Fabric の after config、ChangeSet を用いて
本ディレクトリと `../nxos-overlay/` を再生成します。

```bash
uv run python scripts/generate_single_site_network_ops_examples.py
```
