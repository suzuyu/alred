# Overlay Change Management Design

## 1. 文書の目的

L2VNI / L3VNI の追加設定、作業前後の状態収集、正常性確認を一連のオーバーレイ変更として扱う機能の初期設計を定義する。

共通の収集世代管理、Snapshot、before / after比較、判定結果、収束待ち、レポートについては[Health Check Framework Design](./HEALTH_CHECK_FRAMEWORK_DESIGN.md)を正本とする。本書はOverlay ChangeSet、VNI自動発見、NX-OS EVPN/VXLAN固有の収集・判定、設定投入workflowを定義する。NX-OSコマンドへの変換は[NX-OS Overlay Config Rendering Design](./NXOS_OVERLAY_CONFIG_RENDERING_DESIGN.md)、障害ログを人またはAIへ引き渡すarchiveは[Support Bundle Design](./SUPPORT_BUNDLE_DESIGN.md)を正本とする。

- 作業後に新規追加された L2VNI / L3VNI と付随情報を自動検出する
- 新規リソースが、観測できた範囲で正常に動作しているか確認する
- 作業前から存在するオーバーレイへ悪影響がないか確認する
- 手動または外部システムによる設定投入と、alred 内での設定投入を同じ評価方式で扱う
- 実施予定、実行実績、収集結果、判定根拠をファイルとして保存する

初期対象プラットフォームは NX-OS とする。

## 2. 基本方針

設定投入と正常性確認を分離し、共通Health Check Frameworkを利用する。Overlay変更管理として、以下を独立したコンポーネントとして扱う。

1. Overlay Profile: NX-OS EVPN/VXLAN用の収集コマンドとparserを提供する
2. Overlay Snapshot Extension: 共通Snapshotのprofile namespaceへOverlay状態を格納する
3. Overlay Change Detector: before / afterからVNI、VLAN、VRF、SVIの変更を抽出する
4. ChangeSet Loader: 明示または自動検出されたOverlay ChangeSetを読み込む
5. Overlay Evaluator: 新規リソースの正常性と既存オーバーレイへの影響を判定する
6. Config Renderer / Applier: 同じChangeSetから設定を生成・投入する

Overlay専用のCollectorは原則として新設しない。共通Health Check Frameworkを通じて、既存の `collect-clab`、`collect-list`、`collect-all`、`collect-before-work`、`collect-after-work`を収集基盤として共用する。

Overlay機能は既存collect成果物を入力とし、共通SnapshotへOverlay固有状態を追加する。正常・異常の判定はcollect処理に含めない。

```text
既存 collect-* コマンド
    ↓
rawログ・JSON sidecar・running-config
    ↓
Common Snapshot Builder + Overlay Parser
    ↓
Common Snapshot / profiles.nxos-overlay
    ↓
Overlay Change Detector / Evaluator
```

`overlay-check`または`overlay-change`が機器からの取得も行う場合は、内部で共通`health-check`を呼び出すオーケストレーターとする。収集済みログだけを入力にして、オフラインでSnapshot生成や再評価を行う方式も提供する。

## 3. 対応する実行方式

### 3.1 外部・手動投入（自動発見）

```text
before 取得
    ↓
手動または外部システムで設定投入
    ↓
after 取得
    ↓
before / after から discovered ChangeSet を生成
    ↓
新規リソースと既存環境への影響を評価
```

投入内容を事前入力しないため、確認できるのは「実際に新規出現したリソースが、観測範囲で正常か」である。本来投入されるべき機器に設定がまったく入らなかったケースは、明示的な期待値なしでは確定検出できない。

このモードの最高判定は `OBSERVED_HEALTHY` とし、期待状態まで確認した `VERIFIED` と区別する。

実行例:

```bash
# 1. 既存collect処理を呼び出してbeforeを収集し、Snapshotを生成
alred overlay-check before \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --collect \
  --output operations/CHG-2026-00123

# 2. この間に手動または外部システムで設定を投入

# 3. afterを収集し、新規リソースの発見、収束待ち、正常性評価を実行
alred overlay-check after \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --collect \
  --discover \
  --wait-until-stable 300 \
  --output operations/CHG-2026-00123
```

### 3.2 外部投入（期待値あり）

利用者または外部システムから expected ChangeSet を受け取り、after で観測した discovered ChangeSet と比較する。

実行例:

```bash
# 1. expected ChangeSetを検証し、実施計画を生成
alred overlay-check plan \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --plan expected-changes.yaml \
  --output operations/CHG-2026-00123

# 2. expected ChangeSetを関連付けてbeforeを収集
alred overlay-check before \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --plan expected-changes.yaml \
  --collect \
  --output operations/CHG-2026-00123

# 3. 外部システムで設定投入後、期待値との比較を含むafter確認を実行
alred overlay-check after \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --plan expected-changes.yaml \
  --collect \
  --wait-until-healthy 300 \
  --output operations/CHG-2026-00123
```

### 3.3 alred 内での設定投入

```text
投入内容から expected ChangeSet を生成
    ↓
before 取得・事前確認
    ↓
設定生成・投入
    ↓
after 取得
    ↓
discovered ChangeSet を生成
    ↓
expected / discovered 比較と正常性評価
```

この方式で使用する expected ChangeSet の `metadata.source` は、投入を alred 内で実行するという理由だけでは決めない。ChangeSet の作成経路に従って次のように設定する。

- 利用者が作成した、または利用者が内容を確認・承認した ChangeSet: `declared`
- alred が別の設定ファイルや入力形式から機械的に生成し、まだ利用者が期待状態として承認していない ChangeSet: `generated`
- 外部システムから受け取った未検証の ChangeSet: `imported`

初期実装で想定する標準フローは、利用者が `metadata.source: declared` の ChangeSet を指定し、
alred が validation、before確認、設定生成・投入、after確認を実行する方式とする。alredが
生成した`generated` ChangeSetを利用する場合は、投入前に内容を提示し、期待状態として採用した
ChangeSetを`declared`として保存する。この操作はplanの実機投入承認とは区別する。

設定投入後に before / after から生成される実績側の ChangeSet は、投入に使った expected ChangeSet の source にかかわらず `metadata.source: discovered` とする。

標準的な実行例:

```bash
# 1. beforeを取得して基準状態を固定
alred health-check before \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --collect \
  --output operations/CHG-2026-00123

# 2. declared ChangeSetとbeforeを検証し、forward / rollback planを生成
alred overlay-change plan \
  --hosts hosts.yaml \
  --change-set desired-changes.yaml \
  --operations-root operations

# 3. execution-plan、rollback-plan、resolved-targets、生成configを確認し、operationを承認

# 4. approval recordを生成
alred overlay-change approve \
  --change-id CHG-2026-00123

# 5. 承認したplanを使って設定投入、after確認を連続実行
alred overlay-change apply \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --change-set desired-changes.yaml \
  --approved-plan operations/CHG-2026-00123/plan/execution-plan.json \
  --approved-rollback-plan operations/CHG-2026-00123/plan/rollback-plan.json \
  --approval-record operations/CHG-2026-00123/approval/approval-record.json \
  --health-check \
  --wait-until-healthy 300 \
  --save-on-success \
  --output operations/CHG-2026-00123
```

`generated`または`imported` ChangeSetを期待状態として採用する場合の例:

```bash
alred overlay-change-set promote \
  --input generated-changes.yaml \
  --output desired-changes.yaml
```

`promote`はChangeSetの来歴を`declared`へ変更する操作であり、実機applyを許可しない。
実機applyには別途`overlay-change approve`で生成するapproval recordが必要である。

すべての方式で、評価エンジンへ渡す ChangeSet の `spec` は同じフォーマットとする。

### 3.4 過去の正常状態を使う準備用plan

作業前準備の段階で機器へアクセスせず、生成configと競合候補を確認するため、
`overlay-change prepare-plan`を提供する。通常`plan`の`--before`へ過去operationのSnapshotを
直接指定する方式にはしない。準備結果を投入可能な承認対象と誤認させず、投入直前のfresh
beforeと再検査を必須にするためである。

```bash
# operations-root内から最新の正常な最終状態を自動選択
alred overlay-change prepare-plan \
  --change-set desired-changes.yaml \
  --reference-state latest-known-good \
  --reference-max-age-days 30 \
  --operations-root operations

# 過去operationとphaseを明示
alred overlay-change prepare-plan \
  --change-set desired-changes.yaml \
  --reference-operation-id HC-20260731T033111-p0900-e0922b \
  --reference-phase rollback \
  --operations-root operations
```

`--reference-state`と`--reference-operation-id`は相互排他かつ一方を必須とする。初期実装で
`--reference-state`が受け付ける値は`latest-known-good`だけとする。
`--reference-operation-id`指定時の`--reference-phase`は`after`または`rollback`で、省略時は
operationの最終workflowまたは正常性確認成果物から決定する。`rolled_back_and_verified`では
`rollback`、`completed`では`after`だけを正常な最終状態として許可し、rollback済みoperationの
`after`は拒否する。Overlay変更workflowを持たないstandalone health-check operationは、after
phaseが完了し、after HealthResultが`PASS`で、compare成果物が存在する場合はその結果も`PASS`、
かつ後述の証跡条件を満たす場合に`after`を参照できる。

自動選択はdirectory名ではなくSnapshotの`created_at`で比較し、次をすべて満たす候補から
最新を選択する。

- 対象deviceをすべて含み、各deviceに`nxos-overlay.config`とrunning-config証跡がある
- 対応するHealthResultの総合結果が`PASS`
- `after`候補はworkflow `completed`、またはworkflow未開始のstandalone health-checkでafterが完了し
  HealthResultが`PASS`。compare成果物が存在する場合はcompareも`PASS`
- `rollback`候補はworkflow `rolled_back_and_verified`
- Snapshot、ChangeSet、parser / schemaが現行readerで解釈可能
- 現在のChangeSet operation自身を参照しない

`--reference-max-age-days`の既定値は`30`とする。基準時刻は実行環境の設定timezoneでの実行時刻、
経過時間はtimezone付き`created_at`との差とする。超過時は`REFERENCE_STATE_STALE`で停止する。
初期実装では古い状態を強制利用するoptionを設けず、明示operation指定でも同じ制限を適用する。

参照Snapshotはsourceのchange IDを書き換えて保存しない。source path / operation ID / phase /
created_at / age / SHA-256を
`preparation/attempts/<attempt-id>/reference-state.json`へ固定し、render時だけ現在のChangeSet
change IDへ関連付けたin-memory viewを使用する。

準備用成果物は`preparation/attempts/<attempt-id>/`へattempt単位で保存し、成功attemptだけを
`preparation/current.json`から参照する。失敗、cancel、unknownのattemptは削除・上書きせず、同じ
change IDで新しいattempt IDを自動採番して再実行できる。実行中attemptまたは成功済みattemptが
ある場合は暗黙に再実行しない。失敗時はerror code、message、attempt ID、時刻をoperation execution
とattempt resultへ記録する。

準備用成果物は`PREPARATION_ONLY`であり、`approve`、`apply`、`rollback`の入力として使用不可と
する。後続の`health-check before`と通常`overlay-change plan`は同じoperationで実行でき、fresh
beforeに対して競合検査とrenderを再実行する。準備用と通常planのhashが異なる場合は通常planを
新たにレビュー・承認する。

### 3.5 通常planのbefore自動解決

`overlay-change plan`の`--before`は任意とする。省略時はChangeSetの
`metadata.change_id`から`operations/<change-id>/`を一意に決定し、そのoperationの最新beforeを
使用する。`operations/`配下の別operationを時刻順に検索したり、ChangeSet以外からchange IDを
推測したりしない。

attempt対応operationでは`health/before/current.json`を正本のpointerとし、次をすべて確認する。

- `current.json`、operation metadata、Snapshot、HealthResultのschemaとchange IDが一致する
- metadataの`before.current_attempt`が`current.json`のattempt IDと一致し、phaseが
  `completed`または`completed_with_warnings`である
- attempt配下と公開済み`health/before/snapshot.json`のSHA-256が`current.json`と一致する
- Snapshotのphaseが`before`で、profile hashが`current.json`と一致する
- HealthResultが`PASS`または`WARN`である。`FAIL`、`UNKNOWN`、その他の結果は拒否する
- operation gateが必要な場合は、保存済みdecisionが`continue`である

最新attemptが実行中または失敗してmetadataの`current_attempt`と成功済みpointerが一致しない場合、
古い成功attemptへ暗黙に後退せず停止する。`current.json`導入前のoperationは、before phaseが完了し、
公開済みSnapshotとHealthResultが上記の状態条件を満たす場合だけlegacy成果物として使用できる。

`--before`を明示した場合も、指定可能なpathは同じoperationの公開済み
`health/before/snapshot.json`だけとし、上記の最新性・hash・正常性検査を省略しない。このoptionは
自動解決結果を明示して監査しやすくするためのものであり、古いattemptや別operationを強制利用する
overrideではない。planの端末出力には解決方法、attempt ID、Snapshot path、HealthResultを表示し、
Execution PlanとRollback Planには解決後の公開済みSnapshot pathを固定する。

## 4. ChangeSet フォーマット

### 4.1 基本構造

```yaml
api_version: alred/v1
kind: OverlayChangeSet

metadata:
  change_id: CHG-2026-00123
  source: declared
  generated_at: "2026-07-19T10:30:00+09:00"

spec:
  device_groups_ref:
    path: ./device-groups.fabric.yaml
  l2vnis: []
  l3vnis: []

```

- `spec`: 設定投入と正常性確認で共通利用する構成情報
- `status`: `discovered`で使用する発見根拠、実測状態、競合、正常性確認結果。設定生成には使用しない
- `metadata.source`: ChangeSet がどの経路で作成されたかを記録する

#### metadata.source

初期実装では、`metadata.source` に次の値を使用する。

| 値 | 作成元 | 主な用途 | 期待状態としての扱い | 設定投入での扱い |
|---|---|---|---|---|
| `discovered` | before / after の観測差分から alred が自動生成 | 外部・手動投入後の変更検出と正常性確認 | 観測された変更であり、設計上の期待値とはみなさない | 利用者による確認・昇格なしでは直接使用しない |
| `declared` | 利用者が作成、または利用者が確認・承認 | 作業計画、完全な期待状態との比較 | 正式な期待状態として扱う | plan validation 成功後に使用可能 |
| `generated` | alred が投入用config、既存入力、または内部処理から生成 | alred 内での設定投入と投入前後確認 | 生成元が投入対象として確定していれば期待状態として扱う | 生成元、対象、解決済み内容を検証したうえで使用可能 |
| `imported` | 外部システム、API、別ツールから取り込み | 外部オーケストレーターとの連携 | 取り込み直後は未検証。schema、対象、承認状態を検証後に期待状態として扱う | 取り込み元だけを根拠に直接使用せず、validation または承認を要求する |

各値の詳細は以下のとおり。

##### `discovered`

機器から取得した before / after snapshot の差分を基に自動生成された ChangeSet を示す。

- 実際に観測された新規L2VNI / L3VNI、VLAN、VRF、SVIなどを`spec`へ格納する
- 発見根拠、観測値、競合、確度を`status`へ格納する
- 投入意図を表すものではないため、最高判定は原則`OBSERVED_HEALTHY`とする
- 本来の対象機器、VNI番号、route-targetなどが設計どおりかは保証しない
- 設定投入へ再利用する場合は、利用者が内容を確認して`declared`へ昇格する

##### `declared`

利用者が期待状態として明示した、または自動発見結果を利用者が確認・承認した ChangeSet を示す。

- 正常性確認では正式な expected ChangeSet として使用する
- discovered ChangeSetとの比較により、未投入、部分投入、予定外変更を判定できる
- schema、group展開、VLAN解決、対象ホスト、競合などのplan validationを必須とする
- 設定投入に使用する場合も、実行直前に解決済み内容を提示・保存する

##### `generated`

alred が別の信頼できる入力から機械的に生成した ChangeSet を示す。想定する生成元は次のとおり。

- alred 内で投入予定のconfig
- `generate-vni-map`などの共通Overlay State Model
- approved済みの別フォーマット
- config生成処理が構築した内部の期待状態

`generated`は`discovered`と異なり、投入前に生成される場合がある。ただし、自動生成されたという事実だけでは承認済みを意味しない。`metadata`に生成元とそのhashを保存し、期待状態または設定投入に使える生成元かを検証する。

##### `imported`

外部システムから受け取った ChangeSet を示す。例として、NDFC、Ansible、CI/CD、変更管理システム、独自APIからの入力を想定する。

- 取り込み元を`metadata.import`へ記録する
- schema version、対象inventory、device group、値の範囲を検証する
- 外部システム側の承認状態を受け取る場合も、alred側のplan validationは省略しない
- 未検証の`imported` ChangeSetは設定投入に直接使用しない

推奨する追加metadataの例:

```yaml
metadata:
  change_id: CHG-2026-00123
  source: imported
  imported_at: "2026-07-19T10:00:00+09:00"
  import:
    system: ndfc
    reference: deployment-12345
    content_hash: sha256:0123456789abcdef
```

`source`は来歴を示す値であり、安全性や承認状態そのものを表さない。設定投入の承認は
ChangeSet内の`metadata.approval`ではなく、[Operation State and Approval Design](./OPERATION_STATE_AND_APPROVAL_DESIGN.md)
で定義する独立した`approval-record.json`で管理する。

自動検出した ChangeSet を設定投入へ利用する場合、投入処理は `spec` だけを使用する。誤投入防止のため、discovered ChangeSet を利用者が確認し、declared ChangeSet へ昇格する操作を設けることを推奨する。

### 4.2 完全例

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
    - vni: 10010
      default_vlan: 10
      vlan_name: TENANT-A-WEB
      vrf: TENANT-A
      l3vni: 50001

      svi:
        mtu: 9216
        ipv4_addresses:
          - 192.0.2.1/24
        ipv6_addresses:
          - 2001:db8:10::1/64
        ipv6_link_local: fe80::1
        ipv6_nd_suppress_ra: true
        gateway_mode: anycast

      targets:
        groups:
          server-leafs: {}
          storage-leafs:
            vlan: 110
          border-leafs:
            vlan: 210
            svi: false

        devices:
          leaf03:
            vlan: 12
          leaf12:
            svi: false

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
          border-leafs: {}
```

`l3vnis[].mode`は省略可能で、既定値は`new_l3vni`とする。選択可能な値は`new_l3vni`と`traditional_vlan_svi`である。`traditional_vlan_svi`を選択した場合だけ、L3VNIにも`default_vlan`またはgroup / deviceの`vlan`を指定する。modeごとのconfig生成仕様は[NX-OS Overlay Config Rendering Design](./NXOS_OVERLAY_CONFIG_RENDERING_DESIGN.md)を正本とする。

`l3vnis[].address_families`には`ipv4`、`ipv6`の一方または両方を指定する。各AFでは以下を指定できる。

| 項目 | 省略時 | 内容 |
|---|---|---|
| `advertise_l2vpn_evpn` | `true` | `advertise l2vpn evpn`を生成 |
| `redistribute_direct.enabled` | `true` | connected/direct routeをBGPへ再配布 |
| IPv4 `redistribute_direct.route_map` | `IPv4_REDISTRIBUTE_ALL` | IPv4 `redistribute direct`で参照 |
| IPv6 `redistribute_direct.route_map` | `IPv6_REDISTRIBUTE_ALL` | IPv6 `redistribute direct`で参照 |
| `redistribute_static.enabled` | `true` | static routeをBGPへ再配布 |
| IPv4 `redistribute_static.route_map` | `IPv4_REDISTRIBUTE_ALL` | 省略時はIPv4 directと同じroute-map |
| IPv6 `redistribute_static.route_map` | `IPv6_REDISTRIBUTE_ALL` | 省略時はIPv6 directと同じroute-map |
| `maximum_paths_ibgp` | `4` | BGP VRF AFのiBGP ECMP数 |

`advertise_l2vpn_evpn: false`、`redistribute_direct.enabled: false`、`redistribute_static.enabled: false`は初期実装では`UNSUPPORTED`とする。route-map本体は既存Fabric設定としてalredでは作成せず、対象機器に解決済み名称がなければ`PLAN_ERROR`とする。

`address_families`全体を省略した場合は、同じL3VNIを参照するL2VNI Gateway SVIからAFを導出する。新規VRFで導出できない場合は`PLAN_ERROR`とする。

BGP local ASはChangeSetへ指定せず、対象機器のbefore running-configから取得する。既存BGP process、neighbor、router-id、`network`、direct/static以外のredistribution、eBGP maximum-pathsはFabric前提として維持する。今回生成対象にするのは、解決済みAFの`advertise l2vpn evpn`、`redistribute direct route-map`、`redistribute static route-map`、`maximum-paths ibgp`に限定する。

## 5. device group

### 5.1 目的と責務

VTEP leafをVNIごとに列挙せず、vPCペア、用途、siteなどの安定した所属を共通groupで定義し、
ChangeSetでは`server-leafs`、`storage-leafs`など作業対象だけを選択できるようにする。

device groupファイルは「機器の所属関係」だけを保持する。VLAN、SVI、VNI、VRFなど変更ごとの
値は持たせず、ChangeSetのリソース共通値と`targets.groups` / `targets.devices`で指定する。
初期対象は明示的なdeviceおよび子groupであり、inventoryのrole、site、selectorからの動的選択は
将来拡張とする。

### 5.2 外部device groupファイル

宣言済みChangeSetの標準形式では、`spec.device_groups_ref.path`から専用YAMLを参照する。

```yaml
# desired-changes.yaml
spec:
  device_groups_ref:
    path: ./device-groups.fabric.yaml
  l2vnis: []
  l3vnis: []
```

参照先は独立した`OverlayDeviceGroups` Kindとする。

```yaml
api_version: alred/v1
kind: OverlayDeviceGroups
metadata:
  name: fabric-a
spec:
  device_groups:
    vpc-leaf-pair-01:
      devices:
        - leaf01
        - leaf02
    vpc-leaf-pair-02:
      devices:
        - leaf03
        - leaf04
    vpc-leaf-pair-11:
      devices:
        - leaf11
        - leaf12
    vpc-border-pair-01:
      devices:
        - border01
        - border02
    server-leafs:
      groups:
        - vpc-leaf-pair-01
        - vpc-leaf-pair-02
    storage-leafs:
      groups:
        - vpc-leaf-pair-11
    border-leafs:
      groups:
        - vpc-border-pair-01
    all-vtep-leafs:
      groups:
        - server-leafs
        - storage-leafs
        - border-leafs
```

各groupは`devices`、`groups`の一方または両方を持ち、少なくとも一つのmemberを必要とする。
各list内は空文字列を許可せず、同一要素の重複を拒否する。group名は同じdocument内で一意とする。

### 5.3 参照パスと入力固定

`device_groups_ref.path`はChangeSetファイルの親directoryを基準に解決する。current working
directory基準、環境変数展開、glob、URL取得は使用しない。初期実装では相対pathだけを許可し、
参照先は存在する通常ファイルでなければならない。symlinkは参照先のすり替え防止のため拒否する。

planは次を順番に行う。

1. ChangeSetの構文とschemaを検証する。
2. 参照pathを解決し、`OverlayDeviceGroups` schemaを検証する。
3. groupを再帰展開し、inventoryおよびbefore Snapshotと照合する。
4. source bytesのSHA-256と、schema検証・展開後のcanonical SHA-256を計算する。
5. materializeしたChangeSetを`inputs/change-set.yaml`、検証済みgroup documentを
   `inputs/device-groups.yaml`へ正規化して固定する。
6. 参照元path、hash、schema versionを`plan/input-manifest.json`へ記録する。
7. 機器単位の結果と展開元group chainを`plan/resolved-targets.yaml`へ保存する。

通常`plan`と`prepare-plan`は同じ競合検査器を使用する。ChangeSet内部および入力Snapshotに
対して、少なくとも次を機器単位・VRF単位で検査する。

- 同一VLANの異なるL2VNI利用、同一L2VNIの異なるVLAN利用
- 同一VRFの異なるL3VNI利用、同一L3VNIの異なるVRF利用
- VLAN name、VRF、MTU、IPv6 link-local、RA suppress、anycast gatewayの既存値との競合
- 同一device・同一VRFの別SVI、routed interface、loopbackにおけるIP address重複またはprefix overlap
- ChangeSet内の同一deviceに対するVLAN、VNI、VRF、SVI IPの矛盾
- NVE member、EVPN VNIと既存mappingの競合

同じChangeSetで同一VLAN / VRF / prefixへ配置する複数VTEPの同一anycast gateway addressは
正常として許可する。異なるVRF間の同一address / prefixもVRF分離されるため許可する。
明確な競合は`CONFLICT`、必要なtargetまたはOverlay config証跡がない場合は`UNKNOWN`とし、
いずれもconfig生成と通常applyをfail closedで停止する。結果は通常planでは
`plan/conflict-report.json`と`plan/conflict-report.md`、準備用では`preparation/`配下の同名
ファイルへ保存する。

apply、after、evaluate、rollbackは元の外部ファイルを再読込せず、承認対象として固定した
`input-manifest.json`と`resolved-targets.yaml`を使用する。元ファイルがplan後に変化しても対象を
変更しない。planを再作成する場合は現在の外部ファイルを再検証し、新しいhashを承認対象とする。

### 5.4 groupの階層展開

`groups`は同じdocument内の別groupを参照できる。vPCペアを最小単位とし、その上に用途別group、
さらに全VTEP groupを定義できる。展開は深さ優先で行い、最終的にhostnameの集合へ正規化する。

```text
all-vtep-leafs
├── server-leafs
│   ├── vpc-leaf-pair-01
│   │   ├── leaf01
│   │   └── leaf02
│   └── vpc-leaf-pair-02
│       ├── leaf03
│       └── leaf04
├── storage-leafs
│   └── vpc-leaf-pair-11
│       ├── leaf11
│       └── leaf12
└── border-leafs
    └── vpc-border-pair-01
        ├── border01
        └── border02
```

次をvalidation errorとする。

- 存在しない子groupの参照
- 自分自身の直接参照
- 複数groupを経由して元へ戻る循環参照
- 16階層を超える参照
- 展開後にdeviceが一つもないgroup
- inventoryまたはbefore Snapshotに存在しないhostname

同じdeviceへ複数の経路で到達した場合は一台へdeduplicateするが、`resolved-targets.yaml`には
すべてのgroup chainを根拠として残す。config生成と実行順はhostnameで安定sortし、YAMLの
mapping順序へ依存させない。

### 5.5 対象機器とoverrideの解決

対象機器は以下の和集合である。

```text
targets.groups で選択されたgroupの展開結果
    ∪
targets.devices で指定された機器
```

機器単位の値は次の優先順位で解決する。

```text
targets.devices.<hostname> の override
    ↓
targets.groups.<group-name> の override
    ↓
リソース共通値
```

同一機器が複数の選択groupから同一overrideを受ける場合は許可する。異なるgroup overrideを
受ける場合は`PLAN_ERROR`とする。ただし、`targets.devices.<hostname>`に明示overrideがあれば、
その値で意図的な例外として解決する。group定義の親子関係自体はoverrideを継承せず、ChangeSetで
実際に選択した`targets.groups`のoverrideだけを適用する。

未定義group、対象が空になるresource、VLANを最後まで解決できない対象は`PLAN_ERROR`とする。

machine-readable errorは、参照先不存在を`INPUT_NOT_FOUND`、schema・未知group・循環・階層超過を
`VALIDATION_ERROR`、異なるgroup overrideの衝突を`PLAN_CONFLICT`とする。plan後の固定hash不一致は
`PLAN_STALE`、承認後のhash不一致は`APPROVAL_INVALID`として設定投入前に停止する。

### 5.6 inline形式の後方互換性

既存`OverlayChangeSet.spec.device_groups`は同じ`alred/v1`で継続して受け付ける。自動発見した
`discovered` ChangeSetは単体で解析できるよう、原則としてinline形式を使用する。

`spec.device_groups`と`spec.device_groups_ref`は相互排他とし、両方指定、または両方未指定を
validation errorとする。inline groupにも`devices` / `groups`と同じ階層規則を適用する。
外部参照を標準とするが、既存inline ChangeSetの意味や解決結果は変更しない。

## 6. VLAN の共通値と override

L2VNI、および`mode: traditional_vlan_svi`のL3VNIでは、共通 VLAN を`default_vlan`で表現する。機器またはgroupに`vlan`が指定されている場合は、その値を優先する。既定の`mode: new_l3vni`ではL3VNI専用VLANを使用しないため、L3VNIの`default_vlan`と`targets.*.vlan`は指定不可とし、指定されていれば`PLAN_ERROR`とする。

```text
targets.devices.<hostname>.vlan
    ↓ 未指定なら
targets.groups.<group-name>.vlan
    ↓ 未指定なら
default_vlan
    ↓ すべて未指定なら
PLAN_ERROR
```

例:

```yaml
default_vlan: 10

targets:
  groups:
    server-leafs: {}
    storage-leafs:
      vlan: 110

  devices:
    leaf03:
      vlan: 12
```

- `server-leafs`: VLAN 10
- `storage-leafs`: VLAN 110
- `leaf03`: VLAN 12

比較処理では圧縮された表現を機器単位へ展開してから比較する。`default_vlan`による表現と、全機器へ個別に同じ VLAN を書いた表現は同一状態として扱う。

自動発見時は以下のように圧縮する。

- 全対象機器で同じ VLAN: `default_vlan` を使用
- 一意の最頻値が2台以上に存在: 最頻値を `default_vlan` とし、例外を override
- 一意の最頻値がない: すべて機器単位で記載

## 7. SVI

### 7.1 有効条件

`svi`にはIPv4、IPv6のどちらか一方、または両方を指定できる。

有効:

```yaml
svi:
  ipv4_addresses:
    - 192.0.2.1/24
  gateway_mode: anycast
```

```yaml
svi:
  ipv6_addresses:
    - 2001:db8:10::1/64
  gateway_mode: anycast
```

```yaml
svi:
  ipv4_addresses:
    - 192.0.2.1/24
  ipv6_addresses:
    - 2001:db8:10::1/64
  gateway_mode: anycast
```

`ipv4_addresses`と`ipv6_addresses`が両方とも未指定または空の場合は、初期実装では `PLAN_ERROR` とする。L2-only VNI は `svi`自体を記載しない。

`ipv6_addresses`が1つ以上ある場合は`ipv6_link_local`と`ipv6_nd_suppress_ra`を指定できる。
`ipv6_link_local`の省略時は`fe80::1`、`ipv6_nd_suppress_ra`の省略時は`true`とする。
`ipv6_nd_suppress_ra: true`では`ipv6 nd suppress-ra`を生成し、`false`では生成しない。
IPv4-only SVIでは両項目を指定不可とし、指定されていれば`PLAN_ERROR`とする。

```yaml
svi:
  ipv6_addresses:
    - 2001:db8:10::1/64
  ipv6_link_local: fe80::a
  ipv6_nd_suppress_ra: false
  gateway_mode: anycast
```

link-local値は`fe80::/10`内のIPv6 addressでなければならない。両項目はSVI共通値とし、
group / device単位のoverrideは許可しない。既存SVIの実際のRA suppress状態と指定値が異なる
場合、通常のOverlay追加では設定を暗黙変更せず`PLAN_ERROR`とする。

`svi.mtu`は省略可能で、既定値は`9216`とする。値はSVI共通属性として扱い、初期実装ではgroup / device単位のMTU overrideは許可しない。

```yaml
svi:
  mtu: 9000
  ipv4_addresses:
    - 192.0.2.1/24
  gateway_mode: anycast
```

明示指定がなければ、生成される新規SVIには`mtu 9216`を設定する。`svi`自体を記載しないL2-only対象、および既定の`new_l3vni`にはMTU設定を生成しない。`traditional_vlan_svi`のL3VNI用SVIには同じ既定値を適用する。物理interface、port-channel、NVE、loopback、system jumbo MTUはこのChangeSetの変更対象外とする。

`traditional_vlan_svi`で既定値以外を使う場合は、L3VNIにもSVI属性として指定する。

```yaml
l3vnis:
  - vni: 50001
    vrf: TENANT-A
    mode: traditional_vlan_svi
    default_vlan: 3001
    svi:
      mtu: 9000
```

このL3VNI用`svi`はforwarding SVIの属性であり、L2VNI用Gateway SVIと異なりIPv4 / IPv6 Gateway addressを要求しない。`new_l3vni`で`l3vnis[].svi`を指定した場合は`PLAN_ERROR`とする。

### 7.2 適用規則

- 共通 `svi` がない: 全対象機器で SVI を設定・要求しない
- 共通 `svi` がある: 原則として全対象機器へ同じ SVI を設定・要求する
- group または機器に `svi: false` がある: その対象では SVI を設定・要求しない
- override の省略: 共通 `svi` を継承する

```yaml
svi:
  ipv4_addresses:
    - 192.0.2.1/24
  gateway_mode: anycast

targets:
  groups:
    server-leafs: {}
    border-leafs:
      svi: false

  devices:
    leaf03:
      svi: false
```

初期実装では、group / device 配下の `svi` は `false` または省略だけを許可する。`true`や機器固有 SVI オブジェクトは対象外とする。

`svi: false`対象に実際の SVI が存在した場合の既定判定は `WARN` とし、ポリシーで `ignore` / `warn` / `fail` を選択可能にする。

### 7.3 共通性

初期実装では以下をVNIサービス共通として扱う。

- IPv4 Gateway
- IPv6 Gateway
- IPv6 link-local
- gateway mode
- MTU
- VRF
- VLAN名

SVIを持つ機器間で共通値が一致しない場合、discovered ChangeSet では任意の値を採用せず、`status.conflicts`へ機器別の観測値を保存する。

## 8. generate-vni-map との関係

既存の `generate-vni-map` が扱う以下の情報を共通 Overlay State Model に取り込む。

- `l3vni`
- `vrf`
- `l2vni`
- `gateway_ipv4`
- `gateway_ipv6`
- `device`
- `vlan`
- `vlan_name`

理想的な内部構造は以下とする。

```text
running-config / operational show output
    ↓
共通 Overlay Parser
    ↓
Canonical Overlay State
    ├── generate-vni-map CSV / Markdown
    ├── before / after snapshot
    ├── discovered-changes.yaml
    ├── 正常性評価
    └── generate-vni-config
```

現状の `generate-vni-map` は primary IPv4 と IPv6 を各1件保持する。共通モデルでは将来の secondary address を考慮し、`ipv4_addresses` / `ipv6_addresses`を配列として保持する。CSVは互換・閲覧用、YAML / JSONを正本とする。

### 8.1 Health Check VNI Mapping成果物

実効profileに`nxos-overlay`が含まれる場合、`health-check snapshot`は追加optionを
必要とせず各phaseに次を自動生成する。

- `overlay-state.yaml`: Snapshot内のCanonical Overlay Stateから生成した機械処理の正本
- `vni-map.md`: L2VNI / L3VNIと機器別差分を確認する人間向け一覧
- `vni-map.csv`: 既存`generate-vni-map`と表計算ツールのための機器単位互換表現

`health-check compare`は次を`health/report/`に自動生成する。

- `vni-map-diff.json`: before / after差分の機械処理用正本
- `vni-map-diff.md`: VNI単位の人間向け差分
- `vni-map-diff.csv`: 1行を1機器・1resource・1変更fieldとする派生表現

CSVの列は`change_type,resource_type,vni,vrf,device,field,before,after,status,`
`evidence_before,evidence_after`とする。`change_type`は`ADDED` / `REMOVED` /
`MODIFIED` / `CONFLICT` / `UNKNOWN`、`resource_type`は`L2VNI` / `L3VNI` /
`OVERLAY_STATE`を初期対象とする。複数addressや複合値はJSON配列またはJSON objectを
CSV field内にエスケープして保持する。

期待ChangeSetを入力しないHealth Checkでは変更の意図を断定できないため、
`status` は通常の観測差分を`OBSERVED`、観測値の矛盾を`CONFLICT`、証跡不足を
`UNKNOWN`とする。`EXPECTED` / `UNEXPECTED`は将来、declared ChangeSetと照合した
場合に限って付与する。初期実装のCSVはファイルサイズと確認性のため、
unchanged行を出力しない。

YAML / JSONはphase、生成日時、timezone、profile SHA-256、parser version、対象host、
running-configと`show nve vni`の証跡path / SHA-256を保持する。ロールによる
profile対象選択を導入した場合は、対象hostと対象外hostのrole / reasonも保持する。

現行の`generate-vni-map`と別のOverlay parserを増やさず、Canonical Overlay Stateから
Markdown / CSVを派生させる。before / afterの各mappingと差分は収集ではなく
Snapshotの派生成果物であり、追加の機器コマンドを実行しない。

### 8.2 collect成果物との共存

正常性確認の入力は、既存collectが保存した次の成果物とする。

- running-config
- `show_lists/<hostname>/<hostname>_shows.log`
- 利用可能なJSON sidecar
- `show logging`
- コマンド単位の成功・失敗情報

利用者指定の`show_commands.txt`とOverlay確認用の組み込みprofileをマージし、同一コマンドは1回だけ実行する。

```text
実効収集コマンド =
    collect-clab標準コマンド
    ∪ 利用者指定showコマンド
    ∪ overlay-nxos profile
```

既存の最新ミラーだけを読むと、異なる実行世代のファイルが混在する可能性がある。正常性確認では収集ごとに`collection_id`を付与し、実際に使用したファイルをmanifestへ固定する。

```yaml
collection_id: CHG-2026-00123-before-20260720T100000
change_id: CHG-2026-00123
phase: before
started_at: "2026-07-20T10:00:00+09:00"
completed_at: "2026-07-20T10:01:30+09:00"

hosts:
  leaf01:
    status: success
    files:
      running_config: config/old/20260720100000/leaf01_run.txt
      show_commands: show_lists/leaf01/old/20260720100000/leaf01_shows.log
```

Snapshot Builderはmanifestに記録されたファイルだけを読み取る。各値には、抽出元のファイル、コマンド、取得時刻、parser versionを関連付ける。必須データが欠ける場合は正常とみなさず`UNKNOWN`とする。

### 8.3 実行モード

収集と解析を分離し、次の両方をサポートする。

機器から収集してSnapshotを生成:

```bash
alred overlay-check before \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --collect
```

既存の収集済みログからSnapshotを生成:

```bash
alred health-check snapshot \
  --input raw-before \
  --input-format alred-collect \
  --phase before \
  --change-id CHG-2026-00123 \
  --profile nxos-overlay
```

収集済みbefore / afterだけを比較:

```bash
alred health-check compare \
  --before operations/CHG-2026-00123/health/before/snapshot.json \
  --after operations/CHG-2026-00123/health/after/snapshot.json
```

beforeで解決した`nxos-overlay` profileは`resolved-profiles.yaml`へ固定し、afterとcompareでは同じ内容を再利用する。Overlay自動発見後のVNI単位コマンドはprofile内の条件付き収集を具体化したものであり、別profileへの切替とは扱わない。

## 9. 自動発見

### 9.1 二段階収集

投入内容が不明なため、after は二段階で収集する。

1. Discovery collection
   - BGP EVPN summary
   - NVE interface / peer / VNI
   - VLAN
   - VRF
   - SVI
   - VRF / VNI mapping
2. Targeted collection
   - 新規検出VNIの詳細
   - 対象VLAN、VRF、SVI
   - remote VTEP
   - EVPN Type-2 / Type-3 / Type-5
   - route-target

### 9.2 変更検出

正規化した before / after の集合差分から以下を抽出する。

- 新規L2VNI / L3VNI
- 新規VLAN / VRF / SVI
- 既存リソースの変更
- 既存リソースの削除

L2 / L3 の分類根拠も `status.discovery`に保存する。根拠が矛盾する場合は `ambiguous`または`unknown-vni`とし、推測で確定しない。

### 9.3 group への圧縮

発見された機器集合が既知 group 全体と完全一致する場合だけ、`targets.groups`へ圧縮できる。groupの一部でしか検出されない場合は、観測した機器を`targets.devices`へ明記し、部分投入の可能性を`WARN`として報告する。

## 10. 正常性確認項目

### 10.1 収集の正常性

- TCP疎通、認証、enable
- 必須showコマンドの成功
- 空出力、タイムアウト
- パース成功
- 必須フィールドの取得

判定不能を正常と扱わず、`UNKNOWN`として区別する。

### 10.2 基盤

- BGP EVPN neighbor が Established
- NVE interface が up
- 既存 NVE peer が up
- VTEP loopback が up
- VTEP 宛 underlay route が存在
- 既存 VNI、SVI、VRF が悪化していない
- 重大ログが新規発生していない

### 10.3 新規L2VNI

- L2VNIとして一意に分類できる
- 解決後VLANが各対象機器に存在し active
- VLAN / VNI mappingが正しい
- VLAN名、VRF、Gatewayの共通性
- NVEにVNIが存在し、stateがup
- NVEに`global ingress-replication protocol bgp`が設定済み
- 対象VNIに競合するper-VNI ingress replicationまたはmulticast設定がない
- 複数VTEPへ配置されたことが観測または宣言されている場合、remote VTEPまたはingress-replication peerが存在
- 複数VTEP構成でEVPN control planeを使用する場合、対象VNIに対応するType-3（IMET）routeが存在
- 必要に応じてType-2 route / MACを確認
- SVI対象機器ではSVIが存在しup/up
- IPv4 / IPv6 Gatewayが観測値と一致
- IPv6 SVIではlink-localが解決済み期待値（省略時`fe80::1`）と一致
- SVI MTUが解決済み期待値と一致

### 10.4 新規L3VNI

- L3VNIとして一意に分類できる
- VRF / VNI mappingが正しい
- L3VNI modeを`new_l3vni`または`traditional_vlan_svi`として一意に分類できる
- `new_l3vni`ではL3VNI専用VLAN / SVIを正常条件にしない
- `traditional_vlan_svi`では解決後のL3VNI用VLANとSVIが存在し、mappingが正しい
- NVEにassociate-vrfとして存在し、stateがup
- route-targetに明らかな不整合がない
- 対象機器の既存BGP processとlocal ASを一意に確認できる
- 解決済みIPv4 / IPv6 AFが`router bgp <AS>`配下の対象VRFに存在する
- 対象BGP VRF AFに`advertise l2vpn evpn`が存在する
- 対象BGP VRF AFに、解決済みroute-mapを参照する`redistribute direct`が存在する
- 対象BGP VRF AFに、解決済みroute-mapを参照する`redistribute static`が存在する
- 対象BGP VRF AFの`maximum-paths ibgp`が解決済み値（省略時4）と一致する
- 参照するroute-map本体が存在する
- IP prefixをEVPNへ広告する構成または期待値がある場合、対象VRFのType-5 routeが存在
- VRF routeを取得できる

### 10.5 既存環境への影響

- 既存BGP EVPN neighborの悪化
- 既存NVE peerのdown
- 既存VNI / VLAN / VRF / SVIの消失またはdown
- 既存EVPN routeの異常な減少
- 作業対象外の変更
- 新規重大ログ

### 10.6 NX-OS収集・判定プラン

以下の出力例はCisco Nexus 9000 NX-OSの代表的な表示形式を基にした設計用サンプルである。NX-OS release、platform、IPv4/IPv6 underlay、Multi-Siteなどにより列、フラグ、コマンド構文が異なる場合がある。そのためparserは固定カラム位置だけに依存せず、releaseごとのfixtureを用意する。利用可能な場合は既存collectのJSON sidecarも優先して利用する。

#### 10.6.1 コマンド一覧

| 優先度 | NX-OSコマンド | 主な取得値 | 主な判定 |
|---|---|---|---|
| 必須 | `show running-config` | VLAN/VNI、VRF/L3VNI、SVI、NVE、BGP VRF設定 | 新規設定の発見と設定整合性 |
| 必須（spine/leaf） | `show ip ospf neighbors` | Underlay OSPF neighbor、state、interface | Full neighborの維持、作業後の悪化なし |
| 必須 | `show nve interface` | NVE state、source-interface、VTEP IP | NVEがUpであり、収集前後で悪化していない |
| 必須 | `show nve peers` | peer IP、state、learn type | 既存peerの維持、remote VTEPの状態 |
| 必須 | `show nve vni` | VNI、state、L2/L3、BD/VRF、replication | 新規VNIが正しい種別でUp |
| 必須 | `show bgp l2vpn evpn summary` | EVPN neighbor state、受信prefix数 | neighborがEstablished、既存neighborの悪化なし |
| 必須 | `show vlan brief` | L2VNIおよびtraditional L3VNIのVLAN、name、status | modeに応じて必要なVLANが存在しactive |
| 必須 | `show vrf` | VRF、state | 対象VRFが存在しUp |
| 必須 | `show interface Vlan<VLAN>` | SVI admin/line protocol、IP、MTU | SVI対象機器でup/up、Gateway・MTU一致 |
| 必須 | `show logging` | 指定期間のsyslog | 既存`check-logging`による新規異常候補検出 |
| 既定（leaf） | `show vpc brief` | vPC peer、keepalive、consistency | vPC構成時にpeer adjacencyとconsistencyが正常 |
| 既定（leaf） | `show vpc peer-keepalive` | vPC keepalive状態 | vPC構成時にalive |
| 既定（leaf） | `show vpc orphan-ports` | orphan port一覧 | before / afterの追加・削除を証跡保存し、予期しない変化をWARN |
| 既定（leaf） | `show port-channel summary` | port-channelとmember | Up状態とbundled member数の維持 |

vPC未設定leafではvPC checkを`NOT_APPLICABLE`とし、コマンド出力が空または未設定を示すことだけで`UNKNOWN`や`FAIL`にしない。vPC設定済みなのに出力を解析できない場合は`UNKNOWN`とする。
| 条件付き | `show bgp l2vpn evpn` | Type-2/3/5 route、next hop | IMET、MAC/IP、IP prefixの伝播 |
| 条件付き | `show nve vni ingress-replication` | VNIごとのreplication peer | 対象L2VNIのremote VTEP確認 |
| 条件付き | `show route-map <NAME>` | route-mapの存在、sequence、match/set、可能ならhit情報 | direct/static redistribution参照先の存在確認と証跡保存 |
| 条件付き | `show ip route vrf <VRF>` | VRF route | L3VNI追加後のroute存在・減少確認 |
| 条件付き | `show ipv6 route vrf <VRF>` | IPv6 VRF route | IPv6 L3VNIのroute確認 |

`show interface Vlan<VLAN>`、`show route-map <NAME>`、VRF routeコマンドは、新規VNIと参照route-mapを発見した後のtargeted collectionでVLAN / route-map / VRFを展開して実行する。初期discovery collectionでは、全体を把握できるコマンドを先に収集する。

#### 10.6.2 running-configからの設定状態

コマンド:

```text
show running-config
```

代表的な対象部分:

```text
vlan 10
  name TENANT-A-WEB
  vn-segment 10010

vrf context TENANT-A
  vni 50001
  rd auto
  address-family ipv4 unicast
    route-target both auto
    route-target both auto evpn

interface Vlan10
  no shutdown
  mtu 9216
  vrf member TENANT-A
  ip address 192.0.2.1/24
  ipv6 link-local fe80::1
  ipv6 address 2001:db8:10::1/64
  fabric forwarding mode anycast-gateway

interface nve1
  no shutdown
  host-reachability protocol bgp
  source-interface loopback1
  global ingress-replication protocol bgp
  member vni 10010
  member vni 50001 associate-vrf

router bgp 65000
  vrf TENANT-A
    address-family ipv4 unicast
      advertise l2vpn evpn
      redistribute direct route-map IPv4_REDISTRIBUTE_ALL
      redistribute static route-map IPv4_REDISTRIBUTE_ALL
      maximum-paths ibgp 4
    address-family ipv6 unicast
      advertise l2vpn evpn
      redistribute direct route-map IPv6_REDISTRIBUTE_ALL
      redistribute static route-map IPv6_REDISTRIBUTE_ALL
      maximum-paths ibgp 4

route-map IPv4_REDISTRIBUTE_ALL permit 10
route-map IPv6_REDISTRIBUTE_ALL permit 10
```

抽出・判定:

- `vlan 10`と`vn-segment 10010`からdevice-local VLAN / L2VNI mappingを取得
- `vrf context TENANT-A`と`vni 50001`からVRF / L3VNI mappingを取得
- `interface Vlan10`からVRF、MTU、IPv4、IPv6、IPv6 link-local、anycast gatewayを取得
- `interface nve1`からL2VNI memberとL3VNI associate-vrfを取得
- `interface nve1`の`global ingress-replication protocol bgp`をFabric前提として取得し、対象機器で未設定ならdeclared changeのplanは`PLAN_ERROR`、投入内容なしの観測確認は`FAIL`または証跡不足時`UNKNOWN`とする
- L2VNI member配下にper-VNI ingress replicationまたは`mcast-group`がある場合はglobal方式との競合として`CONFLICT`とする
- `router bgp <AS>`から機器固有local ASを取得し、`vrf TENANT-A`配下のIPv4 / IPv6 AF、`advertise l2vpn evpn`、direct/staticの`redistribute ... route-map`、`maximum-paths ibgp`を取得する
- running-configのroute-map定義から参照先名称の存在を確認する。route-mapのmatch条件自体は初期実装では正常性を意味解析せず、証跡として保存する
- 新規L3VNIの解決済みAFに必要なBGP設定がない、route-mapが存在しない、または値が不一致なら`FAIL`、show証跡不足なら`UNKNOWN`とする
- VRFの`vni <id> l3`とNVEの`associate-vrf`が存在し、同じVNIへ対応し、L3VNI専用VLAN / SVIがない場合は`new_l3vni`として分類する
- L3VNIと同じ`vn-segment`を持つVLAN、およびそのVRFに属するforwarding用SVIがある場合は`traditional_vlan_svi`として分類する
- 証跡不足、両方式の設定混在、または一意に分類できない場合は推測せず`UNKNOWN`または`CONFLICT`とする
- beforeに存在せずafterに存在するmappingを新規候補とする
- 設定が存在しても、運用状態のshowが欠ける場合は「設定確認PASS、運用確認UNKNOWN」とする

#### 10.6.3 NVE interface

コマンド:

```text
show nve interface
```

代表的な出力例:

```text
Interface: nve1, State: Up, encapsulation: VXLAN
 VPC Capability: VPC-VIP-Only [notified]
 Local Router MAC: 0200.0a00.0001
 Host Learning Mode: Control-Plane
 Source-Interface: loopback1 (primary: 10.0.0.11, secondary: 0.0.0.0)
```

抽出・判定:

- `Interface=nve1`
- `State=Up`を必須とする
- `Host Learning Mode=Control-Plane`を期待する
- source-interfaceとprimary VTEP IPをSnapshotへ保存する
- beforeでUp、afterでDownの場合は既存環境の`regression`として`FAIL`
- beforeからDownの場合は`pre_existing`として分離する

#### 10.6.4 NVE peer

コマンド:

```text
show nve peers
```

代表的な出力例:

```text
Interface Peer-IP          State LearnType Uptime   Router-Mac
--------- ---------------  ----- --------- -------- -----------------
nve1      10.0.0.12       Up    CP        01:12:34 0200.0a00.0002
nve1      10.0.0.13       Up    CP        01:10:22 0200.0a00.0003
```

抽出・判定:

- peerごとに`Peer-IP`、`State`、`LearnType`を保存する
- beforeでUpだったpeerがafterで消失またはDownなら`FAIL`
- 自動発見モードでは、新規VNIがどのpeerにも展開される設計か不明なため、peer総数だけから新規VNIを`FAIL`にしない
- 複数VTEPへの新規配置を発見した場合は、`show nve vni ingress-replication`またはType-3 routeでVNI単位のremote情報を補完する
- vPC peer 2台が同じsecondary VTEP IPを持つ場合、その2台は論理的に同一VTEPとして扱う。
  両機器のNVE VNIがUpでありsecondary VTEPが一致するなら、peer間の
  ingress-replication entryが存在しないことだけを理由に`UNKNOWN`または`FAIL`にしない。
  secondary VTEPが異なる別VTEPへの展開では、従来どおりremote情報を要求する

#### 10.6.5 NVE VNI

コマンド:

```text
show nve vni
```

代表的な出力例:

```text
Codes: CP - Control Plane        DP - Data Plane
       UC - Unconfigured         SA - Suppress ARP

Interface VNI      Multicast-group   State Mode Type [BD/VRF]      Flags
--------- -------- ----------------- ----- ---- ------------------ -----
nve1      10010    UnicastBGP        Up    CP   L2 [10]            SA
nve1      50001    n/a               Up    CP   L3 [TENANT-A]
```

抽出・判定:

- VNI 10010は`Type=L2`、`BD=10`、`State=Up`であることを確認する
- VNI 50001は`Type=L3`、`VRF=TENANT-A`、`State=Up`であることを確認する
- running-configから抽出したL2/L3分類とshow出力が異なる場合は`FAIL`
- `Down`は`FAIL`、対象行なしは設定投入後なら`FAIL`、コマンド失敗は`UNKNOWN`
- parserは1つのVNI rowを1行単位で解析し、空白の正規表現で改行を消費して隣接する
  L2/L3 rowを結合してはならない。連続するL2VNIとL3VNIを含むfixtureを回帰試験に含める
- VNI単位の行はNX-OS releaseによってmulticast group、`UnicastBGP`、`n/a`などの表現が異なるため、replication値そのものを固定の正常条件にしない

#### 10.6.6 BGP EVPN neighbor

コマンド:

```text
show bgp l2vpn evpn summary
```

代表的な出力例:

```text
BGP summary information for VRF default, address family L2VPN EVPN
BGP router identifier 10.0.0.11, local AS number 65000
BGP table version is 42, L2VPN EVPN config peers 2, capable peers 2

Neighbor        V    AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down  State/PfxRcd
10.0.0.1       4 65000    1024    1018     42   0    0 01:12:01 24
10.0.0.2       4 65000    1009    1011     42   0    0 01:11:48 24
```

抽出・判定:

- `State/PfxRcd`が数値ならEstablishedとして扱い、その値をprefix受信数として保存する
- `Idle`、`Active`などの状態文字列なら未確立として扱う
- beforeでEstablishedだったneighborがafterで未確立または消失した場合は`FAIL`
- prefix数の増加は新規VNI追加時の期待変化になり得る
- prefix数の減少は即FAILにせず、絶対値・減少率・継続回数をポリシーで評価する

#### 10.6.7 VLAN

コマンド:

```text
show vlan brief
```

代表的な出力例:

```text
VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
1    default                          active    Eth1/1
10   TENANT-A-WEB                     active    Eth1/10, Eth1/11
3001 TENANT-A-L3VNI                   active
```

抽出・判定:

- ChangeSetの`default_vlan`、group override、device overrideを解決したVLANが存在することを確認する
- 対象VLANの`Status=active`を確認する
- L2VNIでは共通`vlan_name`との一致を確認する
- `new_l3vni`のL3VNIに対してL3VNI専用VLANの存在を要求しない
- `traditional_vlan_svi`のL3VNIでは解決後のL3VNI専用VLANを確認する
- VLAN番号はdevice-local値のため、機器間で異なっていてもChangeSetの解決結果と一致すれば正常とする

#### 10.6.8 VRF

コマンド:

```text
show vrf
```

代表的な出力例:

```text
VRF-Name                           VRF-ID State   Reason
default                                 1 Up      --
management                              2 Up      --
TENANT-A                                3 Up      --
```

抽出・判定:

- L2VNIが参照するVRFとL3VNIのVRFが存在することを確認する
- 対象VRFの`State=Up`を確認する
- running-configの`vrf context`、L3VNI、`show nve vni`のVRF表示と相互照合する

#### 10.6.9 SVI、Gateway、MTU

コマンド例:

```text
show interface Vlan10
```

代表的な出力例:

```text
Vlan10 is up, line protocol is up, autostate enabled
  Hardware is EtherSVI, address is 0200.0a00.0010
  MTU 9216 bytes, BW 1000000 Kbit, DLY 10 usec
  Internet Address is 192.0.2.1/24
```

IPv6 addressとVRFは、running-configおよび必要に応じて次の追加コマンドから取得する。

```text
show ip interface brief vrf all
show ipv6 interface brief vrf all
```

抽出・判定:

- 共通`svi`があり、group/deviceに`svi: false`がない対象ではSVIの存在を必須とする
- interface stateとline protocolがともにupであることを確認する
- IPv4-only、IPv6-only、dual-stackを許可する
- `show interface`とrunning-configからMTUを取得し、解決済み期待値（省略時9216）と一致することを確認する
- IPv6 SVIではrunning-configからlink-localを取得し、解決済み期待値（省略時`fe80::1`）と一致することを確認する
- running-configから抽出したIPv4 / IPv6 addressが共通SVI値と一致することを確認する
- 自動発見時、SVI対象機器間でGateway、IPv6 link-local、またはMTUが一致しなければ`status.conflicts`へ記録する
- `svi: false`対象でSVIが観測された場合は既定`WARN`とする

#### 10.6.10 EVPN route

基本コマンド:

```text
show bgp l2vpn evpn
```

代表的なType-3（IMET）行の例:

```text
Route Distinguisher: 10.0.0.11:32777
*>l[3]:[0]:[32]:[10.0.0.11]/88
                      10.0.0.11                         100      32768 i
*>i[3]:[0]:[32]:[10.0.0.12]/88
                      10.0.0.12                           0        100 i
```

代表的なType-5（IP prefix）行の例:

```text
Route Distinguisher: 10.0.0.11:50001    (L3VNI 50001)
*>i[5]:[0]:[0]:[24]:[198.51.100.0]/224
                      10.0.0.21                           0        100 i
```

抽出・判定:

- L2VNIが複数VTEPに新規出現した場合、対象VNIのroute-targetまたはRDコンテキストと関連付けてremote Type-3を確認する
- 単一VTEP配置やremote VTEPが存在しないことが許容される構成では、Type-3不在だけでFAILにしない
- Type-5は、prefix広告が宣言されている場合、またはbefore/afterで対象VRFのType-5広告が観測される場合に評価する
- `advertise l2vpn evpn`の設定確認PASSとType-5 routeの存在確認は分離する。広告対象prefixがまだない場合、設定が正しくてもType-5 routeが0件になり得る
- `redistribute direct`の設定確認PASSと、実際にdirect prefixがType-5として広告されていることの確認は分離する。route-mapでdenyされるprefixや存在しないdirect routeを一律FAILにしない
- `redistribute static`も同様に、設定確認とstatic prefixのType-5広告確認を分離する。対象static routeがない、またはroute-mapでdenyされる場合はroute不在だけでFAILにしない
- 新規L3VNIで広告prefixがまだない場合、Type-5不在だけでFAILにしない
- Type-2 route数、MAC数、Type-5 route数は自然変動するため、原則として完全一致ではなく減少率、最低値、連続観測で評価する
- releaseごとにroute表示と絞り込み構文が異なる可能性があるため、初期実装では全体出力を収集して正規化し、対応確認済みreleaseではVNI / route-type指定コマンドへ最適化する

#### 10.6.11 ingress replication

コマンド:

```text
show nve vni ingress-replication
```

代表的な出力例:

```text
Interface VNI      Replication List  Source    Up Time
--------- -------- ----------------- --------- --------
nve1      10010    10.0.0.12        BGP-IMET  00:46:55
nve1      10010    10.0.0.13        BGP-IMET  00:45:31
```

抽出・判定:

- running-configでNVEの`global ingress-replication protocol bgp`が存在することを前提確認する
- global設定は今回のVNI追加では生成・変更しない
- 新規L2VNIごとにremote VTEP一覧をSnapshotへ保存する
- 同じVNIが複数VTEPで新規検出された場合、対応するremote VTEPが観測できることを確認する
- 観測対象の一部だけpeerが欠ける場合は、収束待ち中は`target_not_ready`、timeout後は`FAIL`とする

Phase 6実装では`show nve vni ingress-replication`をCanonical Snapshotへ正規化し、同じ
L2VNIが複数対象deviceへ配置される場合にremote VTEP証跡を条件付きで要求する。単一device
配置ではこの出力を必須にしない。保存済みattempt列から連続PASS回数を評価するoffline
convergenceを実装し、収集・interval・timeout制御はPhase 7のrunnerが担当する。

#### 10.6.12 logging

`show logging`は既存の`check-logging`で解析する。beforeは既定7日、afterはbefore完了時刻からの期間を使用し、次を新規異常候補として扱う。

- severity閾値以下のログ
- 利用者指定check stringへの一致
- NVE、BGP、VLAN、SVIに関連する新規ログ
- 利用者指定除外文字列に一致しないログ

ログ一致は原因候補であり、原則`WARN`とする。NVE down、BGP neighbor downなど、構造化状態でも同じ異常を確認した場合は関連付けて`FAIL`理由へ含める。

### 10.7 判定の実行順序

正常性確認は次の順序で行う。

1. collection manifestと必須コマンドの完全性を確認
2. running-configから新規VLAN、VRF、L2VNI、L3VNI、SVI候補を検出
3. `show nve vni`でL2/L3分類、BD/VRF、operational stateを照合
4. `show vlan brief`、`show vrf`、SVI出力で関連リソースを確認
5. BGP EVPN neighborとNVE peerのbefore/after regressionを確認
6. 条件が成立する場合だけType-3、Type-5、ingress replicationを評価
7. loggingの新規異常候補を関連付け
8. 収束中の状態なら再収集し、規定回数連続で正常になるまで待機
9. discovered ChangeSet、Snapshot、checklist、最終レポートを保存

設定状態と運用状態は別々に出力する。

```text
CONFIGURATION: PASS
- VLAN 10 maps to L2VNI 10010
- VRF TENANT-A maps to L3VNI 50001
- SVI IPv4/IPv6 matches discovered ChangeSet

OPERATIONAL: FAIL
- L2VNI 10010 is Up on leaf01
- L2VNI 10010 is Down on leaf02

IMPACT: PASS
- Existing BGP EVPN neighbors preserved
- Existing NVE peers preserved
```

## 11. Overlay総合判定

check単位の`PASS`、`WARN`、`FAIL`、`UNKNOWN`、`PLAN_ERROR`と理由分類は共通Health Check Frameworkに従う。Overlay workflowは、その結果へ次の総合判定を追加する。

- `VERIFIED`: declared expected ChangeSetと実測状態が一致し、必須Health Checkがすべて成立
- `OBSERVED_HEALTHY`: expected ChangeSetなしで、自動発見された範囲の必須Health Checkがすべて成立

`OBSERVED_HEALTHY`はVNI番号、対象機器、route-targetなどが設計意図どおりであることを保証しない。共通checkに`FAIL`または`UNKNOWN`があれば、Overlay総合判定でも正常完了にしない。

`overlay-change apply`は、Overlay総合判定とは別にworkflow結果を記録する。

- `APPLIED_AND_VERIFIED`: 全対象への投入成功、expected ChangeSetとの一致、必須Health Check成功、要求された設定保存の成功
- `APPLY_FAILED`: 1台以上で設定投入に失敗
- `HEALTH_CHECK_FAILED`: 投入後の必須Health Checkまたは収束待ちに失敗
- `SAVE_FAILED`: 投入と正常性確認は成功したが、要求された設定保存に失敗

Phase 6では`OverlayHealthResult`として`configuration`、`operational`、`impact`を分離し、
declared / generated / importedの期待値と全必須checkが一致した場合だけ`VERIFIED`、
discovered入力で全必須checkが成功しwarning/conflictがない場合だけ`OBSERVED_HEALTHY`とする。
運用証跡不足は`UNKNOWN`、新規VNI Downや既存EVPN peer/NVE interfaceの悪化は`FAIL`とし、
期待値なしで設計意図まで保証しない。

workflow結果だけで詳細を隠さず、機器別の投入、各Health Check、設定保存の結果を`apply/execution.json`へ個別に記録する。

### 11.1 Apply失敗時の動作

#### 11.1.1 既存config投入方式の再利用

現行`push-config` / `push-config-dir`のNetmiko接続、device内1行単位の
`send_config_set([line])`、送信例外後に同一deviceの残りを停止する方式を共通executorとして
再利用する。新しい独立したSSH送信方式を実装しない。As-Isの根拠と不足機能は
[Existing Push Config As-Is](../as-is/PUSH_CONFIG_AS_IS.md)を参照する。

managed Overlay applyでは既存executorへ次だけを追加する。

- plan、approval、config hashの関連付け
- command別result JSONと応答範囲
- NX-OS応答本文のerror pattern
- SIGINT、timeout、接続断時のoperation state
- `serial: 1`、未着手device停止、reconcile
- after health check成功後のsave gate

初期対象5機種はすべて`device_type: nxos`として同じexecutorを使用する。model名による
送信処理分岐は行わない。release/model差はCapability Matrix、show parser、renderer adapter、
実測に基づくtimeoutへ限定し、差がfixtureまたは公式仕様で確認された場合だけ追加する。

初回Nexus 9000v検証は通常applyにoverride optionを追加せず、Capability設計の
`overlay-change qualify`を使用する。qualifyと`qualify-rollback`も本節のexecutor、
失敗制御、ログ形式をそのまま使用する。相違はqualification専用承認、最大2台、
初期saveなし、rollback時は逆device順、成功後もCapabilityを自動昇格しない点だけとする。
qualification rollbackではapply後のafter Snapshot（apply失敗後の緊急収集を含む）と、
同一sessionで再取得したrunning configの一致を必須とする。

初期実装の安全側既定値は次とする。

```yaml
apply_failure_policy:
  serial: 1
  stop_on_first_error: true
  automatic_command_retry: false
  automatic_rollback: false
  save_on_failure: false
  collect_after_failure: true
```

`serial: 1`では1台ずつ投入し、最初の失敗でその機器の残りのコマンドと未着手機器への投入を停止する。将来並列投入を追加する場合、既に送信中のコマンドを強制中断せず完了・失敗・不明の結果を回収する。

失敗stageごとの動作は次とする。

| 失敗stage | workflow結果 | 後続投入 | 設定保存 | 失敗後収集 |
|---|---|---|---|---|
| plan / hash / inventory検証 | `PLAN_ERROR` | 開始しない | しない | 不要 |
| before Health Check / Operation Gate | `HEALTH_CHECK_FAILED` | 開始しない | しない | before証跡を保持 |
| 接続・認証 | `APPLY_FAILED` | 停止 | しない | 到達可能機器から収集 |
| 設定コマンド | `APPLY_FAILED` | 当該機器の残りと未着手機器を停止 | しない | 対象全体から緊急after収集 |
| コマンド送信後のtimeout / 接続断 | `APPLY_FAILED`、機器状態`UNKNOWN` | 停止 | しない | 再接続後に実状態を収集 |
| after収集不成立 | `HEALTH_CHECK_FAILED` | 投入済み | しない | retry可能なら収束待ち内で再収集 |
| 収束timeout / 必須check FAIL | `HEALTH_CHECK_FAILED` | 投入済み | しない | 最終attemptを保存 |
| 設定保存 | `SAVE_FAILED` | 投入済み | 機器別成否を保持 | 保存結果を収集・記録 |

コマンド送信後に応答を確認できない場合、同じコマンドを自動再送しない。機器側で成功している可能性があり、再送の安全性を保証できないためである。再接続後にrunning-config、VLAN、VRF、NVE、VNIなどを収集し、`applied`、`not_applied`、`unknown`へ分類する。

失敗時の端末例:

```text
[3/6] Apply generated configuration
  PASS         leaf01  commands=18
  FAIL         leaf02  command=7/18
  NOT_STARTED  leaf03

Failure:
  host   : leaf02
  command: member vni 10010
  error  : Invalid command
  log    : operations/CHG-2026-00123/apply/devices/leaf02/commands.log

Configuration save: SKIPPED
Emergency collection:
  raw=operations/CHG-2026-00123/health/after/attempts/failure-001/raw/

Result: APPLY_FAILED
Rollback: REQUIRED_MANUAL_DECISION
```

失敗後も`commands.log`、`command-results.json`、緊急after rawログ、Collection Manifest、`apply/execution.json`を保存する。同一change-idでapplyを単純再開せず、実状態のreconcileと新しいplan / 承認を要求する。

### 11.2 切り戻し方針

切り戻しは「applyの逆コマンドをその場で推測して実行する」処理にしない。forward plan生成時に、対象機器、before状態、依存順序、使用方式を固定したrollback planも生成し、apply前に確認・承認できるようにする。

```text
operations/<change-id>/
├── plan/
│   ├── execution-plan.json
│   ├── rollback-plan.md
│   └── rollback-plan.json
└── rollback-config/
    └── <hostname>.cfg
```

切り戻し方式の優先順位は次とする。

| 方式 | 用途 | 条件 |
|---|---|---|
| scoped inverse config | 今回のChangeSetで追加・変更した範囲だけを戻す | before Snapshotとrunning-configから逆操作を一意に生成できる |
| manual runbook | 自動化条件を満たさない場合 | rollback planへ確認・実行手順だけを出力 |
| platform checkpoint | 対応NX-OSで変更前状態へ戻す | 初期実装では使用せず、将来のcapability検証後に追加 |

checkpointを利用できる場合でも、複数機器をatomicには戻せない。checkpointに作業外の未保存変更が含まれる可能性がある場合は自動切り戻しを禁止する。`show running-config diff`などでbeforeの未保存状態を記録し、rollback対象範囲をplanへ明示する。

rollback policyは次から選択する。

| policy | 動作 | 初期既定 |
|---|---|---:|
| `manual` | applyを停止し、利用者がrollbackコマンドを別途実行 | yes |
| `prompt` | 対話実行時にrollback plan、影響、対象を表示して確認 | no |
| `on-apply-failure` | 設定投入失敗時に承認済みrollback planを自動実行 | no |
| `on-health-failure` | after必須check失敗または収束timeout時に自動実行 | no |
| `on-any-failure` | apply / health failureのいずれでも自動実行 | no |

初期実装で受け付けるpolicyは`manual`だけとする。`prompt`、`on-apply-failure`、
`on-health-failure`、`on-any-failure`は将来予約値であり、指定時は`UNSUPPORTED`とする。
CLIでは`--rollback-policy <policy>`で指定し、省略時は`manual`とする。

```bash
alred overlay-change apply \
  --change-id CHG-2026-00123 \
  --approved-plan operations/CHG-2026-00123/plan/execution-plan.json \
  --approved-rollback-plan operations/CHG-2026-00123/plan/rollback-plan.json \
  --rollback-policy manual
```

automatic rollbackとplatform checkpointは初期実装では行わない。接続断、状態不明、
作業外drift、rollback plan hash不一致がある場合は`ROLLBACK_REQUIRED`で停止する。
将来自動切り戻しを追加する場合も、apply開始前にrollback planが生成・承認済みで、
全対象機器のrollback方式が検証済みであることを必須とする。

手動切り戻しCLI案:

```bash
alred overlay-change rollback \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --approved-rollback-plan operations/CHG-2026-00123/plan/rollback-plan.json \
  --health-check \
  --output operations/CHG-2026-00123
```

切り戻しは、planが定義した依存関係の逆順および機器順で実行する。機器単位のrollbackコマンドと応答は`rollback/devices/<hostname>/commands.log`へ保存する。`overlay-change save-rollback`を実行した場合の保存応答は、同じ機器ディレクトリの`save.log`と`save-result.json`へ分離する。

VRFの切り戻しはbeforeの存在状態とownershipにより分岐する。

| resource | beforeに存在しない／今回新規作成 | beforeから存在 |
|---|---|---|
| BGP VRF | `router bgp <AS>`配下の`no vrf <VRF>`で全体削除 | 今回追加したAF内の行だけ削除 |
| global VRF context | 依存resource除去後に`no vrf context <VRF>` | VRF自体は保持し、今回追加したL3VNI関連付けだけ削除 |

新規VRFでも、作業外interface、static route、routing protocol、route leaking、service、policy、apply後driftなどの残存参照がある場合は一括削除しない。自動rollbackを`ROLLBACK_REQUIRED`で停止し、残存参照とmanual runbookを出力する。

切り戻し後は必ず再収集し、次を確認する。

- beforeで存在したinterface、neighbor、route、NVE peer、既存VNIが復元
- 今回追加したVLAN、SVI、L2VNI、L3VNIがrollback planどおり除去または復元
- 今回新規作成したBGP VRFとglobal VRF contextが削除され、beforeから存在したVRFは保持されている
- 新しいreload-pending、critical log、CPU異常がない
- running-configとbefore状態の差分がrollback planの許容範囲内

切り戻し後の収集rawログ、Collection Manifest、Snapshot、checklistは`rollback-health/`へ保存し、通常のafter結果を上書きしない。

切り戻しworkflow結果は次とする。

- `ROLLED_BACK_AND_VERIFIED`: 全対象の切り戻しとrollback後Health Checkが成功
- `ROLLED_BACK_AND_VERIFIED_WITH_ALLOWED_DIFF`: semantic差分なし、raw差分は承認済み許容差分だけ
- `ROLLBACK_REQUIRED`: 自動実行せず利用者判断が必要
- `ROLLBACK_FAILED`: 1台以上でrollbackコマンド失敗または状態不明
- `ROLLBACK_HEALTH_FAILED`: rollbackコマンドは完了したがbefore相当の正常性へ復元できない

切り戻し後の設定保存は既定で行わない。beforeに未保存変更が存在した可能性があるため、
初期実装では独立した`overlay-change save-rollback`を明示し、rollback後Health Check、
raw running-config一致、semantic config一致がすべて成功した場合だけ実行できるようにする。
元applyが`save_on_success: true`で、apply前のrunning/startup差分なしを確認済みであることも
必須とする。

### 11.3 before running-configとの復元差分確認

rollback後は、beforeで取得した`show running-config`とrollback後に再取得した`show running-config`を機器ごとに比較する。`show running-config diff`だけではbeforeログとの差分にならないため、次の3種類を分離して使用する。

rollback Snapshotは`rollback/execution.json`またはqualification rollback executionの
`metadata.completed_at`以後に作成されていることを必須とする。時刻条件を満たさないSnapshotを
正常な切り戻し後証跡として使用せず、`snapshot_fresh: false`、
`ROLLBACK_HEALTH_FAILED`としてverificationをfail closedとする。

| 確認 | 入力 | 目的 |
|---|---|---|
| semantic config diff | before / rollback-afterのCanonical Config State | VRF、BGP、VNI、VLAN、SVI、NVEなどresource単位の復元確認 |
| normalized raw diff | before / rollback-afterの生`show running-config` | parser対象外を含む設定行の差分検出 |
| `show running-config diff` | 各時点の機器出力 | running-configとstartup-configの未保存差分確認 |

比較元は、同じoperationのbefore Collection Manifestが参照するrawログへ固定する。別change-id、最新ディレクトリ、再収集された別世代を自動選択しない。両方のrawログ、Collection Manifest、取得時刻、hostname、SHA-256を比較manifestへ記録する。

normalized raw diffで自動正規化できるのは次に限定する。

- 末尾空白と改行コード
- 取得ツールが付加したprompt、command echo、ページャ制御文字
- parserで安全と確認済みの区切り行
- release別fixtureで順序非依存と定義したblockの表示順

設定行そのもの、未知のblock、secret masking後に比較不能になった行を広く除外しない。正規化またはmaskingにより同一性を判定できない場合は`UNKNOWN`とする。

新規VRF/VLAN削除前のoperation外参照検査では、NX-OSが生成するtop-levelの
`vlan 1,10-11,13,20,3901`のようなVLAN宣言リストはVLAN resource自身の宣言であり、
外部参照とは扱わない。一方、`switchport access vlan`、`switchport trunk allowed vlan`
などinterfaceからの参照は外部参照として扱い、operation所有resourceを安全に削除できない
場合はconfig送信前に停止する。

許容差分はrollback plan承認時に`allowed_config_differences`として固定し、pattern、対象host、理由、期待するbefore / after値を保存する。rollback実行後に自動追加してはならない。許容差分に一致してもsemantic resourceへ影響する場合は許容せず`ROLLBACK_HEALTH_FAILED`とする。

判定:

| semantic diff | raw diff | 結果 |
|---|---|---|
| なし | なし | `ROLLED_BACK_AND_VERIFIED` |
| なし | 承認済み許容差分のみ | `ROLLED_BACK_AND_VERIFIED_WITH_ALLOWED_DIFF` |
| 今回の設定が残存 | 任意 | `ROLLBACK_HEALTH_FAILED` |
| beforeの既存設定が消失 | 任意 | `ROLLBACK_HEALTH_FAILED` |
| 作業対象外の未許可差分 | あり | `ROLLBACK_HEALTH_FAILED` |
| raw不足、世代不一致、解析不能 | 判定不能 | `UNKNOWN`。自動saveを行わず`ROLLBACK_REQUIRED` |

比較成果物:

```text
operations/<change-id>/
├── health/before/raw/
│   └── ...
├── rollback-health/
│   ├── raw/
│   ├── collection-manifest.yaml
│   ├── snapshot.json
│   └── checklist.md
└── rollback/
    └── config-diff/
        ├── comparison-manifest.yaml
        ├── <hostname>.diff
        └── <hostname>.semantic.json
```

`<hostname>.diff`には正規化後のunified diff、`<hostname>.semantic.json`にはresource key、before値、rollback-after値、classification、ownership、許容判定を保存する。rollback summaryとexecution JSONから両成果物の相対パスとSHA-256を参照可能にする。

## 12. Overlay収束待ち

収束待ちの実行方式は共通Health Check Frameworkに従う。Overlay profileの初期既定値を次とする。

作業後は一度だけ判定せず、設定された時間内で再確認する。

```yaml
convergence:
  timeout_seconds: 300
  interval_seconds: 15
  consecutive_passes: 2
```

- 最大300秒待機
- 15秒ごとに確認
- 2回連続で正常なら収束完了
- VNI down、NVE peer down、BGP未確立、route未収束は再試行対象
- plan不正や認証失敗など、待機で改善しない問題は即時終了

## 13. Overlay固有の出力ファイル

共通成果物の配置はHealth Check Frameworkを正本とする。Overlay workflowは共通の`operations/<change-id>/`へ次を追加する。

```text
operations/<change-id>/
├── preparation/
│   ├── current.json
│   └── attempts/
│       └── <attempt-id>/
│           ├── result.json
│           ├── reference-state.json
│           ├── conflict-report.json
│           ├── conflict-report.md
│           ├── execution-plan.json
│           ├── rollback-plan.json
│           ├── input-manifest.json
│           ├── resolved-targets.yaml
│           ├── generated-config/
│           │   └── <hostname>.cfg
│           └── rollback-config/
│               └── <hostname>.cfg
├── inputs/
│   ├── change-set.yaml
│   └── device-groups.yaml
├── plan/
│   ├── input-manifest.json
│   └── resolved-targets.yaml
├── generated-config/
│   └── <hostname>.cfg
├── apply/
│   ├── apply-summary.md
│   ├── execution.json
│   └── devices/
│       └── <hostname>/
│           ├── commands.log
│           ├── command-results.json
│           ├── save.log
│           └── save-result.json
├── rollback/
│   └── config-diff/
│       ├── comparison-manifest.yaml
│       ├── <hostname>.diff
│       └── <hostname>.semantic.json
└── overlay/
    ├── discovered-changes.yaml
    ├── expected-changes.yaml
    ├── changes-diff.md
    └── overlay-summary.md
```

- `inputs/change-set.yaml`: 外部groupをmaterializeした解決済みChangeSet。inline形式でも生成する
- `preparation/current.json`: 最新の成功済み準備attempt IDと成果物directory
- `preparation/attempts/<attempt-id>/result.json`: attemptの`RUNNING` / `PASS` / `FAILED`、時刻、失敗理由
- `preparation/attempts/<attempt-id>/reference-state.json`: 過去の正常状態のsource種別、operation / phase / path / timestamp / age / hash
- `preparation/attempts/<attempt-id>/conflict-report.json` / `.md`: 過去状態に対する準備時の重複・競合検査結果
- `preparation/attempts/<attempt-id>/execution-plan.json`: `capability_level: PLAN_ONLY`かつ`preparation_only: true`の非投入plan
- `plan/conflict-report.json` / `.md`: fresh beforeに対して再実行した投入前競合検査結果
- `inputs/device-groups.yaml`: planが読み込んだ外部`OverlayDeviceGroups`の正規化済み固定copy。inline形式では生成しない
- `plan/input-manifest.json`: ChangeSetとdevice groupのsource path、source / canonical hash、schema version
- `plan/resolved-targets.yaml`: group chain、default、overrideを機器単位へ解決した承認対象
- `generated-config/<hostname>.cfg`: ChangeSetから生成した機器別設定
- `apply/apply-summary.md`: 設定投入、収束待ち、設定保存の人間向け結果
- `apply/execution.json`: plan検証、機器別投入、使用したconfig path / SHA-256、正常性確認、設定保存を含む機械可読な実行結果
- `apply/devices/<hostname>/commands.log`: 投入順のコマンド、機器応答、エラー、開始・終了時刻を記録した人間向けログ
- `apply/devices/<hostname>/command-results.json`: 機器単位のconfig path / SHA-256、コマンド別status、時刻、応答行範囲を記録した機械可読結果
- `apply/devices/<hostname>/save.log`: `copy running-config startup-config`などの設定保存コマンド、機器応答、開始・終了時刻を記録した人間向けログ
- `apply/devices/<hostname>/save-result.json`: 保存コマンド、status、機器応答行範囲、実行時刻を記録した機械可読結果
- `apply/save-execution.json`: after gate、全台preflight、serial save、前後diff、最初の失敗を記録した集約結果
- `rollback/config-diff/comparison-manifest.yaml`: before / rollback-after rawログ、Collection Manifest、SHA-256、正規化policy、許容差分policy
- `rollback/config-diff/<hostname>.diff`: 機器別の正規化済みunified running-config差分
- `rollback/config-diff/<hostname>.semantic.json`: 機器別のCanonical resource差分と判定
- `rollback/save-execution.json`: 検証済みrollback後にstartup-configをbefore状態へ復元した集約結果

`commands.log`は、接続開始、config mode移行、各コマンド投入、機器応答、error検出、config mode終了までを順番どおり記録する。password、secret、communityなどprofileでsecret指定された値は、保存前に`***REDACTED***`へ置換する。ログファイルは既定で所有者だけが読み書きできるpermissionとし、端末には全文を表示せず保存先だけを表示する。

コマンドが失敗した場合も途中までの`commands.log`と`command-results.json`を保存する。`execution.json`から機器別ログへの相対パスとSHA-256を参照できるようにし、使用したgenerated configと機器応答を対応付ける。

設定保存は設定投入とは別stageとして扱い、`save.log`と`save-result.json`へ分離する。保存失敗時も機器応答を残し、workflow結果を`SAVE_FAILED`とする。`apply/execution.json`には保存対象機器、保存コマンド、各saveログの相対パスとSHA-256を記録する。secret maskingと所有者限定permissionは、設定投入ログと設定保存ログの両方へ適用する。

`save_on_success: true`では、作業外の未保存変更を一緒にstartup-configへ保存しないよう、
apply直前の`show running-config diff`が差分なしであることを必須とする。after正常性確認後の
`overlay-change save`は、全対象のlive running-configがafter Snapshotと一致することを
read-only preflightで確認してから1台目を保存する。保存はforward applyと同じ順序、
serial 1、retryなしで行い、各deviceの保存後diffが差分なしの場合だけ成功とする。

`overlay-change apply --health-check`はHealth Check専用Collectorを持たず、共通Health Check Frameworkを通じて既存collect処理を利用する。beforeは事前に`health-check before --collect`で取得した成果物を再利用し、apply中はafterと収束待ちattemptを収集する。直接収集したrawログは`health/before/raw/`および`health/after/attempts/<attempt-id>/raw/`へ保存し、端末、`apply/execution.json`、Collection Manifestへパスを記録する。
- `overlay/discovered-changes.yaml`: before / afterから検出した共通ChangeSet
- `overlay/expected-changes.yaml`: declared / generated / importedの期待状態
- `overlay/changes-diff.md`: expectedとdiscovered、またはbeforeとafterの人間向け差分
- `overlay/overlay-summary.md`: VNI、VLAN、VRF、SVI、EVPN固有の総合結果

## 14. CLI案

`--change-id`の入力規則、自動採番、before / after間の引き継ぎ、再実行時の成果物保護は共通Health Check Frameworkの仕様に従う。workflow開始コマンドで省略した場合は自動採番する。afterで省略した場合は、安全に一意解決できるactiveな自動採番beforeがあれば同じIDを引き継ぎ、それ以外は`PLAN_ERROR`とする。

この章のCLIのうち`overlay-check discover/evaluate/converge`、
`overlay-change prepare-plan/plan/approve/apply/save/rollback/save-rollback`は実装済みである。
`overlay-check before/after/plan`、`overlay-change-set`、既存collectへ追加する
`--collection-id`は設計案であり、現行実装済みコマンドを示すものではない。

作業方式別の一連の実行例は[Health Check Execution Scenarios](./HEALTH_CHECK_EXECUTION_SCENARIOS.md)を参照する。

実施内容の生成のみ:

```bash
alred overlay-check plan \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --plan expected-changes.yaml \
  --output operations/CHG-2026-00123
```

投入内容なしのbefore:

```bash
alred overlay-check before \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --collect \
  --output operations/CHG-2026-00123
```

外部投入後の自動発見:

```bash
alred overlay-check after \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --collect \
  --discover \
  --wait-until-stable 300 \
  --output operations/CHG-2026-00123
```

既存collectを利用して収集と解析を別々に実行:

```bash
# 1. beforeを既存collect-allで収集
alred collect-all \
  --hosts hosts.yaml \
  --show-commands-file show_commands.txt \
  --output raw-before \
  --collection-id CHG-2026-00123-before

# 2. before Snapshotを収集済みログから生成
alred health-check snapshot \
  --input raw-before \
  --input-format alred-collect \
  --phase before \
  --change-id CHG-2026-00123 \
  --profile nxos-overlay \
  --output operations/CHG-2026-00123/health/before

# 3. 外部または手動で設定投入後、afterを収集
alred collect-all \
  --hosts hosts.yaml \
  --show-commands-file show_commands.txt \
  --output raw-after \
  --collection-id CHG-2026-00123-after

# 4. after Snapshotを生成
alred health-check snapshot \
  --input raw-after \
  --input-format alred-collect \
  --phase after \
  --change-id CHG-2026-00123 \
  --output operations/CHG-2026-00123/health/after

# 5. 機器へ再接続せず、Snapshot間の変更と正常性を評価
alred health-check compare \
  --before operations/CHG-2026-00123/health/before/snapshot.json \
  --after operations/CHG-2026-00123/health/after/snapshot.json \
  --output operations/CHG-2026-00123/health/report

alred overlay-check discover \
  --before operations/CHG-2026-00123/health/before/snapshot.json \
  --after operations/CHG-2026-00123/health/after/snapshot.json \
  --device-groups device-groups.yaml \
  --operations-root operations
```

現行`--device-groups`は省略可能で、次のいずれかのlegacy YAML形式を受け付ける。

```yaml
device_groups:
  server-leafs:
    devices:
      - leaf01
      - leaf02
```

top-levelの`device_groups`を省略し、group名を直接mappingとして記載することもできる。
指定したgroupの全deviceが同じVNI対象で、同じoverrideを持つ場合だけgroupへ圧縮する。
一部deviceだけが対象の場合やoverrideが異なる場合は、推測でgroup化せずdevice表現を維持する。

外部・階層device group実装時は、同optionで`OverlayDeviceGroups` Kindも受け付け、ChangeSet planと
同じresolverを再利用する。legacy mappingは後方互換用adapterで一階層の
`OverlayDeviceGroups`へ正規化する。循環、未知group、最大階層、deduplicate規則はplanと共通にする。

Phase 4実装ではrunning-configからVLAN、VRF、SVI、NVE memberを抽出し、
`show nve vni`があればL2/L3種別、BD/VRF、stateを`status.observed`へ関連付ける。
運用証跡が不足する場合は`status.warnings`へ記録し、confidenceを`medium`以下とする。
`show nve vni`の種別・contextがconfigと矛盾する場合や共通SVI属性が機器間で異なる場合は
`status.conflicts`へ記録してconfidenceを`low`とする。Phase 4は変更発見までを担当し、
Down判定、EVPN/NVE影響判定、収束待ち、`OBSERVED_HEALTHY`への昇格はPhase 6で実装する。

OverlayのPhase 7実行例:

```bash
alred overlay-check evaluate \
  --change-id CHG-2026-00123 \
  --operations-root operations

alred overlay-check converge \
  --result operations/CHG-2026-00123/overlay/attempt-1/health-result.json \
  --result operations/CHG-2026-00123/overlay/attempt-2/health-result.json \
  --consecutive-passes 2 \
  --operations-root operations
```

`evaluate`は機器へ接続せず、`overlay/health-result.json`と
`overlay/overlay-summary.md`を出力する。`converge`も機器へ接続せず、指定順の保存済み結果を
評価して`overlay/convergence.json`を出力する。直接収集は共通`health-check before/after
--collect`を使用し、Overlay専用Collectorを持たない。

`evaluate --change-id`はoperation workspaceから次の正規成果物を自動解決する。

| 入力 | 省略時のpath | 解決規則 |
|---|---|---|
| before Snapshot | `health/before/snapshot.json` | `--before`明示時はそのpathを優先 |
| after Snapshot | `health/after/snapshot.json` | `--after`明示時はそのpathを優先 |
| ChangeSet | `inputs/change-set.yaml` | 宣言済み入力を優先し、存在しない場合だけ`overlay/discovered-changes.yaml`を使用 |

通常のalred投入経路では`--change-id`だけを指定する。外部Snapshot、再評価用Snapshot、発見済み
ChangeSetを使う調査経路では`--before`、`--after`、`--change-set`を明示できる。`--change-id`を
省略する場合は`--before`と`--after`の両方を必須とする。before / after / ChangeSet / operationの
change IDが一致しない場合は、成果物を生成せず`VALIDATION_ERROR`とする。自動解決と明示指定の
いずれもオフライン処理であり、機器アクセスは行わない。

alred内で設定投入:

```bash
alred overlay-change plan \
  --hosts hosts.yaml \
  --change-set desired-changes.yaml \
  --operations-root operations

alred overlay-change approve \
  --change-id CHG-2026-00123

alred overlay-change apply \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --change-set desired-changes.yaml \
  --approved-plan operations/CHG-2026-00123/plan/execution-plan.json \
  --approved-rollback-plan operations/CHG-2026-00123/plan/rollback-plan.json \
  --approval-record operations/CHG-2026-00123/approval/approval-record.json \
  --health-check \
  --wait-until-healthy 300 \
  --save-on-success \
  --output operations/CHG-2026-00123
```

## 15. 初期実装範囲

- NX-OS限定。対応下限は`10.4(5)M`
- 初期対象modelはNexus 9000v、Nexus 9336C-FX2、Nexus 93180YC-FX3、Nexus 9348GC-FX3、Nexus 9364C-H1
- device動作検証と`APPLY_VERIFIED`はNexus 9000vだけを対象とする。hardware 4機種は
  公式資料と機種別golden configによる静的確認だけを行い、managed applyを許可しない
- release/model別fixtureとcapabilityを確認したLevelだけを許可し、未検証releaseへのapplyは禁止
- Multi-Siteは初期対象外
- L3VNI modeは`new_l3vni`を既定とし、`traditional_vlan_svi`を明示選択可能
- NX-OS release / platform capability検証、および非対応時の`UNSUPPORTED`停止
- mode別の設定生成、状態検出、正常性確認、rollback
- 既存`global ingress-replication protocol bgp`を必須Fabric前提として検証し、per-VNI replication設定を生成しない
- L3VNIのIPv4 / IPv6 BGP VRF AFと`advertise l2vpn evpn`の生成、検出、正常性確認、scoped rollback
- AF別`redistribute direct route-map`（既定名`IPv4_REDISTRIBUTE_ALL` / `IPv6_REDISTRIBUTE_ALL`）と`maximum-paths ibgp`（既定4）
- AF別`redistribute static route-map`。省略時はdirectと同じAF別route-map名
- rollback後のbefore running-configとのsemantic / normalized raw二重差分、承認済み許容差分、比較成果物
- 投入内容なしのbefore / after
- 新規L2VNI / L3VNIの自動検出
- VLAN、VRF、SVI、NVE、VTEPの関連付け
- device group、default VLAN、group / device override
- IPv4-only、IPv6-only、dual-stack SVI
- 新規SVIの既定MTU 9216、ChangeSetによる共通MTU override、正常性確認
- IPv6 SVI link-localの既定値`fe80::1`、共通override、正常性確認
- BGP EVPN、NVE、既存VNIの悪化検出
- 構成・観測条件に応じたType-3 / Type-5 routeの存在・件数
- 既存 `check-logging`との連携
- discovered ChangeSet、Markdown、JSON出力
- 外部NX-OS CLI transcriptからのホスト・showコマンド分割とSnapshot生成
- `OBSERVED_HEALTHY` / `WARN` / `FAIL` / `UNKNOWN`
- applyはTTYを持つ対話実行と独立したapproval recordを必須とする
- rollback policyは`manual`だけを受け付け、automatic/checkpoint rollbackは初期対象外
- operation workspaceはlocal filesystem、最大apply対象は50台

明示的期待値、設定投入、個別prefix、ping、Type-2詳細確認、他ベンダー対応は同じモデルを使用して段階的に追加する。

## 16. 主な制約

投入内容なしの自動発見では以下を保証できない。

- VNI / VLAN番号が設計値どおりであること
- 本来投入すべき全機器へ投入されたこと
- route-targetの具体値が設計どおりであること
- 本来必要なremote VTEP数
- 意図したテナントまたはサービスであること

既知groupの一部だけで新規VNIを検出した場合は部分投入の可能性を警告できるが、期待値なしでは異常と確定しない。

alred以外で収集したログも共通Health Check Frameworkの`nxos-transcript`入力として利用できる。ただし、promptまたは実行コマンドが残っていない出力、複数ホストが行単位で混在する出力、曖昧な重複世代は自動的にVNI変更検出へ使用しない。認識済み区間と未解決区間は`transcript-import-manifest.yaml`へ記録し、Overlay Snapshotは認識済みCollection Manifestだけを参照する。

## 17. NX-OSコマンド参考資料

コマンドと出力形式の実装時確認には、対象NX-OS releaseのCisco公式ガイドとcommand referenceを使用する。本設計で参照した代表資料は以下である。

- Cisco Nexus 9000 Series NX-OS VXLAN Configuration Guide, Release 10.2(x), Configure VXLAN BGP EVPN
  - https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/102x/configuration/vxlan/cisco-nexus-9000-series-nx-os-vxlan-configuration-guide-release-102x/m-configuring-vxlan-bbgp-evpn.html
- Cisco Nexus 9000 Series NX-OS VXLAN Configuration Guide, Release 10.6(x), Configure VXLAN Cross Connect
  - https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/106x/configuration/vxlan/cisco-nexus-9000-series-nx-os-vxlan-configuration-guide-release-106x/configuring-vxlan-cross-connect.html
- Cisco Nexus 9000 Series NX-OS VXLAN Configuration Guide, Release 10.6(x), Configure VXLAN with IPv6 in the Underlay
  - https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/106x/configuration/vxlan/cisco-nexus-9000-series-nx-os-vxlan-configuration-guide-release-106x/m_configuring_vxlan_with_ipv6_in_the_underlay_vxlanv6.html
- Cisco Nexus 9000 Series NX-OS Command Reference, Release 10.4(x), N Show Commands
  - https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/104x/command-reference/show/b_n9k_show_commands_104x/m_n_showcmds.html
