# Phase 5 Completion Report

## 1. 結論

Phase 5「ChangeSetと共通config renderer」は2026-07-29に完了した。declared / generated /
imported ChangeSetを機器単位のCanonical Render Modelへ解決し、決定的なforward config、
operation所有範囲だけのrollback config、file/model hash、template provenanceを生成できる。

`overlay-change plan`へのoperation workflow統合とExecution/Rollback Plan生成はPhase 8で行う。
機器アクセスや設定投入は実施していない。

## 2. Adapterと互換性

- group、default VLAN、group/device overrideを解決するChangeSet adapter
- 現行VNI Gateway CSVを`legacy_compatible` policyで共通renderer境界へ渡すCSV adapter
- 既存`generate-vni-config`のadd/delete Jinja2 templateとgolden出力を維持
- 新仕様を既存CLIへ暗黙適用せず、外部互換性を保持

## 3. 新仕様renderer

使用template:

- `alred/j2/nxos_overlay_forward_config.j2`
- `alred/j2/nxos_overlay_rollback_config.j2`

実装対象:

- `new_l3vni`既定と明示的な`traditional_vlan_svi`
- L2 Gateway SVI、IPv4 / IPv6、MTU既定9216、IPv6 link-local既定`fe80::1`
- 既存global ingress replicationを前提とするNVE L2/L3 member
- EVPN L2VNI、auto RD / route-target
- 既存BGP local AS配下のVRF IPv4/IPv6 AF
- `advertise l2vpn evpn`
- direct/static redistributionとAF別既定route-map
- `maximum-paths ibgp`既定4

rendererはglobal ingress replication、BGP process、route-map本体、feature、neighborを作成しない。

## 4. Precondition、no-op、rollback

- before SnapshotのNX-OS model/releaseとrunning-config証跡を必須化
- 初期対象model、NX-OS 10.4(5)M以上だけをplan対象化
- 設定済みresourceは`preserve`とし、全resourceが同一ならconfigを空にする
- VLAN/VNI/VRF mapping、SVI、BGP AF設定の競合は`PLAN_ERROR`
- 判断不能な部分設定を推測で上書きしない
- 新規BGP VRFは`router bgp <AS>`配下の`no vrf <VRF>`でrollback
- 既存BGP VRFはoperationが追加した行だけを個別rollback
- 新規global VRFは残存参照検証を前提に`no vrf context <VRF>`
- 既存global VRF、VLAN、NVE、EVPNはoperationが追加したresourceだけを戻す
- global ingress replicationとBGP process自体はrollback対象外

## 5. 成果物

```text
generated-config/<hostname>.cfg
rollback-config/<hostname>.cfg
plan/render-manifest.json
```

manifestは`OverlayRenderManifest` schemaで検証し、renderer version、実際のtemplate path、
config path、config byte SHA-256、Canonical model SHA-256、resource actionを記録する。
configとmanifestはoperation root配下へatomic writeし、所有者限定permissionで保存する。

## 6. 検証範囲

pytestでdefault/group解決、dual-stack SVI、new/traditional L3VNI、BGP設定、global前提不足、
discovered入力拒否、設定済みno-op、新規/既存VRFのscoped rollback、atomic成果物保存、
schema、既存CSV golden互換性を確認した。

対象hardwareのconfig適用可否、CLI応答、保存、rollback後差分は動作検証対象外である。
Phase 10では公式資料と機種別golden configによる静的確認だけを行い、`APPLY_VERIFIED`へ
昇格しない。
