# VNI Config Renderer As-Is

- Status: Integrated
- Last reviewed: 2026-08-09
- Scope: 現行`generate-vni-config`、`vni_add_config.j2`、`vni_delete_config.j2`

## Evidence

| 種別 | pathまたはcommand | 確認内容 |
|---|---|---|
| Code | `alred/cli.py` | CSV loader、diff、device grouping、render/write |
| Template | `alred/j2/vni_add_config.j2` | 現行add config |
| Template | `alred/j2/vni_delete_config.j2` | 現行delete config |
| Test | `tests/test_phase0_vni_golden.py` | CSV入力とgolden出力 |

## Observed behavior

- CSVは`l3vni,vrf,l2vni,gateway_ipv4,gateway_ipv6,device,vlan`を必須headerとし、
  `vlan_name`は省略できる。
- diffのentity keyは`device + vlan`である。
- outputはdeviceごとのconfigとmerged configに分かれる。
- add/deleteの現行出力は`tests/fixtures/vni/current/`で固定する。

## Known differences from the approved future design

現行goldenは将来仕様への適合を示さない。少なくとも`new_l3vni` modeの選択、SVI MTU 9216、
IPv6 link-local、router BGP VRF address-family、redistribute、maximum-paths、global
ingress-replication precondition、所有resourceに限定したrollbackは未対応または未確認である。

## Recommended design disposition

現行CSVをadapterとして維持し、ChangeSetと同じCanonical Render Modelへ接続する実装は完了した。
現行goldenの変更は意図した互換性変更としてレビューし、新仕様のgoldenとはdirectoryを分ける。

## Integration

- Design document: [VNI Map and Legacy CSV Design](../design/network-ops/VNI_MAP_AND_LEGACY_CSV_DESIGN.md)、[NX-OS Overlay Config Rendering Design](../design/network-ops/NXOS_OVERLAY_CONFIG_RENDERING_DESIGN.md)
- Integrated date: 2026-08-09
