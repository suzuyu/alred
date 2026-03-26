# CONFIG.md

`alred` で利用する設定ファイル、環境変数、入力フォーマットの一覧です。  
設定値の優先順位や、各コマンドで参照される補助ファイルもここにまとめています。

## 1. 設定の優先順位

基本的な優先順位は次の通りです。

1. CLI オプション
2. 環境変数 (`.env`)
3. コード内デフォルト

例:

- `collect --username` / `--password` > `ALRED_USERNAME` / `ALRED_PASSWORD`
- `collect --output` > `ALRED_RAW_DIR` > `ALRED_OUTPUT_DIR` (legacy)
- `--log-file` > `ALRED_LOG_DIR`

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
- `ALRED_TOPOLOGY_DIR`: `generate-clab` / `generate-mermaid` / `generate-doc` の既定出力先 (default: `output`)
- `ALRED_LOG_DIR`: 各コマンドの既定ログディレクトリ (default: `logs`)
- `ALRED_LOG_ROTATION`: `old/` 配下の保持世代数
- `ALRED_OUTPUT_DIR`: 旧互換変数 (`ALRED_RAW_DIR` が未設定時のみ参照)

補足:

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

主な `device_type`:

- `nxos`
- `ios`
- `iosxe`
- `iosxr`
- `eos`
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
  - junos
```

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

exclude_interfaces:
  - mgmt0
  - loopback0
  - vlan1
  - Port-channel
```

項目:

- `node_name_map`: ホスト名の正規化
- `interface_name_map`: インターフェース名の個別変換
- `exclude_interfaces`: 除外するインターフェース名

補足:

- `Port-channel` または `port-channel` を含めると `Port-channel<number>` も広く除外します
- キー名は `interface_name_map` が正です (`interface_map` ではありません)

## 7. ロール定義 (`roles.yaml`)

`generate-clab` / `generate-mermaid` / `generate-tf` / `collect --show-commands-file` で利用します。

```yaml
role_detection:
  spine:
    priority: 2
    position_matches:
      - pos: 0
        value: sp
```

1 つの role に定義できる主な条件:

- `priority` (数値。小さいほど上位)
- `position_matches` (`pos`, `value`)
- `startswith`
- `endswith`
- `contains`

補助 role を追加して、同じ機器に複数 role をマッチさせることもできます。

```yaml
role_detection:
  spine:
    priority: 2
    position_matches:
      - pos: 0
        value: sp

  underlay-route-reflector:
    priority: 2
    position_matches:
      - pos: 0
        value: sp
```

この場合:

- `[spine]` と `[underlay-route-reflector]` の両方の show command が適用されます
- `generate-mermaid --underlay` / `generate-doc --underlay` では該当ノードのラベル先頭に `(BGP-RR)` を表示します

## 8. Description ルール (`description_rules.yaml`)

`normalize-links --description-rules` で利用します。

```yaml
description_rules:
  - name: hostname_interface_space
    regex: '(?P<remote_host>...)(?P<remote_if>...)'
```

注意:

- `regex` には `remote_host` の名前付きキャプチャを含めてください
- `remote_if` は任意です。ホスト名のみを拾いたい場合は `remote_host` だけのルールでも構いません

## 9. show commands (`show_commands.txt`)

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

## 10. containerlab マージ設定

`generate-clab` と `generate-doc` の clab 出力では、生成結果へ YAML をマージできます。

項目:

- `--clab-merge`: 共通のマージ用 YAML
- `--clab-lab-profile`: lab / server 固有設定用 YAML (`--clab-merge` の後にマージ)

例:

```yaml
name: dc-fabric-lab
mgmt:
  network: clab-mgmt
topology:
  kinds:
    cisco_n9kv:
      image: ghcr.io/srl-labs/n9kv:latest
```

マージルール:

- 辞書同士は再帰的にマージ
- それ以外の値 (文字列・配列など) は後勝ちで上書き
- `topology.links` は追加マージ (generated links の後ろに merge 側 links を連結)

## 11. Linux サーバ CSV (`clab_linux_server.csv`)

`generate-clab --linux-csv` で利用します。

CSV ヘッダ:

```text
hostname,VLAN_ID,IP_CIDR,DEF_GW,IPV6_CIDR,DEF_GW6,LEAF1,LEAF1_IF,LEAF2,LEAF2_IF
```

生成内容:

- `nodes.<hostname>` に `kind: linux` / `env` / `binds` / `exec` / `group: server`
- `LEAF1` / `LEAF2` から `eth1` / `eth2` への links

## 12. Kind クラスタ CSV (`clab_kind_cluster.csv`)

`generate-clab --kind-cluster-csv` で利用します。

CSV ヘッダ:

```text
cluster,hostname,VLAN_ID,IP_CIDR,DEF_GW,ROUTES4,IPV6_CIDR,DEF_GW6,ROUTES6,LEAF1,LEAF1_IF,LEAF2,LEAF2_IF
```

生成内容:

- `nodes.<cluster>` に `kind: k8s-kind` / `startup-config` / `extras.k8s_kind`
- `nodes.<cluster>-<hostname>` に `kind: ext-container` / `binds` / `exec`
- `LEAF1` / `LEAF2` から `eth1` / `eth2` への links

## 13. Mermaid underlay 表示設定 (`underlay_render.yaml`)

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

## 14. 関連ドキュメント

- 利用手順と主要コマンド: [README.md](./README.md)
- 設定値や入力ファイルの詳細: この `CONFIG.md`
