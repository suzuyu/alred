# ADR-0002: L3VNI modeの既定をnew_l3vniとする

- Status: Accepted
- Date: 2026-07-26

## Context

NX-OSのL3VNI設定生成では`new_l3vni`と`traditional_vlan_svi`の両方式を扱う必要がある。
省略時の方式を決めなければ、入力元ごとに生成結果が変わる可能性がある。

## Decision

`l3vnis[].mode`は省略可能とし、既定値を`new_l3vni`とする。
`traditional_vlan_svi`は入力で明示された場合だけ使用する。

## Consequences

- ChangeSetで一般的な入力を簡潔にできる。
- CSV adapterを含むすべての入力経路で同じdefault解決を使用する必要がある。
- 既存入力の意味が変わる可能性がある場合は、adapterの互換性確認とmigration方針が必要になる。
- resolved inputとplanへ、default適用後のmodeを明示する必要がある。

## References

- [Overlay Change Management Design](../design/OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)
- [NX-OS Overlay Config Rendering Design](../design/NXOS_OVERLAY_CONFIG_RENDERING_DESIGN.md)
