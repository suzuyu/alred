# nxos-overlay VNI map examples

このディレクトリは、[NX-OS Overlay Health Check](../../06_NXOS_OVERLAY_HEALTH_CHECK.md)で
使用する匿名化済みの説明用成果物です。

## シナリオ

- Health Check対象: `leaf01`、`leaf02`、EVPN route reflectorの`spine01`
- VNI map対象: VTEPである`leaf01`、`leaf02`
- 既存L2VNI: 10010
- 既存L3VNI: 50001 / VRF `TENANT-A`
- 追加VRF / L3VNI: `TENANT-B` / 50002
- 追加L2VNI: 10020 / VRF `TENANT-B`
- 追加VLAN: `leaf01=20`、`leaf02=120`
- Gateway IPv4: `198.51.100.1/24`
- Type-5 確認: connected prefix を広報元 Leaf、`spine01` の EVPN RR、全受信対象 Leaf、
  VRF route の順に確認
- MTU: 9216
- 期待するNVE state: Up

## ファイル対応

| サンプル | 実際の生成先 | 用途 |
|---|---|---|
| [before-checklist.md](./before-checklist.md) | `health/before/checklist.md` | 作業前の機器別Health Check結果 |
| [before-overlay-state.yaml](./before-overlay-state.yaml) | `health/before/overlay-state.yaml` | 作業前の機械処理用正本 |
| [before-vni-map.md](./before-vni-map.md) | `health/before/vni-map.md` | 作業前の人間向け一覧 |
| [before-vni-map.csv](./before-vni-map.csv) | `health/before/vni-map.csv` | 作業前の機器単位一覧 |
| [after-checklist.md](./after-checklist.md) | `health/after/checklist.md` | 作業後の機器別Health Check結果 |
| [after-overlay-state.yaml](./after-overlay-state.yaml) | `health/after/overlay-state.yaml` | 作業後の機械処理用正本 |
| [after-vni-map.md](./after-vni-map.md) | `health/after/vni-map.md` | 作業後の人間向け一覧 |
| [after-vni-map.csv](./after-vni-map.csv) | `health/after/vni-map.csv` | 作業後の機器単位一覧 |
| [vni-map-diff.json](./vni-map-diff.json) | `health/report/vni-map-diff.json` | field単位差分とevidenceの正本 |
| [vni-map-diff.md](./vni-map-diff.md) | `health/report/vni-map-diff.md` | VNI別・同一結果device集約済みの人間向け一覧 |
| [vni-map-diff.csv](./vni-map-diff.csv) | `health/report/vni-map-diff.csv` | field単位差分の表計算・連携用 |

本サンプルの日時、change ID、アドレス、hostname、hashはドキュメント用です。
`vni-map-diff.json`では代表的なconfig・operational fieldにevidenceを掲載し、その他の変更行は
読みやすさのため`evidence_before` / `evidence_after`を空配列にしています。実際の成果物では、
対応するbefore / afterの証跡が各変更行に記録されます。
