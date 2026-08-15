# Topology and Rendering As-Is

## 1. 文書の位置づけ

- Status: Reviewed
- Last reviewed: 2026-08-09
- 対象: `normalize-links`、`generate-clab`、`generate-mermaid`、`generate-graphviz`、
  `generate-drawio`、`generate-doc`、`generate-tf`、`csv-to-md`
- 根拠: `alred/cli.py`、`alred/parsing.py`、`alred/topology.py`、CLI help、関連testとsample
- 統合先:
  [Link Discovery and Normalization Design](../design/topology/LINK_DISCOVERY_AND_NORMALIZATION_DESIGN.md)、
  [Topology Rendering Design](../design/topology/TOPOLOGY_RENDERING_DESIGN.md)、
  [Terraform Inventory Generation Design](../design/common/TERRAFORM_INVENTORY_GENERATION_DESIGN.md)

本書は現行実装の観測記録である。偶然の実装挙動や安全上の問題を、正式仕様として承認するものではない。

## 2. Link evidenceの生成

`normalize-links`はinventory、raw LLDP、raw running config、mapping、role ruleを読み、各機器の
directional recordを生成してから、反対方向のrecordと照合する。

### 2.1 LLDP parser

| device type | parser |
|---|---|
| `nxos`、`ios`、`iosxe`、`iosxr`、`eos`、`asa`、`asav` | NX-OS形式に近いdetail parser |
| `linux` | Linux LLDP parser |
| `junos`、その他 | linkを返さない |

複数platformを同じparserへ通しているが、全platformのfixtureで同等性を確認できたわけではない。

running configからはinterface descriptionを抽出し、mappingに定義された正規表現ruleでremote nodeと
remote interfaceを推定する。SVIは明示的に許可した場合だけ対象となる。

### 2.2 Evidence統合

| 観測 | 出力 | confidence | evidence |
|---|---|---|---|
| 双方向LLDP | confirmed | `high` | `bidirectional-lldp` |
| LLDPと反対向きdescription | confirmed | `medium` | `lldp-plus-description` |
| 双方向description | confirmed | `low` | `bidirectional-description` |
| 片方向LLDP | candidate | `low` | `one-way-lldp` |
| 片方向description | candidate | `low` | `one-way-description` |

同じlocal interfaceについてLLDPとdescriptionのremote endpointが一致しない場合は、一方を黙って採用せず、
`warning`へ`lldp-description-mismatch`を記録する。

## 3. Normalization

- hostnameは`node_name_map`の完全一致mappingを適用する。
- interfaceは`interface_name_map`を最優先し、その後device type別に正規化する。
- Linuxの`PortN`、`ethN`、`ethernetN`は`ethN`へ寄せる。
- network deviceの`Eth`、management、loopback、port-channel表記をcanonical形へ寄せる。
- exclude interfaceの完全一致とport-channel除外を適用する。
- inventoryのdevice typeは元hostnameとmapping後hostnameの両方から解決を試みる。

## 4. Link CSV

出力列は次の順で固定される。

```text
src_node,src_if,dst_node,dst_if,protocol,confidence,evidence,remote_mgmt_ip,rule_name,warning
```

confirmedとcandidateは別fileへ出力する。readerは`csv.DictReader`で読み込むだけで、必須header、未知列、
空endpointを入力時に検証していない。

merge処理はlink keyの集合をそのまま走査し、CSV writer直前にもsortしない。このため、同一入力でもPythonの
hash seedにより行順が変わり得る。後段rendererは正規化後にsortするため描画結果の多くは安定するが、CSV自体の
再生成性は保証されていない。

## 5. Rendering共通処理

confirmed linkは次の順で処理される。

1. `min-confidence`未満を除外する。
2. hostnameとinterfaceを再正規化する。
3. exclude interfaceを除外する。
4. role priorityとnode名でendpointの左右を決める。
5. endpoint pairで重複を除き、role-aware keyでsortする。

containerlab出力ではさらにport-channel linkを除外する。candidateはevidenceを保持して別のvisual styleで
描画される。

role groupingにはlegacy single-role detectorが残っている。ruleはYAML記載順で、`position_matches`、prefix、
suffix、containsの順に評価される。Health CheckとOverlayが使うcanonical multi-role resolverと同じ意味ではない。

site ruleがある場合はnodeをsiteへ分類できる。underlay modeではraw running configから指定loopbackとinterface
addressを読み、node labelとlink labelを付与する。

## 6. Output別の観測

- Mermaid: Markdown内のflowchartとして出力する。
- Graphviz: DOTとして出力する。
- draw.io: XML として出力する。`--all-graph` は `TD`／`LR` の topology／Underlay、計 4 page を既定で作る。
  `--directions TD,LR,BT,RL` を追加した場合は計 8 page を作る。
- `generate-doc`: 同じconfirmed inputからcontainerlab YAMLとMermaid Markdownを一括生成する。
- `generate-clab`: linkに加え、inventory、merge、lab profileからnode definitionを生成する。
- `csv-to-md`: 先頭rowをheaderとしてMarkdown tableへ変換する。短いrowは最大列数まで空cellで補い、
  pipeと改行をescapeする。入力が空ならerrorとし、出力省略時は`.md` suffixへ置換する。

各diagram commandはCSVまたはcontainerlab topologyを入力にでき、`auto`では入力形式を判定する。形式ごとの
表示機能には差があり、全formatで同じmetadataが描画されるわけではない。

## 7. Terraform出力

`generate-tf`はinventory内の`nxos` hostだけを対象に、legacy roleでprovider aliasをgroup化し、NX-OS
provider blockを生成する。現行実装は生成fileへ次を固定出力する。

```hcl
username = "admin"
password = "admin"
```

これはproduction利用、共有、commitに適さない。credential storeや変数参照へ接続されておらず、現在の
`generate-tf`出力は安全なproduction artifactとは扱えない。

## 8. 未確認・設計差分

- Junosを含むplatform別LLDP fixtureの網羅性
- link CSVの決定的な行順と入力schema validation
- legacy single-role groupingからcanonical multi-role resolutionへの移行
- diagram format間のmetadata parity
- Terraform credentialの安全な注入方式と生成物permission
