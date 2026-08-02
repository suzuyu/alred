# NX-OS Capability and Fixture Matrix

## 1. 文書の目的

Health Check、Overlay config生成、apply、rollbackについて、初期対象platform、NX-OS release、
検証証跡、未検証時の動作を定義する。

## 2. 初期対応範囲

| 項目 | 初期方針 |
|---|---|
| OS | Cisco NX-OS |
| 対応下限 | `10.4(5)M` |
| release方針 | `10.4(5)M`以降を対応候補とする |
| lab / tool試験 | Nexus 9000vのみ |
| 文書確認対象hardware | Nexus 9336C-FX2、Nexus 93180YC-FX3、Nexus 9348GC-FX3、Nexus 9364C-H1 |
| 開発時のreference | Nexus 9000v。hardwareの実機または仮想labを前提としない |
| Multi-Site | 初期対象外 |
| 他Nexus 9000 | capability未確認として扱う |
| 10.4(5)M未満 | 初期実装では`UNSUPPORTED_PLATFORM` |

「10.4(5)M以降」はバージョン番号だけで全機能を保証する意味ではない。applyを許可するには、
対象releaseとmodelの組み合わせについて、Nexus 9000vはfixtureとlabでcapabilityを確認する。
対象hardware 4機種はCisco公式資料と機種別golden configだけで確認し、実機動作を検証済みとは
扱わない。未確認の新しいreleaseへ自動的に対応済み判定を広げない。文書確認の手順と判定根拠は
[NX-OS Hardware Document Review](./NXOS_HARDWARE_DOCUMENT_REVIEW.md)を正本とする。

## 3. 実行レベル

| Level | 許可する処理 | 必要な証跡 |
|---|---|---|
| `OBSERVE_ONLY` | raw import、Snapshot、可能な範囲のHealth Check | show command fixtureまたは入力ログ |
| `PLAN_ONLY` | ChangeSet validation、config生成、diff | parser fixture、構文仕様、golden config |
| `APPLY_VERIFIED` | 実機へのapply、save、rollback | release/model別capability確認、lab試験、承認済みmatrix |

capabilityが不足する場合は、可能な低いLevelへ自動降格してapplyを継続しない。利用者が
`APPLY_VERIFIED`を強制指定するoverrideは初期実装では提供しない。

`DOC_REVIEW_PENDING`と`DOCUMENT_REVIEWED`は、上記の実行Levelとは別の文書確認状態で
ある。`DOCUMENT_REVIEWED`は公式資料上のOS対応、構文、制約、scale、licenseと、
機種別golden configの静的確認が完了したことだけを示す。`APPLY_VERIFIED`を与えず、
実機での設定投入、保存、収束、rollbackを保証しない。

### 3.1 初回lab qualification

`APPLY_VERIFIED`を得るための最初の実機試験は、通常の`overlay-change apply`で
`PLAN_ONLY`を強制実行するoverrideとはしない。専用の`overlay-change qualify` workflowを
使用し、次の条件をすべて満たす場合だけ`QUALIFICATION_CANDIDATE`として実行できる。

- 対象は明示的にlab用途として登録したNexus 9000vで、exact model/releaseが
  `OBSERVE_ONLY`以上である
- 対象は1つの検証済みvPC pair、最大2台で、Spineなどの依存先はhealth観測だけに含める
- 対象scopeのbefore Health Checkが`PASS`で、CPU、reload-pending、collectionに異常がない
- forward/rollback config、before Snapshot、inventory、ChangeSet、planのhashを固定する
- TTY上でqualification専用の対象、model/release、hash、rollback準備を再確認する
- `serial: 1`、stop-on-first-error、retryなし、自動rollbackなし、初期saveなしとする
- command応答不明、drift、after Health Check失敗時は`ROLLBACK_REQUIRED`で停止する
- rollbackは専用CLIで、apply後Snapshotとの直前running-config一致、逆device順、
  serial 1、retry/saveなしを必須とする

qualification成功だけでregistryを自動更新しない。apply、after収束、save、rollback、
rollback後health、before configとの差分なしの証跡をレビューし、正確な
`model + release + role + capability set`だけを手動で`APPLY_VERIFIED`へ昇格する。
qualification recordは通常のApproval Recordとkindおよび保存先を分離し、通常applyから
参照できないようにする。

qualificationと`APPLY_VERIFIED`への昇格対象はNexus 9000vのみとする。文書確認対象
hardware 4機種は、文書確認が完了してもqualification対象とせず、Capability Registryの
`APPLY_VERIFIED`登録を行わない。

初回save capabilityは、試験用Overlayをstartup-configへ残さない
`qualify-save-baseline`で確認してよい。この場合はrollbackとbefore復元確認の完了後、
live running-configのbefore一致とrunning/startup差分なしを同一sessionで確認してから
saveし、保存後も差分なしを確認する。config内容に依存しないsave transport／成功markerの
確認として扱い、Overlay apply／rollbackの証跡と組み合わせてレビューする。

開発時はNexus 9000vとoffline fixture/goldenを使用する。hardware modelは文書確認対象に
含めるが、本プロジェクトの受入試験と動作検証の対象には含めない。hardwareの
`release + model + role`は`PLAN_ONLY`以下とし、共通NX-OS構文であることだけを理由に
`APPLY_VERIFIED`へ昇格しない。

NX-OS release文字列はsemverや単純文字列として比較しない。`show version`から元文字列と
正規化componentを保持するが、Capability Registryのapply判定は原則としてexact
`release + model` keyを使用する。「10.4(5)M以降」という範囲判定は対応候補の抽出だけに使い、
未登録releaseへ`APPLY_VERIFIED`を継承しない。

## 4. 初期Matrix

| Model | Release | Observe | Plan | Apply | 状態 |
|---|---|---:|---:|---:|---|
| Nexus 9000v | 10.4(5)M | 要fixture | 要検証 | 要lab試験 | 対応対象・未検証 |
| Nexus 9000v (C9300v) | 10.5(4) | 10台read-only確認済み | renderer確認済み | vPC VTEP leafのqualification apply/health/rollback/save確認済み | `APPLY_VERIFIED`（下記capability set限定）、2026-07-30 |
| Nexus 9336C-FX2 | 10.4(5)M | 実機収集対象外 | 文書・golden config確認済み | 対象外 | `DOCUMENT_REVIEWED`、`PLAN_ONLY`以下 |
| Nexus 93180YC-FX3 | 10.4(5)M | 実機収集対象外 | 文書・golden config確認済み | 対象外 | `DOCUMENT_REVIEWED`、`PLAN_ONLY`以下 |
| Nexus 9348GC-FX3 | 10.4(5)M | 実機収集対象外 | 文書・golden config確認済み | 対象外 | `DOCUMENT_REVIEWED`、`PLAN_ONLY`以下 |
| Nexus 9364C-H1 | 10.4(5)M | 実機収集対象外 | 文書・golden config確認済み | 対象外 | `DOCUMENT_REVIEWED`、`PLAN_ONLY`以下 |
| Nexus 9000v | 10.4(5)Mより新しいrelease | releaseごとに要fixture | releaseごとに要検証 | exact release/modelごとに要lab試験 | 対応候補 |
| hardware 4機種 | 10.4(5)Mより新しいrelease | 実機収集対象外 | releaseごとに文書・golden config確認 | 対象外 | 文書確認候補、`PLAN_ONLY`以下 |
| その他 | 10.4(5)M以降 | `UNKNOWN`可 | 原則`UNSUPPORTED` | 禁止 | 初期対象外 |

初期Matrix作成時点では全行が未検証であった。fixtureと試験結果を登録した行だけ状態を更新する。
Phase 0のsynthetic collect fixtureとmock transport testは形式と現行制御の回帰証跡であり、
上表のrelease/model capabilityを証明しない。未収集内容と取得手順は
[Phase 0 Progress Report](../implementation/PHASE_0_COMPLETION_REPORT.md)を参照する。

C9300v 10.5(4)のsanitized fixture証跡は
`tests/fixtures/nxos/metadata/c9300v_10_5_4.yaml`を正本とする。加えて2026-07-30に
`hosts.lab.yaml`の10台で共通/Overlay read-only収集を実施し、`show version`が返すmodel表記
`Nexus9000 C9300v`をrendererのcanonical key `N9K-C9300V`へ正規化することを確認した。
同日、operation `HC-20260730T122608-p0900-bc53b8`でvPC leaf 2台へ
qualification専用経路からsaveなしapplyを行い、after Overlay `VERIFIED`、逆順rollback、
rollback後health、normalized raw running-config、semantic configのbefore一致を確認した。
復元後にlive running-configのbefore一致、保存前後のrunning/startup差分なし、
`copy running-config startup-config`の成功markerを両機器で確認した。

証跡レビューにより、exact key
`N9K-C9300V + 10.5(4) + vpc_vtep_leaf`のうち、次のcapability setだけを
`APPLY_VERIFIED`へ手動昇格する。

- `baseline_commands`、`reload_pending`
- `new_l3vni`、`bgp_vrf_af`
- dual-stack SVIの`ipv6_link_local`、`svi_mtu`
- `global_ir_bgp`既存前提、`evpn_vni`
- `config_save`、`rollback_diff`

この昇格はNexus 9000vの他release、Spine/Border role、hardware modelへ継承しない。
Capability Registryのmachine-readable実装と通常
`overlay-change plan/approve/apply/save/rollback/save-rollback`は実装済みであり、
2026-07-31に同じexact keyで通常workflowのrunning/startup復元まで受入済みである。
対象hardwareおよび未登録releaseは引き続き`PLAN_ONLY`以下とする。対象hardwareは
文書確認完了後も`APPLY_VERIFIED`へ昇格しない。

2026-08-03にhardware 4機種の10.4(5)M文書確認とmodel別golden manifestを完了した。
確認記録は[`docs/compatibility/nxos/10.4.5M/`](../compatibility/nxos/10.4.5M/README.md)、
full configとhashは`tests/fixtures/nxos/hardware_document_review/`で固定する。scale、license、
vPC、release caveatは現地条件付きであり、実機証跡ではない。

## 5. Capability項目

Nexus 9000vはrelease/modelごとに少なくとも次をfixtureとlabで確認する。
対象hardwareは同じcapability項目を公式資料とgolden configで確認し、結果を
`supported`、`supported_with_conditions`、`unsupported`、`unknown`のいずれかで記録する。

| ID | Capability | Observe | Plan | Apply |
|---|---|---:|---:|---:|
| `show_version` | platform、model、NX-OS release抽出 | 必須 | 必須 | 必須 |
| `baseline_commands` | baseline core command構文と出力 | 必須 | - | 必須 |
| `reload_pending` | `show system config reload-pending` | 必須 | - | 必須 |
| `new_l3vni` | VRF `vni <id> l3`、NVE `associate-vrf` | - | 必須 | 必須 |
| `bgp_vrf_af` | advertise、redistribute、maximum-paths | 必須 | 必須 | 必須 |
| `ipv6_link_local` | SVI link-local構文とshow出力 | 必須 | 必須 | 必須 |
| `svi_mtu` | `mtu 9216`構文と運用前提 | 必須 | 必須 | 必須 |
| `global_ir_bgp` | NVE global ingress replication | 必須 | 必須 | 必須 |
| `evpn_vni` | EVPN L2VNI構文とshow出力 | 必須 | 必須 | 必須 |
| `config_save` | `copy running-config startup-config`結果 | - | - | 必須 |
| `rollback_diff` | beforeとのsemantic/raw比較 | - | 必須 | 必須 |

## 6. Fixture metadata

各fixture setには次を記録する。

```yaml
api_version: alred/v1
kind: NxosFixtureMetadata

metadata:
  fixture_id: nxos-10.4-5m-n9kv-baseline-001
  source_type: lab
  captured_at: "2026-07-26T12:00:00+09:00"
  sanitized: true

spec:
  platform: nxos
  model: Nexus 9000v
  release: "10.4(5)M"
  purpose:
    - baseline
    - overlay
  commands:
    - show version
    - show system config reload-pending
  expected:
    parser_result: pass
  provenance:
    original_retained_outside_repository: true
    sanitization_profile: nxos-fixture-v1
```

実機原本、認証情報、secretはrepositoryへ保存しない。手作りsampleは
`source_type: synthetic`とし、release capabilityを証明するfixtureに数えない。

## 7. Performance budget

初期soft budget:

- 最大対象device数: 50
- baseline/overlay標準収集: 1台あたり5分以内を目標
- budget超過は収集を即時強制終了するhard limitではなく、`PERFORMANCE_BUDGET_EXCEEDED`を記録
- applyは50台を超えるplanを初期実装では拒否
- command timeout、operation timeoutはprofileで明示し、無制限待機を許可しない

Phase 0の実測結果に基づき、コマンド別timeout、raw最大サイズ、route tableの取扱いを更新する。

## 8. Matrix更新

新releaseを追加する場合は次を満たす。

1. Nexus 9000vは`show version`でrelease/model識別をfixture化する。
2. Nexus 9000vは対象Levelに必要なcommand fixtureを追加する。
3. 対象hardwareは対応OS、VXLAN構文、機種制約、scale、licenseを公式資料で確認する。
4. parser、renderer、機種別golden config、error fixtureを実行する。
5. `APPLY_VERIFIED`のplan/apply/rollback検証はNexus 9000vだけで実施する。
6. Matrixと実装状況を更新する。

## 9. Machine-readable Registry

実行時の正本は`alred/capabilities/nxos.yaml`とし、JSON Schema
`NxosCapabilityRegistry`で検証する。entry keyはexact
`model + release + role`であり、`capabilities`とレビュー済みevidence change-idを保持する。
`overlay-change plan`はChangeSetから必要capabilityを抽出し、全対象deviceでexact entryと
必要capabilityが一致する場合だけ`capability_level: APPLY_VERIFIED`を生成する。

未登録release、role不一致、capability不足、registry schema不正はfail closedで
`PLAN_ONLY`とする。registryのpath、SHA-256、device別評価は
`plan/capability-evaluation.json`へ保存し、planと承認の証跡に含める。
`--capability-registry`で別ファイルを指定できるが、Levelの強制overrideではなく、
同じschemaとexact match規則を適用する。

文書確認対象hardwareは`APPLY_VERIFIED` entryを持たせない。文書確認の結果は
Capability Registryと分離して管理し、外部registryによるLevelの強制昇格も認めない。
