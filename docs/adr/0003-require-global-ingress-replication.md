# ADR-0003: global ingress-replicationを前提条件とする

- Status: Accepted
- Date: 2026-07-26

## Context

L2VNIごとに`ingress-replication protocol bgp`を生成する方式と、global
`ingress-replication protocol bgp`をFabricの前提設定として使用する方式がある。
Overlay追加作業がglobal設定まで所有すると、既存VNIへの影響とrollback範囲が拡大する。

## Decision

global `ingress-replication protocol bgp`が設定済みであることをOverlay追加のpreconditionとする。
個別VNI追加configには同設定を生成しない。未設定または確認不能の場合は、plan/applyを
安全に継続できる状態として扱わない。

## Consequences

- Overlay追加configとrollbackの所有範囲を限定できる。
- apply前にglobal running configを確認する必要がある。
- global設定の導入は別operationとして計画する必要がある。
- 外部ログだけを使う場合、必要なrunning configがなければ判定は`UNKNOWN`となる。

## References

- [NX-OS Overlay Config Rendering Design](../design/network-ops/NXOS_OVERLAY_CONFIG_RENDERING_DESIGN.md)
- [Overlay Change Management Design](../design/network-ops/OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)
