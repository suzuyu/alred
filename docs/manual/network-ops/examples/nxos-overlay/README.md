# nxos-overlay VNI map examples

このディレクトリは、[NX-OS Overlay Health Check](../../06_NXOS_OVERLAY_HEALTH_CHECK.md)で
使用する Single-site Fabric の説明用成果物です。構成と `after` の running config は
[Containerlab Single-site Fabric sample](../../../containerlab/examples/single-site-fabric/README.md)と
共通です。

## シナリオ

- Network baseline 対象: Spine 2 台、Leaf 4 台、Network Function 2 台
- Overlay Health Check 対象: VTEP Leaf 4 台、EVPN route reflector Spine 2 台
- Overlay 対象外: Network Function 2 台。`Unexecuted Hosts` に理由を記録
- `before`: Single-site Fabric から L2VNI 10100 だけを除いた状態
- `after`: Containerlab sample の現行 Single-site Fabric
- 追加 L2VNI: 10100 / 既存 VRF `tenant1-vpc1` / 既存 L3VNI 19001
- 追加 VLAN: `adc-lfsw0101/0102=100`、`adc-lfsw0103/0104=10`
- Gateway: `172.16.0.254/24`、`fd21:0:0:1::1/64`
- Type-5 確認: connected prefix を広報元 Leaf、EVPN RR、受信対象 Leaf、VRF route の順に確認
- MTU: 9216
- 期待する NVE state: Up

## ファイル対応

| サンプル | 実際の生成先 | 用途 |
|---|---|---|
| [before-checklist.md](./before-checklist.md) | `health/before/checklist.md` | 作業前の機器別Health Check結果 |
| [before-overlay-state.yaml](./before-overlay-state.yaml) | `health/before/overlay-state.yaml` | 作業前の機械処理用正本 |
| [before-vni-map.md](./before-vni-map.md) | `health/before/vni-map.md` | 作業前の人間向け一覧 |
| [before-vni-map.csv](./before-vni-map.csv) | `health/before/vni-map.csv` | 作業前の機器単位一覧 |
| [before-vni_gateway_map.md](./before-vni_gateway_map.md) | `health/before/vni_gateway_map.md` | 作業前の VNI／Gateway 集約表 |
| [before-vni_gateway_map.csv](./before-vni_gateway_map.csv) | `health/before/vni_gateway_map.csv` | 作業前の VNI／Gateway CSV |
| [after-checklist.md](./after-checklist.md) | `health/after/checklist.md` | 作業後の機器別Health Check結果 |
| [after-overlay-state.yaml](./after-overlay-state.yaml) | `health/after/overlay-state.yaml` | 作業後の機械処理用正本 |
| [after-vni-map.md](./after-vni-map.md) | `health/after/vni-map.md` | 作業後の人間向け一覧 |
| [after-vni-map.csv](./after-vni-map.csv) | `health/after/vni-map.csv` | 作業後の機器単位一覧 |
| [after-vni_gateway_map.md](./after-vni_gateway_map.md) | `health/after/vni_gateway_map.md` | 作業後の VNI／Gateway 集約表 |
| [after-vni_gateway_map.csv](./after-vni_gateway_map.csv) | `health/after/vni_gateway_map.csv` | 作業後の VNI／Gateway CSV |
| [vni-map-diff.json](./vni-map-diff.json) | `health/report/vni-map-diff.json` | field単位差分とevidenceの正本 |
| [vni-map-diff.md](./vni-map-diff.md) | `health/report/vni-map-diff.md` | VNI別・同一結果device集約済みの人間向け一覧 |
| [vni-map-diff.csv](./vni-map-diff.csv) | `health/report/vni-map-diff.csv` | field単位差分の表計算・連携用 |

本サンプルの日時、change ID、operational command の結果と hash は、実機へ接続せずに再生成できる
合成 evidence です。running config は共通 Single-site Fabric sample を解析して使用します。
`vni-map-diff.json` の各変更行には、対応する before／after の evidence path を記録しています。

再生成には repository root で次を実行します。

```bash
uv run python scripts/generate_single_site_network_ops_examples.py
```
