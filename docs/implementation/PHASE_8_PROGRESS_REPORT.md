# Phase 8 Completion Report

## 1. 現在の結論

Phase 8は2026-07-31に完了した。`overlay-change plan/approve/apply/save/rollback`、
rollback後検証、`save-rollback`を実装し、N9K-C9300V 10.5(4)の通常経路で
apply、after gate、save、保存済み変更のrollback、running/startup両方のbefore復元を
実機確認した。未登録model/release/roleは引き続きfail closedである。

2026-08-02に、過去の正常な最終状態を使い機器へ接続せず準備する
`overlay-change prepare-plan`と、準備用／通常planで共用するVLAN、VNI、VRF、SVI IP・prefixの
競合検査を追加した。準備用成果物は承認・投入不可とし、実投入前の通常planではfresh beforeを
使って同じ検査を必ず再実行する。この追加経路はsanitized fixtureによるoffline test済みであり、
新規経路自体の実機試験は実施していない。

## 2. 実装済み

```bash
alred overlay-change plan \
  --change-set operations/CHG-2026-00123/desired.yaml \
  --before operations/CHG-2026-00123/health/before/snapshot.json \
  --operations-root operations
```

出力:

- `generated-config/<hostname>.cfg`
- `rollback-config/<hostname>.cfg`
- `plan/conflict-report.json`
- `plan/conflict-report.md`
- `plan/render-manifest.json`
- `plan/execution-plan.json`
- `plan/rollback-plan.json`

任意の事前準備では次を実行する。

```bash
alred overlay-change prepare-plan \
  --change-set changes/CHG-2026-00123/desired-changes.yaml \
  --reference-state latest-known-good \
  --operations-root operations
```

参照対象は、対象deviceをすべて含む`PASS`の正常性確認と、running configおよびOverlay解析結果を
持つ最新の正常終了operationである。workflow未開始のstandalone health-checkも、afterおよび存在する
compareが`PASS`なら対象に含める。既定では30日以内に限定する。成果物は
`preparation/attempts/<attempt-id>/`へ不変保存し、失敗後は同じchange IDで再実行できる。
成功attemptだけを`preparation/current.json`で示し、`preparation_only: true`、`PLAN_ONLY`として
approve / applyから拒否する。

Execution Planは`capability_level: PLAN_ONLY`、serial 1、最大50台、対話承認必須、
health check成功後だけsaveという制約を記録する。Rollback Planはoperation所有resourceだけを
対象とし、before running-configとの差分なしとhealth checkを検証条件にする。

設定済みresourceは`NO_CHANGE`、生成対象は`PLANNED`としてdevice別config path/hash/actionを
記録する。planとrollback planの既存schemaおよびworkflow state `plan_ready`へ接続済みである。

既存config接続処理を再利用するmanaged executorも実装済みである。configを1行ずつ送信し、
応答、開始・終了時刻、statusを記録する。NX-OS CLI errorでは同一deviceの残りを停止し、
timeoutまたは切断では状態を`UNKNOWN`として再送せず、未着手deviceへの投入も停止する。
設定保存は独立stageとして成功markerを検証する。これらはmockによるoffline test済みである。
通常`overlay-change apply/rollback` CLIへのworkflow統合も完了している。Approval Record、
固定inventoryとplan/rollback/config hash、同一sessionのrunning-config driftを再検証し、
serial 1、retryなし、stop-on-first-errorで実行する。通常rollbackはafter Snapshotを必須とし、
逆device順でoperation所有変更だけを戻す。

qualification専用の`QualificationRecord` schema、`qualify-approve`、`qualify`を実装した。
N9K-C9300V、同一release、vPC VTEP leaf、最大2台、before PASS、declared ChangeSet、
forward/rollbackを含む全artifact hashを必須とする。投入直前に同一sessionでrunning config
driftを確認し、serial 1、retryなし、saveなしでmanaged executorへ接続する。成功、CLI error、
drift、timeout、未着手機器停止、証跡出力はmock確認済みである。

`qualify-rollback`もoffline実装した。apply後に取得したafter Snapshot（失敗後の緊急収集を含む）を
必須とし、直前の同一session running configとの完全一致、逆device順、serial 1、retryなし、
saveなしで固定済みrollback configを実行する。期限切れapprovalでも安全rollbackは許可するが、
全hash検証は維持する。成功、drift拒否、期限切れrecord、逆順、証跡出力をmock確認済みである。
qualification apply/rollbackを既存interrupt guardへ接続し、config送信後の中断を
state unknownまたはrollback requiredとして保存する経路も実装した。
新規VRF/VLANを削除するrollbackについて、current Snapshot内のoperation外参照を
config送信前に拒否する保守的検査も追加した。また、共通before/after比較とOverlay評価の
両方が正常な場合だけworkflowを`after_completed`へ進めるgateを接続した。
`health-check rollback`も追加し、固定済みprofileによる共通health比較、対象2台の
normalized raw running-config完全一致、Overlay semantic config一致を統合して
`rolled_back_and_verified`または`rollback_health_failed`へ遷移する。結果は
`qualification/rollback/verification.json`へ保存する。
apply失敗後の`rollback_required`状態でも`health-check after`がSnapshotと比較証跡を生成し、
workflowを成功状態へ変更しないことをoffline CLI testで確認した。

判定ロジックまたはparser修正後に原証跡を上書きせず再評価する
`health-check snapshot --recheck`、`health-check compare --recheck`、
`overlay-check evaluate --recheck`を実装した。元Overlay結果が`UNKNOWN`の場合だけ、
同一operationの不変入力に基づく成功結果で`rollback_required`を調停できる。

save capabilityを一時Overlayから分離して安全に確認する
`overlay-change qualify-save-baseline`を実装した。workflowが
`rolled_back_and_verified`の場合だけ、全対象のread-only事前検査、同一sessionでの
before running-config一致、保存前後の`show running-config diff`差分なしを要求し、
既存save executorをserial 1、retryなし、stop-on-first-errorで実行する。証跡schema、
device別save log、完全一致phraseを追加し、offline test済みである。

## 3. 意図的に拒否する処理

既存`overlay-change approve`はExecution Planが`APPLY_VERIFIED`でなければ拒否する。
したがって現在のPLAN_ONLY成果物からapplyへ進めない。強制overrideは提供しない。

## 4. 完了根拠

- machine-readable Capability Registryで対象keyだけを`APPLY_VERIFIED`とする
- prepare-planは機器アクセスを行わず、準備成果物を通常planの承認へ流用させない
- 通常planはfresh beforeに対し、準備時と同じ競合検査を再実行する
- Approval Record、plan / rollback / inventory / config hash、同一session driftを再検証する
- apply前の未保存差分がある場合、save承認付きapplyをconfig送信前に拒否する
- after共通HealthResultとOverlayHealthResultが成功した場合だけ通常saveを許可する
- serial 1、retryなし、保存成功marker、保存後diffなしをdevice別に記録する
- 保存済み変更も承認済みrollback後にraw / semantic / healthを検証し、
  `save-rollback`でstartup-configをbeforeへ復元できる

2026-07-30にNexus 9000v 10台のT01 read-only収集を完了した。詳細と未解決のBGP baselineは
[Nexus 9000v ChangeSet Lab Test Plan](./NEXUS_9000V_CHANGESET_LAB_TEST_PLAN.md)を参照する。

同日、`lfsw0103/0104`と依存Spine 2台に限定したbeforeがPASSし、candidate ChangeSetの
PLAN_ONLY生成も完了した。operationは
文書上`<qualification-operation-id>`として参照する。通常applyは引き続きblockedであり、
初回`APPLY_VERIFIED`を作るためのlab qualification経路は通常applyと分離して実装済みである。
実operationのhash/gate検証は成功し、非TTYではrecordを作らず拒否することを確認した。

同operationで`lfsw0103/0104`へ各44 commandをserial投入し、保存せずafterを取得した。
共通health recheckはPASS 40 / UNKNOWN 0、Overlay recheckはConfiguration、
Operational、Impactの全sectionがPASSとなり`VERIFIED`を確認した。その後、逆順で各10
rollback commandを投入し、4台のrollback healthがPASS、対象2台のnormalized raw
running-configとsemantic configがbeforeと一致した。最終workflowは
`rolled_back_and_verified`である。証跡は
`operations/<qualification-operation-id>/`に保存し、config saveは実施していない。
save完了後のredaction済みレビュー成果物は
`support-bundles/qualification-complete/<qualification-operation-id>-all.tar.gz`
であり、verify結果は233 files、archive SHA-256
`2d13c712bf99299882ac34b77431c9095a8b0d5a36e402111e7547471c525691`である。
qualification apply/rollback/saveのdevice別ログと集約結果を含む。
archiveは暗号化されていないため、転送時は保存先のaccess controlを必要とする。

実機証跡から、NVE VNI parserの隣接row結合、vPC pairの共有secondary VTEP、
新規VRF追加時のroute summary比較、NVE未設定Spineの比較、NX-OS生成VLAN宣言リストの
外部参照誤判定を修正し、回帰テストを追加した。通常経路の実機受入と文書同期後の
2026-07-31時点でnon-device pytest 204件とRuffが成功している。

同日、`qualify-save-baseline`を実機実行した。`lfsw0103/0104`ともlive running-configが
beforeと一致し、保存前後の`show running-config diff`は空、save応答は成功marker
`Copy complete.`を含み、最終workflowは`qualification_completed`となった。
この証跡レビューに基づき、C9300v 10.5(4) vtep_leafの検証済みcapability setを設計Matrix上
`APPLY_VERIFIED`へ手動昇格した。

その後、`alred/capabilities/nxos.yaml`と`NxosCapabilityRegistry` schemaを追加し、
ChangeSetから求めたcapabilityをexact model/release/role entryと照合する処理を
`overlay-change plan`へ接続した。評価path/hash/device別根拠は
`plan/capability-evaluation.json`へ保存する。未登録release、standalone role、
capability不足は`PLAN_ONLY`へfail closedする。

通常`overlay-change apply`をApproval Record、固定inventory、plan/rollback/config hash、
same-session running-config drift check、既存managed executor、interrupt guardへ接続した。
serial 1、retryなし、stop-on-first-error、command別証跡をoffline testで確認した。
`APPLY_VERIFIED` planでは`--hosts`を必須にしてinventoryをoperation内へコピーし、
source SHA-256をplanへ固定する。通常`overlay-change rollback`もafter Snapshot、
固定rollback hash、逆順実行、同一session drift、外部参照検査へ接続した。

2026-07-30から31日に、通常経路のoperation
文書上`<normal-operation-id>`として参照するoperationをC9300v 10.5(4)で実行した。
`lfsw0103/0104`へのapplyは両方SUCCESS、保存なしで、4台のafter共通healthは
PASS 36 / FAIL 0 / UNKNOWN 0、before/after比較はPASS 40 / FAIL 0 / UNKNOWN 0、
OverlayはConfiguration / Operational / Impactの全sectionがPASSで`VERIFIED`となった。
その後、`lfsw0104`、`lfsw0103`の逆順でrollbackし、4台のrollback healthはPASS、
対象2台ともbeforeとのraw running-config一致とsemantic config一致が`true`となった。
最終workflowは`rolled_back_and_verified`であり、証跡は同operation配下の
`apply/`、`health/after/`、`overlay/`、`rollback/`、`health/rollback/`に保存した。
redaction済みsupport bundleは
`support-bundles/normal-complete/<normal-operation-id>-all.tar.gz`であり、
verify結果は218 files、archive SHA-256
`c6f9e3bed8714974e8750258a062e47d9c00073415e445ffaaf2e4a01896fe02`である。
archiveは暗号化されていないため、転送時は保存先のaccess controlを必要とする。

2026-07-31に通常saveの受入operation
文書上`<save-rollback-operation-id>`として参照するoperationを実行した。Approval Recordは
`save_on_success: true`で、apply直前の`show running-config diff`は対象2台とも空だった。
apply後の4台共通healthとbefore/after比較はPASS、Overlayは`VERIFIED`となり、
通常saveは両台で成功markerを確認し、保存後diffも空、結果は`APPLIED_AND_VERIFIED`となった。
その後、保存済み状態から逆順rollbackし、4台health PASS、対象2台のraw / semantic configが
beforeと一致した。`save-rollback`も両台成功し、保存後diffは空、結果は
`ROLLED_BACK_AND_SAVED`、最終workflowは`completed`である。
redaction済みsupport bundleは
`support-bundles/phase8-complete/<save-rollback-operation-id>-all.tar.gz`で、
verify結果は232 files、archive SHA-256
`0f889624ef8513909b60b1f91aff5db26ab741e51493b328c456f4b106f2dd52`である。
archiveは暗号化されていないため、転送時は保存先のaccess controlを必要とする。

## 5. Next Action

Phase 8の機能実装は完了した。Phase 10のdevice動作検証はNexus 9000vだけで継続する。
hardware 4機種は公式資料と機種別golden configで確認し、`APPLY_VERIFIED`へ昇格しない。
