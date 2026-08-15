# Schema and Compatibility Policy

## 1. 文書の目的

alredのHealth Check、Overlay変更管理、operation成果物で使用するYAML/JSON schemaの共通規則、
default解決、未知field、version互換性を定義する。

## 2. Schema対象

初期実装では少なくとも次をmachine-readable schemaとして管理する。

| Kind | 主形式 | 用途 |
|---|---|---|
| `HealthCheckProfile` | YAML | 収集、判定、閾値、収束 |
| `HealthCheckExecutionContext` | YAML | beforeで固定した非秘密の収集・入力条件 |
| `OverlayChangeSet` | YAML | 宣言・発見したOverlay変更 |
| `OverlayDeviceGroups` | YAML | ChangeSetから参照する階層device group |
| `OverlayInputManifest` | JSON | ChangeSet、device group、resolved targetのpathとhash |
| `OverlayResolvedTargets` | YAML | group chainと機器単位の固定target |
| `OperationMetadata` | YAML | change-id、phase、attempt、状態 |
| `OperationLocation` | YAML | Operation IDからlive／archiveの物理pathを解決するindex |
| `OperationArchiveManifest` | YAML | archive対象file、hash、mode、storage version |
| `CollectionManifest` | YAML | rawログと取得commandの来歴 |
| `RunningConfigImportManifest` | YAML | 外部show runのsource、host解決、採用区間、canonical config |
| `RunningConfigSourceMap` | YAML | 任意filenameとinventory hostnameの明示対応 |
| `CanonicalLinkEvidence` | JSONまたはCSV | LLDP／descriptionの正規化済みlink証拠、scope、confidence、warning |
| `HealthSnapshot` | JSON | 正規化した観測状態 |
| `HealthResult` | JSON | check結果と比較 |
| `ExecutionPlan` | JSON | apply対象、順序、hash、前提 |
| `RollbackPlan` | JSON | rollback対象、所有権、検証 |
| `ApprovalRecord` | JSON | 承認者、期限、承認対象hash |
| `DiscoveredChanges` | YAML | before/afterからの自動発見 |
| `ExecutionResult` | JSON | apply/save/rollback実績 |
| `SupportBundleManifest` | YAML | bundle内容とredaction証跡 |
| `EvidencePackageManifest` | YAML | 可搬packageのsource、内容、開示policy、checksum |
| `EvidenceDisclosurePolicy` | YAML | field class別の保持、仮名化、mask、除外 |
| `EvidencePackageImportRecord` | YAML | import時のarchive、Manifest、tool version、検証結果 |
| `SecretScanResult` | YAMLまたはManifest field | rule catalog version、finding、confidence、scan状態 |
| `LabTransformParameters` | YAML | Evidence Package configをlab-local値へ変換するparameter |
| `LabTransformManifest` | YAML | package、parameter、変換rule、生成startup configのprovenance |
| `LinkVerificationResult` | JSON | packaged／regenerated linkのsemantic hash、状態、不一致要約 |
| `NetworkDiagramManifest` | YAML | diagram source、実効 option、入力・成果物 hash |
| `EVPNControlPlaneModel` | YAML | EVPN node／session／state／diagnostic と evidence provenance |

schema fileは`schemas/alred/v1/`配下を初期配置候補とし、Python実装と文書例から独立した
検証可能なartifactにする。実装時の配置はpackage resourceとして
`alred/schemas/v1/*.schema.json`とする。

Phase 1では`OperationMetadata`、`OperationExecution`、`OperationLock`、
`ActiveHealthCheckChange`、`ApprovalRecord`、`HealthCheckProfile`、
`CollectionManifest`、`HealthSnapshot`、`HealthResult`、`ExecutionPlan`、
`RollbackPlan`を実装済みとする。Phase 2で`TranscriptImportManifest`を追加した。
Operation dated layoutと手動archiveで`OperationLocation`、`OperationArchiveManifest`を追加した。
Phase 3で`ResolvedHealthCheckProfiles`を追加した。
Phase 7で`HealthCheckExecutionContext`を追加した。
Phase 4で`OverlayChangeSet`を追加し、自動発見結果の`DiscoveredChanges`は
`metadata.source: discovered`の同一Kindとして表現する。
`OverlayDeviceGroups`、`OverlayChangeSet.device_groups_ref`、`OverlayInputManifest`、
`OverlayResolvedTargets`を実装済みとする。既存`OverlayChangeSet.spec.device_groups`も
後方互換形式として継続する。
Phase 5でconfig path、file hash、render model hash、resource action、使用templateを固定する
`OverlayRenderManifest`を追加した。
Phase 6でconfiguration / operational / impactのcheck、Overlay総合結果、warning/conflict、
収束情報を表す`OverlayHealthResult`を追加した。
Phase 7で順序付きattemptと連続成功数を固定する`OverlayConvergenceResult`を追加した。
Phase 9でarchive選択、source/redacted hash、secret scan、解析制約を記録する
`SupportBundleManifest`を追加した。
`EvidencePackageManifest`、`EvidenceDisclosurePolicy`、`EvidencePackageImportRecord`、`SecretScanResult`、
`NetworkDiagramManifest`、`EVPNControlPlaneModel` は Topology の一括生成 command で実装済みとする。
`EVPNControlPlaneModel` は物理 `CanonicalLinkEvidence` と別 schema とし、EVPN session を物理 link として保存しない。
`LabTransformParameters`、`LabTransformManifest`、`LinkVerificationResult`、`RunningConfigImportManifest`、
`RunningConfigSourceMap`は設計済み・未実装である。
Healthで使用する`CanonicalLinkEvidence`のmachine-readable schemaとHealth Snapshot参照fieldは
設計済み・未実装である。既存confirmed／candidate CSVは互換入力・出力として維持する。
`ExecutionResult`、`SupportBundleManifest`は各機能Phaseで実装し、schemaがない状態で
保存済み成果物を正式版として扱わない。

Schema dialectはJSON Schema Draft 2020-12を使用する。構造、型、必須field、enum、基本範囲は
`jsonschema`で検証し、IP prefix、group/device解決、platform capability、running-config競合は
Python domain validatorで検証する。

## 3. Version

- 外部保存するYAMLは`api_version: alred/v1`と`kind`を必須とする。
- JSON成果物は`schema_version: 1`を必須とする。
- `metadata.yaml`を含むYAMLの共通envelopeは`api_version`、`kind`、`metadata`、`spec`とする。
- field追加は、既存fieldの意味とdefaultを変えない場合だけ同じmajorで行う。
- field削除、型変更、意味変更、default変更で既存解釈が変わる場合はmajor versionを更新する。
- 初期実装では異なるmajor間の自動migrationを提供しない。
- 未対応majorは推測変換せず`SCHEMA_UNSUPPORTED`とする。

## 4. 入力と出力の未知field

### 4.1 利用者入力

profile、ChangeSet、policyなど、実行動作を決める入力は未知fieldを拒否する。誤字を黙って
無視しない。errorにはJSON Pointer相当のfield pathを含める。

```text
VALIDATION_ERROR at /spec/l2vnis/0/default_vlna:
unknown field; did you mean default_vlan?
```

### 4.2 保存済み出力

同じmajor versionの保存済みJSON/YAMLを読むreaderは、未知の追加fieldがあっても既知fieldを
安全に解釈できる場合に限り保持または無視できる。ただし、hash検証対象のdocumentを再保存
してはならない。必須field欠落や意味が不明なenumは`SCHEMA_UNSUPPORTED`とする。

## 5. Defaultと解決済み入力

- defaultはschemaまたは単一のdomain default定義から適用し、CLI、renderer、文書へ重複実装しない。
- raw inputとdefault適用後のresolved inputを分離して保存する。
- approval、plan hash、config生成にはresolved inputを使用する。
- `null`、field省略、空配列、空文字列を同じ意味として扱わない。
- default変更は既存planへ遡及適用せず、新しいtool/schema versionで再planする。

## 6. Validation順序

1. YAML/JSON構文
2. `api_version` / `schema_version` / `kind`
3. field、型、enum、値範囲
4. default解決
5. group、device、inventory参照解決
6. cross-field validation
7. platform capability
8. before running-configとの競合
9. planとconfig生成

外部`OverlayDeviceGroups`を参照する場合、手順5の前にChangeSet基準のpath解決、参照先schema、
循環参照、最大階層、source hashを検証する。外部documentを未検証mappingとしてmergeしない。

前段のerrorを後段の推測で補わない。一回のvalidationで安全に列挙できる独立errorはまとめて
返せるが、未解決参照に依存する派生errorは生成しない。複数errorはdocument path、
validator ID、messageの順で安定sortし、同じ入力で順序が変わらないようにする。

## 7. Hashとcanonicalization

- approval対象はraw file byte列ではなく、用途ごとに定義したcanonical representationのhashを使用する。
- JSONはUTF-8、key sort、余分な空白なしのcanonical byte列を定義する。
- YAML入力はvalidation・default解決後のcanonical JSONへ変換してhashする。
- hash algorithmは初期`SHA-256`とし、値には`sha256:`prefixを付ける。
- source file hashとresolved document hashを両方保存する。
- 外部参照を含む入力ではChangeSet、参照先document、展開済みtargetを個別にhashし、参照関係を
  manifestへ保存する。
- secretを含む値をhashだけに置き換えて通常成果物へ残す方法は採用しない。

## 8. Compatibility test

- 各schemaに最小正常例、完全正常例、未知field、欠落、境界値、cross-field errorを用意する。
- 設計書のYAML/JSON例を可能な範囲でschema testへ取り込む。
- 同じmajorの旧fixtureを新readerで読めることを確認する。
- golden成果物はschema、tool version、parser/renderer versionを固定する。

## 9. 配布

- wheel、source distribution、PyInstaller binaryへschemaを同梱する。
- source checkout、installed package、binaryで同じresource loaderを使用する。
- schema pathをcurrent working directoryから暗黙に探索しない。
- build testで全Kindのschemaをresource loaderから読み込めることを確認する。
- schemaと実装のversion不一致は起動時またはvalidation開始前に`SCHEMA_UNSUPPORTED`とする。
