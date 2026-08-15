# ADR-0006: device groupを外部化し階層参照を許可する

- Status: Accepted
- Date: 2026-08-02

## Context

VNI変更ごとにvPC LeafのhostnameをChangeSetへ繰り返し記載すると、Fabricで安定している所属情報と
作業ごとに変わるtargetが混在する。vPCペア、server Leaf、storage Leafを別々に管理したい一方、
外部ファイルを実行時に再読込するとplan後の変更でapply対象が変わる危険がある。

既存`OverlayChangeSet.spec.device_groups`はdeviceの直接列挙だけを持ち、ChangeSet単体で完結するが、
共通groupの重複と更新漏れが発生しやすい。

## Decision

宣言済みChangeSetの標準形式では、ChangeSetから`device_groups_ref`で外部
`OverlayDeviceGroups`を参照する。外部documentではdeviceの直接memberに加え、同じdocument内の
子groupを参照できる。vPCペアを最小group、server／storageなどを上位groupとして構成する。

planは外部documentを検証・再帰展開し、sourceとcanonical hash、固定copy、機器単位の
resolved targetをoperationへ保存する。apply以降は元の外部ファイルを再読込しない。

既存inline `spec.device_groups`は後方互換性とdiscovered ChangeSetの自己完結性のため維持する。
inlineとexternal refは相互排他とする。

## Consequences

- Fabric所属情報とVNI変更内容を分離し、複数ChangeSetでgroupを再利用できる。
- vPCペア、用途、全VTEPという階層を重複なく表現できる。
- 外部入力、参照path、循環、最大階層、重複経路、override競合のvalidationが必要になる。
- operationへ外部入力と展開結果を固定するため、planとapplyの再現性を維持できる。
- 現行schema、renderer、plan、approval hash、sample、テストの拡張が必要になる。

## References

- [Overlay Change Management Design](../design/network-ops/OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)
- [Schema and Compatibility Policy](../design/common/SCHEMA_AND_COMPATIBILITY_POLICY.md)
- [Overlay ChangeSet作成ガイド](../manual/network-ops/07_OVERLAY_CHANGESET_GUIDE.md)
