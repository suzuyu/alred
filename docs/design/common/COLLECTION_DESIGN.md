# Collection Design

## 1. 文書の目的

既存`collect-*`が行うtarget選択、command選択、device単位収集、raw成果物、世代保存の現行仕様を
定める。transportとcredentialは
[Inventory, Credentials, and Device Access Design](./INVENTORY_CREDENTIALS_AND_DEVICE_ACCESS_DESIGN.md)、
rawからSnapshotを生成する契約は
[Health Check Framework Design](../network-ops/HEALTH_CHECK_FRAMEWORK_DESIGN.md)を正本とする。

既存成果物の解析根拠は[Collect Output As-Is](../../as-is/COLLECT_OUTPUT_AS_IS.md)を参照する。
alred外で取得したshow running-configのhost分割、identity解決、Manifest化は
[External Running Config Import Design](EXTERNAL_RUNNING_CONFIG_IMPORT_DESIGN.md)を正本とする。

## 2. 責務分離

```text
inventory / policy / explicit target
    ↓
target resolution
    ↓
collector (SSH / NX-API / auto)
    ↓
raw current mirror + old generation
    ↓
manifest adapter
    ↓
parser / Snapshot / evaluator
```

- collectorはcommand実行とraw保存を担当し、Health Check判定を行わない。
- parserは保存済みrawを解釈し、deviceへ接続しない。
- evaluatorはSnapshotを入力とし、raw directoryの偶発的なfile存在を根拠にしない。
- config投入はcollectionと同じexecutorとして実装せず、既存接続を再利用するmanaged executorを使う。

## 3. Collection command

| command | 主な責務 |
|---|---|
| `collect` | LLDPと必要に応じたrunning configの収集 |
| `collect-list` | fileで指定したshow command群の収集 |
| `collect-run-config` | running config収集 |
| `collect-run-diff` | 対応deviceのrunning config diff収集 |
| `collect-run-diff-cmd` | running config diff commandの実行 |
| `collect-clab` | lab inventoryを既定とするcollection alias |
| `collect-all` | 複数collection stepとarchiveのworkflow |
| `collect-before-work`／`collect-after-work` | legacy作業前後workflow |

既存command名と出力互換を維持する。Health Check operationはこれらのraw形式をadapter経由で利用し、
legacy current mirrorの意味を変更しない。

`network-baseline-nxos`の直接収集ではrunning configとLLDPを同一attemptへ保存し、同じCollection Manifestに
固定する。Health、Topology、Containerlab、Portable Evidence PackageはManifestが指す同一rawを参照し、
用途ごとに再収集または複製しない。

Collection Manifestでは、running configを`source: running-config`、LLDPを`source: lldp`、profileの
追加show outputを`source: show`として区別する。`source: lldp`のcommand IDは`lldp_neighbors_detail`とし、
text artifactをJSON sidecarより優先する。

## 4. Command選択

### 4.1 Base command

- LLDP、running config、logging、connection check、saveなどのdevice type別commandは
  `alred/constants.py`で管理する。
- policyの`collect_running_config_for`に含まれるdevice typeだけrunning configを収集する。
- device固有の追加running config形式がある場合、suffix、format、timeoutを明示する。

### 4.2 Show command file

show command fileはsection形式とする。

```text
[all]
show version

[device_type:nxos]
show interface status

[leaf]
show nve peers

[leaf01]
show module
```

hostごとの解決順は次とし、同一commandは最初の出現だけを残す。

1. `[all]`
2. `[device_type:<device_type>]`
3. hostnameから一致したroleを定義順に適用
4. `[<hostname>]`

section前のcommandはformat errorとする。role解決の移行は
[Role Definition and Resolution Design](./ROLE_DEFINITION_AND_RESOLUTION_DESIGN.md)に従う。

## 5. Raw成果物

### 5.1 Current mirror

raw rootの基本構造は次とする。

```text
raw/
├── lldp/
│   └── <hostname>_lldp.txt|json
├── config/
│   └── <hostname>_run.txt|json
├── show_lists/
│   └── <hostname>/
│       ├── <hostname>_shows.log
│       ├── commands/
│       │   └── <sequence>_<command-id>.txt
│       └── <command-sidecar>.json
└── old/
    └── <generation>/
```

- textは`<hostname>_<suffix>.txt`、structured NX-API outputは`.json`を使用する。
- resolverは同じhostname／suffixのJSONとtextがある場合にJSONを優先する。
- show transcriptはcommand listとcommandごとの境界、収集日時、status、transport、prompt markerを含む。
- 新規収集では command ごとの section を`commands/<sequence>_<command-id>.txt`へ同時に保存し、これを
  canonical source とする。各 file には1 command だけを格納し、sequence で実行順と同一 command ID の
  衝突を区別する。長い未知 command ID は固定長 hash を付けて filename を制限する。
  `<hostname>_shows.log`は既存 consumer 向けの互換成果物として継続する。
- `auto` transportでSSH transcriptをcanonical textとして必要とするflowでは、SSH textを優先し、
  NX-API JSONはsidecarとして保存できる。

### 5.2 Generation

- 既存current fileを更新する前に`old/<generation>/`へ移動し、設定された保持世代数を超えた旧世代を
  pruningする。
- generation名は実行単位を識別できる値とし、同名file衝突時に上書きしない。
- `collect-all` archiveは`old/`を再帰的に含めない。

### 5.3 Manifest境界

legacy current mirrorは複数fileのatomic publishを保証しない。Health Check、比較、再解析では、
次を満たすCollection Manifestを先に固定する。

- 使用したfileの相対path、SHA-256、size
- hostname、command、format、transport、収集時刻
- parserが参照するsource範囲
- 欠落、重複、旧sidecar混入候補

directory内に存在するという理由だけで、今回generationのcanonical sourceへ追加しない。
command 別 file が存在する host では Collection Manifest はそちらを優先し、同じ host の統合 transcript を
重複登録しない。legacy 収集などで command 別 file がない場合、downstream consumer は統合 show transcript の
file 全体ではなく Manifest の
`output_start_line`～`output_end_line`をcommand outputとして使用する。Portable Evidence Packageへexportする場合も
この範囲だけをcommand ID別fileへmaterializeし、元のline rangeはprovenanceとして保持する。

## 6. Parallelismと失敗

- host間は`--workers`で並列化できる。
- host内のcommand順序は解決済みcommand順を維持する。
- command失敗時はhost、command、transport、errorを記録し、成功した別commandのrawを削除しない。
- timeout、接続断、途中成功をhost全体の正常完了とみなさない。
- collection終了時に成功、失敗、skipを区別して表示する。
- read-only collectionのretryは可能だが、旧generationと新generationを混ぜて単一attemptにしない。

## 7. Security

- collectionはread-only commandに限定する。command fileからconfig commandを実行する用途として
  使用しない。
- rawには機器構成、管理IP、hostnameなどの機密情報を含み得るため、そのままcommit・共有しない。
- fixture化前にsecret、実在hostname、管理addressをsanitizeする。
- support bundleへ含める場合はallowlist、redaction、secret scanを適用する。

## 8. 実装状態と既知の制約

- legacy command、raw path、互換 transcript、収集時の command 別 canonical file、旧世代 rotation は実装済みである。
- collect rawからoperation用Collection Manifestを固定するoffline adapterは実装済みである。
- legacy current mirrorの全file atomic publishは未実装である。
- command list変更後に前回のNX-API sidecarがcurrent host directoryへ残る場合がある。manifestを使わない
  legacy consumerはこれを今回generationと誤認し得るため、既知の制約とする。
- 全device type／releaseの実出力、paging、長大output、途中切断fixtureは未整備である。
- 外部running configの任意filename／複数host transcript importとTopology／Containerlab consumer接続は
  設計済み・未実装である。
