# nxos-overlay VNI map examples

このディレクトリは、[NX-OS Overlay Health Check](../../06_NXOS_OVERLAY_HEALTH_CHECK.md)で
使用する匿名化済みの説明用成果物です。

## シナリオ

- 対象: `leaf01`、`leaf02`
- 既存L2VNI: 10010
- 既存L3VNI: 50001 / VRF `TENANT-A`
- 追加L2VNI: 10020
- 追加VLAN: `leaf01=20`、`leaf02=120`
- Gateway IPv4: `198.51.100.1/24`
- MTU: 9216
- 期待するNVE state: Up

## ファイル対応

| サンプル | 実際の生成先 | 用途 |
|---|---|---|
| [before-vni-map.md](./before-vni-map.md) | `health/before/vni-map.md` | 作業前の人間向け一覧 |
| [before-vni-map.csv](./before-vni-map.csv) | `health/before/vni-map.csv` | 作業前の機器単位一覧 |
| [after-vni-map.md](./after-vni-map.md) | `health/after/vni-map.md` | 作業後の人間向け一覧 |
| [after-vni-map.csv](./after-vni-map.csv) | `health/after/vni-map.csv` | 作業後の機器単位一覧 |
| [vni-map-diff.md](./vni-map-diff.md) | `health/report/vni-map-diff.md` | field単位差分の人間向け一覧 |
| [vni-map-diff.csv](./vni-map-diff.csv) | `health/report/vni-map-diff.csv` | field単位差分の表計算・連携用 |

実際のoperationでは、これらに加えて`overlay-state.yaml`と、全変更・evidenceを保持する
`vni-map-diff.json`が生成されます。本サンプルの日時、change ID、アドレス、hostnameは
ドキュメント用です。
