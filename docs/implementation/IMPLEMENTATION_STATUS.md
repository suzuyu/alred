# Implementation Status

## 1. 文書の目的

設計書に記載された機能と現行実装の差を管理する。本書の状態はコードとテストで確認できる
事実を示し、設計の正本としては使用しない。

最終更新日: 2026-08-08

本書は`docs/design/`に記載された新規・変更設計の実装状況を管理するものであり、alredに
存在する全機能の実装状況一覧ではない。本書に記載がない既存機能を`not_started`または
未実装とみなしてはならない。既存機能の設計書化状況は
[Existing Feature Documentation Status](./EXISTING_FEATURE_DOCUMENTATION_STATUS.md)で管理する。

## 2. 状態の定義

| 状態 | 意味 |
|---|---|
| `not_started` | 設計はあるが、対象となる新機能の実装を開始していない |
| `partial` | 一部実装済みだが、設計上の完了条件を満たしていない |
| `implemented` | 設計上の完了条件を満たし、自動テストで確認済み |
| `deprecated` | 廃止済み、または後継へ移行済み |
| `needs_audit` | 既存機能はあるが、設計との対応関係をまだ精査していない |

## 3. 全体状況

新規CLIのうち`health-check snapshot/compare/before/after`、
`overlay-check discover/evaluate/converge`、`operation status/inspect`、
`overlay-change prepare-plan/plan/approve/apply/save/rollback/save-rollback`、
`support-bundle create/inspect/verify`を実装済みである。通常apply/rollbackは
C9300v 10.5(4)のlabで、running/startup両方の復元まで受入済みである。device動作検証は
Nexus 9000vだけを対象とする。hardware 4機種はPhase 10で文書・golden config確認済みだが、実機検証対象外である。
`health-check before/after/rollback`の入力方式は必須相互排他とし、既知のCLI validation
errorはTracebackなし、終了code `2`で表示する。
既存のcollect、VNI map/config生成、Jinja2 templateには再利用候補があるが、新設計との
適合性確認と共通化は未完了である。

| 領域 | 状態 | 根拠・備考 |
|---|---|---|
| 既存`collect-*` | `partial` | current nested show logとrunning-configを変更せずCollection Manifestへ固定するoffline adapterを実装。direct収集連携は後続Phase |
| 既存config push / save | `partial` | 既存接続を再利用するmanaged executor、1行単位結果、timeout/切断時UNKNOWN、保存marker、未着手機器停止をmock検証。9000v qualificationと通常apply/save/rollback/save-rollbackへ統合・実機確認済み。既存legacy push全体の設計統合は別途監査対象 |
| Operation workspace / change-id | `implemented` | secure workspace、JST既定の自動採番、attempt ID、active before解決、atomic writeを実装 |
| Operation state / lock / approval | `implemented` | 状態遷移、排他lock、SIGINT/SIGTERM時の状態保存、対話承認、read-only status/inspectを実装 |
| Machine-readable schema | `partial` | Phase 1-9、HealthCheckExecutionContext、ResolvedRoles、managed config実行結果、通常save、QualificationRecord、通常rollback verification（freshness、非秘密raw差分件数、semantic差分pathを含む）、Capability Registry、OverlayState、OverlayVniMapDiffを含むschemaおよびpackage resource loaderを実装。既存機能全体のschema化は監査継続 |
| 共通Error Catalog | `not_started` | codeと終了codeは設計済み。共通型・CLI mappingは未実装 |
| NX-OS Capability Registry | `implemented` | C9300v 10.5(4) vpc_vtep_leafの検証済みcapability setをmachine-readable registryへ登録。exact model/release/role/capability照合をplanへ接続。hardware 4機種は文書確認対象であり、`APPLY_VERIFIED` entryを登録しない |
| Canonical role 解決 | `partial` | version 省略/v1 の legacy 互換、v2 の単一 topology role、nested function、expectation rule、provenance、conflict、source/policy hash と `resolved-roles.yaml` 固定を実装。既存 topology/diagram/collect 利用機能の resolver 移行は未実装 |
| Role-aware profile scope / Checklist | `partial` | NX-OS baseline の server 除外、Overlay の 4 role allowlist、未実行ホスト一覧、`other` の read-only `UNKNOWN` と compare 停止、v2 role/function 別 command group、function expectation、NVE peer/VNI、VLAN／VRF／SVI operational health、border EVPN、EVPN RR neighbor/config/route、underlay RR config、BGP `template peer`／`inherit peer` の多段展開と dynamic neighbor prefix を実装。VLAN／VRF／SVI は running config から期待対象を自動導出し、一括 command の欠損を `UNKNOWN`、状態異常を `FAIL`、before からの悪化を regression とする。未知 template／循環は `RR_TEMPLATE_UNRESOLVED` の `UNKNOWN` とする。Type-5 は SVI connected prefix と `redistribute direct`／route-map から期待値を導出し、`advertise l2vpn evpn` の明示を必須にしない。`full` mode で広報元、EVPN RR、同一 L3VNI／import RT の全受信対象 Leaf、VRF route 導入、evidence coverage を判定する。EVPN NLRI ごとの全 path を保持し、同じ secondary VTEP を共有する vPC pair は origin group として全 primary／secondary next-hop を照合する。Type-5／VRF route の snapshot 単位検索 index と、正常な prefix x receiver 明細を `stage_summary` へ集約する成果物 scale 対策を実装。受信対象 0 台は receiver stage を `NOT_APPLICABLE` とする。Checklist は失敗 stage、VRF、prefix、device、理由を直接表示する。未対応 route-map match は `UNKNOWN` とする。targeted route command 最適化、`network` による Type-5 広報、`sampled` mode、vPC pair の全 Overlay consistency、plan/apply guard は未実装 |
| 外部transcript import | `implemented` | NX-OS prompt、inventory alias、command区間、ANSI/backspace、未解決・重複・ambiguityをmanifest化 |
| Canonical Health Snapshot | `implemented` | collect/transcript共通manifest、source hash/行範囲、parser version、UNKNOWN provenanceを実装 |
| 共通baseline health evaluator | `implemented` | CPU、memory、environment、reload-pending、logging（hyphen付きfacility、severityなし非構造化record、all / days / start-time、severity、lookback、include / exclude、作業期間の新規候補）、route count、OSPF、BGP IPv4、vPCの単体・比較判定を実装 |
| 共通baseline追加check | `partial` | clock、NTP、interface status/error、port-channel の collect command ID を manifest/parser へ接続し、未収集は `UNKNOWN` とする。NTP の `Distribution Disabled`／`No session` は session 状態、configured peer の有無は設定状態として分離し、`show clock` の time source を補助 evidence として保持する。`show ntp peer-status` の selected/mode、remote/local、stratum、poll、reach、delay、VRF と非対応時 fallback を実装。interface admin / operational状態、NTP同期・選択peer、clock offset・意図しない再起動、interface error delta、port-channel bundle/memberを実装しChecklistへ接続。module、LACP internal、BFD、STP、IPv6、licenseは設計済み・未実装 |
| Health Check Profile | `implemented` | builtin/file profile、順序付き合成、checks省略可能な閾値・policy差分profile、`generate-sample-config`対応logging除外サンプル、閾値override、hash固定、解決元を記録するresolved artifactを実装 |
| `health-check` CLI | `implemented` | snapshot/compare、offline/direct before/after/rollback、直接収集のSSH既定とbefore transport継承、WARN等のbeforeおよび非PASS／処理失敗後のrollback attempt再実行と過去証跡保持、成功／判定完了attemptのcurrent指示・互換正本反映、plan前の理由・旧新hash・field差分付きprofile revision、失敗時の旧正本維持、plan前guard、before execution contextによる`after/rollback --change-id`の入力モード・収集条件継承、inventory/policy hash固定、秘密情報非保存、logging範囲CLI override、profile固定継承、active change引継ぎ、Operation Gate、既存collect raw保存、実施日時・機器別checklist表示を実装 |
| Overlay ChangeSet loader | `implemented` | inline／外部`device_groups_ref`、group/default/device override、SVI（IPv6 RA suppress選択を含む）、L3 AF、既定値解決、cross-field validationを実装 |
| 外部・階層device group | `implemented` | `OverlayDeviceGroups`、groupからgroupへの参照、循環・最大16階層・未知参照・override競合検証、ChangeSet相対path、symlink拒否、input manifest／resolved target固定、approval/apply hash検証を実装 |
| Overlay自動差分検出 | `implemented` | running-configと`show nve vni`から新規L2/L3 VNI、VRF、VLAN、SVIを関連付け、曖昧性と証跡不足を明示 |
| Overlay evaluator | `implemented` | configuration/operational/impact、L2/L3 VNI、SVI、NVE VNI、multi-VTEP replication、EVPN/NVE regression、総合結果とoffline convergenceを実装 |
| 現行VNI config生成 | `needs_audit` | 現行CSVとadd/delete Jinja2出力をgolden固定。新設計との差分はAs-Is文書化済み |
| Canonical Render Model / 共通renderer | `implemented` | legacy CSV adapterとChangeSet adapterを共通境界へ接続。新仕様forward/scoped rollback、IPv6 RA suppress既定有効・明示無効、hash、template provenance、VLAN/VNI/VRF/SVI IP共通競合判定を実装 |
| `overlay-check` CLI | `partial` | offline discover/evaluate/convergeを実装。evaluateはchange IDだけで正規before/after/固定ChangeSetを解決可能。収集はhealth-check before/afterを共用。plan aliasはPhase 8 |
| `overlay-change prepare-plan/plan/apply/save/rollback` | `implemented` | Overlay terminalまたは正常なstandalone afterを使う非投入prepare-plan、attempt単位の失敗証跡と再実行、ChangeSet change IDからの最新成功before自動解決とpointer/hash/health/gate検証、fresh beforeで再実行する共通競合検査、`approve --change-id`からの標準plan／rollback plan解決、machine Registryによるfail-closed plan、通常approve/apply/save/rollback/save-rollback、9000v専用qualification経路を実装。prepare-planはoffline検証済み。通常経路はC9300v 10.5(4)でafter VERIFIED、通常save、保存済みrollback、raw/semanticおよびstartup復元を実機確認済み |
| 出力report | `partial` | HealthResult JSON、management IP を併記する device → profile 単位の checklist（inventory に IP address がない場合は hostname のみ）、check を持つ profile だけの `Result by Profile`、compare summary Markdown、通常／qualification rollbackの統合verification Checklist、`nxos-overlay`有効時のphase別OverlayState / VNI map YAML・Markdown・CSV、compareのVNI map diff JSON・Markdown・CSVを実装。期待ChangeSet未入力の差分はOBSERVEDとし、unchanged行を出力しない。その他のOverlay/report拡張は継続 |
| support bundle | `implemented` | create/inspect/verify、phase/device split、device filter、site policy、Manifest固定raw、redaction/pseudonymization、secret scan、checksum、AI promptを実装 |
| 文書local link検証 | `implemented` | `tests/test_documentation.py`で`AGENTS.md`と`docs/**/*.md`を検証 |
| pytest test runner | `implemented` | 開発依存関係とpytest設定を`pyproject.toml`へ定義。既存`unittest`は互換収集 |
| CI baseline | `implemented` | `.github/workflows/quality.yml`でPython 3.11/3.12のpytestを実行し、`device`を除外。Python 3.11 native PyInstaller build、binary help/version、bundled sample生成も確認 |
| Ruff baseline | `implemented` | 実行障害に直結する初期rule setを`uv.lock`とCIへ追加 |
| Architecture Decision Records | `implemented` | `docs/adr/`に8件の設計判断と運用規則を記録 |
| 既存機能の設計書化管理 | `implemented` | 専用進捗表と`docs/as-is/`の解析・統合規則を追加。個別解析は今後段階実施 |
| 実装前Decision Tracker | `implemented` | 推奨案、初期NX-OS対象、反映先を管理。機能実装は別途未着手 |

## 4. Phase進捗

| Phase | 状態 | 開始日 | 完了日 | 補足 |
|---|---|---|---|---|
| 0 現行仕様の固定とfixture整備 | `implemented` | 2026-07-26 | 2026-07-29 | local baseline、C9300v 10.5(4) sanitized fixture、metadata、fixture検査完了。hardwareはPhase 10の文書確認対象 |
| 1 operation workspaceとschema | `implemented` | 2026-07-29 | 2026-07-29 | workspace、schema、state/lock、preflight、active before解決、interactive approval、atomic writeをoffline testで確認。[完了記録](./PHASE_1_COMPLETION_REPORT.md) |
| 2 rawログimportとSnapshot生成 | `implemented` | 2026-07-29 | 2026-07-29 | collect/external transcript adapter、7 NX-OS parser、provenance、offline snapshot CLIを確認。[完了記録](./PHASE_2_COMPLETION_REPORT.md) |
| 3 共通baseline evaluator | `implemented` | 2026-07-29 | 2026-07-29 | profile解決、11 NX-OS parser、共通単体判定、regression比較、CPU連続sample、reportを確認。[完了記録](./PHASE_3_COMPLETION_REPORT.md) |
| 4 Overlay parserと自動差分検出 | `implemented` | 2026-07-29 | 2026-07-29 | config/NVE VNI parser、device横断関連付け、ChangeSet schema、group/VLAN/SVI圧縮、offline CLIを確認。[完了記録](./PHASE_4_COMPLETION_REPORT.md) |
| 5 ChangeSetと共通config renderer | `implemented` | 2026-07-29 | 2026-07-29 | CSV互換adapter、ChangeSet解決、NX-OS renderer、owned rollback、manifestをoffline確認。2026-08-02に外部・階層device group、入力固定、approval hash、VLAN/VNI/VRF/SVI IP競合検査をfollow-up実装。[完了記録](./PHASE_5_COMPLETION_REPORT.md) |
| 6 Overlay evaluatorと収束待ち | `implemented` | 2026-07-29 | 2026-07-29 | Overlay 3-section判定、VERIFIED/OBSERVED_HEALTHY、multi-VTEP証跡、連続PASS判定を確認。[完了記録](./PHASE_6_COMPLETION_REPORT.md) |
| 7 health-check / overlay-check CLI | `implemented` | 2026-07-29 | 2026-07-29 | offline/direct before/after、active ID、共通compare、Overlay evaluate/converge、gate記録を確認。[完了記録](./PHASE_7_COMPLETION_REPORT.md) |
| 8 overlay-change prepare-plan/plan/apply/save/rollback | `implemented` | 2026-07-29 | 2026-07-31 | 過去の正常な最終状態を使うoffline prepare-plan、fresh before再検査、machine Registry付きAPPLY_VERIFIED plan、通常approve/apply/save/rollback/save-rollback、managed executor、qualification経路、health/raw/semantic/startup復元gateを実装。prepare-planはoffline、通常経路はC9300vで実機受入済み。[完了記録](./PHASE_8_PROGRESS_REPORT.md) |
| 9 support bundle | `implemented` | 2026-07-29 | 2026-07-30 | split、filter、site policy、外部raw hash、part indexを含めてoffline確認。[完了記録](./PHASE_9_COMPLETION_REPORT.md) |
| 10 9000v適合性・運用受入とhardware文書確認 | `partial` | 2026-07-30 | - | C9300v 10.5(4) 10台のT01 read-only収集、vpc_vtep_leaf 2台のqualificationと通常apply/save/rollback/save-rollback、after VERIFIED、running/startup復元を確認。Python 3.11のlocal、glibc 2.17および2.34 Docker binaryでCLIを検証し、build依存をlock化。hardware 4機種は公式資料・model別goldenで`DOCUMENT_REVIEWED`。Nexus 9000v 10.4(5)Mと実配布先は未実施。[進捗記録](./PHASE_10_PROGRESS_REPORT.md) |

## 5. 更新ルール

- 実装作業の開始時に対象Phaseを`partial`へ変更する。
- 機能単位で実装、テスト、文書同期が完了した場合だけ`implemented`とする。
- test未実施、実機未確認、schema未確定などは補足へ明記する。
- 設計だけを追加した機能は`not_started`のままとし、設計済みであることを備考へ記載する。
- 状態を変更するcommitまたは作業では、根拠となるtestまたは対象ファイルを備考へ追記する。
- 日付は`Asia/Tokyo`の暦日を使用する。
