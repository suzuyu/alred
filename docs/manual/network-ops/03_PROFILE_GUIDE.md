# Profile Guide

profileは、収集コマンド、parser、check、閾値、収束条件をまとめたHealthCheckProfile YAMLです。
実行時に解決された内容とhashはresolved-profiles.yamlへ保存されます。
実行環境とinventoryの準備は[Common Preparation](./00_COMMON_PREPARATION.md)を参照してください。


## 1. 組み込みprofile

| 名前 | 用途 |
|---|---|
| `network-baseline-nxos` | NX-OS共通baseline。CPU、memory、logging、route、OSPF、BGP、vPCなど |
| `nxos-overlay` | EVPN/VXLAN。NVE、VNI、EVPN、VRF、SVIなど |

baselineだけを使用:

```bash
alred health-check before \
  --collect \
  --hosts ./hosts.lab.yaml \
  --profile network-baseline-nxos \
  --ask-pass
```

baselineとOverlayを合成:

```bash
alred health-check before \
  --collect \
  --hosts ./hosts.lab.yaml \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --ask-pass
```

profileは指定順に合成されます。カンマ区切りではなく、profileごとにoptionを繰り返します。
VNI mapを含む作業前後の確認例は
[NX-OS Overlay Health Check](./06_NXOS_OVERLAY_HEALTH_CHECK.md)を参照してください。

## 2. 省略時の動作

初回beforeでprofileを省略すると、network-baseline-nxosが使用されます。

```bash
alred health-check before --collect --hosts ./hosts.lab.yaml --ask-pass
```

profileを1件でも明示すると、既定profileは自動追加されません。nxos-overlayだけを指定した場合、
共通baselineは含まれません。

after、rollback、compare、recheckでは、beforeのresolved-profiles.yamlを継承します。通常は
profileを再指定しません。

## 3. profileファイルの指定

相対パスを推奨します。

```bash
alred health-check before \
  --collect \
  --hosts ./hosts.lab.yaml \
  --profile ./profiles/site-a-baseline.yaml \
  --ask-pass
```

絶対パスも指定できます。

```bash
alred health-check before \
  --collect \
  --hosts ./hosts.lab.yaml \
  --profile /opt/alred/profiles/site-a-baseline.yaml \
  --ask-pass
```

## 4. サンプルprofile

実行可能な完全例:

[health-check-profile.network-baseline-logging-3days.example.yaml](../../../alred/sample_configs/health-check-profile.network-baseline-logging-3days.example.yaml)

`generate-sample-config`で配布サンプルを生成し、作業用ディレクトリへコピーします。

```bash
alred generate-sample-config --output-dir ./samples
mkdir -p ./profiles
cp ./samples/health-check-profile.network-baseline-logging-3days.example.yaml \
  ./profiles/site-a-baseline.yaml
```

コピー後、最低限次をレビューします。

- metadata.nameとmetadata.version
- collectorsに含まれるコマンド
- checksとseverity
- CPU、memory、route、loggingの閾値
- operation gate
- 対象NX-OSでコマンドが利用可能か

## 5. profile構造の抜粋

次は項目を説明するための抜粋で、単独では実行できません。実際に使用する場合は、上記の完全な
サンプルをコピーし、必要な項目を変更してください。

```yaml
api_version: alred/v1
kind: HealthCheckProfile

metadata:
  name: site-a-baseline
  version: "1.0"
  description: Site A NX-OS baseline

spec:
  platforms:
    - nxos

  collectors:
    nxos:
      commands:
        # 完全なコマンド定義はサンプルを参照

  checks:
    # 完全なcheck定義はサンプルを参照

  thresholds:
    logging:
      severity_threshold: 4
      time_range:
        mode: days
        days: 3
      include_patterns: []
      exclude_patterns: []
```

HealthCheckProfile v1ではspec.platformsとspec.checksが必須です。logging閾値だけを記載した
断片profileではなく、組み込みbaselineをコピーした完全profileを使用するのが確実です。

コピー版にはbaselineと同じcheck IDが含まれるため、次の指定は行いません。

```text
NG:
--profile network-baseline-nxos
--profile ./profiles/site-a-baseline.yaml
```

コピー版をbaselineとして単独指定し、必要ならnxos-overlayを追加します。

```bash
alred health-check before \
  --collect \
  --hosts ./hosts.lab.yaml \
  --profile ./profiles/site-a-baseline.yaml \
  --profile nxos-overlay \
  --ask-pass
```

## 6. logging範囲

### 6.1 全期間

```yaml
thresholds:
  logging:
    severity_threshold: 4
    time_range:
      mode: all
    include_patterns: []
    exclude_patterns: []
```

### 6.2 実施日時からN日前

```yaml
thresholds:
  logging:
    severity_threshold: 4
    time_range:
      mode: days
      days: 3
    include_patterns: []
    exclude_patterns: []
```

### 6.3 指定日時以降

```yaml
thresholds:
  logging:
    severity_threshold: 4
    time_range:
      mode: start-time
      start_time: "2026-08-01T09:00:00+09:00"
    include_patterns: []
    exclude_patterns: []
```

start_timeにはtimezone offsetが必要です。time_rangeを指定した場合、後方互換用
lookback_secondsよりtime_rangeが優先されます。

CLIのlogging optionを指定すると、profileファイルを変更せず今回のoperationだけ上書きできます。

```bash
alred health-check before \
  --collect \
  --hosts ./hosts.lab.yaml \
  --profile ./profiles/site-a-baseline.yaml \
  --logging-days 1 \
  --ask-pass
```

## 7. resolved profileの確認

plan前に固定profileを変更する必要がある場合は、通常の再実行では暗黙に変更せず、
`--revision-reason`で改訂理由を明示します。詳細な実行例と制約は
[Health Check Operations](./02_HEALTH_CHECK_OPERATIONS.md#41-warnなどを確認後にbeforeを再実行)を
参照してください。変更前後のprofileはattemptごとに保存されます。

実行後:

```bash
less operations/<change-id>/health/resolved-profiles.yaml
```

出力例:

```yaml
metadata:
  change_id: HC-20260802T091500-p1234-a1b2c3
  resolved_at: "2026-08-02T09:15:00+09:00"
  timezone: Asia/Tokyo

spec:
  resolved:
    profile_names:
      - site-a-baseline
    effective_sha256: sha256:0123456789abcdef...
    effective:
      spec:
        thresholds:
          logging:
            severity_threshold: 4
            time_range:
              mode: days
              days: 1
    overrides:
      - path: spec.thresholds.logging.time_range
        previous_value:
          mode: days
          days: 3
        effective_value:
          mode: days
          days: 1
        effective_source: cli
```

レビューではprofile名、hash、実効閾値、CLI overrideを確認します。
