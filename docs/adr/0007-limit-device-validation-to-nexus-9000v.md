# ADR-0007: 動作検証をNexus 9000vに限定しhardwareは文書確認とする

- Status: Accepted
- Date: 2026-08-03

## Context

ADR-0005では、Nexus 9000vと4つのNexus hardware modelを初期対象に定め、release/model別のfixtureとcapability確認を求めた。一方、開発環境でNexus 9336C-FX2、93180YC-FX3、9348GC-FX3、9364C-H1を継続的に準備し、apply/save/rollbackを再現可能に検証することは困難である。

実機証跡がないhardwareを9000vの結果から`APPLY_VERIFIED`へ昇格すると、ASIC、interface、license、scale、release固有制約の差を見落とす。反対に、hardware実機の準備をPhase完了条件にすると、開発とreleaseを継続できない。

## Decision

deviceへの接続、収集、設定投入、保存、収束、rollbackを含む動作検証対象をNexus 9000vだけに限定する。

Nexus 9336C-FX2、93180YC-FX3、9348GC-FX3、9364C-H1は対応想定機種に維持するが、Cisco公式資料と機種別golden configによる静的な文書確認だけを行う。文書確認状態は実行Levelと分離し、`DOCUMENT_REVIEWED`でも`APPLY_VERIFIED`へ昇格させない。これらのhardware modelをCapability Registryの`APPLY_VERIFIED` entryへ登録しない。

9000v固有のcontainerlab向け設定は共通Overlay rendererから分離する。interface admin stateはmodelの既定値ではなく、interface種別と管理責務で決める。物理EthernetはOverlay rendererの対象外とし、SVIはdesired stateとして明示的に有効化し、NVEとLoopbackは既存Fabricの前提として扱う。

## Consequences

- 自動テストとlab受入を9000vで再現できる。
- hardwareのOS対応、構文、制約、scale、licenseを公式資料から追跡できる。
- hardware向けconfigの静的生成は確認できるが、実際のCLI受理、通信影響、収束、保存、rollbackは保証できない。
- hardwareは`PLAN_ONLY`以下に留まり、alredのmanaged applyでは投入できない。
- hardwareへの実投入を正式に対応する場合は、本ADRを置き換える新しい判断と、対象model/release/roleの実機受入が必要になる。

## References

- [ADR-0005](./0005-initial-nxos-support-scope.md)
- [NX-OS Capability and Fixture Matrix](../design/network-ops/NXOS_CAPABILITY_AND_FIXTURE_MATRIX.md)
- [NX-OS Hardware Document Review](../design/network-ops/NXOS_HARDWARE_DOCUMENT_REVIEW.md)
- [NX-OS Overlay Config Rendering Design](../design/network-ops/NXOS_OVERLAY_CONFIG_RENDERING_DESIGN.md)
