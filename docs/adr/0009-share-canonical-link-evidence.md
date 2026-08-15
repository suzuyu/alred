# ADR-0009: LLDP／descriptionのCanonical Link Evidenceを利用機能間で共有する

- Status: Accepted
- Date: 2026-08-09

## Context

既存Topology処理はLLDPとrunning configのinterface descriptionを解析し、hostname／interface mapping、
exclude、description ruleを適用してconfirmed／candidate linkと不整合warningを生成する。一方、現行の
`health-check before --collect`はrunning configを取得するが、base collectionを`run_config_only=True`で
呼ぶためLLDPを取得せず、結線とdescriptionの不整合を正常性確認へ含めない。

商用環境の収集データを隔離labへ移送し、Topology、Containerlab Digital Twin、AI解析へ共用する要件では、
consumerごとにendpoint解釈を実装するとmapping、除外、confidence、before／after比較が一致しなくなる。
外部接続先やserverは管理範囲外でdescription規則も一定しないため、すべてのLLDP neighborをHealth異常へ
含めると誤検出が増える。

## Decision

`network-baseline-nxos`はrunning configと`show lldp neighbors detail`を同じCollection attemptで取得する。
LLDP／descriptionのparse、正規化、照合、confirmed／candidate、warningはTopology設計を正本とする
Canonical Link Evidenceとして一度だけ生成し、Health、Topology、Containerlab、Portable Evidence Packageで
共有する。Healthは独自parserを持たず、対象scopeとstatus変換policyだけを所有する。

Healthの既定対象はinventoryで識別できるmanaged network device間とする。network deviceは含め、server、
inventory未登録endpoint、外部接続先は除外する。`network-functions`は`auto`とし、LLDPで観測され、inventoryへ
一意に解決でき、対応parserで解析できる場合だけ対象へ含める。双方向LLDPが一致してdescriptionがない場合は
既定`PASS`、LLDPと解釈可能なdescriptionの不一致は既定`WARN`とし、site policyで厳格化できる。

mappings、description rules、exclude、normalizer versionはbefore Operationへ固定し、afterでhash検証する。
Digital Twin packageは同じraw、解決済み入力、canonical normalized linksを含め、隔離labで再生成検証できる
形式とする。

## Consequences

- LLDPとrunning configを一度収集し、正常性確認、図面、Digital Twin、AI解析へ再利用できる。
- HealthとTopologyでendpointや不整合の意味がずれなくなる。
- 外部・server linkのevidenceは保持しながら、既定Health判定の誤検出を抑制できる。
- Health直接収集、Collection Manifest、Snapshot、evaluator、compare、execution context、package consumerの
  実装変更とschema追加が必要になる。
- 既存Topology CSVとCLIは互換維持し、Canonical Link Evidenceへの移行中も削除・意味変更しない。

## References

- [Health Check Framework Design](../design/network-ops/HEALTH_CHECK_FRAMEWORK_DESIGN.md)
- [NX-OS Baseline Health Check Commands](../design/network-ops/NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md)
- [Link Discovery and Normalization Design](../design/topology/LINK_DISCOVERY_AND_NORMALIZATION_DESIGN.md)
- [Portable Evidence Package Design](../design/common/PORTABLE_EVIDENCE_PACKAGE_DESIGN.md)
