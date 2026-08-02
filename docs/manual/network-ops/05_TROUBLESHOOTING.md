# Troubleshooting

## 1. option不足

例:

```text
VALIDATION_ERROR: health-check before requires --collect or --input
```

beforeでは、機器へ接続するcollectか、既存ログを読むinputのどちらかが必要です。

```bash
# 直接収集
alred health-check before --collect --hosts ./hosts.lab.yaml --ask-pass

# オフライン
alred health-check before \
  --input ./raw-before \
  --input-format alred-collect
```

通常のoption不足ではPython Tracebackを表示せず、簡潔なerrorと終了code 2を返します。

## 2. logging_healthがUNKNOWN

Checklist例:

```text
- [ ] `logging_health`: UNKNOWN - show logging data is unavailable
```

または:

```text
- [ ] `logging_health`: UNKNOWN - show logging contains unparseable records
```

確認順序:

1. collection-manifest.yamlにshow_loggingが存在するか。
2. statusがsuccessか。
3. file、output_start_line、output_end_lineが正しいか。
4. raw区間にshow loggingの出力があるか。
5. snapshot.jsonのcommon.logging.parse_warningsを確認する。
6. parser_versionsを確認する。

raw確認例:

```bash
sed -n '309,724p' operations/<change-id>/health/before/raw/leaf01/leaf01_shows.log
```

severity番号を持たないNX-OSのtimestamp付き非構造化recordは有効なrecordとして扱われ、
severityはnullになります。timestamp自体を解析できない場合はUNKNOWNになります。

## 3. logging_healthのWARNが多い

```text
- [ ] `logging_health`: WARN - 506 abnormal log record(s) were observed in the selected time range
```

まずtime_rangeを確認します。

```json
{
  "time_range": {
    "mode": "days",
    "days": 7
  },
  "window_start": "2026-07-26T09:15:00+09:00",
  "window_end": "2026-08-02T09:15:00+09:00"
}
```

初期対応:

- 一時確認ならbeforeでlogging-daysを短くする。
- 定常運用ならprofileのtime_rangeを見直す。
- 既知のノイズはexclude_patternsを検討する。
- severityなしrecordを対象にする場合はinclude_patternsを設定する。
- 除外条件は根拠とレビュー履歴を残す。

例:

```yaml
thresholds:
  logging:
    severity_threshold: 4
    time_range:
      mode: days
      days: 1
    include_patterns:
      - "warning:"
    exclude_patterns:
      - "expected maintenance message"
```

## 4. start-time error

```text
VALIDATION_ERROR: --logging-start-time must include a timezone offset
```

timezone付きで指定します。

```bash
--logging-start-time "2026-08-02T09:00:00+09:00"
```

Snapshot日時より未来を指定した場合も判定できません。

## 5. profile error

### ファイルが見つからない

```text
VALIDATION_ERROR: profile file not found: profiles/site-a.yaml
```

現在の作業ディレクトリからの相対パスか、絶対パスを確認します。

### check IDが重複

組み込みbaselineをコピーしたprofileと、元のnetwork-baseline-nxosを同時指定していないか確認します。

```text
NG:
--profile network-baseline-nxos
--profile profiles/site-a-baseline.yaml
```

コピー版を単独baselineとして指定します。

### afterでprofile hash不一致

afterでは通常profileを指定しません。beforeのresolved-profiles.yamlを継承します。意図的に
明示する場合も、beforeと同一内容でなければなりません。

## 6. 対象host不足・重複

- hosts YAMLのhostnameと実機promptが一致するか。
- transcript aliasが設定されているか。
- 同じhostnameが複数ファイルで異なる機器を指していないか。
- beforeとafterのhost集合が一致するか。
- target-hostsで意図せず除外していないか。

曖昧なhostnameは自動的に別機器へ割り当てません。

## 7. parser修正後に再確認

元成果物を上書きせずrecheckします。

```bash
alred health-check snapshot \
  --input operations/<change-id>/health/before/raw \
  --input-format alred-collect \
  --phase before \
  --change-id <change-id> \
  --recheck
```

before-recheck/checklist.mdと元のbefore/checklist.mdを比較します。

## 8. uvのVIRTUAL_ENV warning

```text
warning: VIRTUAL_ENV=... does not match the project environment path .venv
```

別projectの仮想環境がactiveな状態です。alredの依存関係はproject側の環境で実行されます。
必要に応じて現在の仮想環境をdeactivateしてから再実行します。このwarning自体はNX-OSの
health check判定ではありません。

## 9. AIや別担当者へ渡す

operation全体をそのまま共有せず、support bundleを作成します。

```bash
alred support-bundle create \
  --change-id HC-20260802T091500-p1234-a1b2c3 \
  --phase before \
  --split device \
  --prompt-language ja \
  --symptom "logging_health is UNKNOWN" \
  --question "収集失敗かparser未対応かを切り分けてください"
```

作成後にinspectとverifyを実施し、redaction結果、secret scan、Manifest、SHA-256を確認します。
raw loggingを含める場合は、共有先と必要性を確認してください。

## 10. それでも解決しない場合

次を揃えて調査します。

- 実行コマンド
- change IDとphase
- terminal summary
- checklist.md
- health-result.json
- collection-manifest.yaml
- 対象command区間のrawログ
- resolved-profiles.yaml
- snapshot.jsonのparser_versions
- alred version
