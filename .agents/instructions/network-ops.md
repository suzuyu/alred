# Network Operations Instructions

## Scope

operation、Health Check、Overlay、VNI、config生成、apply、save、rollback、support bundleを変更または
実行するときに適用する。

## Rules

- 作業開始前に責務を持つ設計書、operation state、error catalog、実装状況を確認する。
- collect、parser、evaluator、renderer、executorの責務を分離し、同じ処理を別経路へ複製しない。
- plan前とapply直前に設定済み、競合、不明を検査し、安全に判定できない場合はfail closedとする。
- apply前後のconfig、command response、save response、hash、対象deviceをoperationから追跡可能にする。
- rollbackはoperation所有変更だけを逆順で戻し、beforeのrawおよびsemantic configとの差分を検証する。
- attemptは不変とし、失敗attemptを削除・上書きしない。成功済みcurrentと最新実行attemptを区別する。
- partial attempt、stale pointer、canonical artifactとの不一致を想定し、公開前に必須artifactとhashを検証する。
- 既知の利用者修正可能errorではcodeと対処可能なmessageを出し、Tracebackを表示しない。
- support bundleはallowlist、redaction、secret scanを通し、未加工のoperationやraw logを共有しない。

## Sources

- [Design index](../../docs/design/README.md)
- [Operation State and Approval](../../docs/design/common/OPERATION_STATE_AND_APPROVAL_DESIGN.md)
- [Implementation Status](../../docs/implementation/IMPLEMENTATION_STATUS.md)
