# Health Check Operations

実行前に[Common Preparation](./00_COMMON_PREPARATION.md)を完了し、inventory、認証、
入力方式、operation保存先を確定してください。

## 1. 基本フロー

health checkは、同じchange IDのbeforeとafterを関連付けて使用します。

```text
before収集・判定
    ↓
作業継続可否の確認
    ↓
設定変更
    ↓
after収集・判定
    ↓
before / after比較
    ↓
必要な場合はrollbackとrollback後確認
```

beforeのprofile、対象inventory、timezone、logging範囲はoperationへ固定します。afterで別条件へ
変更すると、同じ基準で比較できないため拒否されます。

## 2. 入力方式

### 2.1 機器へ直接接続

```bash
alred health-check before \
  --collect \
  --hosts ./hosts.lab.yaml \
  --profile network-baseline-nxos \
  --ask-pass
```

既存collect runnerを利用し、profileが要求するshowコマンドを収集します。rawログ、
Collection Manifest、Snapshot、判定結果を同じoperationへ保存します。
transportは既定で`ssh`です。`show logging`を含む標準profileでは通常`--transport`指定は不要です。

SSH の事前接続確認では、enable 後の prompt hostname と inventory hostname を大文字・小文字を含めて
完全一致で照合します。NX-OS の既定 hostname `switch` は初期設定候補として警告しますが、Health Check の
ような read-only 処理は継続します。既定 hostname 以外の不一致、または prompt を解析できない場合は対象を
除外します。正当な alias などを意図して接続する場合だけ `--allow-hostname-mismatch` を指定してください。
`--skip-connect-check` はこの事前確認を省略するため、通常運用では使用しません。

接続確認とは別に、`network-baseline-nxos` は `show version` の `Device name` と inventory hostname を
`hostname_identity` で照合します。この正常性判定では `switch` も特例にせず、不一致を `FAIL` とします。
直接収集の端末出力例:

```text
=== HEALTH SNAPSHOT SUMMARY ===
Change ID : HC-20260802T091500-p1234-a1b2c3
Phase     : before
Input     : alred-collect
Hosts     : 2
Warnings  : 0
Result    : PASS
Checks    : PASS=20 WARN=0 FAIL=0 UNKNOWN=0 N/A=2
Attempt   : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/before/attempts/before-20260802T091500-p0900-a1b2c3
Manifest  : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/before/collection-manifest.yaml
Snapshot  : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/before/snapshot.json
Checklist : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/before/checklist.md
Devices   : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/before/device-summary.md
Device CSV: operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/before/device-summary.csv
```

`Input: alred-collect`は、既存collect runnerで機器へ接続して収集したことを示します。

生成される `checklist.md` の先頭には `Started at`、`Completed at` に続けて、両時刻の差分を
`Duration: HH:MM:SS (<seconds> seconds)` 形式で記録します。直接収集では収集開始から解析完了までの
所要時間です。

### 2.1.1 変更作業を伴わないinspection

正常性確認、Topology生成、Digital Twin作成のために収集する場合は`--purpose inspection`を指定します。

```bash
alred health-check before \
  --purpose inspection \
  --collect \
  --hosts ./hosts.lab.yaml \
  --profile network-baseline-nxos \
  --mappings ./mappings.yaml \
  --description-rules ./description_rules.yaml \
  --ask-pass
```

収集内容は通常のbeforeと同じで、running config、LLDP、baseline show outputを同じattemptへ保存します。
inspectionはactive changeへ登録せず、変更継続用Operation Gateを要求しません。異常を修正してafterを取得する場合は、
自動選択に頼らず表示されたchange IDを`--change-id`へ指定します。mappingsとdescription rulesはbeforeでpathとhashを
固定し、afterで継承します。

### 2.2 alredで取得済みのrawログ

```bash
alred health-check snapshot \
  --input ./raw-before \
  --input-format alred-collect \
  --phase before \
  --profile network-baseline-nxos
```

この方式は機器へ接続しません。入力ディレクトリを読んでSnapshotと判定結果を生成します。
オフライン解析の端末出力例:

```text
=== HEALTH SNAPSHOT SUMMARY ===
Change ID : HC-20260802T100000-p1234-b2c3d4
Phase     : before
Input     : alred-collect
Hosts     : 2
Warnings  : 1
Result    : UNKNOWN
Checks    : PASS=17 WARN=0 FAIL=0 UNKNOWN=1 N/A=4
Attempt   : operations/live/2026/08/02/HC-20260802T100000-p1234-b2c3d4/health/before/attempts/before-20260802T100000-p0900-b2c3d4
Manifest  : operations/live/2026/08/02/HC-20260802T100000-p1234-b2c3d4/health/before/collection-manifest.yaml
Snapshot  : operations/live/2026/08/02/HC-20260802T100000-p1234-b2c3d4/health/before/snapshot.json
Checklist : operations/live/2026/08/02/HC-20260802T100000-p1234-b2c3d4/health/before/checklist.md
Devices   : operations/live/2026/08/02/HC-20260802T100000-p1234-b2c3d4/health/before/device-summary.md
Device CSV: operations/live/2026/08/02/HC-20260802T100000-p1234-b2c3d4/health/before/device-summary.csv
```

この例では機器アクセスは発生していません。`UNKNOWN`の場合は、Manifestで不足コマンド、
対象ファイル、parse warningを確認します。

### 2.3 外部ツールや手動で取得したtranscript

```bash
alred health-check snapshot \
  --input ./transcripts/before \
  --input-format nxos-transcript \
  --phase before \
  --hosts ./hosts.lab.yaml \
  --profile network-baseline-nxos
```

transcript内のprompt、hostname、実行コマンドを解析します。複数機器が1ファイルに含まれる場合も、
区間が明確なら機器・コマンド単位に分割します。曖昧な区間は正常と推測せずUNKNOWNにします。
transcript解析の端末出力例:

```text
=== HEALTH SNAPSHOT SUMMARY ===
Change ID : HC-20260802T103000-p1234-c3d4e5
Phase     : before
Input     : nxos-transcript
Hosts     : 2
Warnings  : 2
Result    : WARN
Checks    : PASS=18 WARN=1 FAIL=0 UNKNOWN=0 N/A=3
Attempt   : operations/live/2026/08/02/HC-20260802T103000-p1234-c3d4e5/health/before/attempts/before-20260802T103000-p0900-c3d4e5
Manifest  : operations/live/2026/08/02/HC-20260802T103000-p1234-c3d4e5/health/before/collection-manifest.yaml
Snapshot  : operations/live/2026/08/02/HC-20260802T103000-p1234-c3d4e5/health/before/snapshot.json
Checklist : operations/live/2026/08/02/HC-20260802T103000-p1234-c3d4e5/health/before/checklist.md
Devices   : operations/live/2026/08/02/HC-20260802T103000-p1234-c3d4e5/health/before/device-summary.md
Device CSV: operations/live/2026/08/02/HC-20260802T103000-p1234-c3d4e5/health/before/device-summary.csv
```

`Warnings`はimport時の曖昧区間や重複候補の件数です。判定の`WARN`とは別にManifestの
import warningを確認します。

## 3. show loggingの確認範囲

確認範囲は初回beforeで指定します。

| 指定 | 意味 | 例 |
|---|---|---|
| 省略 | profileの設定。組み込みbaselineは7日 | 指定なし |
| `--logging-all` | 入力に含まれるtimestamp付き全record | 全期間調査 |
| `--logging-days N` | Snapshot実施日時からN日前以降 | `--logging-days 3` |
| `--logging-start-time` | 指定日時以降 | `2026-08-01T09:00:00+09:00` |

例:

```bash
alred health-check before \
  --collect \
  --hosts ./hosts.lab.yaml \
  --logging-start-time "2026-08-01T09:00:00+09:00" \
  --ask-pass
```

重要事項:

- 3つのCLI optionは相互排他です。
- daysはSnapshot作成日時を基準にします。
- start-timeはtimezone offset付きISO 8601を指定します。
- allでもSnapshot作成日時より未来のrecordは除外します。
- after、rollback、compare、recheckではbeforeの範囲を継承します。
- 現在はshow logging全体を収集し、解析時に範囲を絞ります。収集量自体は減りません。

実効範囲はhealth-resultのtime_range、window_start、window_endで確認できます。

```json
{
  "time_range": {
    "mode": "days",
    "days": 3
  },
  "window_start": "2026-08-02T09:15:00+09:00",
  "window_end": "2026-08-02T09:15:00+09:00"
}
```

## 4. before

推奨事項:

- 変更対象だけでなく、影響を受けるpeerや同一Fabricの必要機器を含めます。
- 自動採番されたchange IDを作業記録へ転記します。
- FAIL、UNKNOWNを解消してから設定変更へ進みます。
- WARNは内容を確認し、既存事象として許容できるか記録します。
- reload-pendingがPASSであることを確認します。

対象を限定する場合は、実行前にhostsまたはtarget hostsの内容を確認してください。

### 4.1 WARNなどを確認後にbeforeを再実行

plan、承認、applyへ進む前であれば、同じchange ID、inventory、profile、入力方式でbeforeを
再実行できます。直接収集の例:

```bash
alred health-check before \
  --collect \
  --hosts ./hosts.lab.yaml \
  --change-id CHG-2026-0802-TEST \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --logging-days 1 \
  --ask-pass
```

各実行は`health/before/attempts/<attempt-id>/`へ保存され、以前のrawログ、Snapshot、Checklistを
上書きしません。最新の成功attemptは`health/before/current.json`へ記録され、従来互換の
`health/before/snapshot.json`、`health-result.json`、`checklist.md`にも反映されます。新attemptが
失敗した場合、以前の成功済み正本は維持されます。

次の場合は収集開始前に拒否されます。

- inventory、policy、profile、logging範囲、入力方式が最初のbeforeと異なる
- Overlay plan、承認、applyがすでに開始されている
- 同じbefore attemptが実行中である

`logging-excludes.yaml`などprofile内容を変更する場合は、変更を明示し理由を記録します。

```bash
alred health-check before \
  --collect \
  --hosts ./hosts.lab.yaml \
  --change-id CHG-2026-0802-TEST \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --profile logging-excludes.yaml \
  --logging-days 1 \
  --revision-reason "確認済みのSSHスキャンログを正常性判定から除外" \
  --ask-pass
```

変更前後のprofile hash、profile名、field単位差分、理由は新attemptの
`profile-revision.json`へ保存されます。旧WARNと旧profileは以前のattemptに残り、新profileによる
収集・解析が成功した場合だけ`current.json`と`health/resolved-profiles.yaml`を更新します。
revisionが失敗した場合は以前の成功済みbeforeを維持します。

| option | 必須条件 | 内容 | 既定値 |
|---|---|---|---|
| `--revision-reason TEXT` | profileを変更する再before | 固定profileの改訂を明示する監査用理由。空文字不可 | なし |

profile差分があるのに理由がない場合、初回before、実効profileに差分がない場合、plan／承認／apply後は
revisionできません。収集済みrawを
同じ固定profile・parserで再解析するだけの場合は本書のrecheck手順を使用します。

## 5. after

beforeが直接収集の場合:

```bash
alred health-check after \
  --change-id HC-20260802T091500-p1234-a1b2c3 \
  --ask-pass
```

beforeが外部入力の場合はafter入力も明示します。

```bash
alred health-check after \
  --change-id HC-20260802T091500-p1234-a1b2c3 \
  --input ./transcripts/after \
  --input-format nxos-transcript
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
Manifest  : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/after/collection-manifest.yaml
Snapshot  : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/after/snapshot.json
Checklist : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/after/checklist.md
Devices   : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/after/device-summary.md
Device CSV: operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/after/device-summary.csv
```

before / after比較が完了すると、次の成果物も生成されます。

```text
operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/report/
├── health-result.json
└── summary.md
```

afterでは次を重点確認します。

- beforeで正常だったneighbor、route、vPC、NVEが失われていないか
- 作業期間内に新規の異常loggingが発生していないか
- reload-pendingが新たに発生していないか
- 対象host集合、profile hash、parser versionが比較可能か

## 6. rollback後のhealth check

設定切り戻し後にも同じchange IDで収集します。

```bash
alred health-check rollback \
  --change-id HC-20260802T091500-p1234-a1b2c3 \
  --ask-pass
```

beforeが`--collect`で成功している場合、同じchange IDのrollbackはbefore execution contextから
`--collect`、hosts、transport、target hosts、worker数、timeoutなどを継承します。hostsとpolicyは
保存済みSHA-256を再検証し、変更されていれば収集前に停止します。認証秘密は保存されないため、
必要に応じて`--ask-pass`などを指定します。beforeが外部ログ入力だった場合は、新しいrollback
ログを推測できないため`--input`を明示してください。
rollback healthの端末出力例:

```text
=== HEALTH SNAPSHOT SUMMARY ===
Change ID : HC-20260802T091500-p1234-a1b2c3
Phase     : rollback
Input     : alred-collect
Hosts     : 2
Warnings  : 0
Result    : PASS
Checks    : PASS=20 WARN=0 FAIL=0 UNKNOWN=0 N/A=2
Manifest  : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/rollback/collection-manifest.yaml
Snapshot  : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/rollback/snapshot.json
Checklist : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/rollback/checklist.md
Devices   : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/rollback/device-summary.md
Device CSV: operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/rollback/device-summary.csv
```

比較結果は`health/rollback-report/`へ保存され、既存のafter成果物を上書きしません。
alredによる承認済みrollback後は、共通Health比較に加えてraw / semantic config復元を統合した
`rollback/verification-checklist.md`も出力します。通常のHealth Checklistと重複する全PASS項目は
再掲せず、統合gate、機器別復元結果、非PASS理由を確認できます。

rollback HealthがWARN、FAIL、UNKNOWN、または収集・解析に失敗した場合は、同じchange IDで
再実行できます。各実行は`health/rollback/attempts/<attempt-id>/`へ分離し、以前のraw、Snapshot、
判定、verificationを上書きしません。設定rollbackコマンド自体は再送しません。

rollback後は、before状態へ戻ったこと、running config差分が残っていないこと、作業中に発生した
neighborやrouteの異常が解消したことを確認します。

## 7. 既存rawを新parserで再解析

元のSnapshotを上書きせず再解析します。

```bash
alred health-check snapshot \
  --input operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/before/raw \
  --input-format alred-collect \
  --phase before \
  --change-id HC-20260802T091500-p1234-a1b2c3 \
  --recheck
```

出力先:

```text
operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/before-recheck/
```
recheckの端末出力例:

```text
=== HEALTH SNAPSHOT SUMMARY ===
Change ID : HC-20260802T091500-p1234-a1b2c3
Phase     : before
Input     : alred-collect
Hosts     : 2
Warnings  : 0
Result    : PASS
Checks    : PASS=20 WARN=0 FAIL=0 UNKNOWN=0 N/A=2
Manifest  : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/before-recheck/collection-manifest.yaml
Snapshot  : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/before-recheck/snapshot.json
Checklist : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/before-recheck/checklist.md
Devices   : operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/before-recheck/device-summary.md
Device CSV: operations/live/2026/08/02/HC-20260802T091500-p1234-a1b2c3/health/before-recheck/device-summary.csv
```

recheckは元のbeforeを置換しません。元成果物とparser version、判定差分を比較できます。

## 8. operationの主な成果物

```text
operations/live/YYYY/MM/DD/<change-id>/
├── metadata.yaml
├── execution.json
└── health/
    ├── resolved-profiles.yaml
    ├── before/
    │   ├── current.json
    │   ├── attempts/<attempt-id>/
    │   │   ├── result.json
    │   │   ├── raw/
    │   │   ├── snapshot.json
    │   │   ├── health-result.json
    │   │   ├── device-summary.md
    │   │   └── device-summary.csv
    │   ├── raw/
    │   ├── collection-manifest.yaml
    │   ├── snapshot.json
    │   ├── health-result.json
    │   ├── checklist.md
    │   ├── device-summary.md
    │   └── device-summary.csv
    ├── after/
    │   └── ...
    ├── before-recheck/
    │   └── ...
    └── report/
        ├── health-result.json
        └── summary.md
```

各成果物の読み方は[Output Guide](./04_OUTPUT_GUIDE.md)を参照してください。

## 9. 完了した operation の手動 archive

新規 operation は作成日単位の
`operations/live/YYYY/MM/DD/<change-id>/`へ保存されます。通常の `health-check`、
`overlay-change`、`operation status`などは Operation ID から path を解決するため、日付を
option へ指定する必要はありません。既存の`operations/<change-id>/`も互換 layout として利用できます。

14 日以上経過した完了済み operation の候補だけを確認します。

```bash
uv run python alred.py operation archive --dry-run
```

確認後に archive します。自動 archive は実行されません。

```bash
uv run python alred.py operation archive
```

1 件だけを対象にする場合や日数を変更する場合は次のように実行します。

```bash
uv run python alred.py operation archive \
  --change-id CHG-2026-00123 \
  --older-than-days 30
```

`cron`から実行する場合も専用の自動処理ではなく、この CLI を起動します。最初は
`--dry-run`の結果を log へ保存して対象を確認し、その後に実行 command を登録してください。

```cron
20 3 * * * cd /opt/alred && uv run python alred.py operation archive >> logs/operation-archive.log 2>&1
```

archive 対象は`completed`、`completed_with_warnings`、`cancelled`かつ lock がない operation
だけです。`failed`、`state_unknown`、進行中の operation は保存容量だけを理由に archive しません。
出力は`operations/archive/YYYY/MM/DD/<change-id>.tar.gz`と checksum file です。

archive 後も次は展開せずに利用できます。

```bash
uv run python alred.py operation status --change-id CHG-2026-00123
uv run python alred.py operation inspect --change-id CHG-2026-00123
```

一方、archive 済み operation に対する phase 追加、apply、rollback、Support Bundle／Evidence Package 作成、
reference state 利用は暗黙に展開せず`OPERATION_ARCHIVED`で停止します。現時点では restore CLI を
提供していないため、後からこれらを利用する可能性がある operation は archive しないでください。
