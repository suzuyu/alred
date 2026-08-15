# Preparation

## 1. 実行前確認

```bash
alred --version
alred collect-clab --help
alred init-clab --help
```

source checkoutでは`alred`を`uv run python alred.py`へ置き換える。

既存ネットワークから生成する場合はread-onlyで機器へ接続する。対象host、実行時間、収集先、credentialを
事前に確認する。通常の収集は設定を変更しないが、生成rawには商用構成と管理addressが含まれる。

## 2. 主な入力

| file | 用途 |
|---|---|
| `hosts.txt` | IP、hostname、device typeの簡易入力 |
| `hosts.yaml` | 収集用inventory |
| `policy.yaml` | 収集対象のinclude／exclude |
| `mappings.yaml` | hostname／interface正規化と除外 |
| `description_rules.yaml` | interface descriptionから対向endpointを抽出 |
| `roles.yaml` | node roleとgroup |
| `sites.yaml` | site分類 |
| `clab_merge.yaml` | management subnet、kind、image等のmerge |
| `clab_lab_profile.yaml` | lab固有の最終override |
| `clab_node_map.csv` | 商用node／管理IPからlab値へのmapping |
| `clab_cables.csv` | table-driven linkまたはdescription確認 |

形式と優先順位は[CONFIG.md](../../../CONFIG.md)を参照する。

## 3. Inventory作成

```text
192.0.2.11 leaf01 # nxos
192.0.2.12 leaf02 # nxos
192.0.2.21 spine01 # nxos
```

```bash
alred prepare-hosts --input hosts.txt --output hosts.yaml
```

## 4. Credential

CLI入力、`clab_credentials.yaml`、環境変数の順序は
[Inventory and Device Access Design](../../design/common/INVENTORY_CREDENTIALS_AND_DEVICE_ACCESS_DESIGN.md)を
正本とする。passwordをshell historyへ残さない場合は`--ask-pass`を使用する。

収集用の商用credentialとlab node用credentialは別管理を推奨する。`clab-transform-config`は解決した
credentialをNX-OS startup configのlab userへ使用する場合があるため、実行前に`--delete-username`を含む
変換方針を確認する。

## 5. 対応範囲

startup config変換の正式対象はNX-OSである。alredはcontainerlab topologyとstartup artifactを生成するが、
image取得、license、container runtime、`containerlab deploy`／destroyを所有しない。
