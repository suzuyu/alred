# NX-OS Overlay Health Check

この章では、EVPN/VXLAN FabricへL2VNIまたはL3VNIを追加する前後に、
`network-baseline-nxos`と`nxos-overlay`を併用して正常性を確認する手順を説明します。

このシナリオでは、既存L2VNI 10010が稼働している2台のLeafへ、VRF `TENANT-B`、
L3VNI 50002、新しいL2VNI 10020を追加します。VLANは機器ごとに異なり、
`leaf01`では20、`leaf02`では120を使用する想定です。設定投入はalred外の手動作業または
別システムで行います。
alred自身でVNI設定を生成・投入する場合は
[Overlay ChangeSet作成ガイド](./07_OVERLAY_CHANGESET_GUIDE.md)で入力を準備し、
[alredによるVNI設定投入](./08_ALRED_OVERLAY_CHANGE_APPLY.md)を使用してください。

## 1. profileを併用する理由

| profile | 主な確認対象 |
|---|---|
| `network-baseline-nxos` | CPU、memory、environment、logging、reload-pending、route、OSPF、BGP、vPC |
| `nxos-overlay` | running config、NVE interface、NVE VNI、ingress replication、EVPN BGP |

`nxos-overlay`だけでも実行できますが、Overlay追加によるUnderlayや装置全体への影響を確認する
ため、通常作業ではbaselineとの併用を推奨します。profileは自動合成されないため、beforeで2つ
とも明示します。

## 2. 収集されるOverlayコマンド

`nxos-overlay`は次のコマンドを要求します。

| ID | NX-OSコマンド | 必須 | 用途 |
|---|---|---:|---|
| `running_config` | `show running-config` | はい | VLAN、VNI、VRF、SVI、NVE、BGP設定の正規化 |
| `nve_interface` | `show nve interface` | いいえ | NVE interfaceの状態 |
| `nve_peers` | `show nve peers` | いいえ | NVE peer の状態と learn type |
| `nve_vni` | `show nve vni` | いいえ | L2/L3VNIの存在とUp/Down |
| `nve_vni_ingress_replication` | `show nve vni ingress-replication` | いいえ | BGP ingress replication peer |
| `bgp_l2vpn_evpn_summary` | `show bgp l2vpn evpn summary` | いいえ | EVPN BGP peer |
| `bgp_l2vpn_evpn` | `show bgp l2vpn evpn` | いいえ | EVPN Type-2/3/5 route の保存と比較 |

任意コマンドでも、対象機器で機能が設定されているのに出力を取得・解析できなければ、
正常と推測せず`UNKNOWN`になる場合があります。

`schema_version: 2` の `roles.yaml` を指定した直接収集では、共通 baseline command に加えて、device の topology role と function に必要な Overlay command だけを収集します。たとえば spine に `evpn-route-reflector` function があれば EVPN summary／route を収集しますが、`vtep` function がなければ NVE command は収集しません。version 省略／v1 は後方互換性のため従来どおり全 command を収集します。

```bash
alred health-check before \
  --collect \
  --hosts ./hosts.lab.yaml \
  --roles ./roles.yaml \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --ask-pass
```

function の `required`／`optional`／`forbidden` と running config の実在を比較し、`vtep_function_expectation`、`vpc_function_expectation`、`evpn_rr_config_health`、`underlay_rr_config_health` を出力します。EVPN RR neighbor は `evpn_rr_neighbor_health`、border gateway の EVPN neighbor は `border_evpn_bgp_health` として表示します。underlay neighbor と vPC の運用状態は baseline check を再利用し、同じ異常を重複計上しません。

## 3. シナリオ固有の事前確認

inventory、認証、timezone、保存先などは
[Common Preparation](./00_COMMON_PREPARATION.md)に従って準備します。このシナリオでは、
生成済みの`./hosts.lab.yaml`を使用します。

Overlay作業固有の確認項目:

- 対象Leafと、必要に応じてSpineやroute reflectorがinventoryに含まれている
- 変更対象VNI、VRF、VLAN、Gateway IPを作業手順と照合している
- beforeとafterを同じ対象・profileで取得できる
- `show running-config`を成果物として保存できる

## 4. beforeを取得

```bash
alred health-check before \
  --collect \
  --hosts ./hosts.lab.yaml \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --logging-days 1 \
  --ask-pass
```

change IDを省略すると自動採番されます。端末出力例:

```text
=== HEALTH SNAPSHOT SUMMARY ===
Change ID : HC-20260802T140000-p1234-a1b2c3
Phase     : before
Input     : alred-collect
Hosts     : 3
Warnings  : 0
Result    : PASS
Checks    : PASS=49 WARN=0 FAIL=0 UNKNOWN=0 N/A=5
Manifest  : operations/live/2026/08/02/HC-20260802T140000-p1234-a1b2c3/health/before/collection-manifest.yaml
Snapshot  : operations/live/2026/08/02/HC-20260802T140000-p1234-a1b2c3/health/before/snapshot.json
Checklist : operations/live/2026/08/02/HC-20260802T140000-p1234-a1b2c3/health/before/checklist.md
```

`nxos-overlay`を含むため、通常のhealth成果物に加えて次が生成されます。

```text
operations/live/2026/08/02/HC-20260802T140000-p1234-a1b2c3/health/before/
├── overlay-state.yaml
├── vni-map.md
├── vni-map.csv
├── vni_gateway_map.md
└── vni_gateway_map.csv
```

`vni_gateway_map.*` は既存 command 互換の SVI 中心一覧である。用途と制約は
[VNI Map Guide](09_VNI_MAP_GUIDE.md)を参照する。

beforeのChecklist・VNI map例:

- [before-checklist.md](./examples/nxos-overlay/before-checklist.md)
- [before-overlay-state.yaml](./examples/nxos-overlay/before-overlay-state.yaml)
- [before-vni-map.md](./examples/nxos-overlay/before-vni-map.md)
- [before-vni-map.csv](./examples/nxos-overlay/before-vni-map.csv)

例では既存L2VNI 10010とL3VNI 50001が両LeafでUpです。VLANが10と110で異なるため
`DEVICE_VARIANT`ですが、これは意図した機器差分であり異常ではありません。
`spine01`はEVPN route reflectorとして共通baselineとEVPN BGPを確認し、VTEPではないため
`nve_interface_health`は`NOT_APPLICABLE`です。

## 5. beforeで確認する内容

ChecklistではbaselineとOverlayの両方を確認します。

```text
### Device: `leaf01` (192.0.2.11)

#### Profile: `network-baseline-nxos`

- [x] `collection_complete`: PASS - All required command outputs were parsed
- [x] `reload_pending`: PASS - No reload-pending configuration exists
- [x] `ospf_neighbor_health`: PASS - All observed OSPF neighbors are FULL
- [x] `vpc_health`: PASS - vPC peer and consistency are healthy

#### Profile: `nxos-overlay`

- [x] `nve_interface_health`: PASS - NVE interface state is Up
- [x] `evpn_bgp_health`: PASS - All observed EVPN BGP peers are established
```

続いて`vni-map.md`で次を確認します。

1. 既存VNIが想定した全機器に存在する。
2. L2VNIとVRF、L3VNIの対応が正しい。
3. NVE stateがUpである。
4. `Conflicts: 0`、`Unknowns: 0`である。
5. 機器別 VLAN または IPv6 link-local mode／明示値の差分が意図した`DEVICE_VARIANT`である。
6. Gateway IPv4／IPv6、IPv6 link-local、MTU、anycast gateway が想定どおりである。

beforeでFAILまたはUNKNOWNがある場合は、変更前から存在する事象でも原因と影響を確認してから
作業継続を判断します。

## 6. Overlay設定を投入

承認済みの手順で、L2VNI 10020を追加します。この例では次の状態を期待します。

| 項目 | leaf01 | leaf02 |
|---|---:|---:|
| L2VNI | 10020 | 10020 |
| VLAN | 20 | 120 |
| VLAN name | TENANT-B-APP | TENANT-B-APP |
| VRF | TENANT-B | TENANT-B |
| Gateway IPv4 | 198.51.100.1/24 | 198.51.100.1/24 |
| MTU | 9216 | 9216 |
| NVE state | Up | Up |

L3VNI 50002では、両機器にVRF `TENANT-B`、RD `auto`、BGP VRF address-familyの
`advertise l2vpn evpn`、`interface nve 1`の`member vni 50002 associate-vrf`が追加され、
NVE operational stateがUpになることを期待します。

設定を手動や別システムで投入する場合も、alredへ投入configを入力する必要はありません。
beforeとafterの観測結果から新しいVNIと付随情報を抽出します。

## 7. afterを取得

beforeが直接収集で完了しているため、profile、inventory、収集方式はoperationから継承します。

```bash
alred health-check after \
  --change-id HC-20260802T140000-p1234-a1b2c3 \
  --ask-pass
```

after出力例:

```text
=== HEALTH SNAPSHOT SUMMARY ===
Change ID : HC-20260802T140000-p1234-a1b2c3
Phase     : after
Input     : alred-collect
Hosts     : 3
Warnings  : 0
Result    : PASS
Checks    : PASS=49 WARN=0 FAIL=0 UNKNOWN=0 N/A=5
Manifest  : operations/live/2026/08/02/HC-20260802T140000-p1234-a1b2c3/health/after/collection-manifest.yaml
Snapshot  : operations/live/2026/08/02/HC-20260802T140000-p1234-a1b2c3/health/after/snapshot.json
Checklist : operations/live/2026/08/02/HC-20260802T140000-p1234-a1b2c3/health/after/checklist.md
```

afterのChecklist・VNI map例:

- [after-checklist.md](./examples/nxos-overlay/after-checklist.md)
- [after-overlay-state.yaml](./examples/nxos-overlay/after-overlay-state.yaml)
- [after-vni-map.md](./examples/nxos-overlay/after-vni-map.md)
- [after-vni-map.csv](./examples/nxos-overlay/after-vni-map.csv)

新しいL2VNI 10020が両LeafでUpとなり、既存L2VNI 10010とL3VNI 50001も維持されていることを
確認します。

## 8. before / after差分

after完了後のreportでは次を確認します。

```text
operations/live/2026/08/02/HC-20260802T140000-p1234-a1b2c3/health/report/
├── health-result.json
├── summary.md
├── vni-map-diff.json
├── vni-map-diff.md
└── vni-map-diff.csv
```

人が最初に確認する差分例:

- [vni-map-diff.json](./examples/nxos-overlay/vni-map-diff.json)
- [vni-map-diff.md](./examples/nxos-overlay/vni-map-diff.md)
- [vni-map-diff.csv](./examples/nxos-overlay/vni-map-diff.csv)

`vni-map-diff.json`はfield単位の全変更とbefore/after evidenceを保持する機械処理用の正本です。
MarkdownとCSVはその派生表現です。各形式ともVNIの昇順で、同じVNIの変更が連続します。
Markdownは同じfield・before・after・statusを持つdeviceを1行へまとめます。deviceごとに値が
異なる場合は別行になるため、機器固有の差異も確認できます。VNIを持たないOverlay全体の
`CONFLICT` / `UNKNOWN`は末尾に出力されます。
差分tableの後にある`Field Source List`ではfieldの取得元と再確認用コマンド、`Evidence Files`では
device別のbefore / after証跡pathを確認できます。Verification commandはそのままNX-OSで
実行できる形式です。

この例では新規L2VNI 10020と新規L3VNI 50002の各fieldが`ADDED` / `OBSERVED`として
表示されます。L3VNIのsectionでは、VRF名に加えてBGP設定、RD、NVE associate-vrf、
operational stateを確認できます。field変更件数が1ではないのは、VNI、VLAN、
NVE state、SVI、Gatewayなどを機器・field単位で追跡するためです。

## 9. 作業完了条件

次をすべて満たしたことを確認します。

- beforeで許容していないFAIL、UNKNOWNがない
- afterでbaseline checkのregressionがない
- `nve_interface_health`と`evpn_bgp_health`がPASS
- 新規L2VNI 10020が対象機器すべてで存在し、NVE stateがUp
- VLAN 20/120の差分が計画どおり
- 既存L2VNI 10010とL3VNI 50001が維持されている
- VRF `TENANT-B`とL3VNI 50002が両機器に追加されている
- L3VNI 50002のBGP設定とNVE `associate-vrf`が両機器に追加され、Upになっている
- VNI mapの`Conflicts`と`Unknowns`が0
- diffに計画外のREMOVED、MODIFIED、CONFLICT、UNKNOWNがない
- logging、route、OSPF、BGP、vPC、reload-pendingに新規異常がない

`DEVICE_VARIANT`は、機器別 VLAN や IPv6 link-local mode／明示値などの意図した差分であれば完了を妨げません。作業計画にない
差分の場合は完了せず、設定と入力情報を照合します。

## 10. オフラインログを使用する場合

外部収集したbeforeログ:

```bash
alred health-check snapshot \
  --input ./transcripts/before \
  --input-format nxos-transcript \
  --phase before \
  --hosts ./hosts.lab.yaml \
  --profile network-baseline-nxos \
  --profile nxos-overlay
```

afterログはbeforeで採番されたchange IDへ関連付けます。

```bash
alred health-check snapshot \
  --input ./transcripts/after \
  --input-format nxos-transcript \
  --phase after \
  --change-id HC-20260802T140000-p1234-a1b2c3 \
  --hosts ./hosts.lab.yaml
```

外部ログには、baselineとOverlay profileが必要とするコマンド区間を含めます。hostnameまたは
コマンド区間を一意に特定できない場合、その証跡は`UNKNOWN`として扱われます。

## 11. サンプルファイル

サンプル一式の前提と対応関係は
[examples/nxos-overlay/README.md](./examples/nxos-overlay/README.md)を参照してください。
これらは匿名化された説明用成果物で、実行時の値、件数、path、hashは環境に応じて変わります。
