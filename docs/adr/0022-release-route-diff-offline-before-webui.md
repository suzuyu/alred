# ADR-0022: Route Diff の CLI・オフライン出力を Web UI に先行してリリースする

## 状態

Accepted

## Context

IPv4 / IPv6 Route Diff は、CLI・Health 統合とオフライン HTML によるレビューを設計している。
将来は一時起動する alred Web UI から Route Diff を含む複数機能を使う想定がある。
同時実装では parser / comparator の検証に加え、HTTP、入力転送、job lifecycle、接続管理、
配布の変更も初回リリースの条件となる。

## Decision

ユーザーとの合意に基づき、Route Diff の CLI・Health 統合・オフライン成果物を先行する。
Web UI の実装と詳細設計は今回の対象外とし、リリース後に他機能も含めて検討する。
今回から入力検証、正規化、比較、判定、表示用投影の境界と保存 schema を共通化し、
進捗・中断を呼び出し元に依存しない形で扱う。

現在の仕様は [Route Diff 設計 12](../design/network-ops/ROUTE_DIFF_DESIGN.md#12-初回リリース範囲と共通処理の契約)を正本とする。

## Consequences

- Web server を必要とせず、保存済みログと生成物で比較・レビューを完結できる。
- 初回の品質確認を route 入力・比較・判定・保存に集中できる。
- 将来の Web UI も共通処理を呼び出せるが、Web 用 API や job manager の実装は別途必要となる。
- 静的 HTML の性能と server 側ページングの性能は別々に検証する必要がある。
- 今回の成果物の仕様と互換性を、未確定の Web API に依存させない。
- 本判断は Web UI 全体の機能範囲、framework、既定 port を確定せず、リリース公開の承認も意味しない。
