# Overlay Change and Health Check Implementation Plan

## 1. 文書の目的

設計済みの共通Health Check Framework、Overlay変更管理、NX-OS config生成、support bundleを
段階的に実装するための計画を定義する。

詳細仕様を本書へ複製しない。仕様は[設計書一覧](../design/README.md)、各機能の実装状態は
[IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md)を正本とする。
Phase 0の作業分解、gate、外部fixture条件は
[Phase 0 Implementation Plan](./PHASE_0_IMPLEMENTATION_PLAN.md)を参照する。

## 2. 実装原則

- 小さい縦方向の単位で、schema、実装、CLI、テスト、文書を同時に完成させる。
- test runnerはpytestへ統一し、既存`unittest.TestCase`は関連変更時に段階移行する。
- 新規テストはpytest fixture、parameterization、plain `assert`を原則とする。
- parserとevaluatorはrawログを直接相互参照せず、Canonical Snapshotを境界にする。
- 設定生成はCanonical Render Modelと共通rendererへ集約する。
- 収集、解析、判定、設定生成、投入、rollbackを個別に再実行できるようにする。
- 外部・手動投入とalred内投入で、同じSnapshot、ChangeSet、Evaluatorを使用する。
- 実機投入を含まないoffline pathを先に実装し、fixtureで検証してからdevice accessを追加する。
- 変更対象または依存先の既存実装が設計書に未反映の場合は、As-Is解析とレビューを先に行う。
- 各Phaseの完了時に[IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md)を更新する。

## 3. Phase一覧

| Phase | 内容 | 初期状態 | 主な依存 | 完了条件 |
|---|---|---|---|---|
| 0 | 現行仕様の固定とfixture整備 | 完了 | なし | 既存CLI、renderer、collect成果物の回帰fixtureと対象NX-OS capability証跡がある |
| 1 | 共通operation workspaceとschema | 完了 | Phase 0 | schema、change-id、state、lock、approval、metadata、manifestを検証・保存できる |
| 2 | rawログimportとSnapshot生成 | 完了 | Phase 1 | collect成果物と外部transcriptから同一Snapshotを生成できる |
| 3 | 共通baseline evaluator | 完了 | Phase 2 | before単体およびbefore/afterの共通判定を出力できる |
| 4 | Overlay parserと自動差分検出 | 完了 | Phase 2 | 新規L2VNI/L3VNIと付随情報を`discovered-changes.yaml`へ出力できる |
| 5 | ChangeSetと共通config renderer | 完了 | Phase 0, 1 | CSV/ChangeSetからforward/rollback configとhashを生成できる |
| 6 | Overlay evaluatorと収束待ち | 完了 | Phase 3, 4 | 新規Overlayと既存Fabricへの影響を判定できる |
| 7 | `health-check` / `overlay-check` CLI | 完了 | Phase 3, 4, 6 | offline/direct収集のbefore/afterシナリオが動作する |
| 8 | `overlay-change plan/apply/rollback` | 一部実装 | Phase 5, 6, 7 | precheck、投入、保存、失敗制御、rollback後差分確認が動作する |
| 9 | support bundle | 完了 | Phase 3, 7 | allowlist、redaction、manifest、AI prompt付きarchiveを生成・検証できる |
| 10 | 9000v適合性・運用受入とhardware文書確認 | 一部実施 | Phase 7, 8, 9 | 9000v受入、hardware文書確認、配布binary確認を満たす |

Nexus 9000vを使用するChangeSetの具体的な受入手順は
[Nexus 9000v ChangeSet Lab Test Plan](./NEXUS_9000V_CHANGESET_LAB_TEST_PLAN.md)を参照する。
Phase 10の実施済み証跡、配布binary検証、hardware別の文書確認状況は
[Phase 10 Progress Report](./PHASE_10_PROGRESS_REPORT.md)を参照する。

## 4. Phase詳細

### Follow-up: 物理 interface の admin 状態補完（実装済み）

Phase 3 の追加実装として、`network-baseline-nxos` `1.8` へ `show interface` を追加した。
仕様、入出力、互換性、受け入れ条件は
[Baseline 設計 7.9.10](../design/network-ops/NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md#7910-show-interface-による-admin-状態補完)を参照する。

既存 collector 接続、詳細 parser、Snapshot field と統合 helper、単体／比較 evaluator、
証跡と retry の回帰確認、文書・sample・provenance 更新を実施した。
未装着を admin-up と推定せず、明示 admin 状態を採用して矛盾時は `UNKNOWN` とする。
合成 fixture による offline 検証を実施。追加 command の機器への接続検証は未実施。

### 4.1 Phase 0: 現行仕様の固定

- Markdownのlocal linkを自動検証し、CIで既存テストとともに実行する。
- 重要な既存設計判断をADRとして記録し、現在の仕様書へリンクする。
- pytestを導入し、既存`unittest`を含む全テストのrunnerとCIをpytestへ統一する。
- 既存機能の設計書化状況を棚卸しし、As-Is記録と正式設計への統合手順を定義する。
- `generate-vni-config`の入力と生成configをgolden fixture化する。
- collect成果物のディレクトリ、hostname、command境界、running-configの例をfixture化する。
- 既存CLI helpと代表的な終了codeを記録する。
- 設計例をそのままテスト入力へ使えるか確認し、差異を明示する。
- 現行VNI map/config、collect成果物、CLI基盤の順にAs-Is解析を開始する。
- 既存config push/saveをAs-Is固定し、1行送信、CLI error、timeout、保存応答をfixture化する。
- 開発基準となるNexus 9000vのfixtureを収集・sanitized化する。
- 対象hardwareはPhase 10でCisco公式資料と機種別golden configを確認し、実機fixtureと
  apply/rollback検証は行わない。deviceの動作検証対象はNexus 9000vだけとする。
- Capability Matrixの`OBSERVE_ONLY`、`PLAN_ONLY`、`APPLY_VERIFIED`を証跡に基づき更新する。
- `uv.lock`をGit管理し、CIの依存解決を再現可能にする。
- Ruffで現行baselineを監査し、既存コードを一括修正せず初期rule setと段階導入計画を決める。

### 4.2 Phase 1: operation workspaceとschema

- `operations/<change-id>/`、JST既定の自動採番、before/after attemptを実装する。
- machine-readable schema、未知field、default解決、canonical hashを実装する。
- JSON Schema Draft 2020-12をpackage resourceとしてwheel、sdist、binaryへ同梱する。
- operation state machine、change-id lock、SIGINT時の状態保存、読み取り専用statusを実装する。
- permission、local filesystem、空き容量、lock、artifact hashのoperation preflightを実装する。
- interactive approval recordと24時間の有効期限を実装し、非対話applyを拒否する。
- metadata、collection manifest、profile、Snapshot、結果のschema versionを定義する。
- 明示された`--change-id`と、afterで直前のbeforeを解決する規則を実装する。
- 成果物のatomic write、既存operationとの衝突、再実行をテストする。

### 4.3 Phase 2: rawログimportとSnapshot

- 既存collect成果物adapterを実装する。
- 外部CLI transcriptからhostnameと実行commandを識別するimporterを実装する。
- ambiguity、欠落、重複command、途中で切れた出力を`UNKNOWN`として追跡する。
- parserはNX-OS出力fixtureを使用し、raw provenanceをSnapshotへ保持する。

### 4.4 Phase 3: 共通baseline evaluator

- CPU、memory、environment、reload-pending、routing、BGP、OSPF、vPCなどを段階実装する。
- CPU閾値は既定80%、profileで変更可能とする。
- beforeの既存異常とafterの新規regressionを区別する。
- `PASS`、`WARN`、`FAIL`、`UNKNOWN`、`NOT_APPLICABLE`と終了codeを実装する。

### 4.5 Phase 4: Overlay差分検出

- VRF、L3VNI、L2VNI、VLAN、SVI、NVE、EVPN、BGPのCanonical modelを実装する。
- before/afterから新規リソースと付随情報をdevice横断で関連付ける。
- group、default VLAN、device override、SVI例外を表現するChangeSetを出力する。
- 観測不足や複数候補を推測で補完せず、曖昧性を明示する。

### 4.6 Phase 5: 共通config renderer

- 現行CSV adapterとChangeSet adapterをCanonical Render Modelへ接続する。
- 既存Jinja2 templateを棚卸しし、使用templateのpathをplanへ記録する。
- `new_l3vni`既定、MTU、IPv4/IPv6 SVI、IPv6 link-local、BGP VRF設定を実装する。
- global ingress-replication設定をpreconditionとして検証する。
- running configに基づくno-op、conflict、owned resourceとrollback configを生成する。

Phase 5完了後に合意されたdevice group拡張はfollow-upとして実装済みである。既存Phase 5の
完了実績を変更せず、実装状況は`IMPLEMENTATION_STATUS.md`で個別管理する。

- `OverlayDeviceGroups` schemaと`OverlayChangeSet.spec.device_groups_ref`を追加する。
- ChangeSet相対path、通常ファイル、symlink拒否、source / canonical hashを検証する。
- `devices`と子`groups`を最大16階層まで展開し、未知参照、循環、空groupを拒否する。
- group chain、override根拠、機器単位結果を`plan/resolved-targets.yaml`へ固定する。
- 外部入力を`inputs/device-groups.yaml`、参照関係を`plan/input-manifest.json`へ固定する。
- apply以降は外部sourceを再読込せず、承認済み固定成果物だけを使用する。
- 既存inline `device_groups`を維持し、inline / external同時指定を拒否する。
- schema、resolver、plan、approval改変検知、CLI、golden、後方互換テストを追加する。

### 4.7 Phase 6から10

- Overlay固有checkと収束待ちを実装後、共通CLIへ統合する。
- applyは承認済みplan hashだけを使用し、deviceごとの送信・応答・saveログを保存する。
- 失敗時は未投入deviceへの処理を停止し、状態を記録して自動または手動rollback判断へ渡す。
- rollback後はbeforeのrunning configとの差分とhealth checkの両方を確認する。
- support bundleはoperation全体の直接tar化を禁止し、redacted stagingから生成する。
- 最後にNexus 9000vの対象NX-OS releaseで、parser、timeout、収束時間、権限を確認する。
- hardware 4機種は公式資料でOS、構文、制約、scale、licenseを確認し、機種別golden configを
  固定する。文書確認後も`APPLY_VERIFIED`へ昇格しない。
- 初回`APPLY_VERIFIED`取得は通常applyのoverrideではなく、Nexus 9000vに限定した
  qualification recordと`overlay-change qualify`で実施する。qualification成功後も
  Capability Matrixは証跡レビュー後に手動更新する。

### 4.8 Role-aware Health Check follow-up

既存 Phase の完了実績を変更せず、次を role-aware Health Check の follow-up として段階的に実施する。各項目の実装状態は [Implementation Status](./IMPLEMENTATION_STATUS.md) を正本とする。
check ID、command、Snapshot field、判定、実装状態は [NX-OS Overlay Role Health Check Catalog](../design/network-ops/NXOS_OVERLAY_ROLE_HEALTH_CHECK_CATALOG.md) を正本とする。

1. `roles.yaml` の hostname 規則から 1 つの topology role を解決し、conflict と `other` を区別する。
2. topology role 配下の `functions` と `function_expectation_rules` を validation し、required / optional / forbidden を解決する。
3. `resolved-roles.yaml` schema、resolver version、source hash、before / after 固定を実装する。
4. `network-baseline-nxos` を topology role にかかわらず NX-OS host 全体へ適用する。
5. `nxos-overlay` を `leaf`、`border-gateway`、`spine`、`super-spine` に限定する。
6. `network-functions` と `other` でも対応 OS の baseline を実行し、`server` には NX-OS profile を実行しない。
7. `other` の read-only を `UNKNOWN`、compare、plan、apply を `ROLE_SCOPE_INVALID` で停止する。
8. NX-OS BGP の `template peer` と neighbor／dynamic neighbor prefix の `inherit peer` を展開し、直接定義と同じ実効 RR client model へ正規化する。未知 template、循環、矛盾は `RR_TEMPLATE_UNRESOLVED` として `UNKNOWN` にし、未設定 `FAIL` と区別する。
9. running config から function の実在を確認した後、必要な show command を条件付き収集する。
10. Checklist を device → profile → topology role / function の順に表示し、未実行 host を理由付き一覧へ集約する。
11. EVPN RR は before regression を初期判定とし、underlay 一般項目は baseline の結果を参照する。
12. role/function policy の正常系、競合、証跡欠落、partial attempt、後方互換テストを追加する。

完了時に `CONFIG.md` と配布 sample を実装済み schema へ更新する。未実装の nested function 設定を現行利用可能な設定として配布しない。

## 5. PhaseごとのCodex依頼テンプレート

```text
リポジトリのAGENTS.mdと、対象Phaseから参照される設計書を確認してください。
OVERLAY_CHANGE_IMPLEMENTATION_PLAN.mdのPhase <番号>だけを実装してください。

- 設計の意味を独断で変更しないでください。
- 設計と現行実装が競合する場合は、差異と影響を報告してください。
- 実装、単体テスト、CLI help、必要な設計書を同期してください。
- 実機への接続や設定投入は行わず、fixtureで検証してください。
- 完了後にIMPLEMENTATION_STATUS.mdを実態どおり更新してください。
- 実装済み、未実装、未検証を分けて報告してください。
```

## 6. 設計変更を伴う依頼テンプレート

```text
リポジトリのAGENTS.mdと関連設計書を確認してください。
まず既存仕様、影響範囲、選択肢、推奨案を整理してください。
合意した仕様を責務を持つ設計書へ反映し、文書間の例とデフォルト値を同期してください。
今回は設計更新だけを対象とし、実装コードは変更しないでください。
IMPLEMENTATION_STATUS.mdには「設計済み・未実装」として反映してください。
```

## 7. 計画変更

Phaseの分割、順序、完了条件を変更する場合は、理由と依存関係への影響を本書へ反映する。
進捗だけが変わる場合は本書の初期状態を書き換えず、`IMPLEMENTATION_STATUS.md`を更新する。
