# Health Check Output Formats

## 1. 文書の目的

共通Health Check Frameworkが出力する端末表示、Markdown、JSON、YAMLの初期フォーマットを定義する。

出力先と共通処理は[Health Check Framework Design](./HEALTH_CHECK_FRAMEWORK_DESIGN.md)、Overlay固有項目は[Overlay Change Management Design](./OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)を参照する。

## 2. 出力原則

- 作業全体のrootは`operations/<change-id>/`とする
- 正常性確認成果物は`health/`、設定生成物は`generated-config/`、Overlay差分は`overlay/`へ分離する
- 端末には作業判断に必要な短いsummaryだけを表示する
- 詳細はMarkdownへ保存する
- 外部連携と再評価用にJSONを保存する
- rawログ、コマンド、取得時刻まで根拠を追跡できるようにする
- `PASS`、`WARN`、`FAIL`、`UNKNOWN`、`NOT_APPLICABLE`を区別する
- beforeから存在する問題とafterで発生したregressionを区別する
- secret、password、認証情報は出力しない

時刻の意味は次のとおりとする。

- `CollectionManifest.metadata.started_at` と `completed_at` は、直接収集では機器からの収集開始と
  収集完了を表す
- `Snapshot.created_at` は、解析対象とする収集世代を固定した時点を表す
- `HealthResult.started_at` と `completed_at`、および `checklist.md` の `Started at` と
  `Completed at` は、直接収集では収集開始から解析完了までを表す
- `checklist.md`の`Duration`は`Completed at - Started at`を秒単位で計算し、`HH:MM:SS`
  と総秒数を併記する。時刻が欠落、不正、または完了が開始より前の場合は推測表示しない
- 既存 file を `--input` で解析する場合は、元収集時刻を推測せず、入力解析の開始から完了までを
  `HealthResult` へ記録する

時刻は秒単位で記録するため、実際に同一秒内で完了した処理では開始と完了が同じ値になり得る。
ただし、直接収集で判明している収集時間を捨て、収集後の解析時刻だけを記録してはならない。

### 2.1 metadata.yaml

作業単位のID、採番方法、正本となるphase / attemptを記録する。

```yaml
api_version: alred/v1
kind: OperationMetadata

metadata:
  change_id: HC-20260725T100203-p0900-a1b2c3
  change_id_source: generated
  timezone: Asia/Tokyo
  utc_offset: "+09:00"
  created_at: "2026-07-25T10:02:03+09:00"
  tool_version: 0.2.0a1

spec:
  output_root: operations/HC-20260725T100203-p0900-a1b2c3
  purpose: inspection
  lifecycle: running
  workflow_state: before_completed
  phases:
    before:
      current_attempt: before-20260725T100203-p0900-d4e5f6
      status: completed
    after:
      current_attempt: null
      status: not_started
  last_transition:
    scope: workflow
    from: before_running
    to: before_completed
    at: "2026-07-25T10:05:31+09:00"
    reason: before_health_check_completed
```

`change_id_source`は`specified`または`generated`とする。利用者が`--change-id`を指定した場合は`specified`、alredが自動採番した場合は`generated`を記録する。
`metadata.yaml`の`kind`はHealth Check専用名ではなく、全workflowで共通の
`OperationMetadata`とする。状態遷移の完全な履歴とerrorはrootの`execution.json`へ保存し、
`metadata.yaml`は現在状態と最後の遷移を表す。
`purpose`は`change`、`inspection`、`initial_lab_qualification`などOperationの用途を表す。
`inspection`の保存phase名は互換性のためbefore／afterを維持するが、active changeには登録しない。

### 2.2 active-change.yaml

自動採番したbeforeと、`--change-id`を省略したafterを安全に関連付ける状態ファイルである。

```yaml
api_version: alred/v1
kind: ActiveHealthCheckChange

metadata:
  updated_at: "2026-07-25T10:05:31+09:00"
  timezone: Asia/Tokyo

spec:
  change_id: HC-20260725T100203-p0900-a1b2c3
  change_id_source: generated
  state: before_completed
  output_root: operations/HC-20260725T100203-p0900-a1b2c3
  before:
    completed_at: "2026-07-25T10:05:31+09:00"
    metadata_path: operations/HC-20260725T100203-p0900-a1b2c3/metadata.yaml
    snapshot_path: operations/HC-20260725T100203-p0900-a1b2c3/health/before/snapshot.json
    inventory_sha256: 2b199c1f1d4712441cc32ae8342b8949331e75d5b604f584d55090e79c31bbf8
    profile_sha256: 999cbab92fd5c1d29867b5541446fd555ef47f5c6d7055e4556f02df76f78e9a
  after:
    status: not_started
```

保存先は`operations/.state/active-change.yaml`とし、temporary fileへの完全書込み後にrenameする方法でatomicに更新する。after完了後は`state: completed`へ更新し、省略時の候補から除外する。参照先、hash、状態が一致しない場合は自動修復や最新ディレクトリ検索を行わず`PLAN_ERROR`とする。

## 3. 端末表示

### 3.1 before正常終了

```text
=== HEALTH CHECK BEFORE SUMMARY ===
Change ID : CHG-2026-00123
Profile   : network-baseline-nxos, nxos-overlay
Hosts     : 6
Result    : PASS

Checks:
  PASS           84
  WARN            0
  FAIL            0
  UNKNOWN         0
  NOT_APPLICABLE  8

Snapshot : operations/CHG-2026-00123/health/before/snapshot.json
Report   : operations/CHG-2026-00123/health/before/checklist.md
===================================
```

### 3.2 beforeで警告と継続確認

```text
=== HEALTH CHECK BEFORE SUMMARY ===
Change ID : CHG-2026-00123
Result    : WARN

Warnings:
- leaf01: CPU one-minute utilization is 85% (threshold: 80%)
- leaf02: reload-pending configuration existed before this operation

WARNING: OPERATION GATE REQUIRES CONFIRMATION
- SUSTAINED_HIGH_CPU: leaf01 samples=82%,85%,84%
- RELOAD_PENDING_CONFIG_EXISTS: leaf02 pending=1

Continue the planned operation? [yes/no]:
```

利用者が継続した場合:

```text
Operation continuation approved.
Approval recorded in:
operations/CHG-2026-00123/health/before/execution.json
```

### 3.3 afterでregression検出

```text
=== HEALTH CHECK AFTER SUMMARY ===
Change ID : CHG-2026-00123
Result    : FAIL

Regressions:
- leaf02: BGP neighbor 10.0.0.1 changed Established -> Idle
- leaf02: NVE VNI 10010 changed Up -> Down
- leaf03: new reload-pending configuration detected

Pre-existing warnings:
- leaf01: CPU one-minute utilization remains above 80%

Report : operations/CHG-2026-00123/health/report/summary.md
JSON   : operations/CHG-2026-00123/health/report/health-result.json
==================================
```

### 3.4 自動発見Overlay

```text
=== OVERLAY CHANGE SUMMARY ===
Change ID : CHG-2026-00123
Result    : OBSERVED_HEALTHY

Discovered resources:
- L2VNI 10010 / VRF TENANT-A / leaf01,leaf02
- L3VNI 50001 / VRF TENANT-A / leaf01,leaf02,border01

Limitations:
- No declared expected ChangeSet was supplied.
- Target completeness and intended VNI numbers were not verified.

ChangeSet: operations/CHG-2026-00123/overlay/discovered-changes.yaml
================================
```

### 3.5 外部CLI transcriptの取り込み

```text
=== TRANSCRIPT IMPORT SUMMARY ===
Phase             : before
Files scanned     : 4
Hosts detected    : 8
Commands detected : 184
Unresolved        : 2
Ambiguous         : 1

Detected hosts:
- leaf01: 23 commands
- leaf02: 23 commands
- leaf03: 22 commands

WARNING:
- session-02.log: lines 410-428: command prompt not detected
- session-03.log: lines 91-116: duplicated command generation is ambiguous

Manifest: operations/CHG-2026-00123/health/before/transcript-import-manifest.yaml
=================================
```

未解決区間を別のホストやコマンドへ推測で割り当てない。必須コマンドが不足する場合は、後続のcollection completenessを`UNKNOWN`またはcollection不成立とする。

## 4. summary.md

```text
# Health Check Summary

- Change ID: CHG-2026-00123
- Phase: after
- Started at: 2026-07-21T10:30:00+09:00
- Completed at: 2026-07-21T10:31:45+09:00
- Duration: 00:01:45 (105 seconds)
- Profiles: network-baseline-nxos, nxos-overlay
- Result: FAIL

## Result counts

| Result | Count |
|---|---:|
| PASS | 81 |
| WARN | 2 |
| FAIL | 3 |
| UNKNOWN | 0 |
| NOT_APPLICABLE | 8 |

## Regressions

| Host | Resource | Check | Before | After | Result |
|---|---|---|---|---|---|
| leaf02 | bgp-neighbor/10.0.0.1 | preserve_bgp_neighbors | Established | Idle | FAIL |
| leaf02 | l2vni/10010 | vni_operational_state | Up | Down | FAIL |
| leaf03 | system/reload-pending | reload_pending | none | 1 command | FAIL |

## Warnings

| Host | Check | Classification | Detail |
|---|---|---|---|
| leaf01 | cpu_utilization | pre_existing | one-minute CPU 85% |
| leaf04 | vpc_orphan_ports | unexpected_change | Ethernet1/20 added |

## Collection errors

No collection errors.

## Artifacts

- Before snapshot: `../before/snapshot.json`
- After snapshot: `../after/snapshot.json`
- Machine-readable result: `health-result.json`
```

## 5. checklist.md

```text
# Health Check Checklist

- Started at: 2026-07-21T10:30:00+09:00
- Completed at: 2026-07-21T10:31:45+09:00
- Duration: 00:01:45 (105 seconds)
- Change ID: CHG-2026-00123
- Phase: after
- Result: FAIL

## Result by Profile

| Profile | PASS | WARN | FAIL | UNKNOWN | N/A |
|---|---:|---:|---:|---:|---:|
| network-baseline-nxos | 2 | 2 | 1 | 0 | 0 |

## Checks

### Device: `leaf01` (192.0.2.11)

#### Profile: `network-baseline-nxos`

- [x] `system_identity`: PASS - NX-OS 10.4(5)M was identified
- [ ] `cpu_utilization`: WARN - CPU utilization reached 85%
- [x] `logging_health`: PASS - No new abnormal logs were detected

### Device: `leaf02` (192.0.2.12)

#### Profile: `network-baseline-nxos`

- [x] `system_identity`: PASS - NX-OS 10.4(5)M was identified
- [ ] `bgp_ipv4_health`: FAIL - BGP peer regression: 192.0.2.254
- [ ] `logging_health`: WARN - 1 new abnormal log record was detected

## Unexecuted Hosts

| Host | Platform | Topology Role | Profile | Reason Code | Reason |
|---|---|---|---|---|---|
| `fw01` | nxos | network-functions | nxos-overlay | PROFILE_ROLE_EXCLUDED | topology role is outside the nxos-overlay scope |
| `server01` | linux | server | network-baseline-nxos | PROFILE_PLATFORM_EXCLUDED | platform is outside the profile scope |
| `unknown01` | nxos | other | nxos-overlay | TOPOLOGY_ROLE_UNRESOLVED | hostname did not match one topology role rule |
```

先頭のmetadataは実施開始日時、実施完了日時の順とする。`Result by Profile`は、実際に check
結果を 1 件以上持つ profile だけを resolved profile順に表示する。threshold、logging exclude、
report policy などの override だけを提供し、check を持たない profile を全件 0 の結果行として
表示しない。適用した全 profile と override provenance は `resolved-profiles.yaml` を正本とする。
`Checks` は機器名を昇順に並べ、device 見出しを ``hostname (management IP)`` 形式で表示する。
management IP は収集時に使用した inventory の `ansible_host` を `CollectionManifest`、
`HealthSnapshot`、`HealthResult` の順に引き継ぐ。inventory が指定されていない offline 入力、
または `ansible_host` が IP address ではない場合は、推測せず従来どおり hostname だけを表示する。
機器内を resolved profile 順に section 化し、各 profile 内では profile で
解決したcheck順を維持する。checkがないprofile sectionは機器配下へ出力しない。

`Unexecuted Hosts` は、対象 host に含まれていたが platform または topology role policy により profile を実行しなかった host を hostname、platform、topology role、profile の順に並べる。`network-functions` と `other` でも対応 OS の別 profile を実行した場合、その結果は通常の device → profile section に表示し、未実行の profile だけをこの一覧へ出力する。`server` は NX-OS profile を実行しない。

未実行 host は check 単位の `NOT_APPLICABLE` 件数へ含めない。`other` に対する `nxos-overlay` は未実行理由を表示した上で profile 結果を `UNKNOWN` とし、compare、plan、apply では `PLAN_ERROR` とする。未実行 host が 0 件の場合も `None` を表示して、一覧の生成漏れと区別する。

Markdownのcheckboxはツールが結果として生成する。利用者が手作業で完了状態を書き換えるための正本にはしない。
check の message は判定結果名を先頭へ重複保存しない。renderer が `PASS -`、`FAIL -`、
`UNKNOWN -` などを付加するため、message は `Type-5 propagation: ...` のように理由から開始する。

複数 stage を持つ check の message は、単なる収集 coverage ではなく判定結果を先頭に表示する。
`FAIL` / `UNKNOWN` では stage、VRF、prefix または resource、device、理由を直接表示する。
coverage を表示する場合は `receiver evidence` のように証跡取得数であることを明記し、正常数と
誤認させる `receiver coverage` という表記を使用しない。

Type-5 の例:

```text
- [ ] `type5_prefix_propagation`: FAIL - Type-5 propagation: 1 issue(s) across 8 prefix(es); RECEIVER_VRF_ROUTE tenant2-vpc1 172.17.0.0/24 on leaf05,leaf06: VRF route is missing
```

全受信対象が正常な場合は `receiver evidence 28/28`、受信対象がない場合は
`receiver stage NOT_APPLICABLE (0 targets)` と表示する。詳細な stage 別結果は
`health-result.json` の `failures`、`unknowns`、`stage_summary` に保存する。正常な
`prefix x receiver` の明細は全件保存せず、`stage_summary` の prefix 件数と receiver evidence
件数へ集約する。`failures` と `unknowns` には問題がある stage、VRF、prefix、device、reason
だけを保存する。raw command と `snapshot.json` は再評価可能な証跡として従来どおり保持する。

## 6. health-result.json

```json
{
  "schema_version": 1,
  "change_id": "CHG-2026-00123",
  "phase": "after",
  "started_at": "2026-07-21T10:30:00+09:00",
  "completed_at": "2026-07-21T10:31:45+09:00",
  "profiles": [
    "network-baseline-nxos",
    "nxos-overlay"
  ],
  "result": "FAIL",
  "counts": {
    "pass": 81,
    "warn": 2,
    "fail": 3,
    "unknown": 0,
    "not_applicable": 8
  },
  "unexecuted_hosts": [
    {
      "host": "fw01",
      "platform": "nxos",
      "topology_role": "network-functions",
      "profile": "nxos-overlay",
      "profile_result": "NOT_APPLICABLE",
      "reason_code": "PROFILE_ROLE_EXCLUDED",
      "message": "Topology role is outside the nxos-overlay scope."
    },
    {
      "host": "unknown01",
      "platform": "nxos",
      "topology_role": "other",
      "profile": "nxos-overlay",
      "profile_result": "UNKNOWN",
      "reason_code": "TOPOLOGY_ROLE_UNRESOLVED",
      "message": "Hostname did not match one topology role rule."
    }
  ],
  "checks": [
    {
      "check_id": "preserve_bgp_neighbors",
      "profile": "network-baseline-nxos",
      "host": "leaf02",
      "resource": "bgp-neighbor/10.0.0.1",
      "result": "FAIL",
      "classification": "regression",
      "message": "BGP neighbor changed Established -> Idle",
      "before": {
        "state": "Established",
        "prefixes_received": 24
      },
      "after": {
        "state": "Idle",
        "prefixes_received": null
      },
      "evidence": [
        {
          "collection_id": "CHG-2026-00123-after-20260721T103000",
          "command": "show bgp ipv4 unicast summary vrf all",
          "file": "../../raw-after/show_lists/leaf02/leaf02_shows.log"
        }
      ]
    },
    {
      "check_id": "reload_pending",
      "profile": "network-baseline-nxos",
      "host": "leaf03",
      "resource": "system/reload-pending",
      "result": "FAIL",
      "classification": "regression",
      "message": "New reload-pending configuration detected",
      "before": {
        "commands": []
      },
      "after": {
        "commands": [
          "hardware profile dlb ; dlb-interface Eth1/5,Eth1/7"
        ]
      },
      "evidence": [
        {
          "command": "show system config reload-pending",
          "file": "../../raw-after/show_lists/leaf03/leaf03_shows.log"
        }
      ]
    }
  ],
  "operation_gate": {
    "required": false,
    "decision": null
  },
  "artifacts": {
    "before_snapshot": "../before/snapshot.json",
    "after_snapshot": "../after/snapshot.json",
    "summary": "summary.md"
  }
}
```

`unexecuted_hosts` は host/profile 単位の実行可否を表し、check 単位の `checks` および `counts.not_applicable` とは分離する。配列は 0 件でも省略せず空配列を保存する。`profile_result` は定義済み対象外なら `NOT_APPLICABLE`、role 未解決など正常性を保証できない場合は `UNKNOWN` とする。

この field は既存 field の意味を変更しない追加であるため `schema_version: 1` を維持する。旧成果物で field が欠落している場合、reader は空配列として扱う。ただし、新実装が生成する正規成果物では必須とする。

### 6.1 Link health結果

LLDP／description整合性は`profile: network-baseline-nxos`のcheckとして`health-result.json`へ格納し、
Canonical Link Evidenceのrecord IDとsourceを参照する。外部・serverなどの対象外linkをPASSへ数えず、
`N/A`と除外理由を保持する。

```json
{
  "check_id": "lldp_description_consistency",
  "profile": "network-baseline-nxos",
  "resource": "link/leaf01:Ethernet1/1--spine01:Ethernet1/1",
  "result": "WARN",
  "classification": "mismatch",
  "message": "LLDP and interface description identify different remote endpoints",
  "before": null,
  "after": {
    "lldp_endpoint": "spine01:Ethernet1/1",
    "description_endpoint": "spine02:Ethernet1/1",
    "confidence": "low"
  },
  "evidence": [
    {
      "command": "show lldp neighbors detail",
      "source_id": "lldp_neighbors_detail"
    },
    {
      "command": "show running-config",
      "source_id": "running_config"
    }
  ]
}
```

before／after比較では`neighbor_removed`、`neighbor_changed`、`interface_changed`、
`new_mismatch`、`mismatch_resolved`を区別する。両端が収集対象だったかをrecordへ保持し、remote未収集を
片方向LLDP異常として表示しない。mappings、description rules、normalizer versionがbeforeと一致しない
場合は比較結果を生成せず、入力条件不一致としてfail closedにする。

## 7. execution.json

実行したコマンドとOperation Gateの判断を保存する。

```json
{
  "schema_version": 1,
  "change_id": "CHG-2026-00123",
  "phase": "before",
  "commands": [
    {
      "host": "leaf01",
      "id": "processes_cpu",
      "command": "show processes cpu",
      "status": "success",
      "started_at": "2026-07-21T10:00:05+09:00",
      "elapsed_seconds": 0.82,
      "raw_file": "../../raw-before/show_lists/leaf01/leaf01_shows.log"
    }
  ],
  "operation_gate": {
    "required": true,
    "reasons": [
      {
        "code": "SUSTAINED_HIGH_CPU",
        "host": "leaf01",
        "samples": [82, 85, 84],
        "threshold": 80
      }
    ],
    "decision": "continue",
    "decided_at": "2026-07-21T10:01:00+09:00",
    "decided_by": "operator",
    "plan_hash": "sha256:0123456789abcdef"
  }
}
```

## 8. snapshot.json

Snapshotは表示用レポートではなく、再評価可能な正規化状態である。

```json
{
  "schema_version": 1,
  "change_id": "CHG-2026-00123",
  "collection_id": "CHG-2026-00123-after-20260721T103000",
  "phase": "after",
  "created_at": "2026-07-21T10:31:45+09:00",
  "timezone": "Asia/Tokyo",
  "parser_versions": {
    "snapshot_builder": "1.1",
    "nxos": "1.1"
  },
  "profile_sha256": "sha256:999cbab92fd5c1d29867b5541446fd555ef47f5c6d7055e4556f02df76f78e9a",
  "hosts": {
    "leaf01": {
      "collection_status": "success",
      "common": {
        "cpu": {
          "five_seconds_percent": 82,
          "interrupt_percent": 2,
          "one_minute_percent": 85,
          "five_minutes_percent": 74
        },
        "reload_pending": {
          "required": false,
          "commands": []
        },
        "logging": {
          "records": [
            {
              "timestamp": "2026-07-21T10:15:03+09:00",
              "severity": 3,
              "fingerprint": "sha256-example",
              "text": "2026 Jul 21 10:15:03 leaf01 %APP-3-ERROR: example",
              "parse_warnings": []
            }
          ],
          "parse_warnings": []
        },
        "routing_neighbors": {},
        "interfaces": {}
      },
      "profiles": {
        "nxos-overlay": {
          "nve_interface": {
            "name": "nve1",
            "state": "Up"
          },
          "l2vnis": {
            "10010": {
              "state": "Up",
              "vlan": 10
            }
          }
        }
      },
      "sources": {},
      "parse_warnings": []
    }
  }
}
```

`logging.records[].severity`は構造化syslogでは`0`から`7`、NX-OSのtimestamp付き
非構造化recordでは`null`とする。
`logging_health`の判定詳細には実効`time_range`、`window_start`、`window_end`を記録する。
`all`では`window_start: null`とする。従来の`lookback_seconds`も後方互換と監査のため
保持する。


## 9. resolved-profiles.yaml

before実行時に省略時既定値または`--profile`で指定した参照を解決し、比較条件を固定する。after、rollback、compareはこのファイルを再利用する。`resolution_source`は`default`（省略時既定値）または`explicit`（明示指定）を示す。

```yaml
api_version: alred/v1
kind: ResolvedHealthCheckProfiles

metadata:
  change_id: CHG-2026-00123
  resolved_at: "2026-07-21T09:58:00+09:00"

spec:
  requested:
    - order: 1
      ref: network-baseline-nxos
      type: builtin
      name: network-baseline-nxos
      version: "1.0"
      source: builtin://network-baseline-nxos
      source_sha256: 4218179f1e1e63f73e5ea31af3237b9c3a9dcfe8f6feaa5e15506a7f0ab31d91
      resolution_source: explicit
    - order: 2
      ref: nxos-overlay
      type: builtin
      name: nxos-overlay
      version: "1.0"
      source: builtin://nxos-overlay
      source_sha256: 821a5845001b4695b676f9936cfb2350a2279f7cd1bf152146b587347de47437
      resolution_source: explicit
    - order: 3
      ref: profiles/site-a-policy.yaml
      type: file
      name: site-a-policy
      version: "3"
      source: profiles/site-a-policy.yaml
      source_sha256: 3580264f4dd3495c8ac38b753b81aff3183b35222ee4e54cc68460f05793f923
      resolution_source: explicit

  resolved:
    profile_names:
      - network-baseline-nxos
      - nxos-overlay
      - site-a-policy
    effective_sha256: 999cbab92fd5c1d29867b5541446fd555ef47f5c6d7055e4556f02df76f78e9a
    overrides:
      - path: spec.thresholds.cpu.warn_percent
        previous_value: 80
        previous_source: network-baseline-nxos
        effective_value: 75
        effective_source: site-a-policy
```

SHA-256値は例である。実装では正規化したprofile内容から計算し、ファイルの改行コードやYAML key順だけで値が変わらないようにする。

### 9.1 execution-context.yaml

`health-check before` wrapperが使用した非秘密の入力・収集条件を固定する。direct collectionの
afterはこのファイルを読み、`--change-id`だけで同じ対象を再収集する。inventoryとpolicyは
pathに加えてsource SHA-256を記録し、after接続前に検証する。password、enable secret、
credentials fileの内容は含めない。

schemaと完全な例は
[Health Check Framework Design](./HEALTH_CHECK_FRAMEWORK_DESIGN.md#823-before-execution-context)
を参照する。

## 10. transcript-import-manifest.yaml

外部CLI transcriptの認識結果例:

```yaml
api_version: alred/v1
kind: TranscriptImportManifest

metadata:
  change_id: CHG-2026-00123
  phase: before
  source: external_transcript
  imported_at: "2026-07-25T10:05:00+09:00"
  timezone: Asia/Tokyo

spec:
  input_format: nxos-transcript
  inputs:
    - path: external-before-logs/all-leafs.log
      sha256: 8616873432e9cc50d373f2b4fd7343e8315a27e1c34473b42f801c9c65d6b621

  hosts:
    leaf01:
      detected_prompts:
        - leaf01
      inventory_name: leaf01
      matched_by: hostname
      platform: nxos
      segments:
        - command: show version
          normalized_command: show version
          command_id: show_version
          source_file: external-before-logs/all-leafs.log
          start_line: 1
          end_line: 48
          output_start_line: 2
          output_end_line: 48
          confidence: high
        - command: show processes cpu
          normalized_command: show processes cpu
          command_id: processes_cpu
          source_file: external-before-logs/all-leafs.log
          start_line: 49
          end_line: 62
          output_start_line: 50
          output_end_line: 62
          confidence: high

    leaf02:
      detected_prompts:
        - DC1-LEAF-02
      inventory_name: leaf02
      matched_by: alias
      platform: nxos
      segments:
        - command: show nve vni
          normalized_command: show nve vni
          command_id: nve_vni
          source_file: external-before-logs/all-leafs.log
          start_line: 63
          end_line: 91
          output_start_line: 64
          output_end_line: 91
          confidence: high

  unresolved_segments:
    - source_file: external-before-logs/all-leafs.log
      start_line: 92
      end_line: 106
      reason: command_prompt_not_detected
      confidence: low

  summary:
    files_scanned: 1
    hosts_detected: 2
    commands_detected: 3
    unresolved_segments: 1
    ambiguous_segments: 0
```

`source_file`と行番号により、正規化後のSnapshot値から元ログまで追跡できるようにする。入力が外部ログであっても、このmanifestから生成したCollection Manifest以外をSnapshot Builderが直接走査しない。

## 11. discovered-changes.yaml

Overlay自動発見の例:

```yaml
api_version: alred/v1
kind: OverlayChangeSet

metadata:
  change_id: CHG-2026-00123
  source: discovered
  generated_at: "2026-07-21T10:31:30+09:00"

spec:
  l2vnis:
    - vni: 10010
      default_vlan: 10
      vlan_name: TENANT-A-WEB
      vrf: TENANT-A
      l3vni: 50001
      svi:
        mtu: 9216
        ipv4_addresses:
          - 192.0.2.1/24
        gateway_mode: anycast
      targets:
        groups:
          server-leafs: {}

  l3vnis:
    - vni: 50001
      vrf: TENANT-A
      mode: new_l3vni
      address_families:
        ipv4:
          advertise_l2vpn_evpn: true
          redistribute_direct:
            enabled: true
            route_map: IPv4_REDISTRIBUTE_ALL
          redistribute_static:
            enabled: true
            route_map: IPv4_REDISTRIBUTE_ALL
          maximum_paths_ibgp: 4
      targets:
        groups:
          server-leafs: {}

status:
  discovery:
    confidence: high
  conflicts: []
  warnings: []
```

## 12. Rollback verification

通常rollbackの`rollback/verification.json`とqualificationの
`qualification/rollback/verification.json`は、切り戻し後の共通正常性、対象deviceの
normalized raw running-config、Overlay parserのsemantic configを1つのgateとして示す。
同じディレクトリへ`verification-checklist.md`も出力し、運用者がJSONを直接解析せずに統合gateと
機器別結果を確認できるようにする。

rollback verification の Health compare は before で固定した `health/resolved-roles.yaml` を
通常 rollback と qualification rollback の両方で再利用する。role artifact がある operation では
`compare_snapshots` に同じ resolved role を渡し、通常の Health Checklist と同じ profile／function
適用範囲を維持する。例えば `network-functions` の `nxos-overlay`、EVPN RR だけを持つ Spine の
NVE peer／VNI check は verification に再出現させない。role 解決導入前の operation に
`resolved-roles.yaml` が存在しない場合だけ legacy の全 host 互換動作を維持する。

```json
{
  "api_version": "alred/v1",
  "kind": "QualificationRollbackVerification",
  "metadata": {
    "change_id": "HC-20260730T122608-p0900-bc53b8",
    "verified_at": "2026-07-30T15:40:00+09:00",
    "timezone": "Asia/Tokyo"
  },
  "status": {
    "result": "ROLLED_BACK_AND_VERIFIED",
    "health_result": "PASS",
    "snapshot_fresh": true,
    "raw_config_equal": true,
    "semantic_config_equal": true
  },
  "devices": {
    "lfsw0103": {
      "raw_config_equal": true,
      "semantic_config_equal": true,
      "raw_config_diff": {
        "added_line_count": 0,
        "removed_line_count": 0
      },
      "semantic_difference_paths": []
    },
    "lfsw0104": {
      "raw_config_equal": true,
      "semantic_config_equal": true,
      "raw_config_diff": {
        "added_line_count": 0,
        "removed_line_count": 0
      },
      "semantic_difference_paths": []
    }
  },
  "artifacts": {
    "before_snapshot": "operations/HC-.../health/before/snapshot.json",
    "rollback_snapshot": "operations/HC-.../health/rollback/snapshot.json",
    "health_result": "operations/HC-.../health/rollback-report/health-result.json",
    "verification_json": "operations/HC-.../qualification/rollback/verification.json",
    "verification_checklist": "operations/HC-.../qualification/rollback/verification-checklist.md"
  }
}
```

freshness、Health、raw config、semantic configの4条件のいずれかが不一致なら
`ROLLBACK_HEALTH_FAILED`とし、不一致を成功扱いにしない。
新規生成物ではrollback Snapshotの`created_at`がrollback executionの`completed_at`以後であることも
`snapshot_fresh`として記録する。古いschema v1成果物を読めるよう追加fieldはschema上optionalとするが、
現行writerは必ず出力する。

`verification-checklist.md`は次の順で表示する。

1. verified at、change ID、総合結果
2. `rollback_snapshot_fresh`、`health_restored`、`raw_running_config_restored`、
   `overlay_semantic_config_restored`の統合gate
3. deviceごとのraw / semantic一致
4. raw不一致時の追加・削除行数。設定行自体はsecret漏えい防止のため記載しない
5. semantic不一致時のJSON Pointer形式の差分path。before / rollbackの値は記載しない
6. HealthResultのWARN / FAIL / UNKNOWN項目のhost、check ID、message
7. before / rollback Snapshot、HealthResult、JSON verificationへの証跡path

共通Health Checkの全PASS項目は重複掲載せず、`health/rollback/checklist.md`および
`health/rollback-report/summary.md`を正本として参照する。

rollback再実行では、JSONとChecklistを`verification-attempts/<attempt-id>/`へ不変保存する。
`verification-current.json`は最新の判定完了attemptについて、attempt ID、総合結果、verification、
Checklist、HealthResultのpath、完了時刻を保持する。互換pathの`verification.json`と
`verification-checklist.md`は同じattemptの内容とする。収集、解析、verification処理自体が失敗した
場合はcurrentと互換pathを更新しない。

出力例:

```markdown
# Rollback Verification Checklist

- Verified at: 2026-08-02T21:16:32+09:00
- Change ID: CHG-2026-0802-TEST
- Result: ROLLBACK_HEALTH_FAILED

## Integrated Gates

- [x] `rollback_snapshot_fresh`: PASS
- [ ] `health_restored`: WARN
- [x] `raw_running_config_restored`: PASS
- [x] `overlay_semantic_config_restored`: PASS

## Device: `lfsw0103`

- [x] `raw_config_equal`: PASS
- [x] `semantic_config_equal`: PASS

## Non-Pass Health Checks

- `lfsw0103/logging_health`: WARN - 5 new abnormal log records were detected
```

### 12.1 before attemptと最新正本

beforeの各収集・解析世代は次へ保存する。

```text
health/before/
├── current.json
├── attempts/
│   └── <attempt-id>/
│       ├── result.json
│       ├── resolved-profiles.yaml
│       ├── profile-revision.json  # profileを明示改訂した場合
│       ├── raw/
│       ├── collection-manifest.yaml
│       ├── snapshot.json
│       ├── health-result.json
│       └── checklist.md
├── snapshot.json
├── health-result.json
└── checklist.md
```

`result.json`は attempt ID、`RUNNING`／`COMPLETED`／`FAILED`／`CANCELLED`、health result、開始・完了時刻、
profile hash、失敗時のcode / messageを保持する。`current.json`は最新成功attemptのdirectory、
Snapshot path / hash、profile hash、health resultを保持する。`profile-revision.json`は変更理由、
旧新profile path / hash / nameとfield単位差分を保持する。直下のSnapshot等は既存consumer向けの
互換正本であり、`current.json`が示すattemptと同一内容にする。失敗attemptは`current.json`と
互換正本を変更しない。

直接収集中に利用者が `Ctrl-C` で中断した場合は、collection phase と該当 attempt を
`CANCELLED` として確定し、`COLLECTION_CANCELLED` を記録する。同じ change ID、inventory、profile、
入力方式で再実行した場合は新しい attempt を作成する。旧 version で lock を残さず `RUNNING` のまま
終了した直接収集は、次回再実行時に旧 phase／attempt を `CANCELLED` へ確定してから新 attempt を開始する。
有効な Operation lock が存在する場合は実行中の可能性があるため自動回収しない。

## 13. Overlay VNI Mapping

実効profileに`nxos-overlay`が含まれる場合は、次の派生成果物を自動生成する。

```text
health/
├── before/
│   ├── overlay-state.yaml
│   ├── vni-map.md
│   ├── vni-map.csv
│   ├── vni_gateway_map.md
│   └── vni_gateway_map.csv
├── after/
│   ├── overlay-state.yaml
│   ├── vni-map.md
│   ├── vni-map.csv
│   ├── vni_gateway_map.md
│   └── vni_gateway_map.csv
└── report/
    ├── vni-map-diff.json
    ├── vni-map-diff.md
    └── vni-map-diff.csv
```

`overlay-state.yaml`はCanonical Overlay Stateから生成する機械処理の正本とし、
L2VNI / L3VNI、VRF、device-local VLAN、VLAN name、SVI IPv4 / IPv6 / link-local、
MTU、anycast gateway、NVE membership / operational state、local AS、証跡を保持する。
`vni-map.md`と`vni-map.csv`はその派生表現である。

`vni_gateway_map.md` と `vni_gateway_map.csv` は既存 `generate-vni-map`／`generate-vni-config` と
互換性を持つ SVI 中心の派生表現とする。`OverlayState` から生成し、別 parser や追加収集は使用しない。
CSV field は `l3vni,vrf,l2vni,gateway_ipv4,gateway_ipv6,device,vlan,vlan_name` の固定順とし、
standalone L3VNI 行は含めない。複数 address は既存互換のため先頭の primary IPv4／IPv6 を使用する。
正常性、全 address、L3VNI 単独状態、conflict／unknown の確認では `overlay-state.yaml` と `vni-map.*` を
正本とし、legacy CSV 単独を投入可否の根拠にしない。

`vni-map-diff.json`はbefore / after差分の正本とする。CSVは次の列を固定順で
出力し、unchanged行は出力しない。

```csv
change_type,resource_type,vni,vrf,device,field,before,after,status,evidence_before,evidence_after
ADDED,L2VNI,10020,TENANT-B,leaf01,vlan,,20,OBSERVED,../before/raw/config/leaf01_run.txt,../after/raw/config/leaf01_run.txt
MODIFIED,L2VNI,10010,TENANT-A,leaf01,operational_state,Up,Down,OBSERVED,../before/raw/leaf01/leaf01_shows.log,../after/raw/leaf01/leaf01_shows.log
```

CSV内の配列とobjectはJSON文字列とする。期待ChangeSetがない場合の`status`は
`OBSERVED` / `CONFLICT` / `UNKNOWN`とし、観測差分だけを根拠に`EXPECTED` /
`UNEXPECTED`を付与しない。差分行はVNI、resource type、VRF、device、fieldの順に並べ、
同じVNIの変更を連続して出力する。VNIに関連付けられない`OVERLAY_STATE`の行は末尾に出力する。
MarkdownはVNI / resource type / VRFごとにsectionを分け、change type、field、before、after、
statusが同じdeviceを1行へ集約する。元のfield変更件数と集約後の表示行数を併記し、deviceごとに
値が異なる変更は別行にして差異を保持する。JSONとCSVはfield単位の行を集約しない。
Markdown末尾の`Field Source List`には、表示したfieldの取得元種別と、そのまま再確認に使える
NX-OSコマンドを出力する。`Evidence Files`にはsourceとdeviceごとのbefore / after証跡pathを
出力する。config由来fieldは`show running-config`、VNI operational stateとreplicationは
`show nve vni`へ対応付ける。複合判定または未知fieldは変更行が保持するevidenceを列挙する。
詳細な内部modelと生成条件は
[Overlay Change Management Design](./OVERLAY_CHANGE_MANAGEMENT_DESIGN.md#81-health-check-vni-mapping成果物)を正本とする。

## 14. 出力の互換性

- JSON/YAMLには`schema_version`を必須とする
- field追加は後方互換とし、削除・意味変更ではschema versionを更新する
- parser version変更で結果が変わり得る場合はSnapshotへversionを保存する
- Markdownと端末表示は人間向けであり、外部システムはJSONを使用する
- timestampはtimezone付きISO 8601を使用する
- result、classification、check IDは安定した英数字識別子を使用する

未知field、default解決、canonical hash、major versionの詳細は
[Schema and Compatibility Policy](../common/SCHEMA_AND_COMPATIBILITY_POLICY.md)を正本とする。
設定投入の`approval-record.json`、operation lock、状態遷移は
[Operation State and Approval Design](../common/OPERATION_STATE_AND_APPROVAL_DESIGN.md)を参照する。
