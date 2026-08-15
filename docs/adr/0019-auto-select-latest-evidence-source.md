# ADR-0019: Evidence Package の最新成功 before source を自動選択する

## 状態

Accepted

## Context

`evidence-package create` で毎回 `--change-id` または `--collection-manifest` を指定すると、通常運用で同じ
Operation 情報を手作業で転記する必要がある。一方、directory の更新時刻や最新実行 attempt を選ぶだけでは、失敗中または
partial な収集世代を誤って Package 化する可能性がある。

## Decision

- source option を省略した場合は、live Operation の `health/before/current.json` が指す正常公開済み attempt だけを候補にする。
- `completed_at` が最も新しい候補を選択し、file 更新時刻や Operation metadata の `current_attempt` は選択根拠にしない。
- 最新完了時刻が同じ候補が複数ある場合は fail closed とし、`--change-id` による明示選択を要求する。
- `--change-id` は指定 Operation の current before attempt を選ぶ上書き手段とする。
- `--collection-manifest` と `--input` は、Operation 以外の source または厳密な手動選択の互換経路として維持する。
- archived Operation は透過展開せず、将来の selective restore 実装まで source にしない。
- legacy flat layout の raw-only directory は current before source を持たないため自動選択から除外する。
- legacy directory に `current.json` がある場合は完全な Operation として検証し、不整合を黙ってスキップしない。

## Consequences

- 通常の Digital Twin／AI Package 作成では source path の転記が不要になる。
- 自動選択しても、選択済み attempt と Manifest は Package 作成中に固定され、後続 Operation の完了で切り替わらない。
- 同時刻候補や破損 current pointer では自動継続せず、利用者による source 確認が必要になる。
- 古い raw-only copy が `operations/` 直下に残っていても、正常な最新 Operation の選択を妨げない。
- 初期 Operation source は before／current に限定し、任意 phase／attempt は別途拡張する。
