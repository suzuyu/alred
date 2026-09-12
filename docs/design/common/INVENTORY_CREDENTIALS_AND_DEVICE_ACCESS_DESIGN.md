# Inventory, Credentials, and Device Access Design

## 1. 文書の目的

alredが対象deviceを表現するinventory、credential解決、SSH／NX-API transport、接続確認の
現行仕様と共通安全要件を定める。commandごとの収集内容と成果物は
[Collection Design](./COLLECTION_DESIGN.md)、設定投入のoperation制御は
[Overlay Change Management Design](../network-ops/OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)を参照する。

解析根拠と未確認事項は
[Inventory, Credentials, and Transport As-Is](../../as-is/INVENTORY_CREDENTIALS_AND_TRANSPORT_AS_IS.md)
を参照する。

## 2. Inventory model

### 2.1 `hosts.txt`

`prepare-hosts`の入力はUTF-8 textとし、有効行を次の形式で解釈する。

```text
<management-address> <hostname> # <device_type>[, <metadata>...]
```

- 空行と行頭`#`を無視する。
- addressとhostnameを必須とし、同一file内の重複address、重複hostnameを拒否する。
- device type省略時は`unknown`とする。
- metadataは`key=value`を標準とする。互換のため既知keyの`key:value`も受け付けるが、IPv6を含む
  値では`=`を使用する。
- 未解釈flagは破棄せずmetadataの`flags`へ保持する。

### 2.2 `hosts.yaml`

生成・読込対象は次の最小構造とする。

```yaml
all:
  hosts:
    leaf01:
      ansible_host: 192.0.2.11
      device_type: nxos
      os_type: nxos
      ansible_network_os: cisco.nxos.nxos
      ansible_connection: network_cli
      netmiko_device_type: cisco_nxos
      metadata: {}
```

canonical host fieldは次とする。

| field | 必須性 | 意味 |
|---|---|---|
| `hostname` | 必須 | `all.hosts`のkey |
| `ip` | 接続時必須 | `ansible_host`から正規化した接続先 |
| `device_type` | 必須 | command、driver、capability選択。省略時`unknown` |
| `os_type` | 任意 | 省略時`device_type` |
| `netmiko_device_type` | 接続方式により必須 | Netmiko driver |
| `ansible_network_os` | 任意 | 生成inventoryの互換情報 |
| `ansible_connection` | 任意 | 生成inventoryの互換情報 |
| `metadata` | 任意 | lab profileなど用途別metadata |

alredはAnsible inventory全仕様への互換を保証しない。`all.hosts`以外のgroup構造やpluginは、
個別設計で明示しない限り対象外とする。

### 2.3 Device type

現行の既知device typeは`nxos`、`ios`、`iosxe`、`iosxr`、`eos`、`nokia_srlinux`、`junos`、
`asa`、`asav`、`linux`である。`unknown`はinventory生成を許可するが、必要なdriverやcommandを
安全に決定できない処理では拒否またはskipする。

device typeからAnsible属性、Netmiko driver、collection command、containerlab kindを解決する。
用途固有の対応可否を、device typeが既知であることだけから推測しない。

## 3. Target resolution

device対象は次の順で絞り込む。

1. inventoryをcanonical host listへ正規化する。
2. `--target-hosts`などの明示hostname集合があれば一致hostだけを残す。
3. policyのinclude条件を適用する。
4. policyのexclude条件を適用する。

未知の明示hostnameを黙って別hostへ解決しない。operationでは使用したinventory path、content hash、
明示target、policy path／hashを固定する。

### 3.1 `--target-hosts` 部分一致の対象選択

Status: **実装済み**（2026-09-12）。既存の完全一致を維持し、明示 option で部分一致を追加する。

#### 従来動作と変更理由

`parse_host_filter()` はカンマ区切りの文字列を分割し、前後の空白と重複を除去する。
変更前の `select_target_hosts()` と `run_collect()` は inventory の hostname に完全一致する対象を選んでいた。
複数の完全 hostname は指定できたが、`leaf,spine` のような部分文字列では選択できなかった。
照合対象は接続先 IP や装置の実 hostname ではなく、inventory の hostname とする。

`--target-hosts` は収集だけでなく設定投入・保存でも使う。既定を部分一致へ変更すると、
従来 `leaf01` だけを選んでいた指定が `leaf010` や `backup-leaf01` にも広がる。
この互換性を維持するため、完全一致を既定にして部分一致を明示する方式とする。

#### CLI と照合規則

```bash
python alred.py collect --hosts hosts.yaml --target-hosts leaf,spine --target-hosts-match contains
```

| 項目 | 仕様 |
|---|---|
| 新 option | `--target-hosts-match {exact,contains}`。通常実行の既定は `exact` |
| 複数指定 | 既存のカンマ区切り。各文字列の OR 条件で選ぶ |
| `exact` | 現行の完全一致を維持。部分一致への自動 fallback はしない |
| `contains` | 各文字列が hostname に含まれるかを照合。大文字・小文字を区別する |
| 記号 | 正規表現・glob として解釈しない。`*` なども文字そのもの |
| 重複 | token と解決済み host を重複排除し、host の処理順は inventory 順を維持 |
| policy | 解決済み host へ既存 include／exclude を適用。部分一致で policy を迂回しない |
| 表示 | 照合方式、指定文字列、一致 hostname、policy 適用後の hostname と件数を接続前に表示・記録 |
| 部分一致の入力不備 | 未指定・空 token・空白のみは `VALIDATION_ERROR`／終了 code `2` |
| 部分一致の不一致 | どれかの token が inventory に 0 件なら、その token を示して接続前に error。残りだけ実行しない |
| policy 適用後 0 件 | 部分一致では対象なしの error。全 host を選び直す fallback は禁止 |

例えば `site-leaf01`、`site-leaf02`、`site-spine01`、`site-border01` がある場合、
`leaf,spine` は前の 3 台を選ぶ。`leaf,leaf01` でも `site-leaf01` は 1 回だけ処理する。
完全一致の既存の空入力・不一致処理は、本機能で暗黙に変更しない。
option の繰り返し、空白区切り、正規表現、大文字・小文字を無視する照合は今回の変更に含めない。

#### 実装範囲と責務

単純に `hostname in target_hosts` を substring 判定へ置換するだけでは、呼び出し経路間で差が出る。
[共通 resolver](../../../alred/target_selection.py) が inventory と指定文字列を受け、
解決済み hostname と一致情報を返す。
`parse_host_filter()` は `--show-hosts` にも使われるため、文字列分割と照合の責務を分ける。
内部で確定済み hostname 集合を渡す場合は再度部分一致で展開しない。

| 対象 | 必要な変更 |
|---|---|
| 共通 CLI | `--target-hosts` を持つ parser へ mode を追加。help、completion、Namespace の引き継ぎを更新 |
| collect 系、Health 直接収集 | `run_collect()` の独立した完全一致 filter と共通 selector を同じ resolver に接続 |
| `check-logging`、`check-clab-startup-config` | 共通 selector 経由の照合と option の引き継ぎを更新 |
| `push-config`、`push-config-dir`、`write-memory` | 一度解決した完全 hostname を既存の対象表示・投入・保存処理へ渡す |
| `clab-apply-config` | risk scan の集合積と mutation host 選択を同じ解決結果に統一。後段で設定する完全 hostname を再展開しない |
| `clab-set-cmds`、`generate-vni-config` の自動収集 | wrapper が mode と解決済み対象を失わないようにする |
| archive／対象別成果物 | 接続対象と同じ解決済み host 集合で対象を限定する |

ChangeSet の対象 device、`--show-hosts` の追加 show command 対象、offline transcript の
host 解決には部分一致を流用しない。新しい SSH executor や追加の承認 prompt は導入しない。

#### Health Check の対象固定と互換性

現行の Health execution context は `collection.target_hosts` に分割した指定値を保存し、
after／retry で同じ指定値か確認する。部分文字列をそのまま保存して後から再解決すると、
判定方式の変更などによって対象集合が変わるため、初回接続前に完全 hostname へ解決し、context を保存する。失敗した初回収集でも固定条件を残す。

新 context の `collection.target_hosts` には policy 適用後の完全 hostname を保存する。
新規の Health 直接収集は最終対象 0 件なら開始せず、空集合が全対象へ変換されることを防ぐ。
元の指定 token と照合 mode は、新しい optional `target_selection` field の `tokens`／`mode` に記録する。
未指定による全対象収集でも新 context では実際の対象を固定する。
追加 field は schema v1 の optional field とし、新旧 context の読み取りを検証する。

- after／retry／rollback 検証では inventory と policy の hash を確認し、固定した完全 hostname を使用する。
- option 省略時は before の選択条件を継承する。argparse の内部 default は省略と明示を区別できる値にする。
- option の再指定は固定 inventory／policy 上で解決し、before と同じ対象集合の場合だけ許容する。
- 旧 context の `target_hosts` は従来の完全一致として扱い、空配列の全対象という意味も維持する。
  新 field を必須にして過去の operation を使えなくしない。
- 検証エラーは接続・投入前に停止し、既存の正常 attempt／current を変更しない。

#### 受け入れテスト

- 完全一致の既存 CLI 互換性と、部分一致 OR、重複排除、空白、大小文字、記号の扱い。
- 未指定・空 token・一部 token 不一致・全不一致と、policy include／exclude、最終対象 0 件。
- inventory hostname と接続先 IP の区別、順序の再現性、解決済み集合を再展開しないこと。
- 収集・投入・保存・lab wrapper・archive の対象集合一致。executor を mock し、実機へ接続しない。
- 新旧 execution context、option 継承、対象集合の一致／不一致、inventory／policy の改変。
- retry の途中失敗時も以前の成功 attempt／current と before の固定対象を保持すること。
- CLI help、completion、schema validation、利用者向け例と実装状態の更新。

[対象選択テスト](../../../tests/test_target_selection.py)で CLI 各経路と context を確認し、
既存の retry テストで成功済み成果物の不変性も確認した。実機には接続していない。

## 4. Credential

### 4.1 入力

credentialは次から解決できる。

- CLIの`--username`／`--password`／`--enable-secret`
- 実行時の`--ask-pass`／`--ask-become-pass`
- `--credentials`または`./clab_credentials.yaml`
- `ALRED_*`環境変数
- 移行互換用`NW_TOOL_*`環境変数

credential YAMLは`credentials` wrapperを持つ形式と、内容を直接top-levelへ置く形式を受け付ける。

```yaml
credentials:
  defaults:
    username: admin
    password_env: ALRED_LAB_PASSWORD
  device_type:
    nxos:
      username: nxadmin
  hosts:
    leaf01:
      password_env: ALRED_LEAF01_PASSWORD
```

各entryは`username`、`password`、`enable_secret`、または対応する`*_env`を使用できる。

### 4.2 解決順

必須credentialはfieldごとに次の優先順位で解決する。

1. CLI／prompt
2. credential YAML `hosts.<hostname>`
3. credential YAML `device_type.<device_type>`
4. credential YAML `defaults`
5. ASA／ASAvの場合だけ`ALRED_FW_*`、次に`NW_TOOL_FW_*`
6. 共通`ALRED_*`
7. 共通`NW_TOOL_*`

usernameとpasswordは組で必須とし、片方だけの場合は接続前に拒否する。enable secretはdevice typeの
要件に応じて必須化する。

### 4.3 Secret取扱い

- literal credentialをsample、test fixture、operation artifactへ保存しない。
- credential値、Basic Authorization、enable secretをlogへ出力しない。
- operationにはcredential file本文やsecret hashを保存せず、必要な場合は非秘密のsource種別だけを
  記録する。
- 外部共有前にsupport bundleのredactionとsecret scanを通す。
- credential fileのpermission強制は現在未実装であり、安全なpermissionで管理することを利用者文書へ
  明記する。将来の強制追加は後方互換性を検討する。

## 5. Transport

### 5.1 SSH

- SSH command実行は既存Netmiko接続を共通利用する。
- driverはdevice type overrideを優先し、なければinventoryの`netmiko_device_type`を使用する。
- portは`ALRED_SSH_PORT`、timeoutは`ALRED_TIMEOUT`を優先し、legacy変数と既定値`22`／`60`へ
  fallbackする。
- SR Linuxは現行のsession準備commandをbest effortで実行する。準備失敗はwarningとして記録する。
- privileged exec対象では接続後にenableへ入り、ASA／ASAvではenable secret未指定を拒否する。
- command失敗は`CommandResult`へ`ok: false`、error、transportを記録し、同一host全体を成功扱いしない。

### 5.2 NX-API

- NX-API collectorはNX-OSだけを対象とする。
- scheme明示時は指定した`https`または`http`だけを使い、省略時はHTTPS、HTTPの順で試す。
- JSON outputを先に要求し、利用可能なbodyを得られない場合にtext outputを試す。
- NX-API response codeが`200`以外の場合はcommand失敗とする。
- timeoutはcommand read timeoutとNX-API既定timeoutの大きい方を使う。
- TLS certificate検証は現在opt-inである。この既定値は現行互換として記録するが、安全な長期方針を
  意味しない。変更時はADRと移行手順を必要とする。

### 5.3 `auto`

- NX-OSではNX-APIを優先し、command失敗時にSSHへfallbackする。
- fallback成功時は`fallback_from: nxapi`を記録する。
- NX-OS以外ではSSHを使用する。
- managed operationではrequested transportに加え、実際に成功・失敗したresolved transportを成果物へ
  記録する。

### 5.4 Common Config Session Executor

設定変更を行う上位workflowは、共通のConfig Session Executorを介してdevice sessionを利用する。Executorは
次を所有する。

- resolved inventory／credential／transportを用いたconnection生成と確実なdisconnect
- 設定送信直前またはsave直前に必要なsame-session read-only show command
- config commandの1行単位送信、response、`FAILED`／`UNKNOWN`／`NOT_STARTED`
- device type別save command、success marker、timeout、response
- config mode開始・終了と、timeout／切断後のsession終了

Managed Config OperationとDirect Config Pushは兄弟componentとしてExecutorを利用し、相互を呼び出さない。
Managed側のplan、approval、drift判定、serial順、stop policy、artifact publishと、Direct側の対話確認、並列度、
互換filterは各上位領域が所有する。Direct側の互換optionによってManaged側のCLI error検出やfail-closed動作を
弱めてはならない。

現行実装は`execute_config_session()`と`execute_save_session()`を共有しているが、connection生成、same-session
show command、session lifecycleはCLI／Managed callbackに分散している。単一のCommon Config Session Executor
APIへの統合は未実装である。

## 6. 接続確認

- device接続前確認はTCP reachabilityとauthentication／enableを区別する。
- 結果はhost、IP、requested／resolved transport、`tcp`／`auth`／`enable`／`hostname`／`command` stage、
  経過秒、errorを含む。
- SSH接続ではenable後のpromptからconfig mode suffixと末尾`#`／`>`を除いたhostnameを取得し、inventoryの
  canonical hostnameと大文字・小文字を含めて完全一致比較する。promptを解析できない場合はidentity確認失敗とする。
- NX-OSのdefault hostname `switch`は初期設定の可能性を示すidentity warningとし、read-only処理は継続できる。
  config投入またはsave対象に含む場合は、通常のmutation確認とは別に対象hostname／IPを表示して`yes`確認を要求する。
- default以外のhostname不一致はidentity errorとして対象から除外する。明示的な
  `--allow-hostname-mismatch`を指定した場合だけwarningとして継続でき、端末とlogへexpected／reported hostnameを残す。
  既存の`push-config-dir --force`は接続保護filter解除専用であり、identity overrideへ流用しない。
- mutationは事前接続確認だけに依存せず、実際にcommandを送信する同一SSH sessionでもprompt hostnameを再検証する。
- platform別default hostnameは検証済みregistryで管理する。初期実装はNX-OSの`switch`だけを登録し、未検証platformの
  default値を推測しない。
- 複数hostの確認は並列化できるが、結果表示は決定的なhostname順とする。
- 接続確認成功を、後続の全command成功または設定投入許可とみなさない。
- deviceへ接続するtestには`device` markerを付け、通常testから除外する。

## 7. Errorと再実行

- driver未定義、credential不足、認証失敗、enable失敗、timeout、接続断を区別する。
- command途中の失敗をhost完了として扱わず、最後に確認できたcommandと結果を保存する。
- `auto` fallback後も両transportが失敗した場合、最終失敗とfallback元を追跡できるようにする。
- read-only collectionは安全に再実行できるが、各attemptまたはgenerationを識別し、旧成果物と混在させない。
- config投入・保存・rollbackはread-only collectionと同じ許可として扱わず、対象と承認を確認する。

## 8. 実装状態と未決事項

- `hosts.txt`／`hosts.yaml`、credential解決、SSH／NX-API／auto、接続確認は実装済みである。
- config送信とsaveの低レベルprimitiveは共通化済みだが、Common Config Session Executor APIは一部実装である。
- inventoryのJSON Schema、credential file permission検査、device access共通capability registryは未実装である。
- NX-API TLS検証既定値の変更は未決であり、本整理では変更しない。
- device typeごとの実機対応範囲は、各用途のcapabilityまたは検証記録を正本とする。
