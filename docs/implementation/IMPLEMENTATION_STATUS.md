# Implementation Status

## 1. 文書の目的

設計書に記載された機能と現行実装の差を管理する。本書の状態はコードとテストで確認できる
事実を示し、設計の正本としては使用しない。

最終更新日: 2026-08-16

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
2026-08-10にC9300v 10.5(4) 10台で`health-check before --purpose inspection`の読み取り専用受入を実施し、
10台すべてのrunning config、LLDP、baseline show outputを同一attemptへ収集した。この結果から24件のconfirmed
linkを正規化し、未使用nodeを除いて既存Topologyとnode 20/20、link 38/38が一致するContainerlab Topologyを
生成した。同じCollection Manifestからidentity保持・secret除去のDigital Twin packageを作成・検証・importし、
10台分のlab config変換とstartup-configなしのTopology生成を確認した。deploy、config push、saveは実施していない。
既存のcollect、VNI map/config生成、設定投入、containerlab、topology、diagram、packagingはAs-Is解析と
用途別設計への統合を実施済みである。これは全設計要件の実装完了を意味せず、既知差分は下表で個別に追跡する。

| 領域 | 状態 | 根拠・備考 |
|---|---|---|
| 既存`collect-*` | `partial` | command別canonical fileを収集時に生成し、統合show logを互換成果物として維持する。Collection Manifestはcommand fileを優先し、legacy transcriptだけの入力はline rangeで固定する。`health-check --collect`は既存collectorを利用し、running config、LLDP、profile show outputを同一attemptへ収集する。legacy collection全体のschema化は継続 |
| 既存 config push／save | `partial` | Direct Config Push の既存互換動作と安全制約を正式設計へ統合。default strict NX-OS CLI error 検出、YAML allowlist、非推奨 `--ignore-all-cli-errors` と save 排他、Manifest 固定の `push-config-dir` を実装。`push-config-dir` は login user、management VRF、`mgmt0`、VTY の既定接続保護 filter、sanitized 投入前 summary、`--force` による明示解除、曖昧な平坦化 section の fail-closed validation を持つ。SSH prompt hostname の inventory 照合、NX-OS default hostname `switch` の mutation 前追加確認、明示的な `--allow-hostname-mismatch`、mutation same-session 再検証を実装。`write-memory` の 180 秒 timeout を維持し、host／IP／経過時間／結果の集約 log と、失敗 host の IP および log path を最終表示する。managed executor は 1 行単位 result、timeout／切断時 `UNKNOWN`、保存 marker、未着手機器停止を mock 検証し、9000v qualification と通常 apply／save／rollback／save-rollback へ統合・実機確認済み。connection 生成、same-session read-only command、session lifecycle の Common Config Session Executor API 一元化、Direct Push の immutable evidence、post-check は未実装 |
| Operation workspace / change-id | `implemented` | secure workspace、JST既定の自動採番、`operations/live/YYYY/MM/DD/<change-id>`のdated layout、成功済み Health 成果物だけを指す atomic な`operations/live/latest`、schema付きOperation ID index、legacy flat resolver、attempt ID、active before解決、atomic writeを実装 |
| Operation state / lock / approval | `implemented` | 状態遷移、排他lock、SIGINT/SIGTERM時の状態保存、対話承認、read-only status/inspectを実装 |
| Operation archive | `implemented` | 自動archiveは行わず、terminal／無lock／経過日数をgateとする`operation archive`、dry-run、一括／ID指定、deterministic tar.gz、file／archive hash検証、archive後の非展開status／inspectを実装。restore、archive成果物のSupport Bundle／Evidence／reference利用、index rebuildは未実装 |
| Machine-readable schema | `partial` | Phase 1-9、HealthCheckExecutionContext、ResolvedRoles、managed config 実行結果、通常 save、QualificationRecord、通常 rollback verification（freshness、非秘密 raw 差分件数、semantic 差分 path を含む）、RollbackStateWarnAcceptance、Capability Registry、OverlayState、OverlayVniMapDiff を含む schema および package resource loader を実装。既存機能全体の schema 化は監査継続 |
| 共通Error Catalog | `not_started` | codeと終了codeは設計済み。共通型・CLI mappingは未実装 |
| NX-OS Capability Registry | `implemented` | C9300v 10.5(4) vpc_vtep_leafの検証済みcapability setをmachine-readable registryへ登録。exact model/release/role/capability照合をplanへ接続。hardware 4機種は文書確認対象であり、`APPLY_VERIFIED` entryを登録しない |
| Canonical role 解決 | `partial` | version 省略/v1 の legacy 互換、v2 の単一 topology role、nested function、expectation rule、provenance、conflict、source/policy hash と `resolved-roles.yaml` 固定を実装。既存 topology/diagram/collect 利用機能の resolver 移行は未実装 |
| Role-aware profile scope / Checklist | `partial` | NX-OS baseline の server 除外、Overlay の 4 role allowlist、未実行ホスト一覧、`other` の read-only `UNKNOWN` と compare 停止、v2 role/function 別 command group、function expectation、NVE peer/VNI、VLAN／VRF／SVI operational health、border EVPN、EVPN RR neighbor/config/route、underlay RR config、BGP `template peer`／`inherit peer` の多段展開と dynamic neighbor prefix を実装。VLAN／VRF／SVI は running config から期待対象を自動導出し、一括 command の欠損を `UNKNOWN`、状態異常を `FAIL`、before からの悪化を regression とする。未知 template／循環は `RR_TEMPLATE_UNRESOLVED` の `UNKNOWN` とする。Type-5 は SVI connected prefix と `redistribute direct`／route-map から期待値を導出し、`advertise l2vpn evpn` の明示を必須にしない。`full` mode で広報元、EVPN RR、同一 L3VNI／import RT の全受信対象 Leaf、VRF route 導入、evidence coverage を判定する。EVPN NLRI ごとの全 path を保持し、同じ secondary VTEP を共有する vPC pair は origin group として全 primary／secondary next-hop を照合する。Type-5／VRF route の snapshot 単位検索 index と、正常な prefix x receiver 明細を `stage_summary` へ集約する成果物 scale 対策を実装。受信対象 0 台は receiver stage を `NOT_APPLICABLE` とする。Checklist は失敗 stage、VRF、prefix、device、理由を直接表示する。未対応 route-map match は `UNKNOWN` とする。targeted route command 最適化、`network` による Type-5 広報、`sampled` mode、vPC pair の全 Overlay consistency、plan/apply guard は未実装 |
| 外部transcript import | `implemented` | NX-OS prompt、inventory alias、command区間、ANSI/backspace、未解決・重複・ambiguityをmanifest化 |
| 外部 running config import | `partial` | Host 別任意 filename、複数 host NX-OS transcript、source map、host 別 canonical config、任意 LLDP、resolved inventory、immutable attempt／current／Import Manifest、Topology／Containerlab consumer 接続を実装。Health transcript adapter との内部 code 共用、paging／ANSI／backspace の全 fixture は未実装 |
| Canonical Health Snapshot | `implemented` | collect/transcript共通manifest、source hash/行範囲、native parser version、NTC Templates／TextFSM version、template file／hash、UNKNOWN provenanceを実装 |
| 共通baseline health evaluator | `implemented` | CPU、memory、environment、running／startup config差分の`PASS`／`WARN`／`UNKNOWN`、reload-pending、logging（hyphen付きfacility、severityなし非構造化record、all / days / start-time、severity、lookback、include / exclude、作業期間の新規候補）、route count、OSPF、BGP IPv4、vPCの単体・比較判定を実装 |
| 共通baseline追加check | `partial` | clock、NTP、interface status/error、port-channel の collect command ID を manifest/parser へ接続し、未収集は `UNKNOWN` とする。NTP の `Distribution Disabled`／`No session` は session 状態、configured peer の有無は設定状態として分離し、`show clock` の time source を補助 evidence として保持する。`show ntp peer-status` の selected/mode、remote/local、stratum、poll、reach、delay、VRF と非対応時 fallback を実装。interface admin／operational 状態、NX-OS の `notconnec`／`notconnect`、transceiver 不在の `sfpAbsent`／`xcvrAbsen`／`xcvrAbsent` 正規化、未対応 interface status の fail-closed parse、`show interface brief` の Reason による SVI admin state 補完、NTP 同期・選択 peer、clock offset・意図しない再起動、interface error delta、port-channel bundle/member を実装した。inventory と `show version` の hostname 照合、`show interface counters table` の `InRate`／`OutRate` および C9300v 10.5(4) の `Rx`／`Tx` 表記から input／output Mbps・percent を取得し、50% `INFO`／70% `WARN`／90% `FAIL` の profile 閾値へ接続した。IPv4／IPv6 dynamic BGP range の peer 0 件 `WARN` と全 peer 消失 regression を Checklist へ接続した。NX-OS profile の platform scope を固定し EOS を未実行理由付きで除外する。Health 直接収集の LLDP 保存と Collection Manifest 登録を実装。`show inventory` と `show license usage` の任意収集、NTC Templates parser、Device Summary 向け正規化を実装した。license は情報表示のみで、Health／compliance evaluator と `show license all` は未実装。LLDP／description の Canonical Link Evidence に対する Snapshot／evaluator／compare 統合、module、LACP internal、BFD、STP は未実装 |
| Health Check Profile | `implemented` | builtin／file profile、順序付き合成、checks 省略可能な閾値・policy 差分 profile、`generate-sample-config` 対応 logging 除外 sample、閾値 override、hash 固定、解決元を記録する resolved artifact を実装。NX-OS baseline の running／startup 差分は `show running-config diff unified` を既定とし、旧 command の証跡も同じ command ID で解析する |
| `health-check` CLI | `partial` | snapshot/compare、offline/direct before/after/rollback、直接収集の SSH 既定と before transport 継承、attempt/current、profile revision、before execution context、inventory/policy hash 固定、active change、Operation Gate、既存 collect raw 保存、phase ごとの `device-summary.md`／CSV 生成を実装。`--purpose inspection`、mappings／description rules の path と hash 固定、inspection の active change 非登録、Operation Gate 抑止、明示 ID follow-up の purpose 継承を実装。rollback Health Check は客観判定だけを行い、既存 WARN だけかを監査用 `health_gate.state_warn_eligible` に記録する。Canonical Link Evidence の自動生成・compare は未実装 |
| Overlay ChangeSet loader | `implemented` | inline／外部`device_groups_ref`、group/default/device override、SVI（IPv6 RA suppress選択を含む）、L3 AF、既定値解決、cross-field validationを実装 |
| 外部・階層device group | `implemented` | `OverlayDeviceGroups`、groupからgroupへの参照、循環・最大16階層・未知参照・override競合検証、ChangeSet相対path、symlink拒否、input manifest／resolved target固定、approval/apply hash検証を実装 |
| Overlay自動差分検出 | `implemented` | running-configと`show nve vni`から新規L2/L3 VNI、VRF、VLAN、SVIを関連付け、曖昧性と証跡不足を明示 |
| Overlay evaluator | `implemented` | configuration/operational/impact、L2/L3 VNI、SVI、NVE VNI、multi-VTEP replication、EVPN/NVE regression、総合結果とoffline convergenceを実装 |
| 現行 VNI map 生成 | `partial` | running-config parser、CSV schema、stable sort、Markdown に加え、Health Check の Canonical OverlayState から既存 schema へ投影する `vni_gateway_map.md`／CSV を実装し正式設計へ統合。Status、conflict reason、config／show command の読み取り仕様を明文化し、Traditional VLAN／SVI の L3VNI を L2VNI へ重複登録する false `CONFLICT` を修正した。L2VNI の明示的な IPv6 link-local address／`auto`表示、device 差分の`DEVICE_VARIANT`、legacy CSV の optional 観測 field を実装した。release 別 fixture、mapping 後 hostname 衝突、CSV 完全 validation は未完了 |
| legacy VNI config生成 | `implemented` | CSV adapterとadd/delete Jinja2出力をAs-Isと正式設計へ統合し、goldenで固定。新規Overlayは共通rendererを利用 |
| Canonical Render Model / 共通renderer | `implemented` | legacy CSV adapterとChangeSet adapterを共通境界へ接続。新仕様forward/scoped rollback、IPv6 RA suppress既定有効・明示無効、hash、template provenance、VLAN/VNI/VRF/SVI IP共通競合判定を実装 |
| Link discovery / normalization | `partial` | LLDP／description evidence、LLDP なしの双方向 description confirmed／片方向 candidate、confidence、mapping、external running config Import Manifest 入力、Evidence Package の raw／rules 再生成、packaged canonical との semantic hash 検証、Link Verification Result、Containerlab gate、決定的 sort、atomic CSV publish を実装し test あり。confirmed の代表方向を hash seed／入力順に依存させず、方向非依存 semantic version 2 と旧 version 1 package の完全性検証後の互換比較を実装。入力 CSV header validation は未実装 |
| Topology / diagram rendering | `partial` | common render model、confidence filter、Mermaid、Graphviz、draw.io、containerlab 入力を実装。`generate-mermaid` の role grouping 既定有効、解決済み site metadata に基づく site grouping 自動判定、role priority 順の group 出力、明示的な無効化 option、Mermaid 生成経路の既定方向 `TD` を実装。同一 role priority は draw.io の layout band として `TD` では横並び、`LR` では縦並びに配置し、Mermaid は決定的な source 順だけを保証する。論理 edge は role／site の方向または配置後座標から相手に近い node 側へ anchor し、EVPN LR は Spine 右側から Leaf 左側へ接続する。Overlay Service Summary は route leak adjacency の最大次数 service を hub とする rank layout を使用し、TD は hub 上段／spoke 下段、LR は hub 左列／spoke 右列へ配置して逆方向 edge を 2 lane に分離する。Physical／Underlay／EVPN／Overlay Service の責務を分離し、Underlay の AF 非特定 `(BGP-RR)` 表示を廃止した。`generate-network-diagram` は normalizer 1 回の結果と Manifest 固定 config／任意 operational summary から 4 view、canonical model、review CSV、schema 検証済み Manifest を staging 生成して atomic publish し、短い output path の埋め込みと長い output directory の一括表示を切り替える最終結果 summary を出力する。`--view`、既定 8 page／全方向 16 page、`--no-overlay-service` の 6／12 page 互換、Evidence Package／external import／Operation／直接 file source、Underlay target role 外の片方向 node 除外、dynamic RR range の fail-closed 解決を実装。22 node／40 link、EVPN RR 2 台／VTEP 4 台／configured session 8 本の single-site Fabric golden test あり。pseudonymized address の追加 fixture、EVPN operational state の format 間 parity、legacy single-role consumer の canonical resolver 移行は未完了 |
| Overlay Service diagram | `partial` | `(site, vrf)`／`(site, l2vni)` identity、site 未解決時の node scope、VRF／VNI／RD／RT、New L3VNI／Traditional VLAN/SVI mode、L2／L3 device-local VLAN binding、NVE membership、vPC shared VTEP、config evidence による `evpn-vtep`／`l2-only`／`service-edge` placement 分類、Service Edge Attachment の EVPN 集計除外、Type route 集計、VRF 間 route leak の有向 relation、RT index、RT policy coverage と operational verification の分離、selector／直接隣接 context、Detail 上限、RT `auto` 起源、Same-VRF／Route Leak／Additional RT 分類と peer 単位 AF 集約、SVI Gateway／IPv4／IPv6 address、Markdown Detail、4-band の明示指定 draw.io Detail、`Service → component → EVPN Placement` と `Service → Service Edge` の分離、VLAN／SVI の compact component 表示、label なし membership edge、shared VTEP で曖昧性を排除した vPC pair container、共通 binding の vPC group edge 集約と非対称 binding の個別 edge 維持、Mermaid／Graphviz／draw.io Summary、Manifest、既定 8 page と既存 6 page 互換を実装。異なる VRF／L3VNI 間の Type-5 と destination VRF route を full evidence で照合する。保存済み `OverlayState` の直接 adapter、`sampled` verification、pseudonymized address fixture は未実装 |
| Containerlab workflow | `partial` | 既存 transform と `clab-apply-config` に加え、Evidence archive／import／external config import を入力にする `clab-set-cmds`、verify 付き import 再利用、Canonical Link gate、topology／diagram／VNI 生成、成功・失敗・中断 pipeline attempt、step status、output disposition、成功時だけ更新する `current.json` を実装。`clab-apply-config` は初回 Containerlab inspect の healthy 即時通過、別 lab 名の fail-closed 検出、Docker fallback、readiness 状態 log、SIGINT 証跡、NX-OS 9000v の既存 bootstrap SSH key error だけを許可する built-in rule、`--fail-fast` による未着手 host の停止と記録、投入行番号／総行数／command および直前の正常処理済み最大 5 command を含む Traceback なしの CLI error log、各 `IGNORED_ERROR` の同等 context と該当 command の `WARNING` 表示を実装し、起動済み NX-OS 9000v 10 node で read-only readiness と保存済み error artifact 10 台の rule 一致を確認済み。8 台の NX-OS config、22 node／40 link、Kind／Linux runtime 依存 file を含む single-site Fabric sample の offline 再生 test あり。offline mode は collect、deploy、device access、config push を行わない。非 NX-OS adapter、startup Collection Manifest 統合、pipeline 全体の directory switch、9000v config apply 受入は未完了 |
| Terraform inventory生成 | `partial` | Commonのinventory派生成果物として、`hosts.yaml`と`roles.yaml`からlegacy NX-OS provider `main.tf`を生成する実装が存在する。固定`admin/admin`を出力するため安全なproduction仕様を未実装。credential注入と移行設計の確定が必要 |
| `overlay-check` CLI | `partial` | offline discover/evaluate/convergeを実装。evaluateはchange IDだけで正規before/after/固定ChangeSetを解決可能。収集はhealth-check before/afterを共用。plan aliasはPhase 8 |
| `overlay-change prepare-plan/plan/apply/save/rollback` | `implemented` | Overlay terminalまたは正常なstandalone afterを使う非投入prepare-plan、terminal Overlay の `WARN` と明示 Operation 指定時だけの standalone `WARN` を許可する `--allow-reference-state-warn`、warning 証跡、attempt単位の失敗証跡と再実行、ChangeSet change IDからの最新成功before自動解決とpointer/hash/health/gate検証、fresh beforeで再実行する共通競合検査、`PLAN_CONFLICT`時の`conflict-report.md` path 表示、共通 Health `PASS`／`WARN`と成功 Overlay を許可する after／save gate、旧 WARN 誤判定 Operation の明示 recheck 調停、全対象 `NO_CHANGE` 時の no-op save、`approve --change-id`からの標準plan／rollback plan解決、machine Registryによるfail-closed plan、通常approve/apply/save/rollback/save-rollback、9000v専用qualification経路を実装。rollback state WARN は独立した `accept-rollback-state-warn` の対話承認と hash 固定 acceptance artifact で許可する。prepare-planはoffline検証済み。通常経路はC9300v 10.5(4)でafter VERIFIED、通常save、保存済みrollback、raw/semanticおよびstartup復元を実機確認済み |
| 出力report | `partial` | HealthResult JSON、management IP を併記する device → profile 単位の checklist（inventory に IP address がない場合は hostname のみ）、Started／Completed の差分 Duration、check を持つ profile だけの `Result by Profile`、hostname、管理 IP、manufacturer、model、serial number、OS、license usage、role／function、host 別 Health を一行にまとめる Device Summary Markdown／CSV、compare summary Markdown、通常／qualification rollback の統合 verification Checklist、`nxos-overlay` 有効時の phase 別 OverlayState／VNI map／legacy VNI gateway map、compare の VNI map diff JSON・Markdown・CSV を実装。license usage は Health／compliance 判定に使用しない。期待 ChangeSet 未入力の差分は OBSERVED とし、unchanged 行を出力しない。その他の Overlay/report 拡張は継続 |
| support bundle | `implemented` | create/inspect/verify、phase/device split、device filter、site policy、Manifest固定raw、redaction/pseudonymization、secret scan、checksum、AI promptを実装 |
| Secret Scan Rule Catalog | `partial` | 共通 scanner、NX-OS 親 context rule、username credential／passphrase、SNMP community／user auth／priv／v1／v2c trap host community、common assignment／Authorization／URI／private key、high／low confidence、catalog hash、value-free finding、sanitizer 後の独立 gate、verbatim 結果を Portable Evidence へ実装。Support Bundle 共通化、user 定義追加 rule、全対応 release fixture は未実装 |
| portable evidence package | `partial` | Collection Manifest source の `digital-twin`／`ai-analysis`、regular file／hash allowlist、command 別 materialize、`protected-preserve`／`pseudonymized`／verbatim、Secret Scan、deterministic archive、checksum、inspect／verify／atomic import、検証済み package だけを指して consumer が安全に固定解決できる`imported-evidence/latest`、最新または `--change-id` Operation source を実装。Digital Twin は resolved inventory／mappings／description rules／roles／sites、running config、任意 LLDP、confirmed／candidate Canonical Link Evidence と semantic hash を同梱し、隔離側の再生成 gate で使用できる。任意 phase／attempt、support profile、開示 policy file、minimal／field override は未実装 |
| 文書local link検証 | `implemented` | `tests/test_documentation.py`で`AGENTS.md`と`docs/**/*.md`を検証 |
| pytest test runner | `implemented` | 開発依存関係とpytest設定を`pyproject.toml`へ定義。既存`unittest`は互換収集 |
| CI baseline | `implemented` | `.github/workflows/quality.yml`でPython 3.11/3.12のpytestを実行し、`device`を除外。Python 3.11 native PyInstaller build、binary help/version、bundled sample生成も確認 |
| Ruff baseline | `implemented` | 実行障害に直結する初期rule setを`uv.lock`とCIへ追加 |
| Architecture Decision Records | `implemented` | `docs/adr/` に 21 件の設計判断と運用規則を記録 |
| 用途別設計体系と既存機能の設計統合 | `implemented` | `common`、`network-ops`、`containerlab`、`topology`、`development`へ再編し、CLI、設定、inventory、接続、収集、VNI、Direct Config Push、lab、diagram、packagingのAs-Isと正式設計を追加。Network Operations、Containerlab、Topologyの用途別manual、全体構成、data flow、operation lifecycle、CLI責務を整備し、既知差分は個別行で追跡 |
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
