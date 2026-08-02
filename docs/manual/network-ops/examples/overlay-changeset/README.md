# Overlay ChangeSet examples

[Overlay ChangeSet作成ガイド](../../07_OVERLAY_CHANGESET_GUIDE.md)および
[alredによるVNI設定投入](../../08_ALRED_OVERLAY_CHANGE_APPLY.md)で使用する匿名化済みサンプルです。

| ファイル | 実際の用途 |
|---|---|
| [desired-changes.yaml](./desired-changes.yaml) | 外部groupを参照する標準ChangeSet |
| [device-groups.fabric.yaml](./device-groups.fabric.yaml) | vPCペアとserver／storage用途を定義する共通group |
| [desired-changes.minimal.yaml](./desired-changes.minimal.yaml) | 外部groupを参照し、既定値を省略したChangeSet |
| [desired-changes.inline.yaml](./desired-changes.inline.yaml) | 外部ファイルを使わない一ファイル形式 |
| [leaf01.cfg](./leaf01.cfg) | vPCペア1でplanが生成するforward configの代表例 |
| [leaf01-rollback.cfg](./leaf01-rollback.cfg) | vPCペア1でplanが生成するrollback configの代表例 |
| [leaf03.cfg](./leaf03.cfg) | vPCペア2でplanが生成するforward configの代表例 |
| [leaf03-rollback.cfg](./leaf03-rollback.cfg) | vPCペア2でplanが生成するrollback configの代表例 |

基本方針は、Fabricで共通の所属を`device-groups.fabric.yaml`へ分離し、作業ごとに変わるVNI、
VLAN、VRF、SVIと対象groupを`desired-changes.yaml`へ記載することです。単発利用などで
一ファイルにまとめたい場合は`desired-changes.inline.yaml`を使用できます。3つのChangeSet例は
表現方法だけが異なり、同じ対象とconfigへ解決されます。

サンプルは、新規VRF `TENANT-A`、L3VNI 50001、L2VNI 10020を2組のvPC Leafペアへ追加します。
vPCペア内は同一設定とし、用途別groupごとのVLANをChangeSetのgroup overrideで表現します。

| logical group | vPC group | devices | VLAN | configの関係 |
|---|---|---|---:|---|
| `server-leafs` | `vpc-leaf-pair-01` | `leaf01`, `leaf02` | 20 | `leaf01.cfg`と`leaf02.cfg`はhostコメント以外同一 |
| `storage-leafs` | `vpc-leaf-pair-02` | `leaf03`, `leaf04` | 120 | `leaf03.cfg`と`leaf04.cfg`はhostコメント以外同一 |

生成config内のBGP ASはbefore Snapshotから解決されるため、実環境ではサンプルの65000と
異なる場合があります。実行前にforward configとrollback configの両方をレビューしてください。
