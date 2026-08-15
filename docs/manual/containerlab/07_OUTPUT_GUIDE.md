# Output Guide

## 1. 主な成果物

| path | 内容 | 取扱い |
|---|---|---|
| `raw/lldp/` | 商用機器のLLDP raw | 機密、commit禁止 |
| `raw/config/` | 商用running config | 高機密、commit禁止 |
| `evidence-packages/<package-id>.tar.gz` | Manifest 選択済みの搬送 archive | Secret Scan status と外部 checksum を確認 |
| `imported-evidence/<package-id>/` | verify 後に展開した Package | Package Manifest 外の file を入力にしない |
| `raw/labconfig/` | NX-OS boot 後の投入用 config | lab secret を含み得る |
| `raw/lab-transform-manifest.yaml` | config 変換の source／output hash、warning、risk | device 集合と risk finding を確認 |
| `hosts.lab.yaml` | lab 用 inventory | 管理 IP、`os_type`、Ansible／Netmiko の transport metadata を確認 |
| `output/links_confirmed.csv` | 採用可能なcanonical link | warningとconfidenceを確認 |
| `output/links_candidates.csv` | 証拠不足link | 自動採用しない |
| `output/topology.clab.yaml` | containerlab topology | image、bind、NX-OS `startup-config`の有効／無効を確認 |
| `output/links_design_normalized.csv` | table-driven正規化結果 | source／normalized endpointを確認 |
| `output/init_clab_validation.md` | validation report | error 0件を生成gateにする |
| `output/clab-set-cmds/attempts/<attempt-id>/pipeline-manifest.yaml` | source、step 状態、error、主要 output hash | `SUCCESS`／`FAILED`／`INTERRUPTED` と失敗 step を確認 |
| `output/clab-set-cmds/current.json` | 最新の完全成功 Pipeline | Manifest hash と current output hash を照合 |

## 2. 公開前確認

- sourceと生成先のhostname／management IPが期待どおりか
- missing source configがないか
- `evidence-package inspect`／`evidence-package verify` の `secret_scan_status`、high／low 件数、`secret_scan_declared` を確認したか
- Packageのarchive外checksumを検証したか
- `LabTransformManifest` の device 数、source／output hash、warning、risk finding を確認したか
- candidateや`lldp-description-mismatch`を確認したか
- topologyのnode、kind、image、startup-config pathが正しいか
- NX-OS 9000v を boot 後投入する場合、有効な`startup-config` field が残っていないか
- production password、secret、SNMP community、production endpointが残っていないか
- `send-community` と `no password strength-check` など、保持対象の非 secret command が欠落していないか
- 部分生成物と以前の成功成果物を混在させていないか

`clab-set-cmds` は成功・失敗・中断を Pipeline Manifest へ保存するが、各 step の共有 output directory を一括で
切り替えない。同じ directory にあるという理由だけで全 file を同一実行世代とみなさず、最新成功 Manifest の hash と
current file を照合する。失敗 Manifest の `outputs[].disposition` は、今回の `created`／`modified` と、開始前から変わらない
`unchanged_existing` を区別する。
