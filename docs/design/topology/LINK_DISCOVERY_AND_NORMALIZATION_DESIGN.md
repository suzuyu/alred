# Link Discovery and Normalization Design

## 1. 目的と責務

本書は、LLDPとinterface descriptionから物理link候補を抽出し、正規化、証拠統合、confidence判定を行って
canonical link CSVを生成する仕様を定める。現行実装の観測根拠と未確認点は
[Topology and Rendering As-Is](../../as-is/TOPOLOGY_AND_RENDERING_AS_IS.md)を参照する。

inventory、mapping、credentialの責務は
[Inventory, Credentials, and Device Access Design](../common/INVENTORY_CREDENTIALS_AND_DEVICE_ACCESS_DESIGN.md)、
role解決は[Role Definition and Resolution Design](../common/ROLE_DEFINITION_AND_RESOLUTION_DESIGN.md)、
containerlab生成は[Containerlab Workflow Design](../containerlab/CONTAINERLAB_WORKFLOW_DESIGN.md)を正本とする。

## 2. 入出力

入力はinventory、任意の機器別raw LLDP、機器別raw running config、mapping、description ruleである。収集処理は
[Collection Design](../common/COLLECTION_DESIGN.md)、外部show run folder／複数host transcriptは
[External Running Config Import Design](../common/EXTERNAL_RUNNING_CONFIG_IMPORT_DESIGN.md)へ委譲し、本処理は機器へ
接続しない。LLDPは補助証拠であり、存在しない場合もdescription-onlyで解析を継続する。

出力は次の2 fileとする。

- confirmed: 複数方向または複数sourceでendpoint関係を裏付けられたlink
- candidate: 片方向の証拠しかないlink

CSV schemaは次とする。

| field | 必須 | 意味 |
|---|---:|---|
| `src_node`、`src_if` | yes | 観測元endpoint |
| `dst_node`、`dst_if` | yes | remote endpoint |
| `protocol` | yes | `lldp`、`description`、`lldp+description`、`design` |
| `confidence` | yes | `high`、`medium`、`low` |
| `evidence` | yes | 判定根拠の機械可読値 |
| `remote_mgmt_ip` | no | LLDP等で観測したremote管理address |
| `rule_name` | no | description parser rule |
| `warning` | no | 証拠不一致等の追跡情報 |

入力modeは次を区別する。

| mode | source | 状態 |
|---|---|---|
| legacy alred collect | `<input>/config/<hostname>_run.txt|json`と任意の`lldp/` | 実装済み |
| external running config import | `running-config-import-manifest.yaml`が参照するhost別configと任意 LLDP | 実装対象 |
| Evidence Package | Package Manifestが参照するconfig／任意 LLDP／rules／canonical link | 実装対象 |
| latest Operation | 最新の正常公開済み current before attempt | 実装対象 |

既存 file 入力、external import、Evidence Package、Operation は排他的に一つだけ指定する。external import の option は
`--running-config-import <manifest-or-directory>`とし、host分割やidentity解決を`normalize-links`内へ重複実装しない。
Operation は `--latest-operation` または `--change-id <id>` で選択する。入力 selector を省略した場合は
従来どおり `--input raw` 相当とする。

readerは必須header、必須値、confidenceとprotocolの許容値を検証し、不正な入力をcode付きvalidation errorで
拒否するべきである。現行実装はheader validationを行っておらず未実装である。

## 3. Parsing adapter

device typeごとにLLDP adapterを選択する。別platformの出力形式がfixtureで同等と確認されていない限り、同じ
parserを使えることだけで正式対応とはしない。未対応platformは空結果とwarningを返し、誤ったlinkを推定しない。

descriptionはinterface stanzaから抽出し、設定されたruleに一致した場合だけremote endpointへ変換する。rule名を
evidenceへ残し、推定できないdescriptionをlinkとして扱わない。

## 4. Canonical normalization

1. explicit hostname／interface mappingを最優先する。
2. device type別のinterface略称をcanonical表記へ変換する。
3. exclude interfaceを適用する。
4. 両endpointを方向非依存のcanonical pairへ変換して重複を判定する。

mappingは完全一致を基本とし、意図しない部分文字列置換を行わない。正規化前の観測値をraw collectionに保持し、
canonical CSVだけから元データを復元できると仮定しない。

## 5. Evidenceとconfidence

| evidence | 出力 | confidence |
|---|---|---|
| 双方向LLDP | confirmed | `high` |
| LLDPと反対向きdescription | confirmed | `medium` |
| 双方向description | confirmed | `low` |
| 片方向LLDP | candidate | `low` |
| 片方向description | candidate | `low` |

LLDP recordが0件でもdescription recordを破棄しない。双方向descriptionが相互一致すればconfirmed `low`、片方向だけなら
candidate `low`とする。Containerlabはconfirmedだけを入力とし、description-only candidateを自動昇格しない。

LLDPとdescriptionが同じlocal interfaceについて異なるremoteを示す場合はfail openで片方を消さず、双方の証拠を
維持して`warning`へmismatchを記録する。自動設定生成に使う側はwarning付きlinkを明示的に確認する。

`confidence`は証拠の強さであり、linkが業務上正しいことの保証ではない。default gateは各consumer設計で定める。

## 6. Determinismと再実行

同じraw input、mapping、parser versionからは、row順を含めて同一CSVを生成しなければならない。sort keyは
canonical endpoint pair、protocol、evidenceとする。現行merge処理は集合走査後にsortしておらず、この要件と
不一致である。

生成時は少なくともinput path、mapping path、parser version、record数、mismatch数をlogへ残す。将来operation
artifactへ統合する場合はinput hashとschema versionも記録する。

## 7. Consumer boundary

- diagramとcontainerlabはconfirmed/candidateを区別し、`min-confidence`を適用する。
- containerlabはport-channelを物理linkとして出力しない。
- candidateまたはwarning付きlinkを設定投入へ直接利用しない。
- rendererは入力順に依存せず、endpointの向き、重複、出力順を再度canonical化する。

### 7.1 Health consumer scope

`network-baseline-nxos`は同じCanonical Link Evidenceを参照し、LLDP／description parser、mapping、
exclude規則を再実装しない。Health固有の責務は対象endpointのscopeとstatus判定である。

Healthの既定対象はinventoryで識別できるmanaged network device間とする。`network-functions`は
`auto`とし、LLDPで観測され、inventoryへ一意に解決でき、対応parserで解析できる場合に含める。
server、inventory未登録endpoint、外部接続先は既定のHealth判定から除外するが、Canonical Link Evidence、
confirmed／candidate出力から削除しない。

両endpointが収集対象なら双方向証拠を照合する。remoteが収集対象外ならlocal LLDPとlocal descriptionだけを
評価し、逆方向未収集を片方向異常にしない。descriptionがないだけでは不一致とせず、LLDPが双方向一致する
場合はHealthを`PASS`とする。description必須環境はHealth policyで`WARN`へ変更できる。

Health Operationはmappings、description rules、解決済みexclude、normalizer versionをbeforeで固定し、
afterでhash検証する。規則変更による出力差を実link変更として比較しない。

### 7.2 Evidence Packageの隔離環境再生成検証

`evidence-package import`はarchiveを検証・展開するだけで、link解析を実行しない。隔離環境ではimport成功後に
`normalize-links`の Evidence Package 入力 mode を独立して実行し、package同梱の Canonical Link Evidence を
再生成検証する。

```text
alred normalize-links \
  --evidence-package <imported-package-directory>
```

既存の`--hosts`、
`--input`、`--mappings`、`--description-rules`によるfile入力modeは後方互換を維持し、
`--evidence-package`との同時指定を拒否する。
Evidence Package 入力 mode の必須 option は `--evidence-package` だけとする。`--output-dir` は任意とし、
省略時は従来の link 出力 directory（既定 `output/`）へ成果物を生成する。

#### 7.2.1 入力解決

Package Manifestのartifact IDから次を解決し、directory名やbasenameから推測しない。

| 入力 | 条件 |
|---|---|
| resolved inventory | package対象device、identity、platformを含む検証済みcopy |
| `lldp_neighbors_detail` | 対象deviceごとの成功済みraw。Collection Manifestのpath／size／hashと一致 |
| running config | Package Manifestの`config_content`に対応するartifact。description解析へ使用 |
| resolved mappings | package作成時に固定したhostname／interface mappingとhash |
| resolved description rules | package作成時に固定したrule、exclude、hash |
| role／site context | package作成時にlink scopeへ使用した場合 |
| packaged canonical links | `canonical/normalized-links.csv`とschema／semantic hash |
| version context | normalizer、LLDP／config parser、mapping／rule schema version |

`verbatim` packageでもlink再生成は原文を外部へ公開せずprocess内で読む。出力にはPackage Disclosure Policyを適用した
identityだけを使用し、secretをlink warning、report、exceptionへ含めない。

#### 7.2.2 再生成と比較

1. Package Manifest、Collection Manifest、import record、全入力hashを検証する。
2. package作成時と同じnormalizer／parser major、resolved mappings、description rules、excludeを固定する。
3. LLDPとinterface descriptionをparseし、通常のcanonical normalizationとconfidence判定を実行する。
4. endpoint pair、protocol、confidence、evidence、rule、warningをcanonical sortする。confirmed link の
   endpoint 方向は意味を持たないため、node／interface の組を辞書順で `endpoint_a`／`endpoint_b` に正規化する。
5. 再生成したcanonical semantic hashを同梱`normalized-links.csv`のsemantic hashと比較する。
6. confirmed、candidate、warning、skip host、解析制約をLink Verification Resultへ記録する。
7. `VERIFIED`の場合だけconfirmed linkをatomicに公開する。

表示用 row 順、改行、confirmed link の `src`／`dst` 反転は canonical 化後に同一と判定する。confirmed link の
`remote_mgmt_ip` は LLDP を観測した方向に依存し、管理 identity は resolved inventory で固定されるため、link の
semantic hash には含めない。endpoint pair、interface、protocol、confidence、evidence、rule、warning の差は
semantic 不一致である。candidate は片方向であること自体が evidence なので `src`／`dst` を反転せず、
`remote_mgmt_ip` も含めて比較する。version 差や開示変換によって同じ解析を再現できない場合は、推測で比較結果を
一致にせず、version mismatch または `UNKNOWN` とする。

Canonical Link resource は `semantic_version` を記録する。version 2 は前段の方向非依存規則を使用する。
`semantic_version` がない旧 package は version 1 として、Manifest 宣言値を旧方式の方向依存 hash で検証した後、
packaged／regenerated confirmed link を version 2 へ正規化して比較する。これにより旧 package の改ざん検証を
省略せず、代表方向だけが異なる既存 package を再作成なしで利用できる。

#### 7.2.3 成果物と状態

```text
<lab-work-directory>/links/
├── links_confirmed.csv
├── links_candidates.csv
├── normalized-links.regenerated.csv
├── link-warnings.json
├── link-verification.json
└── normalization-manifest.yaml
```

| 状態 | 意味 | Containerlab生成 |
|---|---|---|
| `VERIFIED` | 入力、version、canonical semantic hashが一致 | confirmedのみ許可 |
| `VERSION_MISMATCH` | normalizer／parser／rule schemaを同一条件で再現できない | 停止 |
| `SEMANTIC_MISMATCH` | endpoint、confidence、evidence、warning等が不一致 | 停止 |
| `INCOMPLETE` | raw、inventory、rules、packaged canonicalが不足 | 停止 |
| `UNKNOWN` | 開示変換や未対応parserにより同一性を判定不能 | 停止 |

candidateとwarning付きlinkは成果物へ保持するが、`VERIFIED`でもContainerlabへ自動採用しない。採用にはpackage外の
明示的なdesign overrideとレビュー記録が必要であり、canonical evidenceを上書きしない。

`normalization-manifest.yaml`にはpackage ID、Package Manifest／import record hash、入力artifact ID／hash、
normalizer／parser／rule version、出力hash、skip理由を記録する。`link-verification.json`にはpackaged／regenerated
semantic hash、状態、不一致fieldの要約を記録し、raw値やsecretを含めない。

## 8. Errorとpartial output

必須入力不足、schema不正、未知confidenceは処理を失敗させる。個別hostのraw file不足や未対応parserは対象hostを
warningとしてskipできるが、confirmed/candidate件数とskip対象を表示する。公開用 CSV は処理完了後に atomic に
置換し、失敗時に既存の成功済み file を壊さない。Evidence Package 照合失敗時は regenerated と
verification を記録するが、confirmed の成功済み公開物は置換しない。

Evidence Package再生成では、必須artifact不足を`EVIDENCE_INCOMPLETE`、version不一致を
`LINK_REGENERATION_VERSION_MISMATCH`、semantic不一致を`LINK_REGENERATION_MISMATCH`とする。以前の成功済み
`VERIFIED`成果物があっても、新しい失敗実行で上書きしない。

## 9. Test要件

- platform別のsanitized LLDP fixture
- description ruleの正常、曖昧、不一致
- mapping前後とexclude interface
- 5種類のevidence判定とmismatch warning
- hash seedを変えても同じCSVになること
- confirmed link の入力順、`src`／`dst` 方向、観測側 `remote_mgmt_ip` が異なっても version 2 semantic hash が一致すること
- 旧 package の version 1 宣言 hash を旧方式で検証してから version 2 比較へ移行すること
- header欠落、空endpoint、不正confidenceのfail closed
- confirmed/candidate consumerのconfidence境界
