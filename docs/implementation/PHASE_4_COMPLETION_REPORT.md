# Phase 4 Completion Report

## 1. 結論

Phase 4「Overlay parserと自動差分検出」は2026-07-29に完了した。before / afterの
Canonical Health Snapshotをoffline比較し、新規L2VNI / L3VNIとVLAN、VRF、SVI、NVEの
関連を`overlay/discovered-changes.yaml`へ保存できる。

機器への直接アクセス、Overlayの正常性判定、収束待ちは行わない。これらはPhase 6-7で
既存collectと共通Evaluatorへ接続する。

## 2. Canonical parser

`show running-config`から次を明示的に抽出する。

- VLAN、name、`vn-segment`
- VRF、L3VNI、RD
- SVIのVRF、MTU、IPv4 / IPv6 address、IPv6 link-local、`ip forward`、anycast gateway
- NVEのglobal ingress replication、L2 member、L3 associate-vrf、per-VNI replication

`show nve vni`からVNI、L2/L3種別、BD/VRF context、state、replication、flagを抽出する。
未認識または空出力は正常と推測せずparse errorとしてSnapshotへ残す。

## 3. ChangeSet生成

- 全device共通VLANは`default_vlan`
- 一意の最頻VLANが2台以上ならその値を`default_vlan`、例外をdevice override
- 一意の最頻値がなければdevice単位
- 完全一致する明示groupだけを`targets.groups`へ圧縮
- Gateway SVIのIPv4 / IPv6、link-local、MTU、gateway modeを共通属性として出力
- SVIがない対象は共通SVIがある場合だけ`targets.*.svi: false`
- SVI共通属性、VLAN name、VRF、L3VNI modeの曖昧性をconflictとして保存
- forwarding SVIがないL3VNI専用VLANをtraditional modeと推測しない

configだけで変更を発見できるが、`show nve vni`が不足する場合はconfidenceを`medium`以下と
し、運用状態未確認のwarningを出す。configと運用出力のL2/L3種別またはcontextが矛盾する
場合はconfidenceを`low`とする。

## 4. CLI

```bash
alred overlay-check discover \
  --before operations/CHG-2026-00123/health/before/snapshot.json \
  --after operations/CHG-2026-00123/health/after/snapshot.json \
  --device-groups device-groups.yaml \
  --operations-root operations
```

`--device-groups`は省略可能である。出力先はbeforeのchange-idから決まる
`operations/<change-id>/overlay/discovered-changes.yaml`であり、既存成果物は上書きしない。

## 5. 検証範囲と後続Phase

pytestでmulti-AF SVI、new L3VNI、NVE VNI出力、共通VLAN、device VLAN override、
最頻VLAN、group圧縮、name conflict、offline CLIを確認した。

Phase 4は発見と証跡の関連付けまでを完了条件とする。VNI Down、既存EVPN peer/NVE peerの
regression、Type-3/Type-5、収束待ち、総合判定はPhase 6で実装する。declared ChangeSetの
default解決、config生成、no-op/conflict/rollback configはPhase 5で実装する。
