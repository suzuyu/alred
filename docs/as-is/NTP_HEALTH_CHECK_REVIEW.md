# NTP Health Check 実装レビュー

- Status: `integrated`。下記は修正前の観測記録。profile `1.9`／parser `1.22` で修正済み
- Integrated date: 2026-09-12
- 現行仕様: [設計 7.10](../design/network-ops/NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md#710-ntpと装置時刻)
- 検証: [NTP 回帰テスト](../../tests/test_health_ntp.py)。実機検証は未実施
- Last reviewed: 2026-09-12
- Scope: working tree の `network-baseline-nxos` `1.8`／NX-OS parser `1.21`
- 本書は調査結果であり、誤判定を正式仕様として定義するものではない

## 1. 結論

**Observed:** 正常な selected peer の証跡があっても `WARN` になる実装不備を offline で再現した。
`show ntp status` の配布状態を時刻同期状態と混同している。既存設計 7.10 にも同じ誤りがある。
外部環境の実際の原因は、使用 binary の version と当該 WARN の入力を未取得のため未確定。

## 2. Command と修正前の解析箇所

| command / ID | 読み取る箇所 | Snapshot field と現行の利用方法 |
|---|---|---|
| `show ntp status` / `ntp_status` | `Clock is synchronized`／`Clock is unsynchronized`、`stratum <n>`、`reference is <address>` | `common.ntp.synchronized`、`stratum`、`reference`。同期状態の分岐を決める |
| 同上 | `Distribution : Disabled` または `Last operational state: No session` | **不具合:** `synchronized: false` を設定する。明示同期行より先にこの条件を評価する |
| `show ntp peers` / `ntp_peers` | 行頭の任意 marker と直後の IP address | `common.ntp.peers.<address>.selected`。`*` だけを selected とする。通常の NX-OS の `Peer IP Address / Serv/Peer` 一覧は選択状態を示さない |
| `show ntp peer-status` / `ntp_peer_status` | `Total peers`、peer 行頭の `*`／`+`／`-`／`=`、`remote local st poll reach delay vrf` の各列 | `common.ntp.peer_status.peers.<remote>`。`*` を selected、`st` を stratum、`reach` を到達性として使う。`poll`／`delay`／`local`／`vrf` は保存するが合否閾値には使わない |
| `show clock` / `clock` | 行頭の `Time source is ...` | `common.clock.time_source` を `after.clock_time_source` と message に転記する。現在の NTP 判定を上書きしない |

実装入口は [parser](../../alred/health/parsers.py) の `_parse_ntp_status`、`_parse_ntp_peers`、
`_parse_ntp_peer_status` と、[evaluator](../../alred/health/evaluator.py) の `_evaluate_ntp`／`_compare_ntp`。

現行の単体判定は、configured かつ `synchronized: true` の場合に限り selected peer を健全性評価する。
詳細 peer が 1 件でもあれば peers 一覧より優先し、selected peer があり、selected peer 全件が
`reach >= 1` かつ `1 <= stratum <= 15` の場合に `PASS`。満たさない場合は `WARN`。
`synchronized: false` または field 欠落なら、selected peer がいても既定 `WARN`、NTP 必須なら `FAIL`。
前後比較では `synchronized` の喪失または選択済み address の消失を `FAIL / regression` とする。

## 3. 主な不具合と再現

次は documentation address を使用した合成入力であり、現地 raw log ではない。

```text
show ntp status:
Distribution : Disabled
Last operational state: No session

show ntp peers:
Peer IP Address Serv/Peer
192.0.2.123 Server (configured)

show ntp peer-status:
Total peers : 1
*192.0.2.123 192.0.2.10 3 64 377 0.12300 management

show clock:
13:00:00.000 JST Sat Sep 12 2026
Time source is NTP
```

現行 parser は詳細 peer の `selected: true`、stratum `3`、reach `377` を取得できる。
しかし status parser が `synchronized: false` にするため、結果は `WARN` となり、message は次になる。

```text
NTP is configured but unsynchronized (operational state: No session; no selected peer; clock time source: NTP)
```

`no selected peer` も不正確である。この分岐では `show ntp peers` だけの marker を見ており、
選択済みの `show ntp peer-status` を反映していない。

**Documented:** [NX-OS 10.4(x) command reference](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/104x/command-reference/show/b_n9k_show_commands_104x/m_n_showcmds.html)
は `show ntp status` を NTP distribution status の表示と定義している。
[Cisco の NX-API command 例](https://developer.cisco.com/docs/cisco-nexus-9000-series-nx-api-cli-reference/latest/ntp-commands/)
にも上記の配布状態と peer-status の列が掲載されている。
配布状態の `Disabled`／`No session` だけから、時計が未同期とは判定できない。

## 4. 併せて確認した問題

| 問題 | 観測結果・影響 |
|---|---|
| `delay` と `vrf` が連結した行 | `0.12300management` を `float()` に変換できず行を黙って捨てる。他の行が正常なら source 全体は parsed となり、選択 peer だけを見落とせる。Cisco の NX-API 文書にも列連結例がある。現地で同形式かは未確認 |
| 同じ remote address の重複 | address だけを辞書 key にし、後続行で上書きする。別 VRF の非選択行で selected が消えるケースを再現。曖昧性の検出がない |
| 必須 source の欠落 | source が存在する場合だけ parse status を確認するため、`ntp_peers` が未収集でも他の証跡だけで `PASS` になり、`ntp_status` が未収集でも `WARN` になる。既存設計の `UNKNOWN` と不一致 |
| NTP 必須時の severity | 同期済み分岐では selected peer の reach が 0 でも `WARN` のまま。既存設計では `required: true` は `FAIL` |
| stratum／reach の解釈 | 現行は stratum 1～15、reach は表示を十進整数として保存する。[Cisco の Nexus 10.2(5) 向け資料](https://www.cisco.com/c/en/us/support/docs/switches/nexus-9000-series-switches/221746-configure-network-time-protocol-on-nexus.html)は 10.1(1) 以降の同期可能 stratum に 13 以下という制約を記載。release 別条件と reach の表現は別途設計確認が必要。今回の selected peer の誤 WARN を直接説明するものではない |

## 5. 検証と修正方針

**Observed:** 一時的な pytest 再現確認 8 件と既存 `tests/test_health_phase3.py` の 63 件、計 71 件を実行。
8 件は現行挙動を確認する characterization であり、不具合修正後の受け入れテストではない。
配布状態＋selected peer、明示同期行と配布状態の併記、列連結、NTP 必須、必須 source 欠落、
重複 address を再現し、明示同期行だけの入力では `PASS` になる対照も確認した。実機接続は未実施。

**Recommended:** 配布状態と時計同期状態を分離し、`show ntp peer-status` の選択・健全性を
同期判定へ正しく接続する。壊れた行を正常な空集合や peer 消失へ変換せず、曖昧な場合は `UNKNOWN` とする。
修正時は source 優先順位、旧 Snapshot の再評価、VRF identity、前後比較を先に設計へ反映し、
parser／profile version と fixture を更新する。詳細な修正仕様は未統合、実装コードは本レビューでは変更していない。

**Unknown:** 外部環境の version、WARN message、4 command の同一収集時点の出力。
取得時点差、実際の reach／stratum 異常、収集欠落による WARN かどうかは、その証跡との照合が必要。
