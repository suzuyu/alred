# network-baseline-nxos Profile Guide


Checklist に出力する check ID は、組み込み
[network-baseline-nxos.yaml](../../../../alred/health/profiles/network-baseline-nxos.yaml) version `1.9` では
次の 22 項目です。以下は現行の [evaluator](../../../../alred/health/evaluator.py) と組み込み profile を
照合した利用者向けの要約です。仕様の正本は
[NX-OS Baseline Health Check Commands](../../../design/network-ops/NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md) とし、
確認した実装上の制約・設計との差は 3 に分けて記載します。

`before` や `snapshot` の単体判定と、`after` / `compare` の前後比較では確認内容が異なります。
表の数値は組み込み既定値です。独自 profile や CLI override を使った実行では、
[resolved profile](../03_PROFILE_GUIDE.md#7-resolved-profileの確認) と `health-result.json` の実効値を確認してください。
収集・解析不足は原則 `UNKNOWN`、機能未設定などの対象外は `NOT_APPLICABLE` です。
`severity: fail` はすべての異常を一律 `FAIL` にする指定ではなく、各 evaluator の条件が適用されます。

## 1. 出力項目・目的・判定内容

| Check ID | 目的・主な確認内容 | 単体判定の条件・既定閾値 | 前後比較での主な確認 |
|---|---|---|---|
| `collection_complete` | 判定に必要な収集・解析の完了 | profile の必須 command がすべて解析済みなら `PASS`、不足は `UNKNOWN` | before / after 双方の必須証跡を確認 |
| `system_identity` | NX-OS version、model、uptime の識別 | system 情報を取得できれば `PASS`、取得不能は `UNKNOWN` | uptime 減少は `FAIL`、version 変更は `WARN` |
| `hostname_identity` | 対象機器の取り違え防止 | inventory hostname と `show version` の hostname が完全一致すれば `PASS`、不一致は `FAIL`、取得不能は `UNKNOWN` | after の一致を再確認し、悪化・改善を分類 |
| `lldp_evidence_completeness` | LLDP と description の判定に必要な証跡の充足 | 完備なら `PASS`、両端収集済みの片方向 LLDP は `WARN`、取得・解析不能、曖昧な証跡や未評価 claim は `UNKNOWN` | 判定の悪化・改善を比較。link 単位の変化分類は未実装 |
| `lldp_description_consistency` | 双方向 LLDP で確認した接続と description の整合 | 対向 device / interface の不一致は `WARN`、不一致なしは `PASS`、評価対象の双方向 link がなければ `NOT_APPLICABLE` | 判定の悪化・改善を比較 |
| `cpu_utilization` | CPU 負荷。既定は 1 分平均、取得不能時は 5 秒値 | 評価 sample に 80% 以上があれば `WARN`、なければ `PASS`。CPU 使用率だけによる `FAIL` 閾値はない | after の同じ閾値判定と、before からの判定変化 |
| `memory_utilization` | memory 使用率 | 85% 未満は `PASS`、85% 以上 95% 未満は `WARN`、95% 以上は `FAIL` | after の同じ閾値判定と、before からの判定変化 |
| `environment_health` | 電源・fan・温度などの環境 alarm | 正常は `PASS`、alarm は `FAIL`、センサー非対応 platform は `NOT_APPLICABLE`。温度の固定数値ではなく装置の状態表示を評価 | 正常から異常への変化を検出 |
| `clock_health` | 装置時刻と command 取得時刻の絶対差 | 60 秒以下は `PASS`、60 秒超 300 秒以下は `WARN`、300 秒超は `FAIL`。外部 transcript は `NOT_APPLICABLE` | after の時刻差を同じ閾値で評価 |
| `ntp_health` | NTP の選択 peer と同期状態。[command・解析列・判定の詳細](../../../design/network-ops/NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md#710-ntpと装置時刻) | 既定は NTP 任意。未設定は `NOT_APPLICABLE`、selected peer の reach が正値かつ stratum 1～13 なら `PASS`。未選択・不健全は `WARN`、NTP 必須なら `FAIL`。配布状態から同期を推定せず、証跡不足・矛盾は `UNKNOWN` | 同期喪失・選択 peer 消失は `FAIL`。片側の証跡が不明なら `UNKNOWN` |
| `interface_health` | interface の admin / operational 状態。[解析・正規化・判定の詳細](../../../design/network-ops/NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md#79-network-baseline-nxosinterface_health) | admin-up／operational-down は `FAIL`。`show interface` の明示 admin state で物理 port を補完し、admin-down は異常対象から除外。確定異常がなく証跡不足・矛盾があれば `UNKNOWN`、すべて確認できれば `PASS` | before で up だった interface の消失・down は `FAIL`。operational 証跡が矛盾する port は `UNKNOWN` |
| `interface_error_health` | interface error counter の累積値・増加量 | 累積値の合計が 0 なら `PASS`、正値なら `WARN` | 既存 counter の最大増分が 1 以上で `WARN`、100 以上で `FAIL`。減少は `UNKNOWN`。before にない正値 counter は `WARN` |
| `interface_utilization` | operational-up の Ethernet / port-channel の送受信利用率 | 最大利用率 70% 未満は `PASS`、70% 以上 90% 未満は `WARN`、90% 以上は `FAIL`。50% 以上 70% 未満は `PASS` のまま表示 severity を `INFO` にする。対象なしは `NOT_APPLICABLE` | after の同じ閾値判定と、before からの判定変化 |
| `port_channel_health` | port-channel の up 状態と bundled member | down または必要な bundled member がなければ `FAIL`、正常は `PASS`、未設定は `NOT_APPLICABLE`。physical member を持たない virtual peer-link は member 判定対象外 | up channel の消失・down、bundled member の消失は `FAIL` |
| `reload_pending` | 再起動が必要な未反映設定の有無 | pending なしは `PASS`、ありは `WARN` | 新規 pending command は `FAIL`、既存だけ残る場合は `WARN`、解消は `PASS` |
| `running_config_diff` | running-config と startup-config の未保存差分 | 差分なしは `PASS`、差分ありは `WARN` | after の未保存差分を再評価 |
| `logging_health` | 指定期間内の異常 log 候補 | 既定は直近 7 日、severity 0～4 または include 条件に一致し、exclude 条件に一致しない候補が 1 件以上で `WARN`、0 件で `PASS` | 作業期間内の新規候補があれば `WARN`。既存候補と分離 |
| `ipv4_route_count` | VRF 別 IPv4 route 数の取得と減少検出 | route summary を取得できれば `PASS`。単体の最低 route 数は設定していない | 既存 VRF の最大減少率が 10% 未満は `PASS`、10% 以上 30% 未満は `WARN`、30% 以上は `FAIL`。VRF 消失は `FAIL`。新規 VRF は分離して記録 |
| `ospf_neighbor_health` | OSPF neighbor の隣接状態 | 観測 neighbor がすべて `FULL` なら `PASS`、非 `FULL` があれば `FAIL`、未適用は `NOT_APPLICABLE` | before の `FULL` neighbor の消失・状態悪化は `FAIL` |
| `bgp_ipv4_health` | IPv4 unicast の static BGP peer | 設定を取得できる場合は各 static peer の存在と `Established` を確認し、不足・異常は `FAIL`、すべて正常なら `PASS`、static peer なしは `NOT_APPLICABLE` | before の `Established` peer の消失・状態悪化は `FAIL` |
| `bgp_dynamic_neighbor_health` | IPv4 / IPv6 dynamic neighbor range 内の peer | 設定 range なしは `NOT_APPLICABLE`、range 内 peer 0 件は `WARN`、非 `Established` peer ありは `FAIL`、全 peer 正常は `PASS`。設定・必要 summary が不明なら `UNKNOWN` | after の range 判定と、以前 peer がいた range の全 peer 消失を確認。全消失は `FAIL` |
| `vpc_health` | vPC peer と consistency の健全性 | 正常は `PASS`、peer / consistency 異常は `FAIL`、未適用は `NOT_APPLICABLE` | 正常から異常への変化を検出 |

## 2. 数値閾値の設定先

次の path は profile の `spec.thresholds` 配下です。境界値の「以上」と「超」は区別してください。

| 設定 path | 組み込み既定値 | 適用内容 |
|---|---|---|
| `cpu.metric` / `cpu.warn_percent` | `one_minute_percent` / `80` | CPU の判定 metric と `WARN` 下限 |
| `cpu.required_consecutive_samples` / `cpu.sample_interval_seconds` | `3` / `15` | 継続超過の評価条件。sample 1 件の超過でも check は `WARN`。取得済みログから不足 sample を補って連続超過とはしない |
| `memory.warn_percent` / `memory.fail_percent` | `85` / `95` | memory 使用率の `WARN` / `FAIL` 下限 |
| `clock.warn_offset_seconds` / `clock.fail_offset_seconds` | `60` / `300` | 絶対時刻差がこの値を超える場合に `WARN` / `FAIL` |
| `ntp.required` | `false` | `true` なら未設定・未同期・選択 peer の不健全を `FAIL`。証跡不足は `UNKNOWN` |
| `interface_errors.warn_delta` / `interface_errors.fail_delta` | `1` / `100` | 前後比較の既存 counter 最大増分の下限 |
| `interface_utilization.info_percent` / `warn_percent` / `fail_percent` | `50` / `70` / `90` | 最大送受信利用率の表示 `INFO` / 判定 `WARN` / `FAIL` 下限 |
| `logging.severity_threshold` / `logging.lookback_seconds` | `4` / `604800` | severity 0～4、直近 7 日。`time_range` 指定時は期間指定を優先 |
| `logging.include_patterns` / `logging.exclude_patterns` | `[]` / `[]` | 異常候補への追加条件 / 除外条件 |
| `route_count.warn_decrease_percent` / `route_count.fail_decrease_percent` | `10` / `30` | 既存 VRF の route 減少率の下限。before が正値の場合、`(before - after) / before × 100` を小数点以下 2 桁に丸めて評価 |

数値閾値のない項目は、1 の状態・存在・一致条件で評価します。
詳細な取得 command と判定根拠は
[共通 command 一覧](../../../design/network-ops/NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md#3-coreコマンド)、
[feature command 一覧](../../../design/network-ops/NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md#4-featureコマンド)、
[判定ポリシー](../../../design/network-ops/NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md#7-判定ポリシー)を参照してください。

## 3. 現行実装の制約・設計との差

- `interface_health`: [明示 admin 状態の補完](../../../design/network-ops/NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md#7910-show-interface-による-admin-状態補完)は物理 Ethernet／breakout が対象。
  `show interface` がない旧ログや当該 port を解析できない場合、未装着表示だけでは admin state を
  確定せず `UNKNOWN` とする。既存 operation の固定 profile には command を自動追加しないため、
  新規 before または明示 profile revision が必要。追加 command の実機検証は未実施。
- `ntp_health`: 通常の NX-OS 出力では `show ntp peer-status` の詳細証跡が必要。
  詳細を取得できず、従来入力の明示同期行もない場合は `UNKNOWN`。
  旧 parser が peer 行を失った Snapshot は、元 raw を新 parser で再 import する必要がある。
  同じ remote address が複数 VRF に現れる場合は、曖昧な対応を避けて `UNKNOWN` とする。
  修正の経緯は [NTP 実装レビュー](../../../as-is/NTP_HEALTH_CHECK_REVIEW.md)を参照。実機検証は未実施。
- `ospf_neighbor_health` / `vpc_health`: 現行実装は正規化状態がない場合も `NOT_APPLICABLE` を返す。
  設計上の「未収集・解析不能は `UNKNOWN`」と異なるため、未使用と断定せず収集証跡を確認する。
- `bgp_ipv4_health`: running config が得られない場合は summary の観測 peer で評価する。
  設定との照合による static peer の欠落検出はできない。summary もなく設定済みと確認できない場合は
  `NOT_APPLICABLE` になるため、収集不足との区別に注意する。
- `interface_error_health`: 現行実装では片側の counter 情報がなければ after の単体判定へ戻る。
  counter 減少は一律 `UNKNOWN` で、uptime による reset 識別や counter 種別・role 別閾値は未実装。
- dynamic BGP の一部 peer 消失、LLDP の link 単位の変化分類など、設計上の比較をすべて実装済みとはしない。
  現行の dynamic BGP 比較は判定変化と range 内の全 peer 消失を検出する。

これらは現行動作の説明であり、設計の変更ではありません。実装状態は
[Implementation Status](../../../implementation/IMPLEMENTATION_STATUS.md#31-baseline-チェック一覧で確認した差分)を参照してください。
