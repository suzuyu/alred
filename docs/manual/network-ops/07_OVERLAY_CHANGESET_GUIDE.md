# Overlay ChangeSet作成ガイド

この章では、alredでL2VNI／L3VNI設定を生成・投入する前に、期待する変更内容を
`OverlayChangeSet` YAMLとして定義する方法を説明します。実際のbefore、plan、approve、apply、
after、save、rollbackは[alredによるVNI設定投入](./08_ALRED_OVERLAY_CHANGE_APPLY.md)を参照してください。

仕様の正本は[Overlay Change Management Design](../../design/network-ops/OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)と
[NX-OS Overlay Config Rendering Design](../../design/network-ops/NXOS_OVERLAY_CONFIG_RENDERING_DESIGN.md)です。

## 1. 作成するタイミング

alred内で設定を投入する場合は、before収集より前に作業用ChangeSetを作成してレビューします。

```text
change IDを決定
    ↓
作業用ChangeSetを作成・レビュー
    ↓
対象機器のbefore収集・正常性確認
    ↓
ChangeSetをoperation配下へ固定保存
    ↓
before Snapshotを使用してplan生成
```

ChangeSet作成時点では機器へアクセスせず、設定も投入しません。既存設定との競合、BGP AS、
route-mapの存在、対応model／NX-OS releaseなどは、before Snapshotを入力とする`overlay-change plan`
で検証します。

ChangeSet、before、plan、apply、afterは同じchange IDを使用します。ChangeSetを先に作成する
このworkflowでは自動採番に依存せず、作業管理番号など一意なIDを事前に決めてください。

```text
CHG-2026-00123
```

## 2. サンプルから作成

設計上の標準である外部group形式は、ChangeSetとgroupファイルを同じ作業用directoryへコピーします。

```bash
mkdir -p ./changes/CHG-2026-00123
cp docs/manual/network-ops/examples/overlay-changeset/desired-changes.yaml \
  ./changes/CHG-2026-00123/desired-changes.yaml
cp docs/manual/network-ops/examples/overlay-changeset/device-groups.fabric.yaml \
  ./changes/CHG-2026-00123/device-groups.fabric.yaml
```

編集対象:

```text
changes/CHG-2026-00123/desired-changes.yaml
changes/CHG-2026-00123/device-groups.fabric.yaml
```

サンプル一式:

- [外部group参照ChangeSet](./examples/overlay-changeset/desired-changes.yaml)（推奨）
- [共通device group](./examples/overlay-changeset/device-groups.fabric.yaml)（推奨）
- [既定値を省略したChangeSet](./examples/overlay-changeset/desired-changes.minimal.yaml)
- [一ファイル形式ChangeSet](./examples/overlay-changeset/desired-changes.inline.yaml)（代替）
- [サンプルの説明](./examples/overlay-changeset/README.md)
- [vPC pair 1 の forward config](./examples/overlay-changeset/adc-lfsw0101.cfg)
- [vPC pair 1 の rollback config](./examples/overlay-changeset/adc-lfsw0101-rollback.cfg)
- [vPC pair 2 の forward config](./examples/overlay-changeset/adc-lfsw0103.cfg)
- [vPC pair 2 の rollback config](./examples/overlay-changeset/adc-lfsw0103-rollback.cfg)

サンプルをそのまま本番環境へ投入せず、change ID、対象hostname、VNI、VLAN、VRF、IP address、
BGP関連値を対象環境に合わせて変更してください。

## 3. 基本構造

設計上の標準である外部group形式の最小構造は次のとおりです。

```yaml
api_version: alred/v1
kind: OverlayChangeSet
metadata:
  change_id: CHG-2026-00123
  source: declared
spec:
  device_groups_ref:
    path: ./device-groups.fabric.yaml
  l2vnis: []
  l3vnis: []
```

| 項目 | 必須 | 内容 |
|---|---:|---|
| `api_version` | はい | 現在は`alred/v1` |
| `kind` | はい | `OverlayChangeSet` |
| `metadata.change_id` | はい | before以降も共通利用するchange ID |
| `metadata.source` | はい | ChangeSetの作成経路 |
| `metadata.generated_at` | いいえ | 生成日時。指定時はtimezone付きISO 8601を推奨 |
| `spec.device_groups_ref` | はい | 共通`OverlayDeviceGroups`へのChangeSet相対path |
| `spec.l2vnis` | はい | 追加するL2VNI。対象なしなら空配列 |
| `spec.l3vnis` | はい | 追加するL3VNI。対象なしなら空配列 |

設定投入用の手書きChangeSetには`status`を記載しません。`status`は主に観測から生成される
`discovered` ChangeSetの根拠や警告を格納する領域です。

一ファイルで完結させる場合は、`device_groups_ref`の代わりにinline定義を使用できます。

```yaml
spec:
  device_groups:
    adc-vpc-pair-01:
      devices:
        - adc-lfsw0101
        - adc-lfsw0102
  l2vnis: []
  l3vnis: []
```

## 4. metadata.source

`metadata.source`は、alredで投入するかどうかではなく、ChangeSetの作成経路を表します。

| 値 | 意味 | 投入用expected ChangeSet |
|---|---|---|
| `declared` | 利用者が作成、または内容を確認して期待状態として確定 | 標準として使用 |
| `generated` | alredや別処理が機械生成し、まだ利用者が確定していない | レビュー後に`declared`として保存を推奨 |
| `imported` | 外部システムから取り込んだ未検証入力 | schema、対象、内容のレビューが必要 |
| `discovered` | before／afterの観測結果から検出 | そのまま設定生成へ使用不可 |

本ガイドの標準フローでは次を指定します。

```yaml
metadata:
  change_id: CHG-2026-00123
  source: declared
```

## 5. vPCペアをdevice groupで表現

基本方針では、ChangeSetから共通の外部groupファイルを参照します。

```yaml
# desired-changes.yaml
spec:
  device_groups_ref:
    path: ./device-groups.fabric.yaml
```

```yaml
# device-groups.fabric.yaml
api_version: alred/v1
kind: OverlayDeviceGroups
metadata:
  name: adc-single-site-fabric
spec:
  device_groups:
    adc-vpc-pair-01:
      devices:
        - adc-lfsw0101
        - adc-lfsw0102
    adc-vpc-pair-02:
      devices:
        - adc-lfsw0103
        - adc-lfsw0104
    adc-all-vtep-leafs:
      groups:
        - adc-vpc-pair-01
        - adc-vpc-pair-02
```

この形式ではgroupファイルに所属関係だけを定義し、VLANなど作業固有値はChangeSetの
`targets.groups`へ記載します。詳細仕様は
[Overlay Change Management Design](../../design/network-ops/OVERLAY_CHANGE_MANAGEMENT_DESIGN.md#5-device-group)を
参照してください。

```yaml
targets:
  groups:
    adc-vpc-pair-01: {}
    adc-vpc-pair-02:
      vlan: 10
```

この例では `adc-lfsw0101/0102` が VLAN 100、`adc-lfsw0103/0104` が VLAN 10 になります。
値の優先順位は
次のとおりです。

```text
targets.devices.<hostname>.vlan
    ↓ 未指定
targets.groups.<group-name>.vlan
    ↓ 未指定
default_vlan
    ↓ すべて未指定
PLAN_ERROR
```

group名は任意ですが、vPCペアと用途を識別できる安定した名前を推奨します。`devices`には
`hosts.yaml`およびbefore Snapshotで識別されるhostnameを記載します。通常はgroup単位で表現し、
ペア内で意図的な差がある場合だけdevice overrideを使用します。

一ファイルで表現する場合は、同じgroupをChangeSet内へinline定義します。

```yaml
spec:
  device_groups:
    adc-vpc-pair-01:
      devices:
        - adc-lfsw0101
        - adc-lfsw0102
    adc-vpc-pair-02:
      devices:
        - adc-lfsw0103
        - adc-lfsw0104
  l2vnis:
    - vni: 10100
      default_vlan: 100
      targets:
        groups:
          adc-vpc-pair-01: {}
          adc-vpc-pair-02:
            vlan: 10
```

## 6. L2VNIを定義

Gateway SVIを含むL2VNIの例:

```yaml
l2vnis:
  - vni: 10100
    default_vlan: 100
    vlan_name: tenant1-vpc1-server-seg1
    vrf: tenant1-vpc1
    l3vni: 19001
    svi:
      mtu: 9216
      ipv4_addresses:
        - 172.16.0.254/24
      ipv6_addresses:
        - fd21:0:0:1::1/64
      ipv6_link_local: fe80::1
      ipv6_nd_suppress_ra: true
      gateway_mode: anycast
    targets:
      groups:
        adc-vpc-pair-01: {}
        adc-vpc-pair-02:
          vlan: 10
```

主な規則:

- `vni`と`targets`は必須
- `default_vlan`、group override、device overrideのいずれかで全対象のVLANを解決できること
- `vlan_name`、`vrf`、`l3vni`、`svi`は対象機器で共通
- `svi`にはIPv4、IPv6の一方または両方を指定可能
- SVI MTUの既定値は9216
- IPv6 SVIで`ipv6_link_local`を省略した場合は`fe80::1`
- IPv6 SVIで`ipv6_nd_suppress_ra`を省略した場合は`true`。RA suppressを設定しない場合は`false`
- L2-onlyで全対象にSVIが不要なら`svi`自体を省略
- 一部対象だけSVI不要なら対象groupまたはdeviceへ`svi: false`

IPv6 RAをsuppressしないSVIでは、次のように明示します。この場合もIPv6 addressとlink-localは
生成されますが、`ipv6 nd suppress-ra`だけが生成configから省略されます。

```yaml
svi:
  ipv6_addresses:
    - 2001:db8:20::1/64
  ipv6_nd_suppress_ra: false
```

一部groupでSVIを生成しない例:

```yaml
targets:
  groups:
    server-leafs: {}
    border-leafs:
      svi: false
```

## 7. L3VNIとBGPを定義

`new_l3vni`の例:

```yaml
l3vnis:
  - vni: 50001
    vrf: TENANT-A
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
        server-leafs: {}
        storage-leafs: {}
```

主な規則:

- `vni`、`vrf`、`targets`は必須
- `mode`の既定値は`new_l3vni`
- `new_l3vni`ではL3VNI専用VLANやSVIを指定しない
- `traditional_vlan_svi`だけ`default_vlan`またはtarget overrideのVLANを使用
- `maximum_paths_ibgp`の既定値は4
- route-map省略時の既定名はIPv4が`IPv4_REDISTRIBUTE_ALL`、IPv6が
  `IPv6_REDISTRIBUTE_ALL`
- 指定したroute-mapはapply前から対象機器に存在すること
- BGP ASはChangeSetへ記載せず、beforeの既存BGP processから解決
- `interface nve1`の`global ingress-replication protocol bgp`は既存設定を前提とし、
  ChangeSetから生成しない

意図をレビューしやすくするため、投入用ChangeSetでは既定値に依存せずBGP項目を明示することを
推奨します。

## 8. 既定値を省略した全体例

次は、外部device groupを使用し、既定値をできるだけ記載しないChangeSetの全体例です。
VNI、VLAN、VRF、Gateway address、対象groupなど、作業ごとに決める値だけを中心に記載します。
同じ内容は[desired-changes.minimal.yaml](./examples/overlay-changeset/desired-changes.minimal.yaml)から
コピーできます。

```yaml
api_version: alred/v1
kind: OverlayChangeSet

metadata:
  change_id: CHG-2026-00123
  source: declared

spec:
  device_groups_ref:
    path: ./device-groups.fabric.yaml

  l2vnis:
    - vni: 10100
      default_vlan: 100
      vlan_name: tenant1-vpc1-server-seg1
      vrf: tenant1-vpc1
      l3vni: 19001
      svi:
        ipv4_addresses:
          - 172.16.0.254/24
        ipv6_addresses:
          - fd21:0:0:1::1/64
      targets:
        groups:
          adc-vpc-pair-01: {}
          adc-vpc-pair-02:
            vlan: 10

  l3vnis: []
```

この例では、plan時に次の既定値または導出値が適用されます。

| 省略した項目 | 適用される値・動作 |
|---|---|
| `l2vnis[].svi.mtu` | `9216` |
| `l2vnis[].svi.ipv6_link_local` | `fe80::1` |
| `l2vnis[].svi.ipv6_nd_suppress_ra` | `true`。`ipv6 nd suppress-ra`を生成 |
| `l2vnis[].svi.gateway_mode` | `anycast` |

このサンプルは既存 VRF／L3VNI を利用するため、`l3vnis` は空配列です。既存 BGP process が
1 つであることと、NVE に global ingress replication が設定済みであることは plan で検証されます。
新規 L3VNI も作成する場合は、前節の完全な記載パターンを使用してください。

## 9. target解決結果をレビュー

サンプルを機器単位へ展開すると次の結果になります。

| device | group | L2VNI | VLAN | L3VNI | VRF |
|---|---|---:|---:|---:|---|
| adc-lfsw0101 | adc-vpc-pair-01 | 10100 | 100 | 19001 | tenant1-vpc1 |
| adc-lfsw0102 | adc-vpc-pair-01 | 10100 | 100 | 19001 | tenant1-vpc1 |
| adc-lfsw0103 | adc-vpc-pair-02 | 10100 | 10 | 19001 | tenant1-vpc1 |
| adc-lfsw0104 | adc-vpc-pair-02 | 10100 | 10 | 19001 | tenant1-vpc1 |

ChangeSetレビュー時には、圧縮されたgroup表現だけでなく、この機器単位の期待値を確認します。
特にvPCペア内でVLAN、VNI、VRF、SVI、BGP設定が一致していることを確認してください。

## 10. 作成時チェックリスト

beforeを開始する前に次を確認します。

1. `metadata.change_id`が作業管理番号およびbeforeの指定値と一致する。
2. `metadata.source`が作成経路と一致し、標準フローでは`declared`である。
3. 全hostnameがinventory上の対象と一致する。
4. vPCペアのgroupとメンバーが正しい。
5. L2VNI、L3VNI、VLAN、VRFに重複や予約値との競合がない。
6. ペア内設定が同一で、ペア間差分は意図したoverrideだけである。
7. Gateway IPv4／IPv6、prefix、link-local、MTUが設計値と一致する。
8. address-family、redistribute、route-map、maximum-pathsが意図どおりである。
9. L2-only対象やSVI不要対象の表現が正しい。
10. サンプル値やドキュメント用addressが残っていない。

## 11. 過去の正常状態で準備用planを作成

作業前準備で機器へアクセスしたくない場合は、過去operationの正常な最終状態を使って
`prepare-plan`を実行できます。最新状態を自動選択する例:

```bash
alred overlay-change prepare-plan \
  --change-set ./changes/CHG-2026-00123/desired-changes.yaml \
  --reference-state latest-known-good \
  --operations-root operations
```

参照元の `WARN` を確認したうえで明示的に許可する場合:

```bash
alred overlay-change prepare-plan \
  --change-set ./changes/CHG-2026-00123/desired-changes.yaml \
  --reference-state latest-known-good \
  --allow-reference-state-warn \
  --operations-root operations
```

参照元を明示する例:

```bash
alred overlay-change prepare-plan \
  --change-set ./changes/CHG-2026-00123/desired-changes.yaml \
  --reference-operation-id HC-20260731T033111-p0900-e0922b \
  --reference-phase rollback \
  --reference-max-age-days 30 \
  --operations-root operations
```

| option | 内容 | 既定値 |
|---|---|---|
| `--reference-state latest-known-good` | 対象機器を含む最新の正常な最終状態を自動選択 | なし |
| `--reference-operation-id <ID>` | 参照する過去operationを明示 | なし |
| `--reference-phase after\|rollback` | 明示operation内のphase。省略時は最終workflowまたは正常性成果物から決定 | 自動 |
| `--reference-max-age-days <DAYS>` | 参照Snapshotの最大経過日数 | `30` |
| `--allow-reference-state-warn` | Overlay terminal、または明示した standalone after の `WARN` を許可 | 無効 |

`--reference-state` と `--reference-operation-id` は相互排他です。rollback 済み Operation では
途中状態の after を使用せず、検証済み rollback を参照します。Overlay 変更 workflow を持たない
Health Check Operation でも、after が完了して HealthResult が `PASS`、compare 成果物がある場合は
compare も `PASS` で、対象機器の running-config と Overlay 解析証跡が揃っていれば参照できます。

既定は `PASS` のみです。`latest-known-good` で `--allow-reference-state-warn` を指定した場合は、workflow が
`completed` または `rolled_back_and_verified` の Overlay terminal Operation の `WARN` だけを自動選択候補に
含めます。standalone Health Check の `WARN` は、対象を `--reference-operation-id` で明示し、さらに
`--allow-reference-state-warn` を指定した場合だけ許可します。`FAIL`、`UNKNOWN` は許可しません。
`WARN` を採用すると、総件数、classification、Checklist path、明示許可 policy が `reference-state.json`、
execution plan、CLI に記録されます。warning は対象 device だけでなく、参照 Operation の HealthResult 全体を
表示します。

standalone Health Check の `WARN` を明示的に参照する例:

```bash
alred overlay-change prepare-plan \
  --change-set ./changes/CHG-2026-00123/desired-changes.yaml \
  --reference-operation-id HC-20260816T011401-p0900-dfb5d4 \
  --reference-phase after \
  --allow-reference-state-warn \
  --operations-root operations
```

prepare-plan は VLAN／L2VNI、VRF／L3VNI、同一 device・同一 VRF の SVI／routed interface／
loopback IP・prefix、既存 SVI 属性を検査し、結果を
`preparation/attempts/<attempt-id>/conflict-report.md` へ保存します。明確な競合は `CONFLICT`、
証跡不足は `UNKNOWN` として config 生成を停止します。同じ VLAN・VRF へ設定する vPC Leaf 間の
anycast gateway 重複は正常として扱います。

```text
=== OVERLAY PREPARATION PLAN ===
Change ID       : CHG-2026-00123
Reference       : HC-20260731T033111-p0900-e0922b (rollback)
Reference age   : 2.25 days
Conflict check  : PASS
Devices         : 4
Execution plan  : operations/live/2026/08/01/CHG-2026-00123/preparation/attempts/prepare-plan-.../execution-plan.json
Generated config: operations/live/2026/08/01/CHG-2026-00123/preparation/attempts/prepare-plan-.../generated-config
Apply            : BLOCKED (fresh before and normal plan required)
```

準備用planは`PREPARATION_ONLY`で、approveやapplyには使用できません。作業実施時はfresh beforeを
取得し、次節の通常planで同じ競合検査を再実行します。通常planのconfigまたはhashが準備用から
変わった場合は、通常planを改めてレビューしてください。

失敗したprepare-planは、同じコマンドを再実行すると新しいattempt IDで再試行されます。失敗済み
attemptの成果物とerrorは保持されます。成功済みattemptがある場合は暗黙に上書きせず停止します。
最新の成功attemptは`preparation/current.json`で確認できます。

## 12. before後に固定してplanで検証

beforeがPASSし、operationディレクトリが作成されたら、レビュー済みChangeSetとgroupファイルを
同じdirectoryへ保存します。

```bash
cp ./changes/CHG-2026-00123/desired-changes.yaml \
  operations/live/2026/08/01/CHG-2026-00123/desired-changes.yaml
cp ./changes/CHG-2026-00123/device-groups.fabric.yaml \
  operations/live/2026/08/01/CHG-2026-00123/device-groups.fabric.yaml
```

planは`device_groups_ref`をChangeSet基準で解決し、materializeしたChangeSetを`inputs/change-set.yaml`、
参照先を`inputs/device-groups.yaml`、展開結果を`plan/resolved-targets.yaml`へ自動固定します。

一ファイル形式の場合は`desired-changes.inline.yaml`だけを`desired-changes.yaml`として保存し、
groupファイルのコピーは不要です。

続いてplanを生成します。

```bash
alred overlay-change plan \
  --change-set operations/live/2026/08/01/CHG-2026-00123/desired-changes.yaml \
  --hosts ./hosts.lab.yaml \
  --operations-root operations
```

`--before`を省略すると、ChangeSetの`metadata.change_id`から同じoperationの最新成功beforeを
自動解決します。別operationのSnapshotを検索・流用する動作ではありません。解決対象は
`health/before/current.json`が指す最新成功attemptで、最新retryが失敗中または実行中、hash不一致、
HealthResultが`FAIL` / `UNKNOWN`、必要な継続判断が未承認の場合は停止します。

pathを明示して監査したい場合は次のように指定できますが、古いattemptを強制利用するoverrideには
なりません。

```bash
alred overlay-change plan \
  --change-set operations/live/2026/08/01/CHG-2026-00123/desired-changes.yaml \
  --before operations/live/2026/08/01/CHG-2026-00123/health/before/snapshot.json \
  --hosts ./hosts.lab.yaml \
  --operations-root operations
```

planではschemaだけでなく、対象機器、Capability、VLAN / VNI / VRF / IPを含む既存設定との
競合、BGP process、route-map、global ingress replicationなどをfresh beforeに対して再検証し、
`plan/conflict-report.json` / `.md`と機器別forward／rollback config、hashを生成します。

plan生成後にChangeSetを直接編集しないでください。修正が必要な場合は作業用ChangeSetを修正し、
beforeからの経過時間と既存状態を確認したうえでplanを再生成します。承認後にChangeSet、plan、
inventory、configのhashが変わった場合、applyは拒否されます。

次の手順は[alredによるVNI設定投入](./08_ALRED_OVERLAY_CHANGE_APPLY.md)のbefore以降を参照してください。
