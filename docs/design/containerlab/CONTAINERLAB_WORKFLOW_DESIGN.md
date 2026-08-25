# Containerlab Workflow Design

## 1. 文書の目的

alredが既存network情報またはtable-driven designからcontainerlab用inventory、startup config、topologyを
生成し、lab起動後のconfigを確認する現行仕様を定める。

現行実装の根拠と未確認事項は
[Containerlab Workflow As-Is](../../as-is/CONTAINERLAB_WORKFLOW_AS_IS.md)を参照する。LLDPとlinkの
canonical意味は[Link Discovery and Normalization Design](../topology/LINK_DISCOVERY_AND_NORMALIZATION_DESIGN.md)、
inventory・credential・transportは
[Inventory, Credentials, and Device Access Design](../common/INVENTORY_CREDENTIALS_AND_DEVICE_ACCESS_DESIGN.md)
を正本とする。

## 2. Workflow

### 2.1 既存環境からlabを生成

```text
hosts.yaml + production device
    ↓ collect-clab
raw LLDP / running config
    ├→ clab-transform-config → hosts.lab.yaml + raw/labconfig/
    └→ normalize-links       → links_confirmed.csv / links_candidates.csv
                                     ↓
                                 generate-clab
                                     ↓
                              topology.clab.yaml
                                     ↓ containerlab deploy（startup-config は既定で無効）
                              booted cisco_n9kv nodes
                                     ↓ push-config-dir
                           raw/labconfig/ を起動後投入
```

`clab-set-cmds`はこのflowにdiagramとVNI map生成を加えた固定pipelineである。stepの詳細仕様は各command
設計を正本とし、pipeline内で独自処理を実装しない。

商用環境へ接続できない隔離labでは次を目標flowとする。

```text
Evidence Package tar.gz
    ↓ evidence-package import（内部 verify）
imported package
    ↓ Manifestからinventory / LLDP / config / rules / packaged linksを解決
normalize-links + packaged canonical比較
    ↓ VERIFIED confirmed links
clab-transform-config + lab-transform-parameters.yaml
    ↓ hosts.lab.yaml + raw/labconfig/ + lab-transform-manifest.yaml
VERIFIED confirmed links + hosts.lab.yaml + 同じnode map
    ↓ generate-clab
topology.clab.yaml
```

Evidence Packageの開示変換は搬送時の情報保護、`clab-transform-config`はlabで起動可能な構成への変換を担当する。
同じ置換処理をpackage exporterへ実装せず、lab parameterを商用側packageへ埋め込まない。
`import`はlink解析を行わない。import後の`normalize-links`が任意のraw LLDPとdescriptionからlinkを再生成し、package同梱の
canonical結果と一致した場合だけ`generate-clab`へ渡す。

Evidence Package を主流経路とする包括 CLI は次とする。

```text
alred clab-set-cmds --evidence-package evidence-packages/<package-id>.tar.gz
alred clab-set-cmds --evidence-import imported-evidence/<package-id>
```

`--evidence-package` は verify 付き import、link 再生成・照合、config 変換、Containerlab topology、
diagram、VNI 成果物の生成までを実行する。`--evidence-import` は同じ pipeline を import 済み
directory から開始する。どちらも `collect-clab`、`containerlab deploy`、device access、config push を
実行しない。archive と import 済み directory は同時指定できない。

source option、`--hosts`、`--output`、`--without-collect` をすべて省略した `clab-set-cmds` は、
`--evidence-import imported-evidence/latest` を実効 source とする。`--evidence-package` は引き続き archive を意味し、
自動選択時に archive の再 import は行わない。直接収集は `--hosts <inventory>`、既存 raw は
`--without-collect` または `--output <raw-root>` を明示して選択する。

alred collectionを使用せず外部show run folderを入力にするflowは次とする。

```text
external show run folder
├── one file per host
└── multiple hosts in transcript
          ↓ import-running-config
per-host config + Running Config Import Manifest
          ├→ clab-transform-config
          └→ normalize-links
                 ├── optional LLDPあり: LLDP + description
                 └── LLDPなし: description-only
                          ↓ confirmed links
                      generate-clab
```

外部入力のhost分割とManifest仕様は
[External Running Config Import Design](../common/EXTERNAL_RUNNING_CONFIG_IMPORT_DESIGN.md)を正本とする。
双方向descriptionはconfirmed `low`として利用できるが、片方向descriptionはcandidateのまま保持して自動採用しない。

### 2.2 Table-driven labを新規生成

```text
hosts.txt + clab_cables.csv
    ↓ init-clab validation
normalized cable CSV + validation report
    ↓ error 0件の場合だけ
topology.clab.yaml
```

`init-clab`はdeviceへ接続しない。`--validate-only`ではnormalized cableとreportまでを生成する。

### 2.3 Runtimeとの境界

alred は topology と startup artifact を生成するが、`containerlab deploy`、image 取得、runtime 起動を実行しない。
起動後の config 投入は既存の`push-config-dir`を再利用し、read-only 確認は`check-clab-startup-config`で行う。
lab node への設定変更は production 機器への変更許可と分離し、対象 topology、lab inventory、credential、投入元を
確認する。

## 3. Input sourceとprovenance

| source | 用途 | 区分 |
|---|---|---|
| production collection | 既存構成の変換元 | 機密 raw。commit 禁止 |
| Evidence Package | 隔離 lab の推奨入力 | verify 済みの可搬境界 |
| external running config import | alred 非依存の config 入力 | device access なし |
| `hosts.txt`／cable CSV | table-driven lab design | 入力design |
| sanitized fixture | offline regression test | 実データではない |
| `hosts.lab.yaml`／`raw/labconfig`／topology | lab生成物 | production原本ではない |
| merge／lab profile | image、kind、bind、exec等 | operator指定override |

生成時は使用したinventory、mapping、role、site、node map、merge、lab profileのpathと適用順をlogへ記録する。
operation schemaは現在ないため、再現に必要な入力fileを利用者が同一versionで管理する。

商用環境へ直接接続できない隔離labでは、検証済み
[Portable Evidence Package](../common/PORTABLE_EVIDENCE_PACKAGE_DESIGN.md)を入力にできる。
package内のsanitized inventory、任意 LLDP、running config、roles、mappings、description rules、sites、
normalized linksを検証して使用し、商用credentialは受け取らない。lab用credential、image、runtime固有値は
隔離lab側で注入する。

Evidence Package consumer の CLI は次とする。既存 file 入力との後方互換を維持し、同時指定は拒否する。

```text
alred clab-transform-config \
  --evidence-package <imported-package-directory>
```

Collection Manifest から作成した `digital-twin` の sanitized／verbatim package について、この入力 mode と
`LabTransformParameters` を実装済みとする。`--evidence-import` は `--evidence-package` の互換 alias とする。
`--lab-parameters` と出力先 option は任意とし、省略時は built-in safety policy と既定出力先を使用する。
verbatim package では `--acknowledge-sensitive-config` を追加で必須とする。
source option、`--input`、`--hosts` をすべて省略した場合は、
`--evidence-package imported-evidence/latest` を実効 source とする。既存 file mode は `--input raw` または
`--hosts <inventory>` を明示して選択する。
Evidence Package 作成時の最新 current before 自動選択と `--change-id` による Operation 固定も実装済みである。
任意 phase／attempt の選択は将来拡張とする。Canonical Link Evidence の再生成 gate は
`normalize-links --evidence-package` が担当する。

外部 show run import 結果を使用する option は、`clab-transform-config`と`normalize-links`で共通の
`--running-config-import <manifest-or-directory>`とする。両commandはManifestが参照する同じhost別config generationを
使用し、任意 filename や複数 host transcript をそれぞれ独自に再分割しない。この mode は実装済みである。

### 3.1 Evidence Packageのlink準備

`clab-transform-config`と`generate-clab`の前に、
[Link Discovery and Normalization Design](../topology/LINK_DISCOVERY_AND_NORMALIZATION_DESIGN.md#72-evidence-packageの隔離環境再生成検証)
に従ってimport済みpackageのlinkを再生成検証する。入力はresolved inventory、LLDP、running config、mappings、
description rules、packaged canonical linksである。

`VERIFIED`の`links-confirmed.csv`だけを`generate-clab`へ入力する。`VERSION_MISMATCH`、`SEMANTIC_MISMATCH`、
`INCOMPLETE`、`UNKNOWN`ではTopology生成を停止する。candidateとwarning付きlinkを自動昇格しない。

link endpointはpackage identityのcanonical値で保持し、`generate-clab`でconfig変換と同じnode mapを一度だけ適用する。
`normalize-links`と`clab-transform-config`の両方でlab hostnameへ変換して二重mappingしない。使用したlink verification
hashとnode map hashを生成topologyのprovenanceへ記録する。

## 4. `init-clab`

### 4.1 Cable CSV

必須headerは次とする。

```text
src_node,src_if,dst_node,dst_if
```

optional headerは`enabled`と`description`である。

- UTF-8 BOMを許容する。
- `enabled`省略／空はtrueとし、`true|yes|1|on`と`false|no|0|off`を受け付ける。
- 未知headerはwarningとして無視する。
- `src`と`dst`に通信方向の意味はない。
- disabled rowはnormalized outputへ残すがtopology linkにしない。

### 4.2 Normalization

1. `node_name_map`をendpoint hostnameへ適用する。
2. inventoryから各endpointのdevice typeを解決する。
3. explicit `interface_name_map`を優先し、次にdevice type別interface正規化を行う。
4. exclude interfaceをwarningとして記録する。
5. linkの両endpointをcanonical pairとして重複判定する。

正規化前後のendpoint、enabled、descriptionを`links_design_normalized.csv`へ保存する。

### 4.3 Validation

次をerrorとし、topology生成を中止する。

- 必須header・値の欠落、不正な`enabled`
- inventoryにないnode、自己link
- 正規化後の同一link重複、同一endpointの複数link利用
- Linux data linkでの`eth0`
- 管理IPv4の不正、重複、subnet外、network／broadcast address
- `mgmt.ipv4-range`が`mgmt.ipv4-subnet`外

次をwarningとし、生成は継続できる。

- 未接続node
- 未対応／`unknown` device type
- static管理IPとdynamic rangeの重複
- 未知CSV列、exclude interface

全issueを`init_clab_validation.md`へerror／warning別に出力する。`--validate-only`でもreportとnormalized
CSVは生成する。

## 5. Lab inventoryとconfig変換

`hosts.lab.yaml` は `prepare-hosts` と同じ device type mapping を使用し、各 host に少なくとも
`device_type` と `os_type` を記録する。対応 device type では `ansible_network_os`、
`ansible_connection`、`netmiko_device_type` も補完する。source inventory がこれらを明示している場合は
上書きせず、未定義 field だけを補完する。これにより、`clab-apply-config`、`push-config-dir`、
read-only 確認が同じ lab inventory を使用できる。

### 5.1 Management address

- `clab-env`の`mgmt.ipv4-subnet`があれば、source管理IPv4のhost bitを維持してlab subnetへ移す。
- node mapがある場合は`source_mgmt_ip`→`target_mgmt_ip`を先に適用し、targetがlab subnet外ならさらに
  host bitを維持して変換する。
- source／target hostnameのどちらをinventory keyに使っていても解決できる。
- inventory値がnode mapの許容source／target addressと一致しない場合、重複hostname／IP、未知sourceは
  errorとする。

### 5.2 Node map

標準headerは次とし、`prd_*`／`lab_*`互換headerも受け付ける。

```text
source_hostname,source_mgmt_ip,target_hostname,target_mgmt_ip
```

mappingはinventory key、`ansible_host`、出力filename、configの`hostname`、同名`vdc`、interface
description、management address、vPC keepaliveへ一貫して適用する。

### 5.3 NX-OS config transform

正式対象はNX-OS running configとする。

- management VRFのnext hop、`mgmt0` address、vPC peer keepalive addressを変換する。
- dot1q subinterfaceをVLAN、SVI、parent trunk allowed VLANへ変換する。
- 既存VLAN／SVI／parent interfaceへ不足lineだけをmergeする。
- L3 Ethernet／port-channelに`no switchport`がなければ追加する。
- `--delete-access-class`は`line vty`内のIPv4／IPv6 access classだけを削除する。
- source configのその他のsection順と未対象lineを可能な限り保持する。

非NX-OS device typeは、専用transform adapterとfixtureを追加するまで正式対応としない。現在のcommandが
fileを処理できることだけを対応根拠にしない。

### 5.4 Lab user

- NX-OSでcredentialが完全に解決できる場合、同名userを削除して
  `username <user> password 0 <password> role network-admin`を1件追加する。
- 同名以外のuserは維持する。
- usernameは英数字、`_`、`.`、`-`に限定する。
- passwordは空または空白を含む値を拒否する。
- `--delete-username`では全`username`と全`snmp-server user`を削除し、lab userを追加しない。
- 平文passwordを含むstartup configをsample、fixture、commitへ含めない。生成物は限定permissionで管理し、
  lab利用後に安全に破棄する。

### 5.5 Missing source

source configがないhostはwarningとして変換をskipする。`hosts.lab.yaml`には残るため、生成完了後に
missing countを必ず確認する。missingを許容できないworkflowでは、topology deploy前に0件をgateとする。

### 5.6 Evidence Packageからのlab parameter変換

Evidence Packageの`sanitized` configは情報開示用の中間artifactであり、そのまま起動可能とは限らない。
`clab-transform-config`はPackage Manifestとchecksumを検証後、`LabTransformParameters`を適用してstartup configを
生成する。package内のpathをdirectory走査で推測せず、artifact IDとManifest相対pathから解決する。
既定の`source_local_users: remove`はcredential行だけでなく、同じusernameのpassphrase lifetimeなどの従属行も
除去する。変換後にcredential commandを伴わない`username <name> passphrase ...`が残った場合はrisk scanで
`LAB_ORPHAN_USERNAME_PASSPHRASE`としてBLOCKし、configを公開しない。

```yaml
api_version: alred/v1
kind: LabTransformParameters

metadata:
  name: fabric-a-lab

spec:
  management:
    ipv4_subnet: 172.20.20.0/24
    gateway: 172.20.20.1
  node_map_ref: node-map.lab.csv
  services:
    ntp:
      action: replace
      servers: [172.20.20.10]
    logging:
      action: remove
    dns:
      action: remove
    aaa:
      action: remove
    snmp:
      action: remove
  access_control:
    management_access_class:
      action: remove
  source_local_users:
    action: remove
  lab_users:
    users:
      - username: lab-admin
        privilege: admin
        primary: true
        authentication:
          password_ref: LAB_ADMIN_PASSWORD
  bootstrap_user:
    action: preserve
```

parameter file へ password、token、community、private key を直接記載しない。`password_ref`は lab 側 credential
source の論理名であり、値は既存 credential 解決または対話 prompt から実行時だけ取得する。生成 config は lab secret を
含み得るため限定 permission で管理する。

parameter file を省略した場合も built-in safety policy を適用する。built-in policy は external service、AAA、SNMP、
certificate／key、management access class、production local user を除去する。Containerlab の bootstrap `admin:admin`は
default で保持し、lab user は parameter で指定された場合だけ追加する。production credential へ fallback しない。

#### 5.6.1 変換対象と既定動作

| 対象 | parameter | 既定 | 動作 |
|---|---|---|---|
| config source | Package Manifestの`config_content` | package作成時に固定 | directory走査やCLI overrideで変更しない |
| hostname／management IP | `node_map_ref`、`management` | 必須 | node名、inventory、filename、configを一貫変換 |
| management default route | `management.gateway` | lab subnetで必要時必須 | production next hopを保持せず置換 |
| vPC keepalive | node mapまたは専用address mapping | vPC使用時必須 | 両peerを一貫変換。片側だけの変換を拒否 |
| NTP／logging／DNS server | `services.<type>.action` | `remove` | `replace`ではlab-local serverを必須とする |
| RADIUS／TACACS／AAA | `services.aaa.action` | `remove` | production server／keyを除去。lab-local定義だけ注入可 |
| SNMP community／user／trap host | `services.snmp.action` | `remove` | production secret／destinationを保持しない |
| source local username | `source_local_users` | `remove` | production config由来のuserを除去 |
| lab username | `lab_users.users` | 空 | 指定された複数lab userをpassword refから生成。指定時はprimaryを1件必須とする |
| bootstrap username | `bootstrap_user.action` | `preserve` | Containerlab imageの`admin:admin`を保持。明示時だけprimary再接続後に削除 |
| certificate／private key | 固定安全rule | `remove` | production materialの保持・自動変換を許可しない |
| management ACL／access class | `access_control` | `remove` | production address前提のfilterを既定除去。replace時は明示rule必須 |
| interface／routing／VLAN／VNI | 既存transformとmapping | preserve | lab image非対応項目以外のsemantic構成を維持 |
| image／kind／startup delay | lab profile／merge | 必須値のみ | config transformではなく`generate-clab`の責務 |

`action`は対象に応じて`remove`、`replace`、`preserve`を受け付けるが、credential、private key、production AAA／SNMP
secretへ`preserve`を指定してはならない。production endpointを残す`preserve`は保護された閉域labで明示承認された
非secret項目だけに許可し、既定では使用しない。

#### 5.6.2 `replace`の共通規則

`replace`は対象カテゴリのproduction設定をすべて除去し、parameterに記載されたlab-local設定集合をcanonical orderで
生成する。既存設定を残したまま値だけを重ねない。NTPだけは5.6.2.1の安全なoption継承のため、明示mappingまたはsource順の
位置対応を使用できる。既存NTP serverが2台でreplacementが1台の場合、出力するNTP serverはreplacementの1台だけであり、
残りの既存NTP serverは削除する。他カテゴリはparameterで完全指定した集合を生成する。

| 対象 | `replace`の必須入力 | 除去範囲 | 生成内容 |
|---|---|---|---|
| NTP | 1件以上の`servers` | `ntp server`／`ntp peer`と production key／authentication／access-group／source関連設定 | 指定 server、任意の lab-local VRF／source／認証参照だけを生成 |
| logging | 1件以上の`servers` | remote logging server、source-interface、VRF、facility等の remote 転送関連設定 | 指定 server と明示された lab-local option を生成。local logging policyは保持 |
| DNS | 1件以上の`name_servers` | production name-server、domain lookup source／VRF、明示対象 domain 設定 | 指定 name server と lab-local domain option を生成 |
| AAA／RADIUS／TACACS | lab-local server定義と`credential_ref` | production AAA method list、server、server group、key、source-interface | lab-local server／group／method listを整合した集合として生成 |
| SNMP | 利用する lab-local user／community／trap定義 | production user、community、host、trap source、credential | secret値をcredential sourceから解決し、指定したlab-local集合だけを生成 |
| management access class | lab-local ACL rule | VTYへ適用されたproduction IPv4／IPv6 access classと、その専用ACL | lab management subnetを許可するACLとVTY参照を生成 |
| local user | username、共通`privilege`、`authentication.password_ref` | production local userと関連passphrase／SNMP user | 指定lab userだけを生成。adapterがplatform固有roleへ変換 |

##### 5.6.2.1 NX-OS NTP server の address 置換

既存NTP serverのoptionを維持してaddressだけを置換する場合、`source_address`は任意とする。省略時は、既存の
`ntp server`行とreplacementをsource config内の出現順で対応させる。`digital-twin`の型付き`mask`でaddressが失われていても、
command、親block、ordinal、安全なoptionが残っていれば同じ位置対応を使用する。

```yaml
spec:
  services:
    ntp:
      action: replace
      servers:
        - address: 192.168.129.254
```

変換前:

```text
ntp server 192.0.2.10 prefer use-vrf management
ntp server 192.0.2.11 use-vrf management
```

変換後:

```text
ntp server 192.168.129.254 prefer use-vrf management
```

replacementの1件目を既存1行目へ対応させ、`prefer`と`use-vrf management`を維持する。replacementがない既存2行目の
`192.0.2.11`は削除する。replacementが既存行より多い場合は暗黙にserverを追加せず、
`LAB_TRANSFORM_PARAMETER_CARDINALITY`として変換前に失敗する。既存行より多く追加する場合は`action: inject`を明示する。

特定の既存serverを選ぶ必要がある場合だけ`source_address`を指定する。明示mappingを先に解決して対象既存行を位置対応poolから
除外し、`source_address`がない残りのreplacementを残りの既存行へ出現順で対応させる。`source_address`がないときも
`inherit_options`の既定は`true`とし、完全指定したい場合は`inherit_options: false`と各optionを指定する。

安全に継承できる option は`prefer`、`use-vrf`、`minpoll`、`maxpoll`の allowlist に限定する。`use-vrf`の VRF は
変換後 config に存在することを検証する。authentication key ID、`ntp authentication-key`、`ntp trusted-key`、
production source interface、未知 option は自動継承しない。lab-local 認証を使用する場合は secret 値を parameter に
直接記載せず、明示した`credential_ref`から新規生成する。

既存 option を継承せず、lab-local 設定を完全指定する場合は次の形式を使用する。

```yaml
spec:
  services:
    ntp:
      action: replace
      servers:
        - address: 192.168.129.254
          prefer: true
          use_vrf: management
```

同じ`source_address`の重複、存在しないsource、複数既存行へ曖昧に一致するsource、replacement超過、allowlist外optionの
継承要求はvalidation errorとする。allowlist外optionを既存configから検出した場合はrisk scanへ記録し、secretまたは
production endpoint を含む場合は`BLOCK`、安全性を確定できない非secret option は`WARN`とする。

NTP の local calendar、timezone、clock format など remote server に依存しない設定は NTP server replacement の対象外として
保持する。どの構文がカテゴリに属するかは platform／release 別 rule catalog で固定し、未分類の credential または
production endpoint を検出した場合は推測で保持せず fail closed とする。replacement list の重複、空値、lab subnet外の
禁止 endpoint、未解決`credential_ref`は validation error とする。

`remove`も同じカテゴリ境界で production 設定をすべて除去するが、新しい設定を生成しない。device ごとの削除件数、
生成件数、未分類行、resolved parameter hash を`lab-transform-manifest.yaml`へ記録する。

boot 後投入では config file から user 行を除去しても、起動 image の bootstrap user は running config に残る。
default の`bootstrap_user.action: preserve`では`admin:admin`を削除も置換もせず、risk scan、Manifest、verificationへ
`WARN`として記録する。`remove-after-primary-ready`を明示した場合だけ、primary lab user を作成し、新 credential での
再接続成功後に bootstrap user を削除する。primary 再接続前には削除しない。

bootstrap credential を明示的に変更する場合は`bootstrap_user.action: replace-credential`と
`authentication.password_ref`を指定する。初回は`admin:admin`で接続し、credential 変更後に session を閉じ、新しい
credential で再接続する。変換時に`BOOTSTRAP_CREDENTIAL_REPLACEMENT`の`WARN`を出し、対話では`yes`、automation では
`--accept-connectivity-risk`を必須とする。再接続失敗時は`FAILED`とし、save を禁止する。

`bootstrap_user.action: preserve`のまま`lab_users.users`へ case-insensitive で同名の`admin`を定義した場合は、どちらの
credential を正本とするか曖昧なため`LAB_TRANSFORM_BOOTSTRAP_USER_CONFLICT`として変換前に拒否する。production source
config 由来の bootstrap `admin`変更は lab parameter による明示変更とみなさず、risk scan の`BLOCK`として除去する。

`lab_users.users`は複数指定できる。username は case-insensitive で一意とし、指定時は`primary: true`をちょうど1件
必要とする。共通`privilege`は`admin`または`read-only`とし、NX-OS adapter が`network-admin`または
`network-operator`へ変換する。対応できない privilege は validation error とする。

#### 5.6.3 `sanitized`と`verbatim`

Containerlab側に`--config-source`を設けず、Package Manifestの`config_content`を変換元の正本とする。
directory名、同名file、sanitized／verbatimの存在数から推測せず、CLIやparameterによるoverrideも許可しない。

| `config_content` | 変換元 | 動作 |
|---|---|---|
| `sanitized` | Manifestが参照する`raw/sanitized/` artifact | pseudonymizeされたidentityへnode mapとlab parameterを適用 |
| `verbatim` | Manifestが参照する`raw/verbatim/` artifact | sensitive承認を再検証後、同じlab parameter変換を適用 |
| `exclude` | なし | startup config変換を実行せず、configを必須とするworkflowではfail closed |

`verbatim` packageに確認用sanitized copyが併載されていても、Containerlabはそれへ切り替えない。反対に
`sanitized` packageへ未参照の原文fileが存在しても使用しない。Manifestの種別、artifact ID、path、hashと実fileが
一致しない場合はfail closedとする。

どちらを変換元にしてもhostname、management address、external service、AAA／SNMP、credential、certificate／key、
ACL、vPC keepaliveを同じ変換flowで書き換えまたは削除する。`verbatim`でもproduction password、AAA key、
SNMP community、private keyをstartup configへ引き継がず、
[Secret Scan Rule Catalog](../common/SECRET_SCAN_RULE_CATALOG.md)と本節のlab置換ruleを適用する。

`verbatim`ではPackage Manifestの`contains_verbatim_config: true`、archiveのsensitive分類、承認期限、import時permissionを
検証し、`--acknowledge-sensitive-config`相当の明示確認を再度必要とする。sanitizedとverbatimを自動比較して欠落値を
補完せず、Manifestが選択したsource artifactとhashを`lab-transform-manifest.yaml`へ固定する。

`sanitized`の型付き`mask`は変換不能を意味しない。Manifest の rule ID、block ID、ordinal と config に残る command 構造から、
lab-local parameter を置換または新規生成できる。型付き placeholder を NX-OS へ送信せず、変換後の secret scan と semantic
validation で残存を拒否する。comment 形式の redaction marker でも parameter が対象カテゴリを完全指定していれば新規生成する。
command または block が`exclude`され、必要な semantic 情報を parameter、inventory、Canonical Link Evidence のいずれからも
解決できない場合だけ`LAB_TRANSFORM_INCOMPLETE_SOURCE`で fail closed とする。任意機能を安全に除去できる場合は
`GENERATED_WITHOUT_SOURCE_SEMANTICS`の`WARN`として続行し、縮退内容を Manifest へ記録する。

#### 5.6.4 変換順とfail-closed

適用順を次で固定する。

1. Evidence Package／Collection Manifest／checksum／schemaを検証する。
2. Package Manifestの`config_content`からsource artifactと対象deviceを確定する。
3. hostname、management address、node mapを適用する。
4. production credential、AAA、SNMP、certificate／key materialを除去する。
5. NTP、logging、DNS、management route／ACL、vPC keepaliveをremove／replaceする。
6. 既存NX-OS transformでsubinterface、SVI、trunk、L3 interfaceを変換する。
7. lab-local credentialと明示追加parameterを注入する。
8. startup configへsecret scanとsemantic validationを行う。
9. 全device成功後に成果物とManifestをatomicに公開する。

必要parameter不足、未解決identity、IP重複、lab subnet外、片側だけのvPC mapping、禁止secret残存、未対応の必須構文では
fail closedとし、production値へfallbackしない。対象commandを安全に除去できるがlab機能が縮退する場合は、除去内容と
影響をwarningおよびManifestへ記録する。

#### 5.6.5 成果物とprovenance

`lab-transform-manifest.yaml`へpackage ID、Package Manifest hash、source artifact／export hash、parameter file hash、
transformer／secret catalog version、device別変換rule、除去／置換／再生成／継承／保持／縮退／未分類件数、Package 側
rule ID、warning、startup config hashを記録する。
原値、secret、credential解決値は記録しない。同一package、parameter、tool versionから同じstartup configを再生成できる
ことをtestする。

#### 5.6.6 Platform adapter

`LabTransformParameters`の共通 schema、Manifest 検証、credential 参照、risk scan、成果物公開は platform 非依存の core が
所有する。config 構文解析、カテゴリ境界、option 継承、共通`privilege`から device role への変換、CLI error、save、
verification 正規化は platform adapter が所有する。初期実装は canonical platform ID `nxos`だけを in-tree adapter として
提供する。

parameter は共通`spec`を正本とし、platform 固有差分は任意の`platform_overrides.<canonical-platform-id>`、device 固有差分は
任意の`device_overrides.<canonical-hostname>`へ限定する。core は adapter capability と override schema を投入前に検証する。
adapter 未登録、必須 capability 不足、platform 固有値を共通 field で安全に表現できない場合は`UNSUPPORTED_PLATFORM`で
fail closed とし、NX-OS parser や role を他 platform へ流用しない。

## 6. `generate-clab`

### 6.1 Base topology

- confirmed linkをconfidence、mapping、role orderingに従って決定的に並べる。
- inventoryがある場合はlink endpointまたはinventoryからnodeを構築する。
- node kindはdevice type mappingから解決する。
- `--group-by-role`ではlegacy single roleを`group`へ設定する。canonical resolver移行前は複数roleの
  意味を自動統合しない。
- site は inventory または Containerlab node の明示 `site`／`labels.site` を優先する。明示値がない node だけ、
  `sites.yaml` の hostname 命名規則で検出した site を node label へ設定する。命名規則は明示値を上書きしない。

### 6.2 Optional overlay

- Linux CSVはLinux node、env、bind、exec、Leaf-to-`eth1|eth2` linkを追加する。
- Kind cluster CSVは`k8s-kind` cluster node、`ext-container` member、support configとlinkを追加する。
- required headerがないCSVはerrorとする。hostname等が空のrowはskipする。
- optional overlayが追加するendpointとbase／merge linkの完全なsemantic validationは現在未実装である。

### 6.3 Merge順

設定は次の順で適用し、後の値を優先する。

```text
generated < clab-env (`init-clab`のみ) < clab-merge < clab-lab-profile
```

- mapping同士は再帰mergeする。
- scalarとlistは後勝ちとする。
- `topology.links`はgenerated linksの後にmerge側linksを追加し、同一link objectを順序維持で重複排除する。
- mergeで明示されたnode／kind値をdefault適用で上書きしない。
- 最終top-level key順は`name`、`mgmt`、`topology`を先頭とする。
- topology key順は`kinds`、`defaults`、`nodes`、`links`を先頭とする。

### 6.4 Defaults

- Linux nodeがあり、kind image未指定なら`ghcr.io/hellt/network-multitool:latest`を使用する。
- `cisco_n9kv` node がある場合、未指定の image と environment default を補う。
- `cisco_n9kv`の`startup-config`は、9000v の boot 中の設定投入が停止する場合を避けるため、既定では出力しない。
- `clab-merge`または`clab-lab-profile`で`startup-config`を明示した場合は、利用者が boot-time 投入を選択したものと
  して有効な field を維持し、default 適用で削除または上書きしない。
- N9Kv startup delayは`BATCH,SECONDS`で指定し、`(node index // BATCH) * SECONDS`を適用する。
  0秒はfieldを追加せず、既存`startup-delay`を上書きしない。

### 6.5 NX-OS 9000v の boot 後 config 投入

既定 workflow は次とする。

1. `startup-config`が有効な field として存在しないことを確認する。
2. `containerlab deploy`で 9000v を起動する。
3. node の management 到達性と bootstrap credential を確認する。
4. `hosts.lab.yaml`と`raw/labconfig/`を指定して`push-config-dir`を実行する。
5. host 別結果を確認し、必要な場合だけ成功 host へ save を行う。
6. `check-clab-startup-config`で期待 config と live running config を比較する。

boot 前には変換後 config 内の lab user がまだ存在しないため、初回接続には image の bootstrap credential または
lab 側で別途用意した credential を使用する。production credential へ fallback しない。投入によって接続中 user、
management interface、AAA、VTY access が変わる可能性があるため、それらを一括投入しても到達性を維持できることを
変換時に検証する。現行 Direct Config Push は CLI error text を検出しない場合があるため、成功表示だけで完全投入を
断定せず、起動後比較を行う。

### 6.6 `clab-apply-config`の config directory

`--input-dir`は既存 file mode として、変換済み`<hostname><suffix>`だけを格納した directory を指定する。標準値は
`raw/labconfig/`、default suffix は`_run.txt`とする。外部 running config import の canonical directory
`<import-directory>/attempts/<attempt-id>/config/`も同じ filename 規則を使用するが、production 由来の未変換 config で
あるため、`clab-apply-config --input-dir`へ直接指定してはならない。

将来の Manifest mode は`--lab-transform-manifest <path>`で変換済み config の artifact ID、relative path、hostname、
hash を解決する。`--input-dir`との同時指定を拒否する。Manifest mode を標準経路、`--input-dir`を既存 file 互換経路とし、
どちらも symlink、hidden file、root外 path、hostname重複、suffix不一致、Manifest hash不一致を fail closed とする。

```text
Running Config Import Manifest
    ↓ clab-transform-config + LabTransformParameters
lab-transform-manifest.yaml + raw/labconfig/<hostname>_run.txt
    ↓ clab-apply-config --lab-transform-manifest
booted cisco_n9kv
```

### 6.7 Readiness、投入、検証

`clab-apply-config`は Containerlab deploy を実行せず、deploy 開始直後または起動完了後から別 process として実行できる。
`--topology`には実際に deploy した Topology を指定し、同じ node 名を持つ別 lab の Topology で代用しない。初回に
`containerlab inspect --all --format json`を実行し、Topology の`name`と一致する lab の対象 node がすべて`healthy`なら
sleepせず投入前処理へ進む。同じ対象 node 群を持つ稼働中の別名 lab だけが見つかった場合は、誤投入を避けるため lab を
推測せず`CLAB_NODE_NOT_READY`で停止し、指定 lab 名、候補 lab 名、候補の Topology path を表示する。

起動途中または未作成の場合は、topology のnode-level `startup-delay`を読み、node deadline を
`開始時刻 + startup-delay + health-timeout`とする。既定は`health-timeout=1200`秒、poll interval 10秒、startup delay
考慮有効とする。初回状態、node ごとの状態変化、未 Ready 理由、pending node、次回 poll までの秒数を標準出力と
`logs/clab-apply-config.log`へ記録する。`containerlab inspect`を実行できない、または JSON を取得できない場合は、
同じ lab 名と node 名から解決した Docker container の State 確認へ fallback し、その理由を log へ記録する。

Containerlab inspect の`up`または Docker health の`healthy`を runtime ready とし、その後 bootstrap `admin:admin`で
既存 connect check を実行する。node 未作成または`starting`は deadline まで待機し、`unhealthy`、`exited`、`dead`、
timeout は host failure とする。対象 host の config／接続失敗はその host を停止し、他 host は継続する。
`--fail-fast` の既定値は無効とし、指定時は [Direct Config Push and Save Design](../network-ops/DIRECT_CONFIG_PUSH_AND_SAVE_DESIGN.md)
の batch 境界に従って未着手 host を停止する。初回受入では `--workers 1 --fail-fast` を推奨し、最初の host failure 後に
別 host へ変更を広げない。失敗 command は Traceback ではなく、host、投入行番号／総行数、秘密値を除去した command、error を
標準出力と `logs/clab-apply-config.log` へ記録する。失敗直前に正常処理された最大 5 command も、投入行番号、status、秘密値を
除去した command を含む `PUSH CLI CONTEXT` として記録する。未着手 host は attempt の `not_started_hosts` に保存する。

readiness 待機中の`SIGINT`は Python Traceback を表示せず、attempt の`apply-result.yaml`へ`INTERRUPTED_READINESS`を
記録して終了する。以前の成功済み`current.json`は更新しない。

lab user が定義されている場合は primary lab user で投入後の再接続を検証する。定義されていない場合は保持した
bootstrap `admin:admin` で再接続を検証し、結果へ `BOOTSTRAP_CREDENTIAL_PRESERVED` の `WARN` を記録する。

config 送信は default strict CLI error 判定を使用する。`--allow-cli-error-pattern` と、利用非推奨の
`--ignore-all-cli-errors` は [Direct Config Push and Save Design](../network-ops/DIRECT_CONFIG_PUSH_AND_SAVE_DESIGN.md) へ従う。
`--ignore-all-cli-errors` を使用した調査では、各 `IGNORED_ERROR` にも直前の正常処理済み最大 5 command と該当 command を
`WARNING` で記録するが、意図的な継続であるため `--fail-fast` の停止条件にはしない。
ただし、NX-OS 9000v の bootstrap SSH 接続に成功した後の `clab-apply-config` に限り、running config 由来の
`ssh key rsa <bits>` へ既存 key を示す次の応答が返った場合は、built-in rule
`NXOS_CLAB_SSH_KEY_ALREADY_EXISTS` で `WARN` として継続する。

```text
ERROR: Cannot configure run ssh key without force as the config is already existing
```

rule は command 全体と error 行全体の両方を anchored pattern で照合する。`force` 付き command、RSA 以外、bit 数なし、
異なる response は許可しない。rule ID、command index、error を command result に保存し、post-apply SSH 再接続と
semantic verification を省略しない。この built-in rule は汎用 `push-config`／`push-config-dir` へ既定適用せず、実機で
許可する場合は `--allow-cli-error-pattern` を明示する。`clab-transform-config` は `ssh key rsa` を秘密情報として除去しない。
投入後は lab credential で再接続し、期待 config と running config を比較する。save は default 無効とし、明示指定時も
strict push、lab credential 再接続、config 検証がすべて成功した host だけを対象とする。`IGNORED_ERROR`がある host は
save しない。

attempt は node 単位の readiness、最後に成功した command、再接続、verification、save 結果を保持する。失敗 attempt を
同じ成果物へ追記せず、再実行では新しい attempt を作成する。再実行時は以前に成功した node も live config の必須
invariant を再確認し、`VERIFIED`なら再投入を省略できる。`VERIFIED_WITH_DIFF`、`FAILED`、`UNKNOWN`は承認なしに成功扱いせず、
必要な node だけを再投入する。write memory は各 node の strict push、再接続、verification 完了後にだけ実施し、途中失敗
node には実施しない。topology hashとLab Transform Manifest hashが成功済み`current.json`と一致する場合だけlive再検証を
行い、`VERIFIED` nodeを再利用する。`--reapply-all`はこの再利用を無効化する。

### 6.8 Config 順序と risk scan

投入時に config 全体を機能別 phase へ並べ替えない。`clab-transform-config`は production endpoint／credentialを
remove／replaceするが、対象カテゴリ以外の section 順は維持する。replacement は最初に除去した同カテゴリ設定の位置へ
挿入し、既存設定がない場合だけ platform rule catalog の安全な anchor へ追加する。

変換完了後、投入前に connectivity／secret risk scan を行う。

| Level | 例 | 動作 |
|---|---|---|
| `BLOCK` | production password、private key、未変換 AAA key、production management IP、production source 由来の bootstrap `admin`変更 | 投入禁止。確認 option でも回避不可 |
| `WARN` | management IP、default route、AAA、VTY、local user の lab-local 変更、bootstrap `admin:admin`の保持または明示的 credential 変更 | 対話で`yes`、automation では`--accept-connectivity-risk`が必要 |
| `INFO` | hostname、description、検証済みNTP置換 | 記録して続行 |

scan 結果には device、rule ID、config line の secret を除いた要約、level、対応を記録する。`WARN`確認は通常の mutation
target 確認とは別に表示する。`--accept-connectivity-risk`は`BLOCK`、secret scan failure、未分類 credentialを許可しない。
初期NX-OS ruleはactive mask placeholder、private key、crypto credential、未固定またはlab subnet外のmanagement addressを
`BLOCK`とし、management／user／AAA／SNMP／VTY／bootstrap変更を`WARN`とする。Manifest生成時と投入直前の両方で実行し、
投入前の結果を`risk-scan.yaml`へ固定する。

### 6.9 Verification と差分成果物

期待 config と live running config の byte／line 完全一致を合格条件にしない。NX-OS の default／動的 line と、投入時に
除外する`version`、`boot`、`copp`等を正規化したうえで、重要 invariant を自動判定し、残差を参考 diff として保存する。

必須 invariant は次とする。

- lab management IP が期待値と一致し、management interface が operational である。
- lab credential で新規接続できる。
- production management IP、user、AAA／SNMP secret、NTP／logging／DNS destination が残っていない。
- parameter で指定した lab-local replacement が存在する。
- VTY／SSH access が維持され、secret scan と strict CLI error 判定が成功している。

| Status | 条件 | Save |
|---|---|---|
| `VERIFIED` | 必須 invariant 成功、重要残差なし | 明示指定時に許可 |
| `VERIFIED_WITH_DIFF` | 必須 invariant 成功、参考残差あり | diff表示後の`yes`または`--accept-verification-diff`が必要 |
| `FAILED` | invariant不一致、未許可CLI error | 禁止 |
| `UNKNOWN` | parser／取得不足で安全に判定不能 | 禁止 |

`--accept-verification-diff`は必須 invariant failure を許可しない。`--ignore-all-cli-errors`による
`IGNORED_ERROR`がある host は、diff を承認しても save しない。

```text
output/clab-apply-config/<attempt-id>/
├── apply-result.yaml
├── risk-scan.yaml
├── command-results/
│   └── <hostname>.yaml
├── running-config/
│   └── <hostname>_run.txt
├── diff/
│   └── <hostname>.diff
└── verification.yaml

output/clab-apply-config/current.json
```

attempt は成功・失敗を問わず不変とし、config／parameter／Manifest／topology hash、runtime backend、readiness、使用した
credential 種別、最後に成功した command、verification status を記録する。password、secret、未加工の secret response は
保存しない。
command resultはstatus、時刻、index、最後に成功したcommandを追跡可能にする一方、username password、AAA key、SNMP
communityとresponse内のecho値を永続化前に`<redacted>`へ置換する。成功attemptの全成果物公開後だけ`current.json`をatomicに
更新し、失敗または中断時は以前の成功pointerを維持する。

## 7. `clab-set-cmds`

- pipeline stepは`alred/constants.py`の順序付き定義を正本とする。
- 各stepは対応する既存handlerを同一process内で呼び、実装を複製しない。
- CLI overrideは各stepの引数へ明示的に引き継ぐ。
- Mermaid step の role grouping は既定で有効とする。site grouping は解決済み site metadata が 1 台以上にある場合に
  自動的に有効化し、`--group-by-site`／`--no-group-by-site` の明示指定を diagram step へ引き継ぐ。
- `--without-collect`は`collect-clab` stepだけをskipし、既存rawを使う。
- step失敗時は後続stepへ進まず、部分生成物を削除しない。
- command 開始時に `output/clab-set-cmds/attempts/<attempt-id>/pipeline-manifest.yaml` を作成し、
  source 解決と各 pipeline step を順番に記録する。attempt ID は開始時刻、timezone offset、microsecond、
  credential を含まない要求 source hash から生成する。`spec.requested_source` は CLI で要求された archive／import／raw を、
  `spec.source` は verify／import 後に固定した Package Manifest hash または Import Manifest hash を保持する。
- step status は `NOT_STARTED`、`RUNNING`、`COMPLETED`、`SKIPPED`、`FAILED`、`INTERRUPTED` とする。
  source archive の verify／import、import 済み Package または外部 config import の解決は
  `source-resolution` step として、固定 pipeline の前に記録する。
- attempt の terminal status は `SUCCESS`、`FAILED`、`INTERRUPTED` とする。step の開始・終了と terminal
  transition は atomic write し、途中の `RUNNING` record を terminal 成果物とみなさない。
- failure は error code、exception type、秘密値を除去した最大 2000 文字の message、失敗 step、完了・未着手 step を
  Manifest に保存する。既知の code prefix または exception code がない想定外例外は `UNEXPECTED_ERROR` とし、
  Manifest 保存後に元の例外を再送出する。Python Traceback を包括的に隠す動作にはしない。
- collect handler を開始した時点で、一部 host へ接続した可能性を考慮して `device_access_performed: true` とする。
  Evidence Package、running config import、`--without-collect` で collect を skip した場合は `false` とする。
  `deploy_performed` と `config_push_performed` は常に `false` とする。
- pipeline 開始前と終了時の主要 canonical output hash を比較し、`created`、`modified`、
  `unchanged_existing` を記録する。失敗時も到達可能な regular file だけを記録し、symlink は成果物とみなさない。
- `output/clab-set-cmds/current.json` は全 step が `COMPLETED` または意図した `SKIPPED` で終了した場合だけ atomic に更新し、
  `SUCCESS` attempt と Manifest hash を指す。失敗・中断時は以前の成功 pointer を維持し、再実行では新しい attempt を作る。
- pipeline の step は既存の共有 path へ個別に出力するため、pipeline 全体の directory switch は行わない。後続の失敗 attempt が
  以前の成功成果物の一部を変更する可能性があるため、成功済み `current.json` だけでなく、その Manifest の output hash と
  current file を照合して同一実行世代であることを確認する。

## 8. Startup config verification

- inventory、policy、target、connect checkでlab nodeを選択する。
- live running configのread-only取得はCommonのCollection／Device Accessを再利用し、Network Operationsを
  経由しない。接続、credential、transport、raw保存、provenanceはCommon、生成startup configとの比較と
  Containerlab固有の正規化・判定は本領域が所有する。
- `<startup-dir>/<hostname><suffix>`とlive running configを比較する。
- device type別に動的・環境依存lineを正規化し、意味のある残差をunified diffにする。
- live running configを`<output-dir>/current/`へ、summaryとdetailを
  `<output-dir>/check-clab-startup-config.txt`へ保存する。
- statusは`matched`、`diff`、`missing-startup`、`unsupported`、`connect-failed`、`failed`を区別する。
- `diff`を自動修正せず、投入元、起動log、image capabilityを確認する。

connect failure recordのdevice typeは`ConnectCheckResult`ではなく、同じinventoryのhostnameから解決する。
この経路は専用testでreport生成まで検証する。
また、現行startup verificationは共通credential／connect checkを再利用するが、running config取得結果を
Collection Manifestへ固定する共通Collection APIには統合されていない。この差分は比較責務をContainerlabに
維持したまま、read-only取得とprovenanceをCommonへ寄せて解消する。

## 9. Securityと検証

- production credential、管理IP、certificate、秘密鍵を生成物、sample、fixtureへcommitしない。
- production rawからlab artifactを作る場合、保存先と取扱区分を明示する。
- offline testでは実機・labへ接続しない。
- runtime／imageを必要とするtestは対象topology、node、read-only／mutation、実行時刻を記録する。
- 同じ入力と同じalred versionから、安定したnode／link順と同じsemantic topologyを生成する。

## 10. 実装状態

- table-driven validation、config変換、node／link生成、merge、Linux／Kind overlay、startup verification、
  pipelineは実装済みである。
- containerlab runtime起動、topology schema validation、生成物manifest、非NX-OS transform adapterは
  実装していない。
- Collection Manifest由来のsanitized Evidence Package入力、`LabTransformParameters` schema、NX-OS adapter、型付き`mask`の
  NTP位置対応、built-in remove policy、複数lab user、bootstrap preserve／replace競合、`lab-transform-manifest.yaml`、
  config／inventoryのatomic publish、logging／DNS／AAA／SNMP／access classの`replace`、明示確認付きverbatim入力を
  実装済みとする。`remove-after-primary-ready`はprimary再接続後の削除と再接続まで実装済みである。非NX-OS adapterは
  platform adapter registryを経由し、非NX-OS adapterは未登録としてfail closedとする。
- `cisco_n9kv`のdefault `startup-config`出力削除、Manifest固定の`push-config-dir`、`clab-apply-config`によるDocker health／
  `startup-delay`考慮のreadiness待機、default strict CLI error検出、Manifestの`password_ref`を実行時解決する投入後再接続を
  実装済みとする。秘密値を除いたNX-OS semantic verification、node単位attempt、検証成功後saveを実装済みとする。
  command単位result、独立risk scan、成功済み`current.json`、live `VERIFIED` node再利用を実装済みとする。
- merge／optional overlay後の全link再validationは要追加testである。
- startup verificationのrunning config取得とCollection Manifest統合は未実装である。
- `clab-set-cmds` の成功・失敗・中断 attempt、step status、output disposition、成功時だけの `current.json` 更新は
  実装済みである。pipeline 全体の directory switch は未実装である。
