# Role Definition and Resolution Design

## 1. 目的

alred 内で device role を一貫して解決し、 topology 描画、コマンド収集、 Health Check、 Overlay 処理が同じ名前を異なる意味で使用しないための正本を定める。

本設計は既存の `roles.yaml` を置換せず、hostname 検出との後方互換性を維持しながら canonical role、複数 role、根拠、競合、利用機能別の利用方法を定義する。現行動作の証拠と不明点は [Role Detection and Resolution As-Is](../../as-is/ROLE_RESOLUTION_AS_IS.md) を参照する。

## 2. 設計原則

- 1 台の device は、配置を表す topology role を最大 1 つ持ち、その topology role の配下に 0 個以上の function を持てる。
- `topology_role` は `roles.yaml` に記載した hostname の命名規則から解決する。inventory や running config から topology role を暗黙に変更しない。
- `spine` や `super-spine` と、 EVPN RR であることは別の軸とする。 super-spine 上の RR も表現できる。
- canonical role 名は小文字 kebab-case とし、表示名や短縮 group 名から分離する。
- topology の表示 group には `topology_role` を使用する。コマンド収集や Health Check は、`topology_role` とその配下の `functions` を使用する。
- role は収集対象、 check 選択、表示 group の決定に使えるが、設定・運用状態の最終判定を role 名だけで PASS または `NOT_APPLICABLE` にしない。
- 解決不能、排他競合、曖昧な legacy role を安全側に扱い、 AF 固有 check を正常と推定しない。
- 入力、 rule 順、解決結果、 hash を固定し、同じ入力から同じ結果を再生成できるようにする。

## 3. Canonical role catalog

### 3.1 Topology role

次の role は相互排他とし、 device ごとに最大 1 つを実効値とする。

| role | 意味 |
|---|---|
| `border-gateway` | Fabric 外部接続を担当する border gateway |
| `super-spine` | 複数 spine または pod の上位に配置される super-spine |
| `spine` | Fabric の spine |
| `leaf` | endpoint または service を収容する leaf |
| `network-functions` | firewall、 load balancer、 router などの network function |
| `server` | server または compute node |
| `other` | canonical topology role を解決できない fallback |

`border-gateway` と `leaf` の機能を兼ねる装置であっても、topology 上の主用途を 1 つ選ぶ。兼務機能は function または将来の capability で表現し、排他的 role を複数付与しない。

### 3.2 Function

| function | 意味 | 主な証跡 |
|---|---|---|
| `vtep` | NVE を終端し VXLAN VTEP として動作する | `interface nve`、 NVE/VNI 状態 |
| `vpc` | vPC domain/member として動作する | `vpc domain`、 vPC 状態 |
| `evpn-route-reflector` | BGP L2VPN EVPN address-family の route reflector | `router bgp` 配下の L2VPN EVPN RR 設定、 EVPN peer 状態 |
| `underlay-route-reflector` | IPv4/IPv6 underlay address-family の BGP route reflector | 対象 AF の RR 設定、 underlay BGP peer 状態 |

`evpn-route-reflector` と `underlay-route-reflector` は併存できる。function 名は配置場所を含まないため、`spine` でも `super-spine` でも使用できる。

### 3.3 Qualification role との境界

Capability Registry の `vpc_vtep_leaf` などは model/release/capability の検証組合せを示す qualification key であり、本設計の topology role または function ではない。`topology_role` と `functions` から qualification key への対応は Capability Registry 側の明示的な mapping でのみ行う。文字列の一致や暗黙の連結では生成しない。

## 4. 入力と後方互換性

### 4.1 `roles.yaml`

既存の top-level `role_detection` と rule field は、topology role の hostname 検出との後方互換性のために維持する。`vtep`、`vpc`、RR などの function を独立した hostname matcher として定義しない。

`roles.yaml` を topology role 解決の正本とし、hostname の命名規則を `position_matches`、`startswith`、`endswith`、`contains` で記述する。機器の running config は topology role の決定には使用せず、function の実在確認に使用する。

```yaml
role_detection:
  leaf:
    priority: 3
    contains:
      - lf
  border-gateway:
    priority: 0
    contains:
      - bgw
  super-spine:
    priority: 1
    position_matches:
      - pos: 0
        value: ss
```

matcher は現行互換で、hostname を小文字化し、各 topology role について `position_matches`、`startswith`、`endswith`、`contains` の順に評価する。複数候補の結果順は YAML 定義順とする。rule key の `priority` は既存利用機能の表示順に使用し、一致判定順や競合判定を変更しない。

canonical role 以外の任意 key は custom role として引き続き受理する。ただし、 canonical role を要求する Health Check や Overlay 機能へ意味が近い名前を自動 mapping しない。

### 4.2 Function 定義

schema version `2`では、functionをtopology roleの配下へ定義する。次は現行実装が解釈する例である。

```yaml
role_detection:
  leaf:
    priority: 3
    contains:
      - lf
    functions:
      vtep:
        expectation: required
      vpc:
        expectation: optional

  border-gateway:
    priority: 0
    contains:
      - bgw
    functions:
      vtep:
        expectation: required

  spine:
    priority: 2
    contains:
      - sp
    functions:
      evpn-route-reflector:
        expectation: optional

  super-spine:
    priority: 1
    contains:
      - ss
    functions:
      evpn-route-reflector:
        expectation: optional
      underlay-route-reflector:
        expectation: optional
```

`expectation` の意味は次のとおりとする。

| 値 | 意味 |
|---|---|
| `required` | この topology role では function が設定され、正常に動作することを期待する |
| `optional` | function が設定されている場合だけ対象 check を実施する |
| `forbidden` | function が設定されていた場合は role policy 違反として報告する |

function の実在を hostname から推測しない。`vtep` は `interface nve`、`vpc` は `vpc domain`、RR は対象 BGP address-family の設定を同一 Snapshot の running config から確認する。`required` なのに設定証跡がなければ `FAIL` または `UNKNOWN`、`optional` で未設定なら `NOT_APPLICABLE` とする。

同じ topology role の中で function の期待値が異なる場合、topology role の既定値を `optional` とし、命名規則で対象を確実に識別できる場合だけ function expectation rule を追加できる。

```yaml
function_expectation_rules:
  vpc:
    required_when:
      contains:
        - vpc
```

この rule は vPC の実在を hostname から推測するものではなく、「対象 hostname の機器には vPC が設定されているべき」という期待値を選択する。実在と正常性は必ず running config と show command で確認する。命名規則が function の期待を一意に表さない環境ではこの rule を使用せず、`optional` として設定証跡から適用可否を決める。

`functions`と`function_expectation_rules`、schema validation、ruleの優先順位、同順位競合errorは
実装済みである。既存topology／diagram／Terraform／legacy collect consumerは、canonical resolverへ
未移行のためversion省略／version `1`の互換経路を使用する場合がある。

## 5. 解決モデル

device ごとに次を生成する。

| field | 内容 |
|---|---|
| `detected_topology_roles` | `roles.yaml` と hostname から検出した topology role の候補 |
| `topology_role` | hostname の命名規則から解決した 1 つの topology role。未一致時は `other` |
| `functions` | topology role 配下で定義された function ごとの期待状態、config から確認した実在状態、判定根拠 |
| `status` | `resolved`、 `fallback`、 `conflict`、 `ambiguous_legacy` |
| `evidence` | source、 rule 種別、 rule 値、入力 path/hash、 definition order |

解決手順は次のとおりとする。

1. topology role 名と function 名を小文字 kebab-case として validation する。custom 名も同じ形式を要求する。
2. hostname から topology role の候補だけを検出し、matcher evidence を記録する。
3. topology role の候補が 1 件なら `topology_role` に採用する。2 件以上なら `conflict` とし、自動的に片方を捨てない。候補がなければ `other` とする。
4. 解決した topology role 配下の function 定義を読み、function expectation rule があれば hostname と照合して期待値を具体化する。
5. 同一 Snapshot の running config から各 function の実在を確認する。
6. function ごとに `expectation`、`configured`、evidence、check の適用状態を記録する。
7. 出力順は `roles.yaml` の定義順を維持し、hash 生成時も同じ順を使う。

`priority` は競合を解消する仕組みではない。排他競合がない場合の表示・sort、および既存単一 role 動作の互換表示にだけ使う。

## 6. `underlay-route-reflector` の移行

現行 sample は spine を `underlay-route-reflector` にも一致させ、 diagram へ `(BGP-RR)` と表示する。しかし現行証跡だけでは、その role が underlay AF、 EVPN AF、または両方を意味するか確定できない。

このため、既存設定を新しい `evpn-route-reflector` へ黙って読み替えない。

- 新規設定では EVPN RR を担う topology role の `functions` に `evpn-route-reflector`、underlay RR を担う topology role の `functions` に `underlay-route-reflector` を定義する。
- legacy 利用機能の既存表示と role 別 show command は、移行期間中も `underlay-route-reflector` を受理する。
- canonical resolver は、設定・運用証跡で AF を確定できない既存の `underlay-route-reflector` を `ambiguous_legacy` として記録する。
- `ambiguous_legacy` だけを根拠に EVPN RR または underlay RR 固有 check を PASS、 FAIL、 `NOT_APPLICABLE` にしない。必要な config/show 出力が不足する場合は `UNKNOWN` とする。
- warningへdevice、legacy role、移行先候補を表示する。legacy名の削除時期は実利用状況を確認した
  別の設計判断で定める。

既に IPv4/IPv6 underlay RR として意図的に使用している設定は canonical 名と同名である。明示的な設定証跡が確認できる場合は `ambiguous_legacy` ではなく canonical `underlay-route-reflector` として解決できる。 hostname 一致だけでは意図を確定しない。

## 7. 利用機能別の規則

| 利用機能 | 使用する値 | 規則 |
|---|---|---|
| containerlab group、Terraform group、legacy diagram band | `topology_role` | 解決した 1 つの topology role を使用。`conflict` は警告し、安全性に関わる処理では停止 |
| diagram filter/annotation | `topology_role` と `functions` | topology 上の配置と RR などの function を区別して表示 |
| role/function 別 show command 収集 | `topology_role` と `functions` | topology role と、その配下で対象になった function の command group をまとめ、順序を維持して重複排除 |
| checklist | device → profile → topology role / function 別 section | 実行した host だけを device section に表示し、profile を実行しなかった host は未実行ホスト一覧へ理由付きで集約 |
| Device Summary | `priority`、`topology_role`、`functions` | 数値の小さい `priority`、次に hostname の順で表示し、role／function を列へ出力 |
| Health Check profile | `topology_role`、`functions`、config evidence | function の期待状態で候補 check を選択し、最終適用・判定は同一 Snapshot の設定証跡で確定 |
| Overlay plan/apply | canonical role と config evidence | role 不足・競合を安全側に扱い、 role だけで投入可否を許可しない |
| Capability Registry | qualification role | 明示 mapping 後だけ照合し、 generic role を直接渡さない |

### 7.1 `nxos-overlay` の role 別 check

`nxos-overlay` の対象 topology role は `leaf`、`border-gateway`、`spine`、`super-spine` に限定する。

| topology role | `nxos-overlay` | `network-baseline-nxos` |
|---|---|---|
| `leaf` | 実行 | 対応 OS が NX-OS なら実行 |
| `border-gateway` | 実行 | 対応 OS が NX-OS なら実行 |
| `spine` | 実行 | 対応 OS が NX-OS なら実行 |
| `super-spine` | 実行 | 対応 OS が NX-OS なら実行 |
| `network-functions` | 未実行 | 対応 OS が NX-OS なら実行 |
| `server` | 未実行 | 未実行 |
| `other` | `UNKNOWN` | 対応 OS が NX-OS なら実行 |

`network-functions` と `other` は、topology role だけを理由にすべての profile から除外しない。inventory で確認した OS が各 profile の対応 platform に一致する場合、その profile を実行する。ただし `nxos-overlay` は対象 role allowlist に一致しないため実行しない。`other` は role を安全に解決できず Overlay の正常性を保証できないため、`nxos-overlay` の結果を `UNKNOWN` とし、compare、plan、apply では `PLAN_ERROR` とする。

`server` には本設計の NX-OS profile を実行しない。将来 Linux 等の対応 profile を追加した場合は、その profile 自身の platform と role policy で別途判定する。

profile を実行しなかった host は Checklist の「未実行ホスト一覧」へ、hostname、platform、topology role、profile、reason code、理由を表示する。`NOT_APPLICABLE` check と未実行 host を同じ件数へ混在させない。

対象 device では次の候補 section を選択できる。

check ID、command、Snapshot field、判定条件、実装状態の正本は [NX-OS Overlay Role Health Check Catalog](../network-ops/NXOS_OVERLAY_ROLE_HEALTH_CHECK_CATALOG.md) とする。

| topology role / function | 主な候補 check |
|---|---|
| `leaf` / `vtep` | NVE、VNI、VLAN、VRF、SVI、anycast gateway、EVPN route |
| `border-gateway` / `vtep` | NVE/VNI、external reachability、EVPN route |
| `spine` または `super-spine` / `evpn-route-reflector` | L2VPN EVPN neighbor、RR 設定、EVPN route propagation |
| `spine` または `super-spine` / `underlay-route-reflector` | VTEP loopback route。一般的な underlay neighbor/route/ECMP は baseline の結果を参照 |
| `spine` または `super-spine` のみ | 共通 underlay/transport。 RR 固有 check は自動追加しない |

function 定義は不要な出力を整理するための候補選択と期待状態を表す。たとえば `evpn-route-reflector` が定義されていても、running config で L2VPN EVPN を確認できなければ正常とはせず `FAIL` または `UNKNOWN` とする。反対に function 定義がなくても、running config で NVE や EVPN が確認された場合は黙って `NOT_APPLICABLE` にせず、発見した機能を評価し policy mismatch を報告する。

一般的な underlay neighbor、route、ECMP、interface、port-channel は `network-baseline-nxos` が所有する。`nxos-overlay` はその結果を重複評価せず、Overlay の依存関係として VTEP loopback 到達性を参照する。

EVPN RR の初期実装は before で Established だった client の消失、down、EVPN route の異常な減少を regression として確認する。期待 client 一覧を hostname から生成しない。新規 client を必須とする場合は ChangeSet または将来の明示 peer policy を根拠にする。

`border-gateway` の初期範囲は VTEP、BGP EVPN、VRF route、Type-5 regression、external BGP regression とする。EVPN Multi-Site 固有チェックは通常の `border-gateway` から推測せず、将来の独立 function として設計する。

この規則は[Health Check Framework Design](../network-ops/HEALTH_CHECK_FRAMEWORK_DESIGN.md)の「 role 名や hostname だけから適用可否を決めない」という原則と両立する。

## 8. 成果物と再実行

現行実装では、profileと収集計画を確定する前に`resolved-roles.yaml`をattemptへ保存する。

```yaml
api_version: alred/v1
kind: ResolvedRoles
metadata:
  change_id: chg-20260808-120000
  resolved_at: 2026-08-08T12:00:00+09:00
  timezone: Asia/Tokyo
  resolver_version: "1.0"
spec:
  role_schema_version: 2
  source:
    path: /work/roles.yaml
    sha256: "sha256:<64桁の16進数>"
  policy_sha256: "sha256:<64桁の16進数>"
  devices:
    ss01:
      status: resolved
      priority: 1
      detected_topology_roles: [super-spine]
      topology_role: super-spine
      functions:
        evpn-route-reflector:
          expectation: required
          source: topology_role_default
```

成果物には schema version、resolver version、inventory／hostname source、role rule hash、解決時刻、device ごとの
`priority` を含める。未解決、競合、legacy schema の `priority` は `99` とし、before で固定した role 解決を
after／rollback で再利用する。再解決結果が変わった場合は比較条件の変更として `PLAN_ERROR` にする。role 定義を
変更してやり直す場合は profile revision と同様に理由、新旧 hash、差分を新 attempt へ保存する。

partial attempt では `resolved-roles.yaml` の存在、 schema、 hash を検証し、欠落または不整合時に以前の成功済み current を上書きしない。

## 9. Error と表示

role 解決で使用する error code は [Error Catalog](./ERROR_CATALOG.md) を正本とする。

| code | 条件 | 扱い |
|---|---|---|
| `ROLE_INPUT_ERROR` | topology role、function、matcher rule が schema 不正 | 接続前に `PLAN_ERROR` として停止 |
| `ROLE_CONFLICT` | 排他的 topology role が複数実効化 | 安全性に関わる利用機能は停止し、read-only 表示は conflict を明示 |
| `FUNCTION_EXPECTATION_CONFLICT` | 同一優先順位の rule が異なる expectation を指定 | 自動選択せず停止 |
| `TOPOLOGY_ROLE_UNRESOLVED` | hostname がどの topology role にも一致しない | read-only は `UNKNOWN` |
| `ROLE_SCOPE_INVALID` | 未解決 role を compare、plan、apply で使用 | 投入前に停止 |
| `ROLE_RESOLUTION_MISMATCH` | before 固定結果と after/rollback 再解決が不一致 | 比較・投入を停止 |

warning は role 名だけでなく device、 source、 matched rule、影響する profile/check、 operator action を表示する。

## 10. Security と安全性

- role 解決は権限昇格、投入許可、 Capability Registry 適合の単独根拠にしない。
- custom role を canonical role の alias として自動推測しない。
- hostname、 inventory path、 hash は記録するが、 credential や未加工 config を `resolved-roles.yaml` へ含めない。
- role conflict または固定 hash 不一致では fail closed とする。

## 11. 実装・移行順序

1. canonical resolver と `resolved-roles.yaml` schema を追加する。
2. 現行 `detect_node_role(s)` を互換 adapter として resolver へ接続する。
3. topology role と function 別の show command 収集を順序付き和集合へ移行する。
4. topology/diagram の単一 group 利用機能を `topology_role` へ移行する。
5. `nxos-overlay` の候補 check 選択と device → profile → topology role / function section を接続する。
6. `roles.example.yaml` と `CONFIG.md` を topology role 配下の function 定義例へ更新し、legacy warning を有効化する。
7. 利用状況を確認後、 legacy ambiguity の終了条件を別途決定する。

各段階で既存 `roles.yaml`、custom role、単一 role 利用機能の外部出力互換性を確認する。schema/CLI/sample は対応実装と同じ変更で更新し、未実装の入力を利用可能とは記載しない。

## 12. テスト方針

- matcher 種別の優先順、大小文字、 YAML 定義順、未一致 `other`
- topology role 配下の required / optional / forbidden function
- 排他的 topology role の conflict と priority による黙示解消の禁止
- hostname から検出した topology role、custom role、短縮 group 名の provenance
- spine/super-spine それぞれに置いた EVPN RR と underlay RR
- EVPN/underlay 両 RR を兼ねる device
- legacy `underlay-route-reflector` ambiguity と `UNKNOWN`
- topology role / function 別 show command の順序付き重複排除
- function の期待状態と running config evidence の一致、不一致、欠落
- `network-functions` と `other` で NX-OS baseline だけを実行する profile scope
- `server` の全 NX-OS profile 未実行と Checklist 未実行ホスト一覧
- `other` の read-only `UNKNOWN` と compare / plan / apply の停止
- function expectation rule の優先、同順位 conflict
- before/after の role hash 固定、 revision、 partial attempt
- Capability Registry qualification role との誤混同防止
- 既存 topology、 diagram、 Terraform、 collect 出力の回帰

実機接続は通常の単体テストから行わない。 parser/evaluator は sanitized fixture で確認し、 device 試験は対象と承認を明示した場合だけ実施する。

## 13. 実装状態

canonical resolver、nested function、function expectation rule、`resolved-roles.yaml`、Health Check の
profile scope、未実行 host 表示、role/function 別 command plan、および catalog で `implemented` とした
個別 check の接続は実装済みである。既存 topology／diagram consumer の canonical resolver 移行と、
catalog で `partial` または `designed` とした check の残機能は未実装である。現行の hostname 検出、
複数 role show command、単一 role topology 利用機能は互換経路として残る。実装状況は
[Implementation Status](../../implementation/IMPLEMENTATION_STATUS.md) を正本とする。
