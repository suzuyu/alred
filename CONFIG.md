# CONFIG.md

`alred` で利用する設定ファイル、環境変数、入力フォーマットの一覧です。  
設定値の優先順位や、各コマンドで参照される補助ファイルもここにまとめています。

## 1. 設定の優先順位

基本的な優先順位は次の通りです。

1. CLI オプション
2. コマンドごとの補助設定ファイル
3. 環境変数 (`.env`)
4. コード内デフォルト

例:

- `collect -u` / `--user` / `--username` と `--password` > `ALRED_USERNAME` / `ALRED_PASSWORD`
- `collect --ask-pass` (`-k`) で入力した SSH パスワード > `ALRED_PASSWORD`
- `collect --ask-become-pass` (`-K`) で入力した enable パスワード > `ALRED_ENABLE_SECRET`
- `collect` / `push-config` / `check-clab-startup-config` などの `--user` / `--password` > `clab_credentials.yaml` > `ALRED_USERNAME` / `ALRED_PASSWORD`
- `collect -i` / `--inventory` / `--hosts` > `./hosts.yaml`
- `collect --output` > `ALRED_RAW_DIR` > `ALRED_OUTPUT_DIR` (legacy)
- `--log-file` > `ALRED_LOG_DIR`

## 1.1. 認証情報ファイル (`clab_credentials.yaml`)

`collect` / `collect-clab` / `collect-all` / `check-logging` / `generate-vni-config` / `push-config` / `push-config-dir` / `write-memory` / `check-clab-startup-config` では、`--credentials` で認証情報 YAML を指定できます。未指定で `./clab_credentials.yaml` が存在する場合は自動で読み込みます。

解決順序:

1. CLI オプション (`--user` / `--password` / `--ask-pass` / `--enable-secret`)
2. `hosts.<hostname>`
3. `device_type.<device_type>`
4. `defaults`
5. 環境変数 (`ALRED_USERNAME` / `ALRED_PASSWORD` など)

例:

```yaml
credentials:
  defaults:
    username: admin
    password: admin
  device_type:
    nxos:
      username: admin
      password: admin
    eos:
      username: admin
      password: admin
    nokia_srlinux:
      username: admin
      password_env: CLAB_SRLINUX_PASSWORD
  hosts:
    leaf01:
      username: admin
      password_env: CLAB_LEAF01_PASSWORD
```

`password_env` / `username_env` / `enable_secret_env` を指定すると、値を環境変数から読み込みます。

## 1.2. 接続確認と hostname 保護

機器へ接続する command は、既定で本処理の前に TCP、認証、enable、SSH prompt hostname を確認します。

- `--connect-check-timeout <seconds>`: 事前接続確認の timeout。既定は 3 秒
- `--skip-connect-check`: 事前接続確認を省略する。接続先 identity も事前確認できないため通常運用では使用しない
- `--allow-hostname-mismatch`: inventory hostname と SSH prompt hostname の意図した不一致を警告として許容する

prompt hostname は inventory key と大文字・小文字を含めて完全一致比較します。NX-OS の既定 hostname
`switch` は初期設定候補として警告し、read-only command は継続します。config 投入または `write-memory` では、
通常の実行確認とは別に hostname／management IP を表示して `yes` の確認を要求します。

`switch` 以外の不一致は既定で対象から除外します。`--allow-hostname-mismatch` は接続先を別手段で確認でき、
不一致が意図したものである場合だけ使用してください。`push-config-dir --force` は投入時の接続保護 filter を
解除する option であり、hostname 不一致は許容しません。

## 2. 環境変数 (`.env`)

`.env.example` をコピーして利用します。

```sh
cp .env.example .env
```

設定例:

```env
ALRED_USERNAME=admin
ALRED_PASSWORD=admin
ALRED_ENABLE_SECRET=
ALRED_FW_USERNAME=
ALRED_FW_PASSWORD=
ALRED_FW_ENABLE_SECRET=
ALRED_SSH_PORT=22
ALRED_TIMEOUT=60
ALRED_RAW_DIR=raw
ALRED_LINKS_DIR=output
ALRED_TOPOLOGY_DIR=output
ALRED_LOG_DIR=logs
ALRED_LOG_ROTATION=20
ALRED_OPERATION_ARCHIVE_AFTER_DAYS=14
```

主な項目:

- `ALRED_USERNAME`: SSH ユーザー名
- `ALRED_PASSWORD`: SSH パスワード
- `ALRED_ENABLE_SECRET`: enable 用パスワード
- `ALRED_FW_USERNAME`: `asa` / `asav` 向けの優先ユーザー名
- `ALRED_FW_PASSWORD`: `asa` / `asav` 向けの優先パスワード
- `ALRED_FW_ENABLE_SECRET`: `asa` / `asav` 向けの優先 enable パスワード
- `ALRED_SSH_PORT`: SSH ポート (default: `22`)
- `ALRED_TIMEOUT`: SSH タイムアウト秒 (default: `60`)
- `ALRED_RAW_DIR`: `collect` の既定出力先 (default: `raw`)
- `ALRED_LINKS_DIR`: `normalize-links` の既定出力先 (default: `output`)
- `ALRED_TOPOLOGY_DIR`: `generate-clab` / `generate-mermaid` / `generate-graphviz` / `generate-drawio` / `generate-doc` の既定出力先 (default: `output`)
- `ALRED_LOG_DIR`: 各コマンドの既定ログディレクトリ (default: `logs`)
- `ALRED_LOG_ROTATION`: `old/` 配下の保持世代数
- `ALRED_OPERATION_ARCHIVE_AFTER_DAYS`: `operation archive`の既定経過日数（default: `14`）。自動実行はしない
- `ALRED_OUTPUT_DIR`: 旧互換変数 (`ALRED_RAW_DIR` が未設定時のみ参照)

補足:

- archive 自体の retention は環境変数では設定せず、実行時に `--delete-older-than-days DAYS` または `--keep-latest-archives COUNT` を明示します。どちらも未指定の場合、既存 archive は削除しません
- `.env` や shell history にパスワードを残したくない場合は、`-k` / `--ask-pass` で SSH パスワードを実行時入力できます
- enable secret が必要な機器では、`-K` / `--ask-become-pass` で enable パスワードを実行時入力できます
- `asa` / `asav` は CLI 引数未指定時に `ALRED_FW_USERNAME` / `ALRED_FW_PASSWORD` / `ALRED_FW_ENABLE_SECRET` を優先して使用します
- これらが未設定の場合は、通常の `ALRED_USERNAME` / `ALRED_PASSWORD` / `ALRED_ENABLE_SECRET` を使用します
- 移行期間向けに、旧 `NW_TOOL_*` 環境変数も fallback として引き続き参照します

## 3. hosts 入力 (`hosts.txt`)

`prepare-hosts` の入力ファイルです。

```text
192.168.129.81 lfsw0101 # nxos
192.168.129.82 lfsw0102 # nxos
192.168.129.90 spsw0101 # nxos
192.168.129.89 spsw0102 # nxos
```

形式:

- `<IP> <hostname> # <device_type>`
- `# <device_type>` を省略すると `unknown`
- IP または hostname が重複するとエラー

`init-clab` 用の Linux ノードでは、コメントに `key=value` のメタデータを追加できます。

```text
192.168.129.101 server01 # linux, profile=bond, vlan=2001, ipv4=100.64.0.1/24, ipv4_gw=100.64.0.254, ipv6=fd12:0:0:1::101/64, ipv6_gw=fd12:0:0:1::1
```

`profile=bond` の Linux ノードでは、次の設定を `topology.nodes.<node>` へ追加します。

- `env.VLAN_ID`: `vlan`
- `env.IP_CIDR`: `ipv4`
- `env.DEF_GW`: `ipv4_gw`
- `env.IPV6_CIDR`: `ipv6` (任意)
- `env.DEF_GW6`: `ipv6_gw` (任意)
- `env.SET_DEFAULT_ROUTE`: `default_route`。省略時は `true`
- `binds`: 省略時 `scripts/linux:/scripts:ro`
- `exec`: 省略時 `sh -lc '/scripts/init-bond-singlevlan-route.sh'`

`key=value` を推奨します。`vlan:2001` のような単純な `key:value` も一部受け付けますが、IPv6 アドレスと紛らわしいため `=` を使ってください。

主な `device_type`:

- `nxos`
- `ios`
- `iosxe`
- `iosxr`
- `eos`
- `nokia_srlinux`
- `junos`
- `asa`
- `asav`
- `linux`

## 4. hosts インベントリ (`hosts.yaml`)

`prepare-hosts` で生成される Ansible 風フォーマットです。`collect` はこの形式を読み込みます。

```yaml
all:
  hosts:
    lfsw0101:
      ansible_host: 192.168.129.81
      device_type: nxos
      ansible_network_os: cisco.nxos.nxos
      ansible_connection: network_cli
      netmiko_device_type: cisco_nxos
```

補足:

- `clab-transform-config` はこの `ansible_host` を `mgmt.ipv4-subnet` セグメントへ変換した `hosts.lab.yaml` を生成できます

## 5. ポリシー (`policy.yaml`)

`collect --policy` で使用します。未指定時は内部デフォルトが使われます。

```yaml
include_device_types: []
include_hostname_contains: []
exclude_device_types: []
exclude_hostname_contains: []
collect_running_config_for:
  - nxos
  - ios
  - iosxe
  - iosxr
  - eos
  - nokia_srlinux
  - junos
  - asa
  - asav
```

補足:

- `nokia_srlinux` は `<hostname>_run.txt` に `info flat` を保存します
- `nokia_srlinux` は startup-config 用に、追加で `<hostname>_config.json` に `info | as json` を保存します

項目:

- `include_*`: 指定が空なら全許可
- `exclude_*`: include 判定後に除外
- `collect_running_config_for`: `show running-config` の収集対象

## 6. マッピング (`mappings.yaml`)

`normalize-links` / `generate-*` 系コマンドで利用します。

```yaml
node_name_map:
  lfsw0101: leaf01
  lfsw0102: leaf02

interface_name_map:
  Eth1/1: Ethernet1/1
  Eth1/2: Ethernet1/2

exclude_node_name_contains:
  - UNUSED

exclude_interfaces:
  - mgmt0
  - loopback0
  - vlan1
  - Port-channel
```

項目:

- `node_name_map`: ホスト名の正規化
- `interface_name_map`: インターフェース名の個別変換
- `exclude_node_name_contains`: 正規化後の endpoint node 名に含まれる文字列による link 除外（大文字・小文字を区別しない）
- `exclude_interfaces`: 除外するインターフェース名

補足:

- `Port-channel` または `port-channel` を含めると `Port-channel<number>` も広く除外します
- `exclude_node_name_contains` のいずれかに一致した node を片側に持つ link は、confirmed／candidate と diagram から除外します。空文字は指定できません
- キー名は `interface_name_map` が正です (`interface_map` ではありません)
- inventory が利用できるリンク処理では、両端の `device_type` に応じて名前を正規化します
- Linux の `Port 1` / `port1` / `eth1` は `eth1` に正規化します。データリンクでの `eth0` は管理インターフェースと衝突するため `init-clab` ではエラーです
- `interface_name_map` の完全一致は device_type 別の標準変換より優先されます

## 7. ロール定義 (`roles.yaml`)

`generate-clab` / `generate-mermaid` / `generate-tf` / `collect --show-commands-file` と `health-check --roles` で利用します。

`topology_role` は、`roles.yaml` に記載した hostname の命名規則から解決する方針です。running config は topology role の決定には使用せず、VTEP や vPC などの function の実在確認に使用します。

```yaml
schema_version: 2

role_detection:
  spine:
    priority: 2
    position_matches:
      - pos: 0
        value: sp
    functions:
      evpn-route-reflector:
        expectation: required
      underlay-route-reflector:
        expectation: optional
```

1 つの role に定義できる主な条件:

- `priority` (数値。小さいほど上位)
- `position_matches` (`pos`, `value`)
- `startswith`
- `endswith`
- `contains`

`schema_version: 2` では topology role を 1 つだけ解決します。VTEP、vPC、EVPN RR、underlay RR は独立した hostname role にせず、topology role 配下の function として `required`、`optional`、`forbidden` の期待状態を定義します。

```yaml
schema_version: 2

role_detection:
  leaf:
    contains: [lf]
    functions:
      vtep:
        expectation: required
      vpc:
        expectation: optional

function_expectation_rules:
  vpc:
    required_when:
      contains: [vpc]
```

version を省略した既存形式は `schema_version: 1` として扱い、既存機能の複数 role 判定を維持します。Health Check の role-aware scope は `schema_version: 2` のときだけ有効です。

完全な例は [roles.example.yaml](alred/sample_configs/roles.example.yaml) を参照してください。

`vtep` や `vpc` は hostname から推測する配置 role ではありません。function の期待状態は `roles.yaml` で定義し、実在と正常性は running config と show command の証跡で確認します。詳細は [Role Definition and Resolution Design](docs/design/common/ROLE_DEFINITION_AND_RESOLUTION_DESIGN.md) を参照してください。

## 8. サイト定義 (`sites.yaml`)

`health-check` の Device Summary、`generate-mermaid --group-by-site` / `generate-graphviz --group-by-site` /
`generate-drawio --group-by-site`、`generate-clab`、`init-clab` で利用します。

`--sites` を省略した場合でも、実行ディレクトリに `sites.yaml` があれば自動で読み込みます。

```yaml
site_detection:
  site-1:
    priority: 1
    startswith:
      - site1-
      - s1-

  site-2:
    priority: 1
    startswith:
      - site2-
      - s2-

  wan:
    priority: 0
    contains:
      - wan
      - dci
```

各 site に定義できる主な条件は `roles.yaml` と同じです。

- `priority` (数値。小さいほど上位。未指定は `99`)
- `position_matches` (`pos`, `value`)
- `startswith`
- `endswith`
- `contains`

利用方法:

- `generate-mermaid --group-by-site` / `generate-graphviz --group-by-site` / `generate-drawio --group-by-site` は、`labels.site` がないノードを `sites.yaml` で自動判定して site group に配置します
- site group は `priority` の小さい順に並びます。draw.io の `TD` では priority ごとに段を作り、同じ priority の site を横並びに配置します
- `generate-clab --sites sites.yaml` / `init-clab --sites sites.yaml` は、生成する `topology.nodes.<node>.labels.site` に判定結果を書き込みます
- `health-check before --sites sites.yaml` は inventory に明示 site がない host の Device Summary site を解決し、source path と hash を after／rollback 用 context に固定します
- 既に `labels.site` がある場合は、その値を優先し、`sites.yaml` では上書きしません

## 9. Description ルール (`description_rules.yaml`)

`normalize-links --description-rules` で利用します。

```yaml
description_rules:
  - name: hostname_interface_space
    regex: '(?P<remote_host>...)(?P<remote_if>...)'
```

注意:

- `regex` には `remote_host` の名前付きキャプチャを含めてください
- `remote_if` は任意です。ホスト名のみを拾いたい場合は `remote_host` だけのルールでも構いません
- 同梱 example は `MGMT`、`mgmt`、`vPC-peer-link`、`vpc-peer-link` を interface token として扱います。これらの文字列だけの description は remote hostname として扱いません

## 10. show commands (`show_commands.txt`)

`collect --show-commands-file` で利用する追加 show コマンド定義ファイルです。

単純な例:

```text
[all]
show version
show interface status
show ip route summary
```

グループ指定の例:

```text
[all]
show clock

[device_type:nxos]
show version

[spine]
show interface status

[leaf]
show port-channel summary

[lfsw0101]
show version
```

指定方法:

- `[all]`: 全ホスト共通
- `[device_type:nxos]`: 機種別
- `[spine]`: role 名
- `[hostname]`: 個別ホスト名

実行例:

```sh
uv run python alred.py collect \
  --hosts hosts.yaml \
  --roles roles.yaml \
  --show-commands-file show_commands.txt
```

関連オプション:

- `--show-commands-file`: コマンド定義ファイル
- `--show-hosts`: 追加コマンド実行対象ホスト (カンマ区切り)
- `--show-read-timeout`: 追加コマンドの `read_timeout` 秒数 (default: `120`)
- `--show-only`: LLDP / running-config を収集せず、追加コマンドのみ実行

主な出力:

- `<ALRED_RAW_DIR>/show_lists/`
- `<ALRED_RAW_DIR>/show_lists/<hostname>/<hostname>_<command>_<YYYYMMDD-HHMMSS>.json` (NX-API JSON が取得できた場合)

## 11. containerlab マージ設定

`generate-clab` と `generate-doc` の clab 出力では、生成結果へ YAML をマージできます。

項目:

- `--clab-merge`: 共通のマージ用 YAML
- `--clab-lab-profile`: lab / server 固有設定用 YAML (`--clab-merge` の後にマージ)

例:

```yaml
name: dc-fabric-lab
mgmt:
  network: clab-mgmt
  ipv4-subnet: 192.168.129.0/24
topology:
  kinds:
    cisco_n9kv:
      image: ghcr.io/srl-labs/n9kv:latest
```

マージルール:

- 辞書同士は再帰的にマージ
- それ以外の値 (文字列・配列など) は後勝ちで上書き
- `topology.links` は追加マージ (generated links の後ろに merge 側 links を連結)
- `clab-transform-config` は `--clab-env` で指定した Containerlab YAML の `mgmt.ipv4-subnet` だけを参照し、`hosts.lab.yaml` と `raw/labconfig/<hostname><suffix>` の管理 IP を変換します。同じ YAML の `topology.kinds`、image、bind mount などはこの command の出力へ merge しません。`--file-suffix` の既定は `_run.txt` です
- `clab-transform-config`は`--lab-parameters`の`LabTransformParameters`を検証し、未指定時もbuilt-in safety policyでproduction user、AAA、SNMP、NTP、remote logging、DNS、certificate／key、management access classを除去します
- lab userは`lab_users.users[].authentication.password_ref`と同名の環境変数から解決します。secret本文はparameterやManifestへ記載しません
- NX-OSでは共通`privilege: admin|read-only`を`network-admin|network-operator`へ変換します。lab user指定時は`primary: true`を1件だけ必要とします
- bootstrap `admin:admin`は`bootstrap_user.action: preserve`で既定保持し、production source config由来の同名userとは分離します
- `--delete-username` を指定すると、containerlab イメージのデフォルト認証を維持するため、NX-OS startup-config から全 `username` 行と全 `snmp-server user` 行を削除します。このモードでは認証情報が指定されていてもラボユーザーを追加しません
- `--delete-access-class` を指定すると、NX-OSの `line vty` セクション内にある `access-class` と `ipv6 access-class` 行を削除します。`line console` や、VTY内のその他の設定は変更しません
- `--node-map` では `source_hostname,source_mgmt_ip,target_hostname,target_mgmt_ip` のCSVを指定できます。`prd_hostname,prd_mgmt_ip,lab_hostname,lab_mgmt_ip` も互換ヘッダーとして受け付けます
- node mapは `hostname`、同名の `vdc`、interface description内のホスト名、`interface mgmt0`、`vpc domain` の `peer-keepalive`、`hosts.lab.yaml` のホストキーと `ansible_host`、labconfigの出力ファイル名へ適用されます
- 管理IPはCSVの `source_mgmt_ip` → `target_mgmt_ip` を先に適用し、変換後のIPが `mgmt.ipv4-subnet` 外なら、そのホスト部を維持して指定サブネットへさらに変換します。inventoryにはsource / targetホスト名のどちらも利用でき、source、target、サブネット変換後の対応する管理IPと一致しない場合、重複したホスト名/IP、source / targetホストのどちらもinventoryに存在しない場合はエラーです
- `--cables` を指定すると、変換後のinterface descriptionをケーブル表と比較し、descriptionの欠落、解析不能、対向ノードまたは対向インターフェースの不一致をwarningとして出力します。比較には `--mappings` と `--description-rules` を利用できます

### cisco_n9kv startup-delay

`generate-clab` / `init-clab` / `generate-doc` では、`kind: cisco_n9kv` ノードに段階的な `startup-delay` を追加できます。

```sh
alred generate-clab \
  --input output/links_confirmed.csv \
  --hosts hosts.yaml \
  --n9kv-startup-delay 5,600
```

`--n9kv-startup-delay BATCH,SECONDS` の形式で指定します。

- `5,600` は5台ごとに600秒ずつ遅らせます
- 1-5台目: `startup-delay` なし
- 6-10台目: `startup-delay: 600`
- 11-15台目: `startup-delay: 1200`
- 既に `startup-delay` が指定済みのノードは上書きしません

互換エイリアスとして `--startup-delay-nxos` も利用できます。

## 12. 新規 lab ケーブル結線表 (`clab_cables.csv`)

`init-clab --cables` で利用します。UTF-8 の CSV とし、ヘッダーは必須です。
配布サンプルの `init_clab_hosts.example.txt` と `clab_cables.example.csv` は対応する組み合わせです。

```text
src_node,src_if,dst_node,dst_if,enabled,description
```

必須列:

- `src_node` / `src_if`: ケーブルの一方のノードとインターフェース
- `dst_node` / `dst_if`: もう一方のノードとインターフェース

任意列:

- `enabled`: 省略時は `true`。`false` / `no` / `0` / `off` の行は生成対象外
- `description`: 確認用の説明。topology YAML には出力しません

`src` と `dst` に通信方向の意味はありません。ノード名とインターフェース名は正規化後に重複を判定します。

```csv
src_node,src_if,dst_node,dst_if,enabled,description
leaf01,Eth1/1,spine01,Eth1/1,true,underlay link
server01,Port 1,leaf01,Eth1/10,true,server connection
leaf01,Eth1/20,leaf02,Eth1/20,false,reserved
```

`init-clab` の設定適用順序は次の通りです。後に適用される設定を優先します。

```text
自動生成 < --clab-env < --clab-merge < --clab-lab-profile
```

Linuxノードが存在し、mergeするYAMLにimage指定がない場合は次の既定値を設定します。

```yaml
topology:
  kinds:
    linux:
      image: ghcr.io/hellt/network-multitool:latest
```

エラーとして生成を停止する項目:

- 必須列・必須値の欠落、不正な `enabled`
- `hosts.txt` に存在しないノード、自己接続
- 正規化後のリンク重複、同一 endpoint の複数使用
- Linux データリンクでの `eth0` 使用
- 管理 IPv4 の不正、重複、subnet 外、network/broadcast アドレス
- `mgmt.ipv4-range` が `mgmt.ipv4-subnet` の外側

警告して生成を継続する項目:

- `hosts.txt` に存在するが結線されていないノード
- 未対応または `unknown` の `device_type`
- 静的管理 IP と動的割当用 `mgmt.ipv4-range` の重複
- 未知の CSV 列、除外対象インターフェース

出力:

- `output/topology.clab.yaml`: containerlab topology YAML (`--validate-only` では生成しません)
- `output/links_design_normalized.csv`: 変換前後のendpointを含む確認用CSV
- `output/init_clab_validation.md`: エラー・警告レポート

## 13. Linux サーバ CSV (`clab_linux_server.csv`)

`generate-clab --linux-csv` で利用します。

CSV ヘッダ:

```text
hostname,VLAN_ID,IP_CIDR,DEF_GW,IPV6_CIDR,DEF_GW6,LEAF1,LEAF1_IF,LEAF2,LEAF2_IF
```

生成内容:

- `nodes.<hostname>` に `kind: linux` / `env` / `binds` / `exec` / `group: server`
- `LEAF1` / `LEAF2` から `eth1` / `eth2` への links

## 14. Kind クラスタ CSV (`clab_kind_cluster.csv`)

`generate-clab --kind-cluster-csv` で利用します。

CSV ヘッダ:

```text
cluster,hostname,VLAN_ID,IP_CIDR,DEF_GW,ROUTES4,IPV6_CIDR,DEF_GW6,ROUTES6,LEAF1,LEAF1_IF,LEAF2,LEAF2_IF
```

生成内容:

- `nodes.<cluster>` に `kind: k8s-kind` / `startup-config` / `extras.k8s_kind`
- `nodes.<cluster>-<hostname>` に `kind: ext-container` / `binds` / `exec`
- `LEAF1` / `LEAF2` から `eth1` / `eth2` への links

## 15. 構成図入力形式

`generate-mermaid` / `generate-graphviz` / `generate-drawio` は `--input-format auto` が既定です。

- `.yaml` / `.yml` は containerlab topology YAML として読み込みます
- それ以外は正規化済み links CSV として読み込みます
- 明示する場合は `--input-format csv` または `--input-format clab` を指定します

containerlab topology YAML 入力では、次の値を利用します。

- `topology.links[*].endpoints`: Mermaid のリンク
- `topology.nodes`: Mermaid に表示するノード。リンクがないノードも表示します
- `topology.nodes.<node>.mgmt-ipv4`: mgmt 表示
- `topology.nodes.<node>.group`: `--group-by-role` 指定時の group 名
- `topology.nodes.<node>.labels.site`: `--group-by-site` 指定時の site group 名
- `topology.nodes.<node>.labels.domain`: `--group-by-site` 指定時の domain group 名。`site` がない場合に利用します
- `topology.nodes.<node>.labels.alred.site` / `labels.alred.domain`: namespaced にしたい場合の代替
- `topology.nodes.<node>.extras.alred.site` / `extras.alred.domain`: labels を使わない場合の代替
- `topology.nodes.<node>.kind`: device_type 推定。例: `cisco_n9kv` は `nxos` 相当、`linux` は `linux`

例:

```sh
alred generate-mermaid \
  --input output/topology.clab.yaml \
  --group-by-site \
  --group-by-role \
  --output output/topology.md
```

EVPN Multisite のように WAN/DCI と複数サイトを表現したい場合は、site/domain と role を分けて定義します。

```yaml
topology:
  nodes:
    site1-bgw01:
      kind: cisco_n9kv
      group: border-gateway
      labels:
        site: site-1
    wan01:
      kind: cisco_n9kv
      group: wan
      labels:
        site: wan
    site2-bgw01:
      kind: cisco_n9kv
      group: border-gateway
      labels:
        site: site-2
```

## 16. Mermaid underlay 表示設定 (`underlay_render.yaml`)

`generate-mermaid` / `generate-doc` で `--underlay` を使うと、対象ノードの表示を `mgmt` から underlay loopback に切り替えられます。

設定例:

```yaml
target_roles:
  - super-spine
  - spine
  - leaf
  - border-gateway
vrf: default
interfaces:
  - name: loopback0
    label: lo0
    vrf: default
  - name: loopback1
    label: lo1
    vrf: default
```

項目:

- `target_roles`: 適用対象 role
- `vrf`: loopback の `vrf member` (`default` は vrf 指定なしを意味)
- `interfaces`: 参照する loopback インターフェース群
- `interfaces[].name`: インターフェース名
- `interfaces[].label`: Mermaid 表示ラベル
- `interfaces[].vrf`: そのインターフェースを評価する VRF (省略時は上位 `vrf`)

## 17. `push-config-dir` 接続保護

NX-OS の `push-config-dir` は、接続中の login user、management VRF、`interface mgmt0`、`line vty` を
既定で投入対象から除外します。`--exclude-protected-config` で同じ安全動作を明示できます。`--force` は
この接続保護 filter だけを解除します。入力 file の section は
元のインデントまたは `!` 境界を維持してください。

対象 command、投入前表示、`--force` の維持される安全機能は
[push-config-dir Guide](./docs/manual/network-ops/10_PUSH_CONFIG_DIR.md)を参照してください。正式仕様は
[Direct Config Push and Save Design](./docs/design/network-ops/DIRECT_CONFIG_PUSH_AND_SAVE_DESIGN.md#33-nx-os-接続保護-filter)
を正本とします。

## 18. 関連ドキュメント

- 利用手順と主要コマンド: [README.md](./README.md)
- 設定値や入力ファイルの詳細: この `CONFIG.md`

## Route Diff の standalone 入力

`route-diff-nxos` は `--before` / `--after` / `--input-format`、または `--source-map` を指定します。
`--before` / `--after` は両側 file または両側 directory に対応します。directory は `nxos-transcript` を指定し、
直下の `.log` / `.txt` をホスト名で対応付けます。子 directory は `--recursive` で含めます。
重複取得は自動選択せず、片側欠落は UNKNOWN として残します。
Source Map 内の相対 path は YAML のある directory が基準です。2 file 形式と Source Map は併用しません。
本文形式は `--host` / `--command-id`、指定 VRF command は `--command-vrf` も必要です。
`--af`（既定 `both`）と繰り返し指定できる `--vrf` は比較対象を指定します。
`--policy` は正常性の条件、`--review` は確認記録、`--before-label` / `--after-label` は表示名です。
出力は `--output-dir`（既定 `./route_diff`）へ保存し、`ALRED_OUTPUT_DIR` は参照しません。
認証情報・inventory・active Health operation は参照しません。
詳細は [Route Diff 利用ガイド](docs/manual/network-ops/13_ROUTE_DIFF_GUIDE.md)を参照してください。

Health では before の `--profile route-diff-nxos` で詳細比較を追加します。baseline と併用する場合は
`--profile network-baseline-nxos` も指定します。追加 YAML profile の `spec.route_diff` で
`families`（既定 `[ipv4, ipv6]`）、`vrfs`（既定 `[]`）、inline `policy` を固定し、after / rollback が継承します。
設定例と保存先は [利用ガイド](docs/manual/network-ops/13_ROUTE_DIFF_GUIDE.md#62-比較範囲と必須経路を追加する)を参照してください。
