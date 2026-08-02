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
- Change ID: CHG-2026-00123
- Phase: after
- Result: FAIL

## Checks

### Device: `leaf01`

- [x] `system_identity`: PASS - NX-OS 10.4(5)M was identified
- [ ] `cpu_utilization`: WARN - CPU utilization reached 85%
- [x] `logging_health`: PASS - No new abnormal logs were detected

### Device: `leaf02`

- [x] `system_identity`: PASS - NX-OS 10.4(5)M was identified
- [ ] `bgp_ipv4_health`: FAIL - BGP peer regression: 192.0.2.254
- [ ] `logging_health`: WARN - 1 new abnormal log record was detected
```

先頭のmetadataは実施開始日時、実施完了日時の順とする。`Checks`は機器名を昇順に並べ、
各機器の見出し配下ではprofileで解決したcheck順を維持する。

Markdownのcheckboxはツールが結果として生成する。利用者が手作業で完了状態を書き換えるための正本にはしない。

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

`result.json`はattempt ID、`RUNNING` / `COMPLETED` / `FAILED`、health result、開始・完了時刻、
profile hash、失敗時のcode / messageを保持する。`current.json`は最新成功attemptのdirectory、
Snapshot path / hash、profile hash、health resultを保持する。`profile-revision.json`は変更理由、
旧新profile path / hash / nameとfield単位差分を保持する。直下のSnapshot等は既存consumer向けの
互換正本であり、`current.json`が示すattemptと同一内容にする。失敗attemptは`current.json`と
互換正本を変更しない。

## 13. Overlay VNI Mapping

実効profileに`nxos-overlay`が含まれる場合は、次の派生成果物を自動生成する。

```text
health/
├── before/
│   ├── overlay-state.yaml
│   ├── vni-map.md
│   └── vni-map.csv
├── after/
│   ├── overlay-state.yaml
│   ├── vni-map.md
│   └── vni-map.csv
└── report/
    ├── vni-map-diff.json
    ├── vni-map-diff.md
    └── vni-map-diff.csv
```

`overlay-state.yaml`はCanonical Overlay Stateから生成する機械処理の正本とし、
L2VNI / L3VNI、VRF、device-local VLAN、VLAN name、SVI IPv4 / IPv6 / link-local、
MTU、anycast gateway、NVE membership / operational state、local AS、証跡を保持する。
`vni-map.md`と`vni-map.csv`はその派生表現である。

`vni-map-diff.json`はbefore / after差分の正本とする。CSVは次の列を固定順で
出力し、unchanged行は出力しない。

```csv
change_type,resource_type,vni,vrf,device,field,before,after,status,evidence_before,evidence_after
ADDED,L2VNI,10020,TENANT-B,leaf01,vlan,,20,OBSERVED,../before/raw/config/leaf01_run.txt,../after/raw/config/leaf01_run.txt
MODIFIED,L2VNI,10010,TENANT-A,leaf01,operational_state,Up,Down,OBSERVED,../before/raw/leaf01/leaf01_shows.log,../after/raw/leaf01/leaf01_shows.log
```

CSV内の配列とobjectはJSON文字列とする。期待ChangeSetがない場合の`status`は
`OBSERVED` / `CONFLICT` / `UNKNOWN`とし、観測差分だけを根拠に`EXPECTED` /
`UNEXPECTED`を付与しない。詳細な内部modelと生成条件は
[Overlay Change Management Design](./OVERLAY_CHANGE_MANAGEMENT_DESIGN.md#81-health-check-vni-mapping成果物)を正本とする。

## 14. 出力の互換性

- JSON/YAMLには`schema_version`を必須とする
- field追加は後方互換とし、削除・意味変更ではschema versionを更新する
- parser version変更で結果が変わり得る場合はSnapshotへversionを保存する
- Markdownと端末表示は人間向けであり、外部システムはJSONを使用する
- timestampはtimezone付きISO 8601を使用する
- result、classification、check IDは安定した英数字識別子を使用する

未知field、default解決、canonical hash、major versionの詳細は
[Schema and Compatibility Policy](./SCHEMA_AND_COMPATIBILITY_POLICY.md)を正本とする。
設定投入の`approval-record.json`、operation lock、状態遷移は
[Operation State and Approval Design](./OPERATION_STATE_AND_APPROVAL_DESIGN.md)を参照する。
