# Output and Troubleshooting

## 1. 主な成果物

| 成果物 | 内容 |
|---|---|
| `links_confirmed.csv` | 複数方向または複数sourceで裏付けられたlink |
| `links_candidates.csv` | 片方向の証拠しかないlink |
| `topology-graph.md` | `generate-network-diagram` の Mermaid topology |
| `topology_underlay.md` | `generate-network-diagram` の Mermaid Underlay |
| `topology_evpn.md` | EVPN RR／client、VTEP、session state の Mermaid |
| `evpn-control-plane-model.yaml` | EVPN node／session／diagnostic と evidence provenance |
| `evpn-session-links.csv` | review 用の正規化済み EVPN session 一覧 |
| `topology_overlay_service.md` | VRF／VNI／RT、VTEP、route leak の Mermaid |
| `overlay-service-model.yaml` | service／有向 route leak／diagnostic と evidence provenance |
| `overlay-service-links.csv` | service と有向 route leak の review 用一覧 |
| `overlay-services/*.md` | 既定 20 件または selector／option で選んだ service Markdown Detail |
| `overlay-services/*.drawio` | `--overlay-detail-format` に `drawio` を指定した VRF Detail |
| `topology-graph.drawio` | `generate-network-diagram` の編集可能な draw.io XML |
| `topology-graph-all.drawio` | `--all-graph` 指定時の 4 view、既定 8 page draw.io XML |
| `network-diagram-manifest.yaml` | diagram source、実効 option、入力・成果物 hash |
| `topology.md` | 個別 `generate-mermaid` で出力先を指定した Mermaid 構成図 |
| `topology.dot` | Graphviz DOT |
| `topology.drawio` | 編集可能なdraw.io XML |

`generate-network-diagram` の成果物名は固定し、`--output-dir` で配置先を変更する。個別 renderer の出力名は固定仕様として
仮定せず、運用 script では各 command の `--output*` で明示する。

`generate-network-diagram` は publish 完了後、最後に diagram と Overlay Service Detail の生成結果を表示する。短い output directory は
各 path に含める。

```text
### NETWORK DIAGRAM RESULT ###

Diagrams:
  output/topology-graph.md
  output/topology_underlay.md
  output/topology_evpn.md
  output/topology_overlay_service.md
  output/topology-graph-all.drawio

Overlay Service details:
  output/overlay-services/
  Markdown: 3 files
  draw.io: 3 files

Status: SUCCESS
################################
```

output directory が 2 階層を超えるか、`/` 込みで 16 文字を超える場合は `Output directory` を 1 回表示し、以降は file name または
`overlay-services/` だけを表示する。model が `partial` の場合は成果物を公開した上で `Status: PARTIAL` と表示し、終了 code は `1` となる。

## 2. Linkが生成されない

- `--input`配下に`config/`または`lldp/`があるか確認する。
- raw filenameと`hosts.yaml`のhostnameが対応しているか確認する。
- descriptionが`description_rules.yaml`のruleへ一致するか確認する。
- SVI descriptionが必要な場合は`--include-svi`を指定する。
- 未対応platformのLLDPはwarningとなり得るため、description側の証拠も確認する。

## 3. Candidateが多い

片方向しか収集できていない、対向機器がinventory外、descriptionの対向表記が一致しない、といった可能性がある。
candidateをconfirmedへ手作業で移動する前に、対向側rawとmapping／ruleを確認する。

## 4. LLDPとdescriptionが食い違う

同じlocal interfaceのremote endpointが異なる場合、現行仕様は片方を破棄しない。配線変更後のdescription更新漏れ、
hostname alias、interface略称、古い収集結果の混在を確認する。

## 5. Groupが期待と異なる

- `--roles`または`--sites`を明示する。
- `--group-by-role`と`--group-by-site`のどちらを使ったか確認する。
- 現行rendererのlegacy single-role判定とcanonical multi-role解決には未移行差分があるため、複数roleを持つnodeの
  groupは生成後に確認する。

## 6. Underlay情報が表示されない

- `generate-network-diagram` では `topology_underlay.md` を確認する。
- Evidence Package／external import／Operation の場合は source Manifest に running config が含まれるか確認する。
- `--underlay`を指定したか確認する。
- `--underlay-config`の対象role、VRF、interfaceがraw configと一致するか確認する。
- `--underlay-raw`配下の`config/`に対象hostのrunning configがあるか確認する。
- 解決できないaddressは安全のため自動推測されない。

## 7. EVPN session が表示されない

- `evpn-control-plane-model.yaml` の `status` と `diagnostics` を確認する。
- running config に BGP L2VPN EVPN AF、exact neighbor、peer template 継承が含まれるか確認する。
- peer address が Router ID／Loopback address へ一意に対応するか確認する。
- dynamic neighbor range だけでは endpoint を生成しないため、対向側 exact neighbor または operational summary を確認する。
- `show bgp l2vpn evpn summary` がない場合、設定から確認できた session は正常に `configured` と表示される。

## 8. Diagram を共有するとき

構成図には hostname、管理 address、interface、Underlay address、site／role が含まれ得る。外部共有前に生成 file を
確認し、必要な開示 policy を適用する。raw config や収集 directory 全体を diagram へ添付しない。

## 9. Overlay Service または route leak が表示されない

- `overlay-service-model.yaml` の `status` と `diagnostics` を確認する。
- running config に VRF、VNI、EVPN scope の `route-target import`／`export` があるか確認する。
- `auto` RT を AS と L3VNI から一意に解決できない場合は route leak を推測しない。
- `site` が未解決の node は同名 VRF を自動結合しないため、`sites.yaml` または inventory の site を確認する。
- route leak policy があっても Type-5／destination VRF route が未収集なら `operational_state: unknown` が正常な表示である。
- Detail がない場合は `overlay_detail_selection` と `--overlay-detail-limit` を確認する。
- draw.io Detail がない場合は `--overlay-detail-format markdown,drawio` を指定したか確認する。`--all-overlay-details` だけでは
  既定形式の Markdown のみを生成する。
- L3VNI 用 VLAN／SVI が `L2 Services` に見える場合は生成 version を確認する。現行出力では `L3VNI Interfaces` に分離し、
  `New L3VNI (VLAN/SVI-less)` と `Traditional VLAN/SVI` を区別する。
- 複数 Leaf で VLAN が異なる場合は `overlay-service-model.yaml` の `bindings` と Markdown の node 別 row を確認する。
- 対象 VRF はあるが L3VNI／L2VNI／NVE binding がない node は、`EVPN Placements` ではなく `Service Edge Attachments` に表示する。
  `service-edge` は外部 Network Function または Border Gateway と決めつけず、VRF attachment evidence だけを表す。
- `service-edge` が `EVPN Placements` に表示される、または L3VNI／L2 Service component へ接続される場合は、生成 version と
  `overlay-service-model.yaml` の `placements[].placement_type` を確認する。

## 10. Site 名と Detail file 名が想定と異なる

service ID の site は hostname prefix 自体ではなく、固定 source の `sites.resolved.yaml` にある `site_detection` の key を使用する。
例えば `site-1.startswith: [adc-]` では `adc-*` node の site は `site-1` になる。`adc` と表示したい場合は source policy の key を
`adc` に変更し、収集と Evidence Package 作成をやり直す。import 済み Package の policy を描画時に暗黙に上書きしない。

Detail file 名末尾の 8 文字は canonical service ID の SHA-256 先頭 8 文字である。内容 hash や random 値ではなく、portable な
文字へ置換した file 名の衝突を避け、同じ service を再生成したときに同じ file 名を得るための識別子である。
