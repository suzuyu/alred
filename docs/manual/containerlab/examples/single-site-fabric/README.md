# Single-site Fabric Sample

この directory は、実際に起動確認した single-site の NX-OS Fabric 構成を基に、documentation 用へ整理した
実用規模 sample である。最小手順を確認する 4 node sample は
[Containerlab Quick Start Sample](../quick-start/README.md) を使用する。

本 sample は 22 node／40 link で構成する。`hosts.lab.example.yaml` と NX-OS config の対象は Network Device 8 台、
Topology の対象は対向 server と Kind node を含む 22 台である。この差は意図した inventory scope の違いである。

| Role | Node 数 | Config 投入 |
|---|---:|---|
| Spine | 2 | 対象 |
| Leaf | 4 | 対象 |
| Network Function | 2 | 対象 |
| Linux server | 6 | 対象外 |
| Kind cluster／external container | 8 | 対象外 |

## 1. Sample の対応

| 内容 | Sample |
|---|---|
| 変換元 inventory | [hosts.source.example.yaml](hosts.source.example.yaml) |
| site 判定 rule | [sites.example.yaml](sites.example.yaml) |
| role 判定 rule | [roles.example.yaml](roles.example.yaml) |
| Evidence Package の `sanitized` 相当 config | [source-config/](source-config/) |
| Lab 変換 parameter | [lab-transform-parameters.example.yaml](lab-transform-parameters.example.yaml) |
| 変換後 config | [labconfig/](labconfig/) |
| Lab inventory | [hosts.lab.example.yaml](hosts.lab.example.yaml) |
| 変換 Manifest | [lab-transform-manifest.example.yaml](lab-transform-manifest.example.yaml) |
| Containerlab Topology | [topology.clab.example.yaml](topology.clab.example.yaml) |
| Containerlab runtime 依存 file | [runtime/](runtime/) |
| Secret Mask の構文例 | [secret-mask-example/](secret-mask-example/) |
| Mermaid／Underlay／draw.io | [Topology Single-site Fabric Sample](../../../topology/examples/single-site-fabric/README.md) |

## 2. Site と hostname

`adc-*` は A Data Center を表す documentation 用 hostname である。既定では `sites.example.yaml` の命名規則から
`site=adc` を解決する。将来の複数 site 例として `bdc-*`、`cdc-*` と、WAN node の `p01*`／`pe*` も定義する。
Containerlab node や inventory に明示的な `site`／`labels.site` がある場合は明示値を優先し、命名規則で上書きしない。
WAN の priority は `10`、Data Center は同じ `100` とし、draw.io `TD` では同じ priority の Data Center を横並びにする。
本 single-site topology に含まれる node は `adc-*` だけであり、rule の追加だけでは `bdc`／`cdc` node を生成しない。

## 3. Address plan

すべて lab 内で使用する address であり、外部到達性を前提としない。

| Prefix | 用途 |
|---|---|
| `192.168.0.0/16` | Lab management address の管理 pool |
| `192.168.129.0/24` | 本 sample の Containerlab external management segment |
| `10.0.0.0/24` | Router ID／Loopback |
| `10.0.1.0/24`、`10.0.2.0/24` | VTEP Loopback |
| `10.0.3.0/24`、`10.0.4.0/24` | Spine–Leaf Underlay |
| `172.16.0.0/16` | Tenant 1 segment |
| `172.17.0.0/16` | Tenant 2 segment |
| `100.64.0.0/24` | Lab 内 controller／service segment |
| `fd12::/16`、`fd21::/16`、`fd22::/16` | Lab 内 IPv6 ULA segment |

`100.64.0.0/10` は RFC 1918 private address ではなく shared address space である。本 sample では外部へ広告しない
隔離 lab 用途に限定する。利用環境の既存 address と重複する場合は、Topology、config、変換 parameter を同じ世代で変更する。

`source-config/` と `labconfig/` の `interface mgmt0` section は、parser、変換、投入前保護の試験対象とするため
有効な config として収容する。投入時の接続断回避は config をコメントアウトして表現せず、
`clab-transform-config` による lab management address への変換と、config 投入機能の管理経路保護で扱う。

## 4. Secret の扱い

実際の取得 config と credential は repository へ収容していない。`source-config/` は Secret Scan 後の
Evidence Package `sanitized` config 相当であり、credential-bearing command は値を残さず
`! REDACTED <rule-id>` へ置換している。

`secret-mask-example/input.example.txt` は scanner の positive match を説明するための非実行 fragment である。
値はすべて `DOCS_ONLY_*` の synthetic sentinel であり、実際の credential ではない。username password、username
passphrase、SNMP user auth／priv、SNMP community、SNMP v1／v2c trap host community が、
`output.example.txt` の value-free marker へ変換される対応を示す。

Containerlab の NX-OS 9000v bootstrap credential `admin:admin` は runtime の初期接続条件であり、source config へ
password や hash を埋め込まない。変換 parameter は `bootstrap_user.action: preserve` とし、LabTransformManifest に
確認 warning を残す。

## 5. Config 変換を再現

repository root から次を実行する。実機や Containerlab node へは接続しない。

```bash
alred clab-transform-config \
  --hosts docs/manual/containerlab/examples/single-site-fabric/hosts.source.example.yaml \
  --input docs/manual/containerlab/examples/single-site-fabric/source-config \
  --lab-parameters docs/manual/containerlab/examples/single-site-fabric/lab-transform-parameters.example.yaml \
  --output-hosts docs/manual/containerlab/examples/single-site-fabric/hosts.lab.example.yaml \
  --output-dir docs/manual/containerlab/examples/single-site-fabric/labconfig \
  --manifest-output docs/manual/containerlab/examples/single-site-fabric/lab-transform-manifest.example.yaml
```

変換後は production 由来の logging、DNS、AAA、SNMP、management access-list を除去し、NTP を lab-local address へ
complete-set replacement する。`interface mgmt0` は inventory の lab management address へ変換し、data plane の
interface、description、VLAN、VRF、BGP、OSPF、NVE、VPC は保持する。

## 6. 起動と Config 投入

Topology の相対 path を解決するため、sample directory へ移動して起動する。Cisco NX-OS image と license は同梱しない。

```bash
cd docs/manual/containerlab/examples/single-site-fabric
containerlab deploy -t topology.clab.example.yaml
cd -
```

Cisco NX-OS node には `startup-config` を設定していない。Docker health と node ごとの `startup-delay` を確認後、
repository root から変換 Manifest 固定で投入する。

```bash
alred clab-apply-config \
  --topology docs/manual/containerlab/examples/single-site-fabric/topology.clab.example.yaml \
  --hosts docs/manual/containerlab/examples/single-site-fabric/hosts.lab.example.yaml \
  --lab-transform-manifest docs/manual/containerlab/examples/single-site-fabric/lab-transform-manifest.example.yaml \
  --workers 1 \
  --fail-fast
```

`runtime/` には Topology が直接参照する Kind YAML と network interface 初期化 script だけを収容する。MetalLB などの
追加 workload manifest は Containerlab topology の再現条件ではないため、本 sample には含めない。
