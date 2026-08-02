# Phase 3 Completion Report

## 1. 結論

Phase 3「共通baseline evaluator」は2026-07-29に完了した。profileを固定したbefore単体判定と
before / after比較をofflineで実行し、`PASS`、`WARN`、`FAIL`、`UNKNOWN`、
`NOT_APPLICABLE`を機械可読JSONとMarkdownへ出力できる。

機器への直接アクセス、CPU再sample、対話継続確認は実施しない。これらはPhase 7で既存collect
runnerへ接続する。

## 2. Profile

- builtin `network-baseline-nxos` / `nxos-overlay`
- 利用者管理`HealthCheckProfile` YAML
- 指定順を保持したcommand和集合とcheck ID一意性
- 同じcommand IDの競合をfail closed
- 後指定profileによるthreshold / convergence / gate override
- override pathと値の記録
- canonical effective SHA-256
- `health/resolved-profiles.yaml`によるbefore / after条件固定
- after / compareでのprofile hash不一致拒否

## 3. ParserとEvaluator

Phase 2の7 commandに、environment、IPv4 route summary、OSPF、BGP IPv4を追加し、
C9300v 10.5(4) sanitized fixtureは11 commandとなった。

共通baselineの初期判定:

- 必須command completenessとparse成否
- system identity、NX-OS version、uptime低下
- CPU 1分値、既定80%以上WARN
- memory既定85% WARN / 95% FAIL
- hardware environment alarm
- reload-pendingの既存・追加・解消
- VRF別IPv4 route countの10% WARN / 30% FAIL
- OSPF FULL neighborの消失
- IPv4 BGP Established peerの消失
- vPC peer / keepalive / consistency

`nxos-overlay`初期判定:

- NVE interface state
- EVPN BGP configured / capable peerとEstablished state

## 4. CPU連続sample

閾値は`>=`で判定する。単一高値はWARNと`HIGH_CPU`を記録し、途中で閾値未満になれば
連続回数をresetする。profile既定3回連続で`SUSTAINED_HIGH_CPU`となり、Operation Gateを
requiredにする。

Phase 3のoffline入力は再sampleしない。Phase 7のdirect runnerが既存collectを使って追加sampleを
取得し、sample列を同じEvaluatorへ渡す。

## 5. CLIと成果物

`health-check snapshot`はPhase 2のSnapshotに加え、次を出力する。

```text
health/resolved-profiles.yaml
health/<phase>/health-result.json
health/<phase>/checklist.md
```

offline比較:

```bash
alred health-check compare \
  --before operations/CHG-2026-00123/health/before/snapshot.json \
  --after operations/CHG-2026-00123/health/after/snapshot.json
```

出力:

```text
health/report/health-result.json
health/report/summary.md
```

終了codeはPASS / NOT_APPLICABLE=`0`、WARN=`1`、入力不正=`2`、UNKNOWN=`3`、FAIL=`4`とする。

## 6. 検証と制約

- profile合成、閾値override、重複check拒否
- 11 command parser
- CPU境界値80%、連続回数reset、sustained gate
- 必須parser不足をUNKNOWNとすること
- CPU / reload-pending regression
- route count、OSPF、BGP neighbor regression
- snapshot / compare CLIと成果物

未実装parserを正常とみなさずprovenanceへ`unsupported`として残す。interface、module、logging、
NTP、BFD、port-channelなど全baseline commandのparser / evaluatorは、対応fixtureを追加する
後続拡張とする。対象hardwareの合否保証や`APPLY_VERIFIED`昇格は行っていない。
