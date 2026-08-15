# Collect Output As-Is

- Status: Integrated
- Last reviewed: 2026-08-09
- Scope: `alred/cli.py:collect_from_host`とcollect path helper

## Evidence

| 種別 | pathまたはcommand | 確認内容 |
|---|---|---|
| Code | `alred/cli.py:collect_from_host` | base/show commandの収集と保存 |
| Code | `alred/cli.py:build_collect_output_path` | hostname/suffix/extension規則 |
| Test | `tests/test_phase0_collect_baseline.py` | path、format優先、transcript境界 |
| Fixture | `tests/fixtures/collect/synthetic/` | external accessを伴わない出力例 |

## Observed behavior

- raw root配下ではLLDPを`lldp/`、running configを`config/`へ保存する。
- textは`<hostname>_<suffix>.txt`、NX-API JSONは
  `<hostname>_<suffix>.json`となる。
- current mirrorと同じ内容を`old/<generation>/`配下にも保存する。
- text/JSONの両方があると、既存resolver/list処理はJSONを優先する。
- show listは`<show-output>/<hostname>/<hostname>_shows.log`に保存する。
- show transcriptの先頭には`### COMMAND_LIST`があり、各command sectionは
  `### COMMAND`、`### COLLECTED_AT`、`### STATUS`、`### TRANSPORT`と
  `<hostname># <command>`を含む。
- auto transportのNX-OSでは、show transcriptはSSH textを優先し、取得できたNX-API JSONを
  command別sidecarとして同じhost directoryへ保存する。
- `collect-all` archiveは`old/`を除外するが、host directoryに以前のcommand listで生成された
  JSON sidecarが残っている場合、それをcurrent artifactとしてarchiveへ含める。

## Synthetic fixtureの位置づけ

`tests/fixtures/collect/synthetic/`はdirectoryとcommand境界の回帰試験用である。
`source_type: synthetic`であり、NX-OS 10.4(5)Mまたはmodel固有capabilityの証明には使わない。

## Unknowns and conflicts

- 実在するNX-OS 10.4(5)Mの長大なroute/BGP出力、途中切断、paging混入は未fixture化である。
- hostname promptの変種と外部ツールtranscriptの解析はPhase 2の対象であり、現行collectが
  一般的な外部transcriptをimportできることを意味しない。
- current mirror更新は複数file writeからなり、operation単位のatomicityは提供しない。
- JSON sidecarは今回generationに取得しなかったcommandの旧fileを除去しないため、archiveを
  単一generationとして扱うにはmtimeだけでなくmanifestまたはallowlistが必要である。

## Recommended design disposition

本形式を既存collect adapterの入力契約として維持し、raw保存処理自体は再利用する。
Snapshot/parserはこのdirectoryを直接変更せず、manifestとprovenanceを別成果物として追加する。
旧sidecar混入の可能性は保証仕様へ昇格せず、manifestで除外する既知の制約とする。

## Integration

- Design document: [Collection Design](../design/common/COLLECTION_DESIGN.md)、[Health Check Framework Design](../design/network-ops/HEALTH_CHECK_FRAMEWORK_DESIGN.md)
- Integrated date: 2026-08-09
