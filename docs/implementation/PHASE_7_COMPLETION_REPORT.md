# Phase 7 Completion Report

## 1. 結論

Phase 7「health-check / overlay-check CLI」は2026-07-29に完了した。既存ログを使うoffline
経路と、既存collect runnerを使うdirect経路の両方でbefore / after Snapshot、共通比較、
Overlay発見・評価・収束判定をoperation workspaceへ保存できる。

自動テストではdeviceへ接続せず、direct経路の既存runner呼び出しと保存先をmockで確認した。

## 2. Health Check CLI

```bash
alred health-check before \
  --hosts hosts.yaml \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --collect

alred health-check after \
  --hosts hosts.yaml \
  --collect
```

`--collect`は機器へ直接アクセスする。resolved profileからshow command fileを生成し、
既存collectの接続、credential、transport、timeout、running-config取得を再利用する。

offline入力:

```bash
alred health-check before \
  --input raw-before \
  --input-format alred-collect \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos

alred health-check after \
  --input raw-after \
  --input-format alred-collect \
  --change-id CHG-2026-00123
```

afterは単体判定後にbefore / after compareも実行する。

## 3. change-idとOperation Gate

- beforeでchange-id省略時はJST既定で自動採番
- hosts hash、profile hash、before Snapshot、operation状態をactive stateへ保存
- after省略時は一致するactiveな自動採番beforeだけを再利用
- CPU連続高負荷またはreload-pending gateはTTYでのみ継続確認
- 非対話または未承認は`stop`としてHealthResultへ記録
- gate承認は警告をPASSへ変更せず、applyが別途確認する

## 4. Overlay CLI

- `overlay-check discover`: before / afterからChangeSet生成
- `overlay-check evaluate`: configuration / operational / impact判定
- `overlay-check converge`: 保存済み結果を指定順に連続PASS判定

Overlay CLI自体はCollectorを持たず、直接収集は共通Health Check CLIへ集約する。

## 5. 成果物

```text
health/<phase>/raw/
health/<phase>/show-commands.txt
health/<phase>/collect.log
health/<phase>/collection-manifest.yaml
health/<phase>/snapshot.json
health/<phase>/health-result.json
health/report/health-result.json
health/report/summary.md
overlay/discovered-changes.yaml
overlay/health-result.json
overlay/overlay-summary.md
overlay/convergence.json
```

## 6. 検証範囲

pytestでoffline before/after、direct collect runner adapter、raw path、command list、profile固定、
change-id自動引継ぎ、自動compare、Overlay evaluate成果物、ordered convergence成果物を確認した。
Nexus 9000vのcredential、transport fallback、timeout、実収束時間はPhase 10で確認する。
hardware 4機種は動作検証対象外とする。
