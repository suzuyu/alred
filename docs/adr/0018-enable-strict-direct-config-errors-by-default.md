# ADR-0018: Direct Config Push の CLI error 検出を default で有効にする

## 状態

Accepted

## Context

現行`push-config`／`push-config-dir`は transport exception を検出する一方、NX-OS CLI response 内の error text を
検出しない互換動作を持つ。このため、device が command を拒否しても success と集計される可能性があり、
Containerlab の boot 後 config 投入を含む標準経路には不十分である。

## Decision

- Direct Config Push の CLI error 検出を default で有効にする。
- 未許可 error では対象 host の残りを停止し、他 host は継続する。
- 既知の許容可能な response は`--allow-cli-error-pattern`で限定する。
- 利用非推奨の緊急互換 option として`--ignore-all-cli-errors`を提供するが、error の検出と記録は継続する。
- `--ignore-all-cli-errors`と allowlist または save の同時指定を拒否する。
- 今回の実装、fixture、回帰試験を通して default を一度に移行し、段階的 opt-in 期間は設けない。

## Consequences

- 以前 success 扱いだった投入が failure になる可能性があるため、release note で behavior change を通知する。
- config error を含む host が自動保存されることを防げる。
- 一時的な互換性が必要な場合も、無視した error と非推奨 option 使用を追跡できる。
- NX-OS error pattern の false positive／negative を sanitized fixture と mock response で継続的に検証する必要がある。
