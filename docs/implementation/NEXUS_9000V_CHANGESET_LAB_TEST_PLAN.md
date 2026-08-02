# Nexus 9000v ChangeSet Lab Test Plan

## 1. 目的と現在の承認範囲

Nexus 9000v labで、Overlay ChangeSetのvalidation、config生成、事前競合検査、apply、save、
after health check、rollback、rollback後差分確認を段階的に検証する。

初期inventoryはrepository rootの`hosts.lab.yaml`とする。2026-07-30時点で次の10 hostが
登録されている。

- `lfsw0101`から`lfsw0106`
- `spsw0101`、`spsw0102`
- `bgrt0101`、`bgrt0102`

これらの名称だけからroleやvPC pairを決めない。read-only事前収集でhostname、model、
NX-OS release、role、BGP AS、vPC、NVE、既存VRF/VLAN/VNIを確認してからconfig対象を選ぶ。

lab環境であるため、上記hostへのSSH接続、show command、試験用Overlay resourceの
apply/save/rollbackを試験候補とする。ただし、次は別の明示承認がない限り実施しない。

- reload、power操作、NX-OS image変更
- featureの有効化または無効化
- management、underlay、既存NVE source-interface、既存BGP neighborの変更
- 既存VRF/VLAN/VNI、物理interface、port-channelの削除または停止
- test planが所有しない設定のrollback

実機applyは現行Capability Matrixの対象keyが`APPLY_VERIFIED`ではなく、通常の
`overlay-change apply`も未提供であるため、通常経路では実施できない。通常運用から
分離した明示実行のdevice qualification経路に限り、対象・release・hashをTTYで承認し、
saveなしで実施する。

## 2. 追加情報の解決方針

試験開始前に必要な値を次の順で解決する。認証情報は文書や成果物へ保存しない。

| 項目 | 解決方法 | 未解決時 |
|---|---|---|
| username/password | `.env`または`clab_credentials.yaml` | 接続前に停止 |
| model/release | `show version` | apply対象外 |
| leaf/vPC pair | vPC、NVE、BGP、running-configの証跡 | 推測せず停止 |
| local BGP AS | before running-config | planを停止 |
| global ingress replication | before running-config | planを停止 |
| IPv4/IPv6 route-map | before running-config | L3VNI planを停止 |
| 空きVLAN/VNI/VRF | 全config対象のbefore Snapshot | 競合時は別値を再選択 |
| SVI subnet |既存route/addressとの重複検査後にlab用範囲を選択 | apply前に停止 |
| anycast gateway前提 | Fabric既存設定とSVI構成 | SVI scenarioを除外 |

候補値は、競合がないことを確認できた場合に限り次を使用する。

| Resource | 第1候補 |
|---|---|
| VRF | `ALRED-LAB-01` |
| VLAN | `3901`、`3902` |
| L2VNI | `103901`、`103902` |
| L3VNI | `903900` |
| IPv4 SVI | `198.18.39.1/24`、`198.18.40.1/24` |
| IPv6 SVI | `2001:db8:3901::1/64` |
| IPv6 link-local | `fe80::1` |
| MTU | `9216` |

候補値は予約ではない。before調査で1台でも使用済み、重複、または安全性不明なら使用しない。

## 3. Gate

| Gate | 条件 | 許可される次工程 |
|---|---|---|
| G0 Access | 対象全hostの接続結果とinventoryを記録 | read-only収集 |
| G1 Baseline | baseline/overlay healthに未説明の`FAIL`がない | ChangeSet作成 |
| G2 Plan | schema、capability、no-op/conflict、forward/rollback configをレビュー | qualification apply |
| G3 Apply | 対象、hash、設定範囲を再承認し、1台目が成功 | 後続device |
| G4 After | overlay収束、Fabric regressionなし | rollback試験 |
| G5 Rollback | health復旧、before running-configとの差分なし | baseline save試験 |
| G6 Baseline Save | running/startup差分なしを確認後、save成功markerと再差分を記録 | capabilityレビュー |

CPUが既定80%以上、reload-pending、CLI error、timeout、切断、既存設定との競合、
想定外差分のいずれかを検出した場合はfail closedとし、未着手deviceへ進まない。

## 4. 実施シナリオ

### T01 接続・inventory

`hosts.lab.yaml`の10 hostへ接続し、show commandだけを取得する。

```bash
uv run --frozen python alred.py health-check before \
  --collect \
  --hosts ./hosts.lab.yaml \
  --profile network-baseline-nxos \
  --profile nxos-overlay
```

自動採番されたchange-id、raw path、Snapshot path、host別の接続成否を記録する。最初の実行では
`--workers 1`を使用し、対象を段階的に増やしてもよい。

2026-07-30の実施結果:

- `hosts.lab.yaml`の10 hostすべてで接続とread-only収集に成功した。
- 全hostは`Nexus9000 C9300v`、NX-OS `10.5(4)`として観測した。
- canonical再評価operationは、文書上`<read-only-operation-id>`として参照する。
- 判定は`PASS=92 / FAIL=2 / UNKNOWN=0 / NOT_APPLICABLE=26`となった。
- NVEを持たないSpine、EVPN/NVEを持たないBorderはrunning configに基づき
  `NOT_APPLICABLE`となり、role適用誤りによる`UNKNOWN`は解消した。
- NX-OSの`config peers` / `capable peers`件数差はdynamic neighbor prefixや複数AFにより
  発生し得るため、件数差だけの4件は設計どおりpeer state判定へ修正した。
- 残る2件は`lfsw0101`、`lfsw0102`の`tenant1-vpc1` IPv4 peerが`Idle`である。
  G1は未通過とし、既存lab構成の問題としてChangeSet対象から分離する。

初回の不完全な試行と判定修正前のoperationも障害証跡として保持する。試験の正本には
上記R3を使用し、過去成果物を上書きしない。

### T02 topologyと試験対象の選択

before Snapshotとrawから、VTEP leaf、vPC pair、border/spineを分類する。最初のconfig投入対象は
最大2台の検証済みleaf pairとし、それ以外は影響確認対象にする。

2026-07-30のread-only証跡では、peer keepaliveとvirtual peer-linkの相互関係から
`lfsw0101/0102`、`lfsw0103/0104`、`lfsw0105/0106`を各vPC pairとして確認した。
初回候補はbaselineに個別FAILがない`lfsw0103/0104`とする。このpairではBGP AS `65001`、
global ingress replication、anycast gateway MAC、route-map `permit-all-v4` /
`permit-all-v6`を観測した。候補VLAN/VNI/VRFは10 hostの取得済みrunning config内で
未使用だったが、apply直前の再収集で再検証する。

対象pairとEVPN依存先にscopeを限定した正式な作業前operationとして
`operations/<qualification-operation-id>/`を作成した。対象は
`lfsw0103`、`lfsw0104`、`spsw0101`、`spsw0102`で、結果は
`PASS=36 / FAIL=0 / UNKNOWN=0 / NOT_APPLICABLE=12`である。
このoperation内の`desired-changes.yaml`から2台分のforward/rollback configを生成し、
`PLAN_ONLY`のschema、競合検査、hash固定まで成功した。通常applyはCapability Matrixが
未検証であるため、設計どおり`APPLY_CAPABILITY_UNVERIFIED`で停止している。

qualification専用CLIのoffline実装後、同operationに対して次の非TTY gate確認を実施し、
全artifact検証後に`APPROVAL_REQUIRED`で停止することを確認した。

```bash
uv run --frozen python alred.py overlay-change qualify-approve \
  --change-id <qualification-operation-id> \
  --hosts ./hosts.lab.yaml \
  --operations-root operations
```

SIGINT時の状態保存とqualification rollback経路はoffline実装済みである。apply失敗時の
`rollback_required`を維持したまま既存`health-check after`で緊急afterを作成できることも
offline CLI testで確認した。rollback前の新規VRF/VLAN残存参照検査、live running-config
drift検査、rollback後のhealth/raw/semantic統合gateもoffline実装済みである。

rollbackはafterまたは緊急after Snapshot取得後、次の専用CLIで行う。実行時は対象を逆順にし、
saveしない。recordが期限切れでもrollbackは可能だが、全artifact hashとlive
running-config一致は必須である。

```bash
uv run --frozen python alred.py overlay-change qualify-rollback \
  --change-id <qualification-operation-id> \
  --hosts ./hosts.lab.yaml \
  --operations-root operations

uv run --frozen python alred.py health-check rollback \
  --collect \
  --hosts ./hosts.lab.yaml \
  --target-hosts lfsw0103,lfsw0104,spsw0101,spsw0102 \
  --change-id <qualification-operation-id> \
  --operations-root operations
```

2026-07-30のqualification実施結果:

- `qualify-approve`でN9K-C9300V 10.5(4)と全artifact hashを固定した
- `lfsw0103`、`lfsw0104`へserial 1で各44 commandを投入し、両機器で成功した
- config saveは実施していない
- 対象pairとSpine 2台のafter rawを取得し、共通healthは再評価後
  `PASS=40 / FAIL=0 / UNKNOWN=0 / NOT_APPLICABLE=8`だった
- OverlayはConfiguration / Operational / ImpactがすべてPASSで`VERIFIED`だった
- `lfsw0104`、`lfsw0103`の逆順で各10 rollback commandを投入し、両機器で成功した
- rollback healthは`PASS=36 / FAIL=0 / UNKNOWN=0 / NOT_APPLICABLE=12`だった
- 対象2台のnormalized raw running-configとsemantic configがbeforeに一致し、
  workflowは`rolled_back_and_verified`となった

元のafter判定とOverlay判定は上書きせず保存した。実機証跡を使ったparser／判定修正後の
成果物は`health/after-recheck/`、`health/report-recheck/`、`overlay/recheck/`に分離した。
NVE VNI隣接row、vPC共有secondary VTEP、新規VRFのroute比較、NVE未設定Spine、
VLAN宣言リストの外部参照判定を回帰試験へ追加した。

### T03 L2-only

新規VLAN/L2VNIをleaf pairへ作成し、SVIは作成しない。group、`default_vlan`、NVE L2 member、
global ingress-replication前提を検証する。

### T04 L2VNIとdual-stack SVI

新規L2VNIへIPv4/IPv6 anycast SVIを作成し、`mtu 9216`と
`ipv6 link-local fe80::1`を検証する。Fabricのanycast gateway前提が確認できない場合は
このscenarioを実施しない。

### T05 new L3VNI

`ALRED-LAB-01`、`new_l3vni`、NVE `associate-vrf`、BGP VRF IPv4/IPv6 AFを検証する。
既存の`IPv4_REDISTRIBUTE_ALL`、`IPv6_REDISTRIBUTE_ALL` route-mapがない場合、rendererで
route-mapを新規作成せず`PLAN_ERROR`となることを確認する。

### T06 device override

同じL2VNIでdevice別VLAN overrideを使用し、groupの共通値よりdevice値が優先されることを
PLAN_ONLYで確認する。実config投入はFabric設計上許容される場合だけ行う。

### T07 idempotency

T03からT05の成功後、同じbefore相当状態に同じChangeSetを再planし、設定済みresourceが
`NO_CHANGE`になることを確認する。重複configを投入しない。

### T08 conflictと不完全証跡

offline copyを使い、使用済みVLAN/VNI、異なるSVI MTU/link-local、route-map不存在、
BGP AS不明をそれぞれ`PLAN_ERROR`または`PLAN_CONFLICT`として拒否する。実機へ意図的な
競合設定は投入しない。

### T09 rollback

生成済みrollback configだけを使用し、operationが所有するresourceを逆順で削除する。
新規作成したVRFのBGP VRFは`router bgp <asn>`配下の`no vrf ALRED-LAB-01`で削除する。
rollback後にhealth checkを再実行し、before running-configとのsemantic差分とraw差分が
ないことを確認する。rollback後のstartup-config保存は独立した承認点とする。

### T10 baseline save

workflowが`rolled_back_and_verified`で、live running-configがbeforeと一致し、
`show running-config diff`が差分なしの場合だけ`copy running-config startup-config`を
実施する。これにより試験用Overlayをstartup-configへ保存せず、save command、成功marker、
serial停止制御だけを検証する。

```bash
uv run --frozen python alred.py overlay-change qualify-save-baseline \
  --change-id <qualification-operation-id> \
  --hosts ./hosts.lab.yaml \
  --operations-root operations
```

保存前後のdiff、保存応答、対象順、未着手deviceをoperation workspaceへ記録する。
1台でも失敗または応答不明の場合は自動再送せず停止する。

## 5. 初回ChangeSet案

T02完了後、実際のleaf pairと未使用resourceを反映して次のdraftを確定する。
`change_id`は実際のbeforeで自動採番された値へ置換する。

```yaml
api_version: alred/v1
kind: OverlayChangeSet

metadata:
  change_id: REPLACE_WITH_ACTIVE_CHANGE_ID
  source: declared

spec:
  device_groups:
    lab-leaf-pair:
      devices:
        - REPLACE_WITH_LEAF_1
        - REPLACE_WITH_LEAF_2

  l2vnis:
    - vni: 103901
      default_vlan: 3901
      vlan_name: ALRED-LAB-APP
      vrf: ALRED-LAB-01
      l3vni: 903900
      svi:
        mtu: 9216
        ipv4_addresses:
          - 198.18.39.1/24
        ipv6_addresses:
          - 2001:db8:3901::1/64
        ipv6_link_local: fe80::1
        gateway_mode: anycast
      targets:
        groups:
          lab-leaf-pair: {}

  l3vnis:
    - vni: 903900
      vrf: ALRED-LAB-01
      mode: new_l3vni
      address_families:
        ipv4:
          advertise_l2vpn_evpn: true
          redistribute_direct:
            enabled: true
            route_map: IPv4_REDISTRIBUTE_ALL
          redistribute_static:
            enabled: true
            route_map: IPv4_REDISTRIBUTE_ALL
          maximum_paths_ibgp: 4
        ipv6:
          advertise_l2vpn_evpn: true
          redistribute_direct:
            enabled: true
            route_map: IPv6_REDISTRIBUTE_ALL
          redistribute_static:
            enabled: true
            route_map: IPv6_REDISTRIBUTE_ALL
          maximum_paths_ibgp: 4
      targets:
        groups:
          lab-leaf-pair: {}
```

## 6. 必須証跡と完了条件

次を同じchange-idのoperation workspaceへ保存する。

- inventory、resolved profile、before/after/rollback後Snapshot
- before/after/rollback後のrawログとCollection Manifest
- 確定ChangeSetとhash
- resolved ChangeSet、forward/rollback config、template provenanceとhash
- command単位の開始・終了時刻、出力、結果、CLI error
- save出力
- health結果、overlay結果、収束結果
- rollback後のsemantic/raw running-config差分
- sanitized fixture、正確なmodel/release/role metadata

全scenarioの期待結果を満たし、レビューされた正確な`model + release + role`だけをCapability
Matrixの`APPLY_VERIFIED`候補とする。他release/modelへ自動継承しない。

2026-07-30にT01、T02、T09、T10と、T03からT05を組み合わせたcandidateを
文書上`<qualification-operation-id>`として参照するoperationで完了した。対象2台のapply、after収束、rollback復元、
baseline saveが成功したため、`N9K-C9300V + 10.5(4) + vtep_leaf`の実際に検証した
capability setだけをMatrix上`APPLY_VERIFIED`へ手動昇格した。この時点では通常apply CLIと
machine-readable registryの受入を別scenarioとして残した。

2026-07-30から31日に、machine-readable registryと通常
`plan/approve/apply/rollback`経路を
文書上`<normal-operation-id>`として参照するoperationで受け入れた。apply対象2台はSUCCESS、4台のafter
共通healthとbefore/after比較はPASS、Overlayは`VERIFIED`であった。保存せず逆順rollbackし、
4台のrollback healthはPASS、対象2台のraw running-configとsemantic configはbeforeと
一致した。最終workflowは`rolled_back_and_verified`である。通常save stageは別scenarioとして
残す。

2026-07-31に通常saveと保存済みrollbackのscenarioを
文書上`<save-rollback-operation-id>`として参照するoperationで完了した。apply前のrunning/startup差分なし、
apply、after共通health、Overlay `VERIFIED`、通常save成功marker、保存後diffなしを確認した。
保存済み状態から逆順rollbackし、rollback health、raw / semantic before一致後に
`save-rollback`を実行した。両台の保存後diffは空で、running/startupともbeforeへ復元し、
最終workflowは`completed`となった。
