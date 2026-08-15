# Containerlab Workflow As-Is

- Status: Reviewed
- Last reviewed: 2026-08-09
- Scope: `init-clab`、`generate-clab`、`clab-transform-config`、`collect-clab`、
  `check-clab-startup-config`、`clab-set-cmds`

## Evidence

| 種別 | pathまたはcommand | 確認内容 |
|---|---|---|
| Code | `alred/design.py` | cable CSV、正規化、validation report |
| Code | `alred/transform.py` | management IP、hostname、NX-OS config変換 |
| Code | `alred/topology.py`、`alred/cli.py` | node／link生成、merge、YAML出力、pipeline |
| Config | `CONFIG.md` | cable、merge、Linux、Kind、node map形式 |
| User doc | `README.md` | command順、成果物、利用手順 |
| Test | `tests/test_design.py` | cable、IP、merge、startup delay、description照合 |
| Test | `tests/test_transform.py` | config変換の正常系・境界条件 |

## Observed behavior

### `init-clab`

- `hosts.txt`とcable CSVからinventory、node、linkを生成する。
- cable endpointはhostname・interface mappingとdevice type別正規化を適用してから検証する。
- 必須値欠落、未知node、自己link、重複link、endpoint再利用、Linux `eth0` data link、管理IPv4
  不正・重複・subnet外をerrorとする。
- 未接続node、未知device type、未知CSV列、除外interface、dynamic range重複はwarningとする。
- normalized cable CSVとvalidation reportはerror時または`--validate-only`時にも出力する。
- errorが1件でもあればtopologyを生成しない。

### `generate-clab`

- confirmed links CSVからlinkを正規化・方向付けし、confidence閾値未満を除外する。
- inventoryがあればnode kind、management IP、role groupを生成する。
- Linux server CSV、Kind cluster CSVを追加overlayとして適用できる。
- generated topologyへ`--clab-merge`、次に`--clab-lab-profile`をdeep mergeする。
- mapping同士は再帰mergeし、scalar・listは後勝ち。ただし`topology.links`はfinalize時にgenerated linksの
  後へmerge側linksを連結し、同一objectを重複排除する。
- top-levelとtopology key、node、linkを決定的な順序へ整え、endpoint listをflow styleで出力する。
- `cisco_n9kv`／Linux kindの既定値は、merge側に値がない場合だけ補う。
- N9Kv startup delayはnode順を使い、先頭batchを0、以降をbatch単位で増加させ、既存値を上書きしない。

### `clab-transform-config`

- source inventoryを`mgmt.ipv4-subnet`へ変換し、`hosts.lab.yaml`を生成する。
- node mapがあればhostname、management IP、config内hostname／VDC／description／mgmt0／management
  VRF route／vPC keepaliveを変換する。
- NX-OS subinterfaceをVLAN、SVI、parent trunkへ変換し、既存sectionへ重複なくmergeする。
- L3 Ethernet／port-channelに不足する`no switchport`を補う。
- NX-OSではresolved lab userを置換・追加でき、`--delete-username`では全usernameとSNMP userを削除する。
- `--delete-access-class`は`line vty`内だけを対象とする。
- source config欠落hostはwarningとしてskipし、変換済みinventoryからは除外しない。
- config変換parserはNX-OS構文向けだが、commandはsource fileがある非NX-OS hostを一律に拒否しない。

### Startup verificationとpipeline

- `check-clab-startup-config`はlab inventoryと生成startup configを対応付け、live running configを収集して
  正規化後にunified diffを作る。
- credential解決とconnect checkは共通処理を再利用するが、live running configはstartup verification固有の
  host処理で取得し、`collect-*`のraw generationやCollection Manifestを経由しない。
- statusは`matched`、`diff`、`missing-startup`、`unsupported`、`connect-failed`、`failed`を想定する。
- live configは`<output>/current/`、reportは`<output>/check-clab-startup-config.txt`へ保存する。
- `clab-set-cmds`は固定stepを順番に実行し、`--without-collect`ではcollectionだけをskipする。
- いずれの生成commandもcontainerlab runtimeを起動しない。

## Documented but not verified

- 生成topologyがすべての現行containerlab versionで受理されることは、schemaまたはruntimeで自動検証していない。
- Linux／Kind overlayのinit scriptと外部imageを使用した起動完了はoffline testだけでは保証しない。

## Inferred behavior

- `clab-set-cmds`は利便性重視のlegacy pipelineであり、step単位のimmutable manifestやatomic publishを
  提供しない。
- source config欠落をwarningに留めるため、生成topologyに存在するN9Kv nodeのstartup-configが欠落する
  状態を別途確認する必要がある。

## Unknowns and conflicts

- `check-clab-startup-config`のconnect failure処理は、`ConnectCheckResult`に存在しない`device_type`を参照していたが、
  inventoryから解決するよう修正済みである。
- 非NX-OS configを`clab-transform-config`へ渡した場合の正式な対応範囲は定義されていない。
- merge後のnode／linkがgenerated cable validationと同じ重複・endpoint検査を再実行する契約はない。
- lab用平文passwordをstartup configへ埋め込む方式の保管・削除policyは文書化が不足している。

## Recommended design disposition

- production source、sanitized fixture、generated lab artifactを明確に区別する。
- `init-clab`のfail-closed validationとmerge順、既存filenameを正式仕様として維持する。
- config変換の正式対象をNX-OSとし、他device typeは個別adapterなしに対応済みと扱わない。
- startup verificationのconnect failureは専用testでreport生成まで確認する。
- startup verificationの比較責務はContainerlabに維持し、deviceへのread-only取得とprovenanceはCommon
  Collection／Device Accessへ統合する。
- runtime起動確認はoffline生成testと分け、対象topologyとimageを指定した承認済みlab testで行う。

## Integration

- Design document: [Containerlab Workflow Design](../design/containerlab/CONTAINERLAB_WORKFLOW_DESIGN.md)
- ADR: Not required
- Integrated date: 2026-08-09
