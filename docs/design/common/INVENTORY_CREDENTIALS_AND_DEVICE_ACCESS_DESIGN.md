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
- 結果はhost、IP、requested／resolved transport、`tcp`／`auth`／`enable`／`command` stage、
  経過秒、errorを含む。
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
