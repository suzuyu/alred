# NX-OS Hardware Document Review

## 1. 目的

Nexus 9336C-FX2、93180YC-FX3、9348GC-FX3、9364C-H1について、実機または仮想labを使用せず、Cisco公式資料と機種別golden configでalredのOverlay設定生成を静的に確認する方法を定義する。

本書は文書確認の手順を定める。対応範囲、実行Level、Capability Registryの正本は[NX-OS Capability and Fixture Matrix](./NXOS_CAPABILITY_AND_FIXTURE_MATRIX.md)とする。

## 2. 対象と保証範囲

| Model | Family | 検証方法 | Apply |
|---|---|---|---|
| Nexus 9336C-FX2 | FX2 | 公式資料、機種別golden config | 未検証・許可しない |
| Nexus 93180YC-FX3 | FX3 | 公式資料、機種別golden config | 未検証・許可しない |
| Nexus 9348GC-FX3 | FX3 | 公式資料、機種別golden config | 未検証・許可しない |
| Nexus 9364C-H1 | H1 | 公式資料、機種別golden config | 未検証・許可しない |

`DOCUMENT_REVIEWED`は実機動作の保証ではない。次は確認できないため、完了と表示しない。

- CLIの実際の受理とerror message
- 投入順序中の一時的な通信影響
- NVE、EVPN、BGP、vPCの収束時間
- running/startup configの保存とrollback後復元
- optics、breakout、FEC、license、scaleを含む現地条件下の動作

## 3. 証跡状態

| 状態 | 意味 |
|---|---|
| `DOC_REVIEW_PENDING` | 必要な公式資料またはgolden configの確認が残っている |
| `DOCUMENT_REVIEWED` | 公式資料とgolden configの全必須項目が確認済み |
| `DOCUMENT_UNSUPPORTED` | 必須capabilityが公式資料上で非対応 |
| `DOCUMENT_UNKNOWN` | 公式資料だけで判定できない |

これらは実行Levelではない。`DOCUMENT_REVIEWED`でもruntimeは`PLAN_ONLY`以下とし、`APPLY_VERIFIED`へ昇格しない。

## 4. 公式資料の確認順序

releaseごとに次の順で確認する。URLだけでなく、文書title、release、更新日、sectionまたは表名を証跡に残す。

1. Release NotesのDevice Hardwareでexact PIDと対応imageを確認する。
2. VXLAN Configuration Guideで対象family/modelのBGP EVPN、L2VNI、L3VNI、vPC制約を確認する。
3. Interfaces、Unicast Routing、BGP、IPv6 Configuration Guideでrendererが生成するcommandを確認する。
4. Verified Scalability GuideでVLAN、VNI、VRF、SVI、route、neighborの上限を確認する。
5. License GuideでL3、VXLAN EVPN、telemetry等の必要licenseを確認する。
6. model data sheetでport type、speed、breakout、buffer、ASIC familyの差を確認する。
7. Release NotesのOpen/Resolved Caveatsで対象workflowに関係する問題を確認する。

10.4(5)Mの初期確認で使用する主な公式資料は次のとおり。

- [Cisco Nexus 9000 Series NX-OS Release Notes, Release 10.4(5)M](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/104x/release-notes/cisco-nexus-9000-nxos-release-notes-1045.html)
- [Cisco Nexus 9000 Series NX-OS VXLAN Configuration Guide, Release 10.4(x)](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/104x/configuration/vxlan/cisco-nexus-9000-series-nx-os-vxlan-configuration-guide-release-104x/m_configuring_vxlan_93x.html)
- [Cisco Nexus 9000 Series NX-OS Interfaces Configuration Guide, Release 10.4(x)](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/104x/configuration/interfaces/cisco-nexus-9000-series-nx-os-interfaces-configuration-guide-release-104x/m_configuring_basic_interface_parameters_93x.html)
- [Cisco Nexus 9000 Series NX-OS Verified Scalability Guide, Release 10.4(5)M](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/104x/configuration/scalability/cisco-nexus-9000-series-nx-os-verified-scalability-guide-1045.html)
- [Cisco Nexus 9300-FX2 Series Switches Data Sheet](https://www.cisco.com/c/en/us/products/collateral/switches/nexus-9000-series-switches/datasheet-c78-742282.html)
- [Cisco Nexus 9300-FX3 Series Switches Data Sheet](https://www.cisco.com/c/en/us/products/collateral/switches/nexus-9000-series-switches/datasheet-c78-744052.html)
- [Cisco N9364C-H1 Switch Data Sheet](https://www.cisco.com/c/en/us/products/collateral/switches/nexus-9000-series-switches/nexus-9364c-h1-switch-ds.html)

2026-08-03に、10.4(5)M Release NotesのDevice Hardware一覧に4つのexact PIDが掲載されていることを確認した。続いて、10.4(x)のVXLAN、Unicast Routing、Interfaces、Command Reference、10.4(5)MのScalability、およびLicensing Options Guideで必須項目を確認した。機種別の確認記録は[`docs/compatibility/nxos/10.4.5M/`](../../compatibility/nxos/10.4.5M/README.md)、golden configは`tests/fixtures/nxos/hardware_document_review/`を正本とする。

| PID | Device Hardware掲載 | 全capability確認 |
|---|---|---|
| `N9K-C9336C-FX2` | 確認済み | `DOCUMENT_REVIEWED` |
| `N9K-C93180YC-FX3` | 確認済み | `DOCUMENT_REVIEWED` |
| `N9K-C9348GC-FX3` | 確認済み | `DOCUMENT_REVIEWED` |
| `N9K-C9364C-H1` | 確認済み | `DOCUMENT_REVIEWED` |

## 5. Capability確認表

機種とreleaseごとに、次を`supported`、`supported_with_conditions`、`unsupported`、`unknown`のいずれかで記録する。

- OS/imageがexact PIDを対応するか
- `vrf context`、L3VNI、L2VNI、VLAN、SVIの構文
- `interface nve1`、`member vni`、`associate-vrf`
- global ingress-replication BGPの前提
- EVPN VNI、RD、route-target
- BGP VRF address-family、`advertise l2vpn evpn`
- `redistribute direct/static route-map`、`maximum-paths ibgp`
- IPv4/IPv6 SVI、link-local、RA suppression、anycast gateway
- MTU 9216とunderlay MTUの前提
- vPC VTEPの制約
- VLAN/VNI/VRF/SVIのscale
- 必要licenseとrelease caveat

1項目でも`unsupported`または`unknown`が残る場合、機種全体を`DOCUMENT_REVIEWED`にしない。`supported_with_conditions`は文書確認を完了できるが、planで条件を明示し、実機検証済みとは扱わない。

## 6. 機種別golden config

同一の最小ChangeSetとdual-stack ChangeSetを使用し、機種ごとにsynthetic before Snapshotからforward/rollback configを生成する。synthetic入力は実機出力ではないことをmetadataに明記する。

自動テストで次を確認する。

- exact model/releaseがrendererの静的対象として解決される
- 必要commandと順序が公式資料の確認結果に一致する
- 9000v/containerlab専用configがhardware用configに混入しない
- forwardとoperation所有範囲のrollbackが対称である
- 同一入力から同一configとhashを生成する
- `unknown`または`unsupported` capabilityを安全側で拒否する
- Capability Registryのexact entryがないため`PLAN_ONLY`以下となり、approve/applyへ進めない

## 7. Interface admin state

admin stateはmodelではなくinterface種別と管理責務で決定する。

| Interface | 方針 |
|---|---|
| 物理Ethernet | Overlay rendererの管理対象外とし、`shutdown` / `no shutdown`を変更しない |
| L2/L3 SVI | 有効状態をdesired stateとし、modelに依存せず`no shutdown`を明示する |
| NVE | 既存Fabricの前提とし、beforeで存在とadmin stateを確認して通常は変更しない |
| Loopback | 既存Fabricの前提とし、Overlay rendererでは変更しない |
| containerlab用interface | 9000v専用transform/profileで必要な`no shutdown`を適用する |

9000v専用のinterface起動処理を共通Overlay templateへ混在させない。将来物理interfaceの設定生成を追加する場合は、modelの既定値に依存せず、入力schemaでdesired admin stateを明示する。

## 8. Review record

確認結果には少なくとも次を記録する。

```yaml
model: N9K-C9336C-FX2
release: "10.4(5)M"
review_status: DOCUMENT_REVIEWED
apply_allowed: false
reviewed_at: "2026-08-03"
capabilities:
  ipv6_link_local:
    result: SUPPORTED
    source:
      title: Cisco Nexus 9000 Series NX-OS Command Reference
      section: ipv6 link-local
      url: https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/104x/command-reference/config/b_n9k_config_commands_104x/m_i_cmds.html
notes:
  - Actual device behavior is not verified by alred.
```

確認日だけでなく、参照した文書のreleaseとsectionを固定する。公式資料の更新時は既存結果を暗黙に上書きせず、review revisionを追加する。
