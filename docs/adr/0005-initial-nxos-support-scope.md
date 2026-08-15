# ADR-0005: 初期NX-OS対応範囲と検証Levelを限定する

- Status: Accepted
- Date: 2026-07-26

## Context

NX-OSはreleaseとmodelによりshow出力、VXLAN/EVPN構文、capabilityが異なる。単にバージョン番号が
新しいことを根拠に設定投入を許可すると、parser誤認や非対応構文を実機へ送信する危険がある。

## Decision

初期対応下限をNX-OS `10.4(5)M`とし、対象modelをNexus 9000v、Nexus 9336C-FX2、
Nexus 93180YC-FX3、Nexus 9348GC-FX3、Nexus 9364C-H1とする。10.4(5)M以降は
対応候補とするが、release/model別のfixtureとcapability確認が完了したLevelだけを許可する。

処理Levelは`OBSERVE_ONLY`、`PLAN_ONLY`、`APPLY_VERIFIED`に分け、未検証releaseを
バージョン比較だけで`APPLY_VERIFIED`にしない。Multi-Siteは初期対象外とする。

## Consequences

- 未検証の新releaseへの危険な設定投入を防止できる。
- release/modelごとのfixtureと試験記録が必要になる。
- 解析できる一部情報があっても、applyは別途禁止される場合がある。
- 対応release追加はMatrix更新とテスト追加を伴う。

## References

- [NX-OS Capability and Fixture Matrix](../design/network-ops/NXOS_CAPABILITY_AND_FIXTURE_MATRIX.md)
- [NX-OS Overlay Config Rendering Design](../design/network-ops/NXOS_OVERLAY_CONFIG_RENDERING_DESIGN.md)
- [NX-OS Baseline Health Check Commands](../design/network-ops/NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md)
- hardwareの検証方法は[ADR-0007](./0007-limit-device-validation-to-nexus-9000v.md)で具体化した。
