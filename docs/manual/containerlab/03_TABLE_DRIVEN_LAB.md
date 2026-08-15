# 結線表から新規 Lab を生成

本手順は、再現元となる商用環境や Evidence Package がない状態で、`hosts.txt` と cable CSV を設計入力として
Containerlab の新規 lab を一から作成する場合に使用する。実機への接続、情報収集、既存環境の config 再現は行わない。

商用環境を収集した Evidence Package から再現用 lab を生成する場合は
[Evidence Package Quick Start](01_QUICK_START.md)を使用する。

## 1. 入力例

`hosts.txt`:

```text
172.20.20.11 leaf01 # nxos
172.20.20.12 leaf02 # nxos
172.20.20.21 server01 # linux, profile=bond, vlan=2001, ipv4=100.64.0.1/24
```

`clab_cables.csv`:

```csv
src_node,src_if,dst_node,dst_if,enabled,description
leaf01,Eth1/1,leaf02,Eth1/1,true,peer link
server01,Port 1,leaf01,Eth1/10,true,server connection
```

## 2. Validation

```bash
alred init-clab \
  --hosts hosts.txt \
  --cables clab_cables.csv \
  --mappings mappings.yaml \
  --roles roles.yaml \
  --sites sites.yaml \
  --validate-only \
  --output-normalized output/links_design_normalized.csv \
  --validation-report output/init_clab_validation.md
```

未知 node、自己 link、endpoint 重複、管理 IP 重複などは error である。未接続 node や未知 device type は warning として
report へ残る。

## 3. 生成

```bash
alred init-clab \
  --hosts hosts.txt \
  --cables clab_cables.csv \
  --clab-env clab_merge.yaml \
  --mappings mappings.yaml \
  --roles roles.yaml \
  --sites sites.yaml \
  --group-by-role \
  --n9kv-startup-delay 5,600 \
  --output output/topology.clab.yaml \
  --output-normalized output/links_design_normalized.csv \
  --validation-report output/init_clab_validation.md
```

disabled row は normalized CSV へ残るが topology link にはならない。生成後も validation report を成果物と一緒に
保持する。

## 4. 任意の外部 runtime 操作

生成した Topology を確認後、必要に応じて Containerlab CLI で deploy する。

```bash
containerlab deploy -t output/topology.clab.yaml
```

alred はこの command を自動実行しない。NX-OS 9000v の起動方法と boot 後の config 投入を追加する場合は、
[NX-OS Boot and Config Push](05_NXOS_BOOT_AND_CONFIG_PUSH.md)を参照する。
