# Quick Start

この章では、NX-OS機器の作業前後health checkを最短手順で実行します。最初はラボ環境または
取得済みログで試し、生成される成果物と判定を確認してください。

## 1. 共通事前準備

最初に[Common Preparation](./00_COMMON_PREPARATION.md)を完了してください。このQuick Startでは、
生成済みの`./hosts.lab.yaml`を使用し、直接収集する想定です。

health checkの直接収集はshowコマンドを実行し、設定投入は行いません。

## 2. beforeを直接収集

次の例は、loggingを実施日時から1日前まで確認します。change IDを省略すると自動採番されます。

```bash
alred health-check before \
  --collect \
  --hosts ./hosts.lab.yaml \
  --profile network-baseline-nxos \
  --logging-days 1 \
  --ask-pass
```

端末には、次の形式で結果と保存先が表示されます。

```text
=== HEALTH SNAPSHOT SUMMARY ===
Change ID : HC-20260802T091500-p1234-a1b2c3
Phase     : before
Input     : alred-collect
Hosts     : 2
Warnings  : 0
Result    : WARN
Checks    : PASS=18 WARN=2 FAIL=0 UNKNOWN=0 N/A=2
Manifest  : operations/HC-20260802T091500-p1234-a1b2c3/health/before/collection-manifest.yaml
Snapshot  : operations/HC-20260802T091500-p1234-a1b2c3/health/before/snapshot.json
Checklist : operations/HC-20260802T091500-p1234-a1b2c3/health/before/checklist.md
```

この例では処理は完了していますが、2件のWARNがあります。まずChecklistを確認します。

```bash
less operations/HC-20260802T091500-p1234-a1b2c3/health/before/checklist.md
```

## 3. Checklistを確認

```text
# Health Check Checklist

- Started at: 2026-08-02T09:15:00+09:00
- Completed at: 2026-08-02T09:15:31+09:00
- Change ID: HC-20260802T091500-p1234-a1b2c3
- Phase: before
- Result: WARN

## Checks

### Device: `leaf01`

- [x] `collection_complete`: PASS - All required command outputs were parsed
- [x] `cpu_utilization`: PASS - CPU one_minute_percent is 34.0% (warning threshold: 80%)
- [x] `reload_pending`: PASS - No reload-pending configuration exists
- [ ] `logging_health`: WARN - 12 abnormal log record(s) were observed in the selected time range
- [x] `ospf_neighbor_health`: PASS - All observed OSPF neighbors are FULL
- [x] `vpc_health`: PASS - vPC peer and consistency are healthy
```

最初に次を確認します。

1. 実施日時、change ID、phaseが意図どおりか。
2. 全対象機器が表示されているか。
3. FAILまたはUNKNOWNがないか。
4. WARNが作業継続可能な既存事象か。
5. evidenceのrawファイルを追跡できるか。

判定の詳細は[Output Guide](./04_OUTPUT_GUIDE.md)を参照してください。

## 4. 設定変更を実施

beforeの確認後、承認済みの手順で設定変更を実施します。設定投入をalred外で実施しても、
同じchange IDを使ってafterを取得できます。

## 5. afterを実行

直接収集で作成したbeforeでは、収集方式とhostsをoperationから継承します。認証情報は必要に
応じて再入力します。

```bash
alred health-check after \
  --change-id HC-20260802T091500-p1234-a1b2c3 \
  --ask-pass
```

afterの端末出力例:

```text
=== HEALTH SNAPSHOT SUMMARY ===
Change ID : HC-20260802T091500-p1234-a1b2c3
Phase     : after
Input     : alred-collect
Hosts     : 2
Warnings  : 0
Result    : PASS
Checks    : PASS=20 WARN=0 FAIL=0 UNKNOWN=0 N/A=2
Manifest  : operations/HC-20260802T091500-p1234-a1b2c3/health/after/collection-manifest.yaml
Snapshot  : operations/HC-20260802T091500-p1234-a1b2c3/health/after/snapshot.json
Checklist : operations/HC-20260802T091500-p1234-a1b2c3/health/after/checklist.md
```

after単体だけでなく、before / after比較結果も確認してください。生成されている場合は
operation配下のhealth reportを参照します。

## 6. 取得済みログから試す

機器へ接続せず試す場合:

```bash
alred health-check snapshot \
  --input ./raw-before \
  --input-format alred-collect \
  --phase before \
  --profile network-baseline-nxos \
  --logging-days 1
```

外部CLIログの場合は、入力形式を明示します。

```bash
alred health-check snapshot \
  --input ./transcripts/before \
  --input-format nxos-transcript \
  --phase before \
  --hosts ./hosts.lab.yaml \
  --profile network-baseline-nxos
```

## 次に読む

- 実行方式と時間範囲: [Health Check Operations](./02_HEALTH_CHECK_OPERATIONS.md)
- profileの作成: [Profile Guide](./03_PROFILE_GUIDE.md)
- 出力と判定: [Output Guide](./04_OUTPUT_GUIDE.md)
- EVPN/VXLAN作業: [NX-OS Overlay Health Check](./06_NXOS_OVERLAY_HEALTH_CHECK.md)
- alred内でVNI設定投入:
  [Overlay ChangeSet作成ガイド](./07_OVERLAY_CHANGESET_GUIDE.md) →
  [alredによるVNI設定投入](./08_ALRED_OVERLAY_CHANGE_APPLY.md)
