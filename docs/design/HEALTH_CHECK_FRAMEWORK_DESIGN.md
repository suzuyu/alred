# Health Check Framework Design

## 1. 文書の目的

ネットワーク作業の種類に依存しない、共通の作業前後正常性確認基盤を定義する。

この基盤はOverlay追加だけでなく、インターフェース変更、ルーティング変更、メンテナンス、OS upgradeなどから再利用する。作業固有の知識はprofileとevaluatorへ分離する。

Overlay固有のChangeSet、VNI自動発見、EVPN/VXLAN判定、設定投入については[Overlay Change Management Design](./OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)を参照する。

正常性確認の異常を人またはAIへ引き渡すarchive、redaction、Manifest、prompt生成は[Support Bundle Design](./SUPPORT_BUNDLE_DESIGN.md)を参照する。

## 2. 設計原則

- 収集は既存の`collect-*`コマンドへ一本化する
- 正常性確認は収集済みログからオフラインでも再実行できる
- rawログ、Snapshot、判定を分離する
- 共通フレームワークへ作業固有の判定知識を埋め込まない
- 収集不能と正常を区別し、判定不能は`UNKNOWN`とする
- beforeから存在する異常と、afterで新規発生したregressionを区別する
- 人間向けMarkdownと外部連携用JSONの両方を保存する
- 同じ入力から同じ結果を再生成できるよう、収集世代、schema、parser versionを固定する

## 3. アーキテクチャ

```text
既存 collect-* コマンド
    └─ rawログ・JSON sidecar・running-config ───────┐
                                                    │
外部NX-OS CLI transcript                            │
    └─ External Transcript Importer                 │
         ├─ Transcript Import Manifest              │
         └─ 正規化したコマンド区間 ────────────────┤
                                                    ↓
Collection Manifest
    ↓
Snapshot Builder
    ├── Common Parsers
    └── Profile Parsers
    ↓
Canonical Health Snapshot
    ↓
Comparator + Check Evaluators
    ↓
Convergence Runner
    ↓
Markdown / YAML / JSON Report
```

### 3.1 Existing Collectors

既存の以下を再利用する。

- inventoryとpolicy
- 認証情報解決
- SSH / NX-API
- 接続事前チェック
- 並列実行
- running-config取得
- 任意showコマンド取得
- rawログ、JSON sidecar、履歴、archive
- コマンド失敗情報

Health Check専用Collectorは作成しない。`health-check --collect`は既存collect処理を呼ぶ薄いオーケストレーターとする。

#### 3.1.1 External Transcript Importer

alred以外で取得したCLIセッションログも入力可能とする。`External Transcript Importer`は指定されたファイルまたはディレクトリを読み、1つのログに混在する複数機器・複数showコマンドを、ホストとコマンド単位へ分割してCollection Manifestへ変換する。

```text
外部CLI transcript
    ↓
制御文字・ANSI escape・paging文字の正規化
    ↓
prompt検出
    ↓
hostname / command / output区間の分割
    ↓
Transcript Import Manifest
    ↓
Collection Manifest
    ↓
既存Snapshot Builder
```

初期実装の対象は、次のように実行コマンドを含む連続したNX-OS CLI transcriptとする。

```text
leaf01# show processes cpu
CPU utilization for five seconds: 12%/3%; one minute: 10%

leaf01# show nve vni
Codes: CP - Control Plane
...

leaf02# show processes cpu
CPU utilization for five seconds: 18%/4%; one minute: 13%
```

認識するpromptは`hostname#`、`hostname>`、`hostname(config)#`、`hostname(config-if)#`などとする。FQDN、`-`、`_`を含むhostnameを許可する。抽出名はinventoryのhostnameおよび`aliases`と照合し、大文字小文字、短縮名、aliasの衝突を一意に解決できない場合は`PLAN_ERROR`とする。

コマンドはprompt直後の文字列から抽出し、余分な空白、`terminal length 0 ;`などの既知prefix、出力を変えない`| no-more`を正規化してprofileのcommand IDへ対応付ける。`| include`、`| exclude`など出力範囲を変えるfilterは、filterなしのコマンドと同一視しない。

Importerは各区間に`high`、`medium`、`low`のconfidenceを付ける。正常性判定へ自動採用するのは`high`だけを既定とし、曖昧な区間を推測で割り当てない。次は`unresolved_segments`へ記録する。

- promptまたは実行コマンドが記録されていない
- ログ途中から始まり、最初の出力のホスト・コマンドが不明
- コマンドがterminal幅で折り返され、復元を確定できない
- 複数ホストの出力が行単位で混在している
- terminal serverのpromptと機器promptを区別できない
- 同一ホスト・同一コマンドが複数あり、採用世代を決定できない
- pagingや制御文字により出力が破損している

行ごとに`[leaf01]`のようなホストprefixを付ける並列実行ツールのログは、汎用prompt解析へ含めず、形式ごとのinput adapterとして追加する。

元ログは変更・上書きせず、入力ファイルのSHA-256、検出区間、行番号、正規化内容、未解決区間を`transcript-import-manifest.yaml`へ保存する。必須コマンドが見つからない場合は正常と推定せず、collection completenessを`UNKNOWN`またはcollection不成立として扱う。

### 3.2 Collection Manifest

既存collectの最新ミラーだけを参照すると、異なる実行世代のファイルが混ざる可能性がある。正常性確認では`collection_id`を発行し、使用したファイルをmanifestへ固定する。

```yaml
api_version: alred/v1
kind: CollectionManifest

metadata:
  collection_id: CHG-2026-00123-before-20260720T100000
  change_id: CHG-2026-00123
  phase: before
  started_at: "2026-07-20T10:00:00+09:00"
  completed_at: "2026-07-20T10:01:30+09:00"
  timezone: Asia/Tokyo

spec:
  profiles:
    - network-baseline
    - nxos-overlay

  hosts:
    leaf01:
      status: success
      commands:
        running_config:
          status: success
          collected_at: "2026-07-20T10:00:15+09:00"
          file: config/old/20260720100000/leaf01_run.txt
          sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
        show_commands:
          status: success
          collected_at: "2026-07-20T10:00:40+09:00"
          file: show_lists/leaf01/old/20260720100000/leaf01_shows.log
          sha256: abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789
```

Snapshot Builderはmanifestに記録されたファイルだけを読む。
同じtranscriptに複数commandが含まれる場合、各command recordには`start_line`、
`end_line`、`output_start_line`、`output_end_line`を保存する。`file`のSHA-256をSnapshot生成時に
再検証し、hash不一致や範囲外を推測で読み直さず`PARSER_ERROR`とする。

### 3.3 Snapshot Builder

rawログを共通Snapshotへ正規化する。値ごとに次を追跡できるようにする。

- 取得元コマンド
- rawファイル
- 取得時刻
- parser名とversion
- parse warning
- collection status

Phase 2の初期NX-OS parserは`show version`、`show processes cpu`、
`show system resources`、`show system config reload-pending`、`show vpc brief`、
`show nve interface`、`show bgp l2vpn evpn summary`を対象とする。その他の収集済みcommandは
破棄せず`parse_status: unsupported`としてprovenanceへ残す。profileが必須とするcommandの
不足・unsupported判定はPhase 3のEvaluatorで`UNKNOWN`とする。

### 3.4 Comparator

before / afterを比較し、次を抽出する。

- added
- removed
- changed
- preserved
- collection status change

比較方式はcheckごとに選択する。

- 完全一致
- 状態遷移禁止
- 減少禁止
- 最低値
- 許容幅
- 新規発生禁止
- 情報のみ

### 3.5 Check Evaluator

共通Evaluatorとprofile固有Evaluatorが、同じ結果型を返す。

```json
{
  "check_id": "preserve_bgp_neighbors",
  "profile": "network-baseline",
  "host": "leaf01",
  "result": "FAIL",
  "classification": "regression",
  "resource": "bgp-neighbor/10.0.0.1",
  "before": "Established",
  "after": "Idle",
  "evidence": {
    "command": "show bgp all summary",
    "file": "after/raw/leaf01_shows.log"
  }
}
```

### 3.6 Convergence Runner

after直後の一時的な未収束を即時FAILにせず、profileがretry可能と定義したcheckを再実行する。

```yaml
convergence:
  timeout_seconds: 300
  interval_seconds: 15
  consecutive_passes: 2
```

plan不正、認証失敗、unsupported parserなど、待機で改善しない問題は即時終了する。

### 3.7 Operation Gate

作業前または設定投入batch間で継続的な高CPUなどを検出した場合、check結果とは別に後続操作を制御するgateを設ける。

- 単発閾値超過はWARNとして再sampleする
- 規定回数連続した場合は、対話実行では継続確認を行う
- 非対話実行ではpromptを出さず、profileの`non_interactive_action`に従う
- 安全側の既定値は`abort`とする
- 継続承認は時刻、利用者、観測値、plan hashとともに記録する
- after評価など後続操作が存在しない場面では確認を求めず、結果へ記録する

Operation Gateは`WARN`を自動的に`FAIL`へ変更するものではない。正常性判定と「作業を続行してよいか」を分離する。

change-id単位の状態遷移、排他制御、中断、設定投入承認、成果物permissionは
[Operation State and Approval Design](./OPERATION_STATE_AND_APPROVAL_DESIGN.md)を正本とする。
共通schema互換性は[Schema and Compatibility Policy](./SCHEMA_AND_COMPATIBILITY_POLICY.md)、
共通error codeとCLI終了codeは[Error Catalog](./ERROR_CATALOG.md)に従う。

## 4. Health Check Profile

profileは、正常性確認で使用する収集、解析、判定、収束待ち、作業継続条件をまとめた設定単位である。`--profile`は機器のroleや実行phaseを指定するoptionではなく、この設定単位を選択するために使用する。

- 対象platform
- 必須・任意収集コマンド
- feature検出と条件付き収集
- parser
- check evaluator
- severity
- retry可否
- 閾値
- Operation Gate
- report policy

### 4.1 `--profile`の引数仕様

```text
--profile <profile-ref>
```

`--profile`は複数回指定可能とし、指定順を保持して合成する。カンマ区切りは採用しない。
`health-check before`および`health-check snapshot --phase before`で省略した場合は、
`network-baseline-nxos`を1件だけ既定値として解決する。

- `--profile`を1件以上明示した場合は、その指定列が実効profileとなり、既定profileを自動追加しない
- `nxos-overlay`はOverlay作業でも自動追加せず、必要な場合に明示する
- after / rollbackではbeforeの`resolved-profiles.yaml`を継承し、既定値を再解決しない
- 解決済み成果物には各参照の`resolution_source: default | explicit`を記録する


初期実装で受け付ける`profile-ref`は次の2種とする。

| 種別 | 形式 | 内容 | 例 |
|---|---|---|---|
| 組み込みprofile名 | `<name>` | alredに同梱し、profile registryへ登録されたprofile | `network-baseline-nxos`、`nxos-overlay` |
| profileファイル | `<path>.yaml`または`<path>.yml` | 利用者が管理する`HealthCheckProfile` YAML | `profiles/site-a-overlay.yaml` |

絶対パスも許可するが、再現性のため作業ディレクトリからの相対パスを推奨する。URL、任意のPython module、カンマ区切りリストは初期実装では受け付けない。存在しない名前、読めないファイル、未知の`api_version` / `kind`は実行前に`PLAN_ERROR`とする。

CLI例:

```bash
# 組み込みprofileを1つ指定
alred health-check before \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos

# 共通baselineとOverlay固有profileを合成
alred health-check before \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos \
  --profile nxos-overlay

# site固有profileを追加
alred health-check before \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --profile profiles/site-a-policy.yaml
```

組み込みprofile名は次の用途とする。

| profile名 | 適用対象 | 主な内容 |
|---|---|---|
| `network-baseline-nxos` | NX-OSを対象とする通常の作業前後確認 | CPU、memory、interface、route、neighbor、logging、設定保存、reload-pending。featureに応じてvPC、BFD、OSPF、BGPなどを追加 |
| `nxos-overlay` | EVPN/VXLANの追加・変更 | NVE、VNI、EVPN route、VLAN、VRF、SVI、anycast gateway、および新規Overlay変更の発見・評価 |

`nxos-overlay`だけの指定も許可するが、通常運用では既存通信への影響も確認するため、`network-baseline-nxos`との併用を推奨する。

### 4.2 Profile YAMLのパラメータ

profileファイルは次の構造を正規形とする。

| パス | 必須 | 内容 |
|---|---:|---|
| `api_version` | yes | schema互換性を示す。初期値は`alred/v1` |
| `kind` | yes | `HealthCheckProfile`固定 |
| `metadata.name` | yes | profileの一意な論理名 |
| `metadata.version` | yes | profile内容の版。文字列として扱う |
| `metadata.description` | no | 用途の説明 |
| `spec.platforms` | yes | 対象platformの配列。例: `[nxos]` |
| `spec.command_sets` | no | 組み込みcommand set。例: `core`、`routing` |
| `spec.collectors` | no | platform別のコマンド、必須性、実行条件 |
| `spec.auto_features` | no | 実機情報から条件付き収集を有効にするfeature |
| `spec.parsers` | no | command IDとparser IDの対応 |
| `spec.checks` | 条件付き | evaluator、severity、適用条件、before/after比較方法。差分profileでは省略可。合成後全体では1件以上必須 |
| `spec.thresholds` | no | CPU、memory、route減少率などの閾値 |
| `spec.convergence` | no | retry間隔、timeout、安定回数 |
| `spec.operation_gate` | no | 作業前WARN時の対話・非対話動作 |
| `spec.report` | no | WARNのexit code、証跡出力などの方針 |

`--profile`には閾値やホスト名を直接記載しない。閾値を変更する場合はsite固有profileを追加し、対象機器は`--hosts`およびinventoryのgroup / roleで選択する。これにより、実行した判定条件をファイルとして保存し、再利用できる。

閾値やreport policyだけを変更する差分profileでは`spec.checks`を省略できる。ただし、
合成後の実効profile全体では1件以上のcheckが必須であるため、差分profileは
`network-baseline-nxos`などのcheck定義を持つprofileより後へ指定する。

loggingの除外文字列だけを追加する場合は、`generate-sample-config`で差分profileを生成し、
作業用profileへコピーして編集する。

```bash
alred generate-sample-config
cp samples/health-check-profile.logging-excludes.example.yaml \
  ./logging-excludes.yaml
```

`logging-excludes.yaml`の`exclude_patterns`を編集後、baselineより後へ指定する。
profileは任意のファイルパスを指定でき、実行ディレクトリ直下への配置を標準例とする。
`profiles/`などの専用ディレクトリは必須ではない。専用ディレクトリへ整理する場合は、
コピー前に`mkdir -p profiles`などで作成する。

```bash
alred health-check before \
  --collect \
  --hosts ./hosts.lab.yaml \
  --profile network-baseline-nxos \
  --profile ./logging-excludes.yaml
```

同梱テンプレートの正本は
[health-check-profile.logging-excludes.example.yaml](../../alred/sample_configs/health-check-profile.logging-excludes.example.yaml)
とする。生成先に同名ファイルが存在する場合は上書きせず、テンプレート更新を反映するときだけ
`generate-sample-config --force`を使用する。

`exclude_patterns`は大文字小文字を区別しない部分文字列照合で、正規表現ではない。
後段profileの配列が前段profileの配列全体を置換するため、最終的に除外したい文字列を
差分profileの`exclude_patterns`へすべて記載する。

### 4.3 共通baseline例

```yaml
api_version: alred/v1
kind: HealthCheckProfile

metadata:
  name: network-baseline-nxos
  version: "1.0"

spec:
  platforms:
    - nxos

  collectors:
    nxos:
      commands:
        - id: clock
          command: show clock
          required: true
        - id: interface_status
          command: show interface status
          required: true
        - id: logging
          command: show logging
          required: true
        - id: running_config_diff
          command: show running-config diff
          required: false

  checks:
    - id: collection_complete
      evaluator: collection_complete
      severity: fail
    - id: preserve_up_interfaces
      evaluator: preserve_up_interfaces
      severity: fail
    - id: new_critical_logs
      evaluator: logging
      severity: warn
    - id: unsaved_config
      evaluator: running_config_diff
      severity: warn

  thresholds:
    cpu:
      metric: one_minute
      warn_percent: 80
      consecutive_samples: 3
      sample_interval_seconds: 15

  convergence:
    retry_interval_seconds: 15
    timeout_seconds: 300
    stable_success_count: 2

  operation_gate:
    interactive_action: confirm
    non_interactive_action: abort
```

### 4.4 Profile合成

複数profileを同時に指定できる。

```bash
alred health-check before \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --collect
```

実効収集コマンドは以下の和集合とし、重複を1回にまとめる。

```text
collect標準コマンド
    ∪ 利用者指定showコマンド
    ∪ 全profileの収集コマンド
```

異なるprofileが同じcommand IDへ異なるコマンドを定義した場合は入力エラーとする。

合成時の原則は次の通りとする。

- command IDとcommand文字列が同じ場合は1回だけ実行し、要求元profileをすべて記録する
- check IDは全profile間で一意とする
- 同じ閾値キーを複数profileが定義した場合は、後に指定したprofileを優先する
- 上書きが発生した値は`resolved-profiles.yaml`へ元値、上書き値、指定元を記録する
- platform不一致のprofileは黙って無視せず、対象hostごとに`NOT_APPLICABLE`とする

### 4.5 before / afterでのProfile固定

beforeでprofile参照を解決し、合成後の内容を`resolved-profiles.yaml`へ保存する。保存対象は、指定順、profile名、version、取得元、解決元（省略時既定値または明示指定）、元ファイルのSHA-256、合成後設定のSHA-256とする。

afterでは同じ`change-id`の`resolved-profiles.yaml`を既定で再利用する。このため、通常はafterで`--profile`を再指定しない。

```bash
alred health-check before \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos \
  --profile nxos-overlay

alred health-check after \
  --change-id CHG-2026-00123
```

afterまたはcompareで`--profile`を明示した場合は、beforeで固定した指定順と合成後SHA-256が完全一致することを検証する。不一致は比較条件が変わるため`PLAN_ERROR`とし、自動的な上書きや再解決は行わない。

診断用の追加コマンドは比較profileへ追加せず、別の`--diagnostic-profile`として実行・記録する。Overlay変更の発見後に必要となるVNI単位のコマンドは、`nxos-overlay`内の条件付きコマンドを具体化したものとして扱い、profile自体のhashは変更しない。

## 5. 共通正常性確認項目

NX-OSで使用する具体的なコマンド、必須・条件付き分類、判定対象、初期閾値は[NX-OS Baseline Health Check Commands](./NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md)を正本とする。

profileで有効化した項目だけを実行する。すべてを全作業で必須にはしない。

`nxos-overlay`では`show running-config`を全対象で必須とし、NVE、NVE VNI、
EVPN BGPのshow commandは条件付きとする。running configから設定有無を判定した結果と
運用状態の扱いは次のとおりとする。

| 設定状態 | show command結果 | 判定 |
|---|---|---|
| 対象機能が未設定 | unsupported、空、または未取得 | `NOT_APPLICABLE` |
| 対象機能が設定済み | 正常に解析可能 | 取得値に基づく`PASS` / `WARN` / `FAIL` |
| 対象機能が設定済み | timeout、欠落、parser error | `UNKNOWN` |
| running config自体が欠落または解析不能 | 状態を安全に推定できない | collection completenessを`UNKNOWN` |

この規則により、NVEを持たないSpineやEVPN/NVEを持たないBorderへLeaf用commandを
実行した結果を異常扱いしない。一方、設定済み機能の運用情報欠落は正常と推定しない。
role名やhostnameから適用可否を決めず、同じ収集時点の設定証跡を使用する。

before / afterの双方でrunning config上NVEが未設定の場合、`show nve ...`の欠落や
unsupportedは比較でも`NOT_APPLICABLE`とする。同様に、before / afterの双方で
EVPN BGPが未設定の場合、`show bgp l2vpn evpn summary`の欠落やunsupportedは
比較でも`NOT_APPLICABLE`とする。片方だけ設定済み、または設定状態を判定できない
場合はこの例外を適用せず、状態に応じて`FAIL`または`UNKNOWN`とする。

NX-OS BGP summaryの`config peers`と`capable peers`は、dynamic neighbor prefixや
複数address-familyを含む構成では一致しないことがあるため、その件数差だけを
peer downと判定しない。neighbor tableに現れた各peerのstateを判定し、1つでも
非Establishedなら`FAIL`、BGPが設定済みなのにpeer rowを1件も観測できなければ`FAIL`とする。
before/after比較ではbeforeでEstablishedだったpeerの消失または非Established化を
regressionとする。件数は診断用metadataとしてSnapshotへ保持する。

route summaryのVRF単位比較では、beforeに存在したVRFの消失またはroute数減少を
regressionとして評価する。Overlay変更によってafterで新規VRFが追加されたこと自体は
異常ではなく、既存VRFとは分離して追加情報として記録する。

### 5.1 収集

- TCP疎通
- SSH / NX-API認証
- enable
- 必須コマンドの成功
- 空出力、timeout
- parser成功
- 必須フィールド取得

### 5.2 装置基本状態

- uptime低下または再起動
- CPU、memory
- 電源、fan、温度
- module状態
- core dump、重大障害
- clock / NTP

### 5.3 Interface

- beforeでupだったinterfaceのdown
- line protocolのdown
- port-channel memberの減少
- error counterの急増
- interface flap

### 5.4 Routing/control plane

- BGP、OSPF、IS-IS neighborの維持
- 重要routeの消失
- route数の異常な減少

プロトコル固有parserはplatform/profile側に置き、共通Comparatorは正規化されたneighbor状態だけを比較する。

### 5.5 Loggingと設定保存

- 既存`check-logging`による新規異常候補
  - beforeはprofileのlookback期間に一致した既存候補をbaselineとして記録する
  - compareはbefore Snapshot作成後からafter Snapshot作成までの新規候補だけを`WARN`にする
  - severity、lookback、include / exclude patternはprofileで変更可能とする
- `show running-config diff`
- 未保存設定
- reloadを必要とするpending設定の有無とbefore / after差分

## 6. Snapshot schema

Snapshot全体を共通形式とし、profile固有状態をnamespaceで分離する。

```json
{
  "schema_version": 1,
  "collection_id": "CHG-2026-00123-after",
  "phase": "after",
  "hosts": {
    "leaf01": {
      "common": {
        "uptime_seconds": 864000,
        "interfaces": {},
        "logging": {},
        "routing_neighbors": {}
      },
      "profiles": {
        "nxos-overlay": {
          "nve_interface": {},
          "nve_peers": {},
          "l2vnis": {},
          "l3vnis": {},
          "evpn_routes": {}
        }
      },
      "sources": {}
    }
  }
}
```

## 7. 判定

共通のcheck結果は次とする。

- `PASS`: 正常であることを確認できた
- `WARN`: 確認が必要だが、直ちに異常とは断定しない
- `FAIL`: 明確な異常または期待状態不成立
- `UNKNOWN`: 収集・解析不足で判定不能
- `NOT_APPLICABLE`: コマンドは取得したが、対象featureが未設定で判定対象外
- `PLAN_ERROR`: profile、対象、入力が不正

理由を次に分類する。

- `normal`
- `pre_existing`
- `regression`
- `improvement`
- `expected_change`
- `unexpected_change`
- `target_not_ready`
- `collection_error`

作業profileは、共通結果に固有の総合判定を追加できる。Overlay自動発見の`OBSERVED_HEALTHY`、期待値確認済みの`VERIFIED`がその例である。

## 8. CLI案

単体判定を含む`health-check snapshot`、offline `health-check compare`、既存collectを利用する
`before` / `after` wrapperを実装済みとする。

beforeからafterまでの一連のCLI例は[Health Check Execution Scenarios](./HEALTH_CHECK_EXECUTION_SCENARIOS.md)を参照する。

### 8.1 `health-check`サブコマンド一覧

```text
alred health-check <subcommand> [options]
```

| subcommand | 用途 | 機器へ直接アクセス | 主な入力 | 主な処理 | 主な出力 |
|---|---|---:|---|---|---|
| `before` | 作業開始前の正常性確認 | `--collect`指定時のみあり | hosts、profile | 既存collectによる収集、before Snapshot生成、単体判定、Operation Gate | collection manifest、Snapshot、checklist、execution結果 |
| `after` | 作業終了後の正常性確認 | beforeが直接収集なら`--change-id`だけであり | change-id、before execution context | beforeの収集条件継承、収集、after Snapshot生成、beforeとの差分判定 | collection manifest、Snapshot、checklist、attempt結果 |
| `snapshot` | 収集済みログからSnapshotとphase単体判定を生成 | なし | alred collect成果物または外部CLI transcript | input adapter、ログ解析、正規化、必須データ確認 | collection manifest、必要に応じてtranscript import manifest、Snapshot、checklist |
| `compare` | 生成済みbefore / after Snapshotをオフライン比較 | なし | before Snapshot、after Snapshot | change-id・profile hash検証、差分抽出、正常性総合判定 | summary、health-result、diff |

#### 8.1.1 `before`

作業前の基準状態を確定する。`--collect`を指定した場合は機器へ接続して収集し、そのままSnapshot生成と判定を行う。CPU高負荷やreload-pendingなど、作業継続判断が必要な状態はOperation Gateへ渡す。

`--change-id`を省略した場合は自動採番する。profile、対象host、collection世代、判定条件を固定し、afterで再利用できる状態にする。

#### 8.1.2 `after`

beforeと同じ作業IDへ作業後状態を追加する。beforeで固定したprofileを再利用し、対象、profile hash、Snapshot schemaの整合を確認してから比較する。

`--change-id`を省略した場合は、新しいIDを採番せず、自動採番された直前の未完了beforeをactive change stateから引き継ぐ。安全に一意解決できない場合は`PLAN_ERROR`とする。retry可能なcheckは設定時間内で収束待ちを行う。

beforeが`--collect`だった場合は、`health/execution-context.yaml`に固定した非秘密の収集条件を
再利用するため、afterは原則として`--change-id`だけで実行できる。beforeが`--input`だった
場合は新しいafterログを推測できないため`--input`だけを必須とし、`--input-format`はbeforeから
継承する。

#### 8.1.3 `snapshot`

機器へ接続せず、収集済みファイルだけを解析する。alred collect成果物と、alred以外で取得したNX-OS CLI transcriptの両方をinput adapterで共通Collection Manifestへ変換する。

`--phase before`では作業開始としてchange-idを自動採番できる。`--phase after`では対応するbeforeのchange-idを必須とする。

#### 8.1.4 `compare`

機器やrawログへ再接続せず、before / afterのSnapshotだけを比較する。change-id、profile hash、対象host、schema versionが比較可能であることを先に検証する。

change-idは両Snapshotから取得するため、CLIでの指定は原則不要とする。不一致の場合は`PLAN_ERROR`とする。

### 8.2 オプション一覧

「必須」は常に必須という意味ではなく、適用先と条件欄に記載した条件で判定する。「デフォルトなし」のoptionは、省略時に別の入力から継承される場合と、入力エラーになる場合がある。

#### 8.2.1 共通option

| option | 適用先 | 内容 | 必須条件 | 複数指定 | デフォルト | デフォルト値・省略時動作 |
|---|---|---|---|---:|---:|---|
| `--change-id <id>` | before、after、rollback、snapshot | 作業とbefore / after / rollback成果物を関連付けるID | rollbackでは必須。afterはactiveな自動採番beforeがなければ必須 | no | あり | beforeでは自動採番。afterではactive changeを継承。rollbackでは既存operation IDを指定。形式は8.3参照 |
| `--profile <ref>` | before、after、snapshot | 組み込みprofile名またはprofile YAMLパス | no | yes | あり | beforeと`--phase before`は`network-baseline-nxos`。明示時は指定列で置換。after / rollbackはbeforeの`resolved-profiles.yaml`を継承 |
| `--revision-reason <text>` | before再実行 | plan前の固定profile改訂を明示し、理由を証跡へ保存 | profile差分を許可する場合 | no | なし | 空文字不可 |
| `--logging-all` | before、`snapshot --phase before` | timestampを解析できた全`show logging` recordを確認 | no | no | あり | 未指定。profileの範囲を使用 |
| `--logging-days <days>` | before、`snapshot --phase before` | Snapshot実施日時から指定日数前までを確認 | no | no | あり | 未指定。1以上の整数 |
| `--logging-start-time <ISO8601>` | before、`snapshot --phase before` | 指定日時以降を確認 | no | no | あり | 未指定。timezone offset必須 |
| `--diagnostic-profile <ref>` | before、after | 比較profileを変えずに追加調査コマンドを実行するprofile | no | yes | あり | 指定なし |
| `--hosts <path>` | 機器収集、transcript alias照合 | inventory / hostsファイル | beforeの`--collect`時は必須入力。ただし既定ファイルが存在すれば省略可 | no | あり | after / rollbackではbeforeのpathとSHA-256を継承・検証 |
| `--transport <ssh\|nxapi\|auto>` | before、after、rollbackの直接収集 | 既存collect runnerがshowコマンドに使うtransport | no | no | あり | 新規beforeは`ssh`。after / rollbackはbefore execution contextを継承し、contextがない明示的な直接収集では`ssh` |
| `--output <path>` | 全サブコマンド | 当該コマンドの成果物出力先 | no | no | あり | `operations/<change-id>/`配下のphase / reportに応じたパス |
| `--timezone <IANA name>` | 全サブコマンド | 表示、採番、成果物日時に使用するtimezone | no | no | あり | `ALRED_TIMEZONE`。未設定時は`Asia/Tokyo` |

`--logging-all`、`--logging-days`、`--logging-start-time`は相互排他とする。CLI指定はresolved
profileの`spec.thresholds.logging.time_range`へ変換し、effective hashとoverride履歴へ保存する。
通常の再before、after、rollback、compare、recheckでは固定範囲を継承する。plan前の
`--revision-reason`指定時は、理由と旧新差分を記録する場合に限りlogging範囲も改訂できる。

#### 8.2.2 `before` / `after` / `rollback` option

| option | 適用先 | 内容 | 必須条件 | 複数指定 | デフォルト | デフォルト値・省略時動作 |
|---|---|---|---|---:|---:|---|
| `--collect` | before、after、rollback | 既存collect処理を呼び、機器へ直接接続して必要なshowコマンドを収集する | beforeで直接収集する場合に指定 | no | あり | beforeは`false`。after / rollbackはbeforeが直接収集なら`true`を継承 |
| `--wait-until-healthy <seconds>` | after | retry可能checkの収束待ち上限秒 | no | no | あり | profileの`spec.convergence.timeout_seconds`。組み込みprofileの初期値は`300` |

beforeでは`--input`と`--collect`をCLI上の必須相互排他optionとする。after / rollbackでは両方を
省略でき、before execution contextが`collect`なら直接収集を継承する。beforeがoffline
`input`だった場合、after / rollbackの新しい入力パスは推測せず`--input`を必須とする。

Phase 7実装では`health-check before/after/rollback`に`--input`と`--input-format`も指定でき、明示的な
offline wrapperとして同じSnapshot処理を呼び出す。`--collect`との同時指定は拒否する。
`--input`と`--collect`の同時指定は拒否する。beforeでどちらもない場合、afterで継承可能な
contextも明示入力もない場合は、機器接続前にusage error、終了code `2`で停止し、通常実行で
Python Tracebackを表示しない。`--collect`時の`--hosts`など条件付き必須optionの不足も
`VALIDATION_ERROR`、終了code `2`として簡潔に表示する。
`--collect`では新しいCollectorを実装せず、resolved profileから生成した
`health/<phase>/show-commands.txt`を既存collect runnerへ渡す。running-configは既存のbase
collectで取得し、その他のprofile commandをshow listとして取得する。rawは
`health/<phase>/raw/`、collect logは`health/<phase>/collect.log`へ保存する。

health-checkの直接収集では`ssh`を既定transportとする。NX-OSの`show logging`などCLI経由で
必要な出力を一貫して取得し、`auto`によるNX-APIとSSHの二重収集・fallbackに伴う実行時間増加を
避けるためである。`nxapi`と`auto`は明示指定用として維持するが、profile必須コマンドを取得できない
場合は正常と推測せずCollection ManifestとHealthResultへ不足を記録する。既存before execution
contextに`auto`または`nxapi`が固定されているafter / rollbackは、後方互換性と比較条件維持の
ため記録済み値を継承する。

afterはSnapshot単体判定に続けてbefore/after共通compareを自動実行する。afterで
`--change-id`を省略する場合は、hosts file hash、固定profile hash、before成果物、operation
状態が一致するactiveな自動採番beforeだけを引き継ぐ。明示change-idのoperationを探索して
推測しない。

#### 8.2.3 before execution context

`health-check before` wrapperは正常にSnapshot生成を完了した時点で、次を
`operations/<change-id>/health/execution-context.yaml`へ保存する。schema kindは
`HealthCheckExecutionContext`とする。

- `input_mode`: `collect`または`input`
- inventoryの正規化済み絶対pathとsource SHA-256
- policyの正規化済み絶対pathとsource SHA-256
- offline入力の`input_format`。before input path自体はafter / rollbackへ流用しない
- transport、target hosts、workers、read / connect timeout
- username、credentials file path、password再入力要否

password、enable secret、credentials fileの内容は保存しない。beforeでCLI passwordを使用した
場合、after / rollbackは同じ値を保存せず対話で再入力する。環境変数またはcredentials fileを
使用した場合は各実行環境で再解決する。inventoryとpolicyはafter / rollbackの機器接続前に
SHA-256を検証し、不一致、欠落、symlinkではfail closedとする。target hostsはbeforeと同一に
固定する。transport、workers、timeoutは明示指定時のみafter / rollbackで上書きできる。

```yaml
api_version: alred/v1
kind: HealthCheckExecutionContext
metadata:
  change_id: CHG-2026-00123
  recorded_at: 2026-08-02T12:30:00+09:00
  timezone: Asia/Tokyo
spec:
  input_mode: collect
  inventory:
    path: /home/user/alred/hosts.lab.yaml
    sha256: sha256:...
  policy: null
  input_format: null
  collection:
    transport: ssh
    target_hosts: []
    workers: 5
    show_read_timeout: 120
    skip_connect_check: false
    connect_check_timeout: 3.0
  authentication:
    username: null
    credentials_file: /home/user/alred/clab_credentials.yaml
    ask_pass: false
    ask_become_pass: false
    password_was_cli: false
    enable_secret_was_cli: false
```

contextを持たない旧operationでは暗黙推測せず、従来どおりafter / rollbackへ
`--collect --hosts`または`--input --input-format`を指定すれば継続できる。

#### 8.2.4 `snapshot` option

| option | 内容 | 必須条件 | 複数指定 | デフォルト | デフォルト値・省略時動作 |
|---|---|---|---:|---:|---|
| `--input <path>` | alred collect成果物、外部ログファイル、または外部ログディレクトリ | 必須 | yes | なし | 省略時は`PLAN_ERROR` |
| `--input-format <format>` | 入力adapterを`alred-collect`または`nxos-transcript`から選択 | 必須 | no | なし | 誤認防止のため`auto`判定しない |
| `--phase <before\|after>` | 生成するSnapshotのphase | 必須 | no | なし | 省略時は`PLAN_ERROR` |

#### 8.2.5 `compare` option

| option | 内容 | 必須条件 | 複数指定 | デフォルト | デフォルト値・省略時動作 |
|---|---|---|---:|---:|---|
| `--before <snapshot-path>` | beforeの`snapshot.json` | 必須 | no | なし | 省略時は`PLAN_ERROR` |
| `--after <snapshot-path>` | afterの`snapshot.json` | 必須 | no | なし | 省略時は`PLAN_ERROR` |
| `--profile <ref>` | 固定済みprofileの明示的な再検証 | no | yes | あり | beforeの`resolved-profiles.yaml`を使用。明示値が不一致なら`PLAN_ERROR` |

compareの`change-id`は両Snapshotから取得するため、CLI指定を原則設けない。両者が不一致の場合は`PLAN_ERROR`とする。

#### 8.2.5 既存collect連携option

| option | 適用先 | 内容 | 必須条件 | 複数指定 | デフォルト | デフォルト値・省略時動作 |
|---|---|---|---|---:|---:|---|
| `--collection-id <id>` | `collect-*` | 1回の収集世代を識別するID | no | no | あり | change-id、phase、設定timezone日時、offset、randomから自動生成 |
| `--health-profile <ref>` | `collect-before-work`など | 既存収集へHealth Check profileのコマンドを追加 | no | yes | あり | 指定なし。Health Check処理を追加しない |
| `--show-commands-file <path>` | `collect-all`など | 利用者定義showコマンド一覧 | no | no | 既存collect仕様に従う | profileコマンドと和集合にして重複排除 |

boolean optionの`--collect`は、明示された場合だけ`true`になる。パス、profile、入力形式などに不正がある場合は、機器接続やファイル生成を始める前に検証して`PLAN_ERROR`とする。

beforeのCPU連続高負荷またはreload-pendingによりOperation Gateがrequiredになった場合、
対話TTYでのみ`yes`による継続判断を受け付ける。非対話実行または`yes`以外は`stop`として
`health/before/health-result.json`へdecision、時刻、interactive有無を記録する。この判断は
health result自体をPASSへ変更せず、後続applyが確認する独立gateである。

### 8.3 `--change-id`

```text
--change-id <change-id>
```

`change-id`は、1回の作業に属するbefore、after、compare、収集manifest、Snapshot、判定結果を関連付ける論理IDである。設定内容そのもののIDではなく、作業・正常性確認セッションのIDとして扱う。

利用者指定値は、外部の変更管理番号や作業番号をそのまま利用できる。

```bash
--change-id CHG-2026-00123
```

入力規則は次とする。

- 1文字以上128文字以下
- 先頭はASCII英数字
- 2文字目以降はASCII英数字、`-`、`_`、`.`だけを許可
- 大文字と小文字を区別する
- 空白、`/`、`\`、`..`、control characterは許可しない
- pathへ展開した結果が設定済みの出力root外になる値は拒否する

正規表現による表現は次とする。

```regex
^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,127})$
```

追加で、値に`..`が含まれる場合は拒否する。

#### 8.3.1 自動採番

before実行時に`--change-id`を省略した場合は、次の形式で自動採番する。

```text
HC-<設定timezoneの日時>-<UTC offset>-<random>
HC-YYYYMMDDTHHMMSS-<p|m>HHMM-<6桁の小文字hex>
```

例:

```text
HC-20260725T100203-p0900-a1b2c3
```

- 既定timezoneはJSTを表すIANA timezone名`Asia/Tokyo`とする
- 日時は実行開始時の設定timezoneとし、秒単位で記録する
- UTC offsetは、`+09:00`を`p0900`、`-05:00`を`m0500`のようにpathで安全な文字へ変換する
- random部は暗号学的乱数から生成した24 bitを6桁の小文字hexで表す
- 出力ディレクトリをatomicに作成し、衝突した場合はrandom部を再生成する
- 採番結果を端末へ最初に表示し、`metadata.yaml`、全manifest、Snapshot、reportへ記録する
- 自動採番か利用者指定かを`metadata.change_id_source`へ記録する

```text
Change ID was not specified.
Generated Change ID: HC-20260725T100203-p0900-a1b2c3
Timezone: Asia/Tokyo (+09:00)
Output: operations/HC-20260725T100203-p0900-a1b2c3/
```

timezoneの解決順序は次とする。

1. CLIの`--timezone`
2. `.env`またはprocess環境変数の`ALRED_TIMEZONE`
3. コード内既定値`Asia/Tokyo`

```bash
alred health-check before \
  --timezone Asia/Tokyo \
  --profile network-baseline-nxos
```

通常運用では毎回CLIへ指定せず、alredの既存`.env`へ次を設定することを推奨する。

```env
ALRED_TIMEZONE=Asia/Tokyo
```

値はIANA timezone database名で指定する。`JST`や固定offsetだけの指定は、地域の履歴や将来の時刻規則を表現できないため受け付けない。未知のtimezoneはシステムtimezoneやUTCへfallbackせず、実行前に`PLAN_ERROR`とする。OSの`TZ`環境変数はalredの判定条件として暗黙には参照しない。

すべてのYAML / JSON日時は設定timezoneのISO 8601 offset付き表現で保存する。比較・並べ替え用にUTCが必要な場合は内部で変換してよいが、利用者向けの既定表示、自動採番、成果物の日時は設定timezoneを使用する。各成果物には解決済みIANA timezone名も記録する。

自動採番するコマンドは次とする。

| コマンド | `--change-id`省略時 |
|---|---|
| `health-check before` | 自動採番する |
| `health-check snapshot --phase before` | 自動採番する |
| `overlay-check before` / `overlay-change plan` | workflow開始として自動採番する |
| `health-check after` | 新規採番しない。省略時はactiveな自動採番beforeのIDを継承する |
| `health-check snapshot --phase after` | 自動採番しない。対応するbeforeのIDを必須とする |
| `health-check rollback` / `snapshot --phase rollback` | 自動採番しない。対象operationのIDを必須とする |
| `health-check compare` | before / after Snapshotから取得し、両者の一致を検証する |

afterを別IDで自動採番するとbeforeとの比較関係を失うため禁止する。beforeを自動採番した場合、alredは`operations/.state/active-change.yaml`をatomicに更新する。afterで`--change-id`を省略した場合は、このstateに記録されたIDを引き継ぐ。

```bash
alred health-check before \
  --hosts hosts.yaml \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --collect

# active changeから同じIDを自動的に引き継ぐ
alred health-check after
```

省略時の解決順序は次とする。

1. `--change-id`が明示されていれば、そのIDを使用する
2. 省略時は、同じ出力rootの`active-change.yaml`を読む
3. stateが指すbefore成果物と`metadata.yaml`を検証する
4. inventory hash、profile hash、before status、after未実施を検証する
5. 一意に検証できた場合だけ、そのchange-idをafterへ採用する

端末には、機器接続前に解決結果を表示する。

```text
Change ID was not specified.
Using active before Change ID: HC-20260725T100203-p0900-a1b2c3
Before completed at: 2026-07-25T10:05:31+09:00
Output: operations/HC-20260725T100203-p0900-a1b2c3/
```

次の場合は「最新らしいディレクトリ」を検索して推測せず、`PLAN_ERROR`とする。

- active change stateが存在しない、破損している、または参照先が存在しない
- stateのIDが利用者指定IDであり、自動採番されたbeforeではない
- beforeが正常に完了していない
- afterがすでに完了している
- 実行時inventory hashがbeforeと異なる
- 複数の未完了作業があり、activeな1件を保証できない
- 指定した`--output`とactive changeの出力rootが異なる

afterが正常に完了した場合はstateを`completed`へ更新し、次回の省略実行では再利用しない。afterが途中失敗した場合は同じIDで再実行できるよう`after_failed`として保持し、attempt履歴を追加する。

compareではCLIの`--change-id`を原則不要とする。before / after Snapshotに異なる`change_id`が記録されている場合は、誤った組み合わせとして`PLAN_ERROR`にする。

#### 8.3.2 出力先と再実行

既定出力先は次とする。

```text
operations/<change-id>/
```

`--output`を指定した場合は、そのパスを当該コマンドの出力先として使用するが、`change-id`自体は変更しない。自動採番時に`--output`を省略した場合だけ、上記の既定パスを自動生成する。指定出力先が別の`change-id`の成果物を含む場合は`PLAN_ERROR`とする。

同じ`change-id`の成果物が存在する場合は暗黙に削除・上書きしない。

- 未作成phaseへの継続は許可する。例: before済みIDへのafter追加
- 同じphaseの再実行は`attempts/<attempt-id>/`へ新しい世代として保存する
- どのattemptを正本にしたかを`metadata.yaml`へ記録する
- profile hash、inventory、既存before Snapshotが一致しない再開は`PLAN_ERROR`とする
- 明示的なarchive / purge操作なしで過去のrawログや判定結果を削除しない

before再実行はOverlay workflowが開始されておらず、plan、approval、apply成果物が存在しない場合に
限って許可する。既存beforeが`WARN`、`FAIL`、`UNKNOWN`または収集・解析失敗でも、同じinventory、
同じ固定済みprofile、同じ入力方式を使用する新attemptとして再実行できる。

profile、logging除外、閾値またはlogging範囲を変更する場合は、空でない`--revision-reason`を
profile改訂の明示指定として必須とする。変更前後のeffective profile hash、profile名、field単位差分、理由、
実行時刻、attempt IDを`profile-revision.json`へ保存し、旧attemptのprofileと判定結果を保持する。
新profileによる収集・解析が成功した場合だけ固定profileとbefore正本を更新し、失敗時は以前の正本を
維持する。初回before、実効profileに差分がない場合、plan／approval／apply後はrevisionを拒否する。
profile差分があるのに`--revision-reason`がない場合も拒否する。

各attemptは`health/before/attempts/<attempt-id>/`へ不変保存し、`health/before/current.json`が最新の
成功済みattemptを指す。既存CLIとの互換性のため、最新成功attemptの主要成果物を
`health/before/snapshot.json`などの正本pathにもatomicに反映する。新attemptが失敗した場合は以前の
成功済み正本を維持し、失敗attemptとerrorだけを追加する。新しいbeforeが正本になった後に生成する
planは、そのSnapshot hashと改訂後profile hashを改めて固定する。各attemptには、その判定に使用した
`resolved-profiles.yaml`も保存する。

rollback後Health Checkは、初回を含めて
`health/rollback/attempts/<attempt-id>/`へ収集、Snapshot、単体HealthResultを保存する。共通比較は
`health/rollback-report/attempts/<attempt-id>/`、統合verificationは通常rollbackでは
`rollback/verification-attempts/<attempt-id>/`、qualificationでは
`qualification/rollback/verification-attempts/<attempt-id>/`へ保存する。`WARN`、`FAIL`、`UNKNOWN`、
収集失敗、解析失敗、verification失敗後も、同じchange ID、固定profile、inventory、対象scopeで
再実行できる。

判定まで完了した最新attemptだけを`health/rollback/current.json`と
`rollback/verification-current.json`（qualificationでは対応するqualification path）で指す。
既存CLIとの互換性のため`health/rollback/snapshot.json`、
`health/rollback-report/health-result.json`、`rollback/verification.json`等も最新完了attemptと
同じ内容へatomicに更新する。収集・解析・verification処理自体が失敗したattemptは履歴とerrorを
保持し、以前のcurrentと互換正本を変更しない。`ROLLED_BACK_AND_VERIFIED`後の再実行は、確定済み
復元証跡を変更しないため許可しない。

`collection-id`は各収集実行を識別し、`change-id`とは分離する。既定値は`<change-id>-<phase>-<設定timezone日時>-<offset>-<random>`とする。

### 8.4 作業前

```bash
alred health-check before \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --collect \
  --output operations/CHG-2026-00123
```

### 8.5 作業後

```bash
alred health-check after \
  --change-id CHG-2026-00123
```

`--profile`省略時は、beforeで保存した`resolved-profiles.yaml`を再利用する。明示指定する場合はbeforeと完全一致しなければならない。

### 8.6 収集と解析を分離

```bash
alred collect-all \
  --hosts hosts.yaml \
  --show-commands-file show_commands.txt \
  --output raw-before \
  --collection-id CHG-2026-00123-before

alred health-check snapshot \
  --input raw-before \
  --input-format alred-collect \
  --phase before \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --output operations/CHG-2026-00123/health/before
```

### 8.7 外部CLI transcriptからSnapshotを生成

`--input`は単一ファイルまたはディレクトリを受け付ける。ディレクトリの場合は通常ファイルを再帰的に検索する。symbolic linkの追跡は既定で無効とし、出力先自身と既知のbinary/archiveは除外する。

```bash
# ディレクトリ内の複数ログを解析
alred health-check snapshot \
  --input external-before-logs \
  --input-format nxos-transcript \
  --hosts hosts.yaml \
  --phase before \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --output operations/CHG-2026-00123/health/before

# 単一の一括ログを解析
alred health-check snapshot \
  --input external-before-logs/all-leafs.log \
  --input-format nxos-transcript \
  --phase before \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --output operations/CHG-2026-00123/health/before
```

`--input`は複数回指定可能とする。同じ実体ファイルが複数の入力経路から見つかった場合はSHA-256と正規化済み絶対パスで重複排除する。

`--input-format`の初期値は次とする。`auto`は誤認を防ぐため初期実装では採用しない。

| 値 | 入力 |
|---|---|
| `alred-collect` | alred collect成果物とcollection manifest |
| `nxos-transcript` | promptと実行コマンドを含む外部NX-OS CLIログ |

外部ログの認識結果はSnapshot生成前にmanifestへ保存する。`high` confidenceの区間だけで必要データが揃う場合はそのまま続行できる。曖昧区間または必須コマンド不足がある場合は端末と`checklist.md`へ表示し、非対話実行で黙って採用しない。

手動収集時は解析精度を確保するため、コマンドリストの先頭で`terminal length 0`と十分な`terminal width`を設定し、promptと入力コマンドをログへ残すことを推奨する。

### 8.8 オフライン比較

```bash
alred health-check compare \
  --before operations/CHG-2026-00123/health/before/snapshot.json \
  --after operations/CHG-2026-00123/health/after/snapshot.json \
  --output operations/CHG-2026-00123/health/report
```

compareはbefore Snapshotが参照する`resolved-profiles.yaml`を使用し、after Snapshotに記録されたprofile hashとの一致を検証する。

### 8.9 既存作業前後収集との統合

既存挙動を変えないため、初期段階はoption指定時だけHealth Checkを追加する。

```bash
alred collect-before-work \
  --hosts hosts.yaml \
  --health-profile network-baseline-nxos \
  --health-profile nxos-overlay

alred collect-after-work \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123
```

## 9. 出力ファイル

各ファイルと端末表示の具体例は[Health Check Output Formats](./HEALTH_CHECK_OUTPUT_FORMATS.md)を正本とする。

```text
operations/<change-id>/
├── metadata.yaml
├── execution.json                    # operation全体の状態遷移とerror履歴
├── plan/
│   ├── execution-plan.md
│   ├── execution-plan.json
│   ├── rollback-plan.md
│   └── rollback-plan.json
├── generated-config/                 # 設定生成を行う場合
│   └── <hostname>.cfg
├── rollback-config/                  # scoped inverse configを利用する場合
│   └── <hostname>.cfg
├── apply/                            # 設定投入を行う場合
│   ├── apply-summary.md
│   ├── execution.json
│   └── devices/
│       └── <hostname>/
│           ├── commands.log
│           ├── command-results.json
│           ├── save.log
│           └── save-result.json
├── rollback/                         # 切り戻しを実行する場合
│   ├── rollback-summary.md
│   ├── execution.json
│   ├── verification.json             # raw/semantic/healthの統合gate
│   ├── verification-checklist.md      # 運用者向け統合Checklist
│   ├── verification-current.json      # 最新完了verification attempt
│   ├── verification-attempts/
│   │   └── <attempt-id>/
│   │       ├── verification.json
│   │       └── verification-checklist.md
│   └── devices/
│       └── <hostname>/
│           ├── commands.log
│           ├── command-results.json
│           ├── save.log
│           └── save-result.json
├── health/
│   ├── resolved-profiles.yaml
│   ├── execution-context.yaml              # beforeの非秘密な実行条件
│   ├── before/
│   │   ├── collection-manifest.yaml
│   │   ├── transcript-import-manifest.yaml  # 外部ログ入力時
│   │   ├── raw/                             # --collectによる直接収集時
│   │   ├── execution.json
│   │   ├── snapshot.json
│   │   ├── checklist.md
│   │   ├── overlay-state.yaml          # nxos-overlay有効時
│   │   ├── vni-map.md                 # nxos-overlay有効時
│   │   └── vni-map.csv                # nxos-overlay有効時
│   ├── after/
│   │   ├── attempts/
│   │   │   └── <attempt-id>/
│   │   │       ├── raw/
│   │   │       └── collection-manifest.yaml
│   │   ├── collection-manifest.yaml
│   │   ├── transcript-import-manifest.yaml  # 外部ログ入力時
│   │   ├── execution.json
│   │   ├── snapshot.json
│   │   ├── checklist.md
│   │   ├── overlay-state.yaml          # nxos-overlay有効時
│   │   ├── vni-map.md                 # nxos-overlay有効時
│   │   └── vni-map.csv                # nxos-overlay有効時
│   ├── report/
│   │   ├── summary.md
│   │   ├── health-result.json
│   │   ├── diff.json
│   │   ├── vni-map-diff.json          # nxos-overlay有効時
│   │   ├── vni-map-diff.md            # nxos-overlay有効時
│   │   └── vni-map-diff.csv           # nxos-overlay有効時
│   ├── rollback/                     # 切り戻し後の収集と単体判定
│   │   ├── current.json
│   │   ├── attempts/
│   │   │   └── <attempt-id>/
│   │   │       ├── raw/
│   │   │       ├── collection-manifest.yaml
│   │   │       ├── snapshot.json
│   │   │       ├── health-result.json
│   │   │       ├── checklist.md
│   │   │       └── result.json
│   │   ├── raw/                      # 最新完了attemptとの互換正本
│   │   ├── collection-manifest.yaml
│   │   ├── snapshot.json
│   │   └── checklist.md
│   └── rollback-report/              # beforeとの共通正常性比較
│       ├── attempts/<attempt-id>/
│       │   ├── health-result.json
│       │   └── summary.md
│       ├── health-result.json         # 最新完了attemptとの互換正本
│       └── summary.md
├── qualification/rollback/           # qualification時のみ
│   ├── verification.json             # raw/semantic/healthの統合gate
│   ├── verification-checklist.md      # 運用者向け統合Checklist
│   ├── verification-current.json
│   └── verification-attempts/<attempt-id>/
└── overlay/                          # Overlay workflowを利用する場合
    ├── discovered-changes.yaml
    ├── expected-changes.yaml
    ├── changes-diff.md
    └── overlay-summary.md

operations/.state/
└── active-change.yaml
```

`operations/`は設定投入、正常性確認、差分確認を含む作業全体のworkspaceである。`generated-config/`と`apply/`を`health/`配下へ置かず、正常性確認成果物、投入候補config、投入実行結果の責務を分離する。Health Checkだけを実行する場合、`generated-config/`、`apply/`、`overlay/`は作成しない。

rawファイルは既存collect成果物を正本とし、manifestから参照する。archiveへまとめる場合を除き、Health Check側へ不要な複製を作らない。

`health-check --collect`または`overlay-change apply --health-check`が既存collectを内部実行する場合は、collectの出力先自体を`health/<phase>/raw/`または`health/after/attempts/<attempt-id>/raw/`に設定するため、複製は発生しない。既に別の場所へ収集済みのログを`health-check snapshot`で読む場合は、rawログをoperation workspaceへコピーせず、Collection Manifestから元のパスとSHA-256を参照する。

## 10. 終了コード

共通のCLI終了codeは[Error Catalog](./ERROR_CATALOG.md)を正本とする。

- `0`: blockingな異常なし
- `1`: WARNまたは利用者判断が必要
- `2`: validation、plan、approval、capability error
- `3`: collection、parser、schema世代不整合
- `4`: health check FAILまたはregression
- `5`: apply、save、rollback失敗またはdevice状態不明
- `6`: support bundle失敗
- `130`: SIGINT

profileはWARNの表示・gate条件を変更できるが、共通終了codeの意味を変更しない。
旧文書や既存実装で使用する`PLAN_ERROR`は終了code `2`に属するlegacy umbrella nameとし、
新規machine-readable結果ではError Catalogの具体的なcodeを使用する。

## 11. 拡張ポイント

- 新しいplatform parser
- 新しいHealth Check Profile
- 新しいEvaluator
- HTML reporter
- CI/CD連携
- 既知問題・maintenance windowの抑制ルール
- topologyやinventory属性からの対象選択

profile、parser、evaluator、reporterのinterfaceを先に固定し、個別作業の機能追加で共通コアを変更しない構造を目指す。

## 12. 実装とテスト方針

Health Checkの実装本体はpytestへ依存させず、通常のPythonモジュールとして作成する。

```text
alred/health/
├── manifest.py
├── snapshot.py
├── comparator.py
├── evaluator.py
├── convergence.py
├── operation_gate.py
├── report.py
└── profiles/
    ├── baseline_nxos.py
    └── overlay_nxos.py
```

test runnerはpytestへ統一する。既存の`unittest.TestCase`はpytestの互換収集機能で継続実行し、
関連機能を変更するタイミングで段階的にpytest形式へ移行する。既存テストの一括書き換えは
移行だけの大きな差分を避けるため行わない。新規Health Checkテストは原則としてpytestの
fixture、parameterization、plain `assert`を使用する。

推奨するテスト構成:

```text
tests/
├── fixtures/nxos/
│   ├── show_processes_cpu/
│   ├── show_reload_pending/
│   ├── show_bgp_summary/
│   ├── show_nve_vni/
│   └── show_vpc_brief/
├── expected/
│   ├── snapshots/
│   └── reports/
├── test_health_parsers.py
├── test_health_snapshot.py
├── test_health_comparator.py
├── test_health_evaluator.py
├── test_health_report.py
└── test_health_cli.py
```

最低限、次をテストする。

- 実際のNX-OS出力fixtureを正しくparseできる
- NX-OS releaseごとの表示差を吸収できる
- 空出力、command error、未知形式を`UNKNOWN`にする
- before / afterのadded、removed、changedを正しく検出する
- `pre_existing`と`regression`を区別する
- CPU閾値と連続sampleを判定できる
- reload-pendingの追加・解消を判定できる
- `NOT_APPLICABLE`とcollection failureを区別する
- JSON schemaとgolden Markdown出力が一致する
- CLI終了コードが仕様どおりになる

通常のCIでは`device` markerを除外する。labまたは実機へ接続するテストは、対象、認証方法、
実行許可を明示した専用jobまたは手動実行に限定する。

```bash
uv run pytest -m "not device"
```

fixture、parameterized test、snapshot/golden testはpytestで実装するが、実装コードをpytestへ
依存させない。
