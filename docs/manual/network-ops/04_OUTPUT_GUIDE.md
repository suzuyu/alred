# Output Guide

## 1. 最初に見る順番

1. 端末summaryでchange ID、phase、host数、総合Resultを確認
2. `device-summary.md`で対象機器の識別情報、role、Health結果を一覧確認
3. `checklist.md`で機器ごとのFAIL、UNKNOWN、WARNを確認
4. `health-result.json`で判定値、閾値、時間範囲、evidenceを確認
5. `collection-manifest.yaml`からrawログのファイルと行範囲を確認
6. `snapshot.json`でparserが正規化した状態を確認
7. `execution.json`でphase状態とerror履歴を確認

## 2. 端末summary

```text
=== HEALTH SNAPSHOT SUMMARY ===
Change ID : HC-20260802T091500-p1234-a1b2c3
Phase     : before
Input     : alred-collect
Hosts     : 2
Warnings  : 0
Result    : WARN
Checks    : PASS=18 WARN=2 FAIL=0 UNKNOWN=0 N/A=2
Manifest  : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/before/collection-manifest.yaml
Snapshot  : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/before/snapshot.json
Checklist : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/before/checklist.md
Devices   : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/before/device-summary.md
Device CSV: operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/before/device-summary.csv
```

項目:

| 項目 | 確認内容 |
|---|---|
| Change ID | 作業記録と一致するか |
| Phase | before、after、rollbackのどれか |
| Input | alred-collectまたはnxos-transcript |
| Hosts | 想定した対象台数か |
| Warnings | importや収集上のwarning件数 |
| Result | operation全体の代表判定 |
| Checks | check判定数 |
| Manifest / Snapshot / Checklist | 詳細確認先 |
| Devices / Device CSV | 機器一覧の Markdown／CSV |

## 3. 判定

| 判定 | 意味 | 初期対応 |
|---|---|---|
| PASS | 定義した正常条件を満たす | 次のcheckへ |
| WARN | 処理は完了したが確認が必要 | 既存事象か、新規事象かを確認 |
| FAIL | 正常条件を満たさない、またはregression | 作業を止めて影響と切り戻しを検討 |
| UNKNOWN | 収集不足、parser警告、比較不能 | 正常と扱わず原因を解消 |
| NOT_APPLICABLE | 機能未使用などで対象外 | 適用判定が妥当か確認 |

UNKNOWNは「異常がない」という意味ではありません。判定に必要な証跡が不足している状態です。

## 4. Checklist

```text
### Device: `leaf01` (192.0.2.11)

#### Profile: `network-baseline-nxos`

- [x] `collection_complete`: PASS - All required command outputs were parsed
- [x] `system_identity`: PASS - NX-OS 10.5(4) model Nexus9000 C9300v was identified
- [x] `cpu_utilization`: PASS - CPU one_minute_percent is 34.0% (warning threshold: 80%)
- [-] `environment_health`: NOT_APPLICABLE - Hardware environment sensors are unavailable on this platform
- [ ] `logging_health`: WARN - 12 abnormal log record(s) were observed in the selected time range
- [x] `reload_pending`: PASS - No reload-pending configuration exists
```

表示記号:

| 記号 | 主な判定 |
|---|---|
| `[x]` | PASS |
| `[ ]` | WARN、FAIL、UNKNOWN |
| `[-]` | NOT_APPLICABLE |

Checklistは概要です。WARNやFAILの全証跡はhealth-result.jsonで確認します。
完全なChecklistでは、先頭にprofile別件数を表示し、各deviceの配下をprofile単位に分けます。

## 5. health-result.json

logging_healthの例:

```json
{
  "check_id": "logging_health",
  "profile": "network-baseline-nxos",
  "host": "leaf01",
  "result": "WARN",
  "classification": "pre_existing",
  "message": "12 abnormal log record(s) were observed in the selected time range",
  "resource": "system/logging",
  "after": {
    "total_records": 342,
    "matched_records": 12,
    "severity_threshold": 4,
    "lookback_seconds": 604800,
    "time_range": {
      "mode": "days",
      "days": 1
    },
    "window_start": "2026-08-01T09:15:00+09:00",
    "window_end": "2026-08-02T09:15:00+09:00",
    "matches": [
      {
        "timestamp": "2026-08-02T08:41:12+09:00",
        "severity": 3,
        "text": "2026 Aug 2 08:41:12 leaf01 %APP-3-ERROR: example",
        "match_reasons": [
          "severity<=4"
        ]
      }
    ]
  }
}
```

確認点:

- classificationがpre_existingかregressionか
- matched_recordsとmatchesの内容
- severity_threshold
- time_rangeとwindow境界
- 除外すべき既知ログか
- 作業時間内に新規発生したか

## 6. Collection Manifest

`metadata.started_at` と `metadata.completed_at` は、`--collect` を使用した場合の実際の収集開始と
収集完了を示します。`checklist.md` と `health-result.json` は、収集開始から解析完了までの時刻を
示すため、通常は Collection Manifest の範囲を内包します。時刻は秒単位のため、同一秒内で
完了した処理では開始と完了が同じ表示になる場合があります。

```yaml
spec:
  hosts:
    leaf01:
      commands:
        show_logging:
          command: show logging
          normalized_command: show logging
          status: success
          file: operations/.../health/before/raw/leaf01/leaf01_shows.log
          sha256: 0123456789abcdef...
          source: alred_collect
          transport: ssh
          output_start_line: 309
          output_end_line: 724
```

Manifestのfileと行範囲から、判定に使用したraw出力へ到達できます。

```bash
sed -n '309,724p' operations/.../health/before/raw/leaf01/leaf01_shows.log
```

rawログを共有する場合は、認証情報、IPアドレス、hostname、設定内容などの機微情報を確認して
ください。

## 7. Snapshot

Snapshotは、rawコマンド出力を共通schemaへ正規化した成果物です。

```json
{
  "created_at": "2026-08-02T09:15:00+09:00",
  "timezone": "Asia/Tokyo",
  "parser_versions": {
    "nxos": "1.16",
    "snapshot_builder": "1.2",
    "ntc_templates": "9.0.0",
    "textfsm": "2.1.0"
  },
  "hosts": {
    "leaf01": {
      "collection_status": "success",
      "common": {
        "logging": {
          "records": [],
          "parse_warnings": []
        }
      }
    }
  }
}
```

parse_warningsが存在する場合は、対応しているNX-OS出力形式か、入力区間が正しいかを確認します。

## 8. before / after比較

比較結果の例:

```text
Result    : FAIL
Checks    : PASS=18 WARN=1 FAIL=1 UNKNOWN=0 N/A=2
```

```text
## Regressions

| Host | Resource | Check | Before | After | Result |
|---|---|---|---|---|---|
| leaf02 | routing/bgp-ipv4 | bgp_ipv4_health | Established | Idle | FAIL |
```

regressionは作業前に正常だった状態が作業後に失われたことを示します。作業内容との関連、影響範囲、
切り戻し条件を確認します。

## 9. Device Summary

`device-summary.md` と `device-summary.csv` は同じ列順と 1 device 1 row で生成されます。
Markdown はレビュー、CSV は表計算や後続処理に使用します。

| 列 | 確認内容 |
|---|---|
| `hostname` / `management_ip` | 収集対象と管理 IP |
| `manufacturer` / `model` / `serial_number` | メーカー、機種、primary chassis の serial number |
| `os_type` / `os_version` | OS 種別と version |
| `license_usage` / `license_parse_status` | 観測した license usage と解析状態 |
| `topology_role` / `functions` | 解決済み role policy から得た role と function |
| `health_result` / `collection_status` | host ごとの代表 Health 判定と収集状態 |
| `collected_at` | Snapshot 作成時刻 |

`license_usage` は情報表示であり、契約、entitlement、registration、compliance の
正常性判定ではありません。`not_collected` や `unknown` を正常とみなさず、
Collection Manifest、Snapshot source、raw output を確認します。詳細は
[Device Summary Design](../../design/network-ops/DEVICE_SUMMARY_DESIGN.md)を参照してください。

## 10. nxos-overlayのVNI map

`nxos-overlay`が実効profileに含まれる場合、phaseごとのOverlay状態とbefore / after差分が
追加で生成されます。

| 成果物 | 確認内容 |
|---|---|
| `overlay-state.yaml` | VNI、VRF、VLAN、SVI、NVE状態とevidenceの正規化正本 |
| `vni-map.md` | VNI単位の人間向け一覧 |
| `vni-map.csv` | 機器単位の表計算・既存連携向け一覧 |
| `vni_gateway_map.md` | 既存 `generate-vni-map` 互換の SVI 中心一覧 |
| `vni_gateway_map.csv` | `generate-vni-config` 互換の legacy CSV |
| `vni-map-diff.json` | before / afterのfield単位差分とevidence |
| `vni-map-diff.md` | 差分の人間向け一覧 |
| `vni-map-diff.csv` | 差分の表計算・連携向け一覧 |

実際のbefore、after、diffの表示例と確認手順は
[NX-OS Overlay Health Check](./06_NXOS_OVERLAY_HEALTH_CHECK.md)を参照してください。同じVNIに
属するdiff行は連続して出力されます。Markdownでは同じ結果のdeviceを1行へ集約し、
VNIを持たないOverlay全体の差分は末尾に並びます。末尾の`Field Source List`と
`Evidence Files`から、fieldの取得コマンドとbefore / afterの証跡を確認できます。
作成方法、schema、用途の違いは [VNI Map Guide](09_VNI_MAP_GUIDE.md)を参照してください。

## 11. CLI終了code

| Code | 意味 |
|---:|---|
| 0 | 成功、blockingな異常なし |
| 1 | WARNまたは利用者判断が必要。成果物は生成済み |
| 2 | validation、plan、approval、capability error |
| 3 | collection、parser、schema不整合で判定不能 |
| 4 | health check FAILまたはregression |
| 5 | apply、save、rollback失敗またはdevice状態不明 |
| 6 | support bundleのsecret、integrity、生成失敗 |
| 130 | Ctrl+Cによる中断 |

自動化では終了codeだけでなく、health-result.jsonとexecution.jsonも保存・確認してください。
