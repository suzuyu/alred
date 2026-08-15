# Containerlab Quick Start Sample

この directory は、Quick Start で生成する主要成果物の対応例である。すべての hostname、address、設定値は
documentation 用に作成した架空値であり、実機から取得した credential や secret は含まない。

## 変換前後の対応

| 内容 | Sample |
|---|---|
| 変換元 inventory | [hosts.source.example.yaml](hosts.source.example.yaml) |
| 変換 parameter | [lab-transform-parameters.example.yaml](lab-transform-parameters.example.yaml) |
| 変換前 NX-OS config | [source-config/](source-config/) |
| 変換後 lab config | [labconfig/](labconfig/) |
| 代表差分 | [transformation.example.diff](transformation.example.diff) |
| 変換 Manifest | [lab-transform-manifest.example.yaml](lab-transform-manifest.example.yaml) |
| lab inventory | [hosts.lab.example.yaml](hosts.lab.example.yaml) |
| Containerlab Topology | [topology.clab.example.yaml](topology.clab.example.yaml) |
| role rule | [roles.example.yaml](roles.example.yaml) |

`source-config/` と `labconfig/` は hostname ごとに対応する。変換例では production の NTP server、remote logging、
DNS、AAA、管理 access-list、local user を除去または lab-local 値へ置換し、interface、description、Underlay address を
維持している。`transformation.example.diff` は `site1-leaf01` の代表差分である。

`topology.clab.example.yaml` の image 名は説明用であり、そのまま deploy するための実在 image ではない。
`startup-config` は出力せず、NX-OS 9000v の起動確認後に `clab-apply-config` で `labconfig/` を投入する前提である。
`roles.example.yaml` は現在の推奨形式である `schema_version: 2` を使用する。

この sample は secret scan と schema validation に加え、変換処理の golden test で変換後 config と Manifest hash の
一致を確認する。実際の Evidence Package では、Package の disclosure policy と secret scan 結果も必ず確認する。
