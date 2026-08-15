# ADR-0017: NX-OS 9000v は Containerlab 起動後に config を投入する

## 状態

Accepted

## Context

Containerlab topology の`topology.kinds.cisco_n9kv.startup-config`から変換済み config を読み込ませると、
NX-OS 9000v が boot 中の設定投入で停止する場合がある。現行`generate-clab`は`cisco_n9kv` node がある場合、
未指定の kind-level `startup-config`を自動設定している。

alred には host 別 config を起動済み node へ投入する既存の`push-config-dir`と、投入後の running config を
期待 config と比較する`check-clab-startup-config`がある。

## Decision

- `generate-clab`は、`cisco_n9kv`の`startup-config`を既定で有効な YAML field として生成しない。
- 想定 path の comment も含め、default の`startup-config`は生成 YAML へ出力しない。
- 利用者が`clab-merge`または`clab-lab-profile`で明示した`startup-config`は維持する。
- 標準 workflow は、9000v を config なしで起動し、management 到達性確認後に`push-config-dir`で
  `raw/labconfig/`を投入する。
- 初回接続には lab 専用 bootstrap credential を使用し、production credential へ fallback しない。
- トラブル時の接続経路を維持するため、Containerlab の bootstrap `admin:admin`は default で削除しない。
- production source user の除去と bootstrap user の扱いを分離し、明示指定時だけ primary lab user の再接続成功後に
  bootstrap user を削除する。
- 投入後は`check-clab-startup-config`で live running config を検証する。

## Consequences

- boot-time config 投入に起因する停止を既定経路から避けられる。
- lab 起動と config 投入が別 phase となり、投入失敗時の node 状態と対象 host を確認しやすくなる。
- deploy だけでは production 相当 config が適用されず、追加の config push と検証が必要になる。
- 変換後 config で作成する lab user は初回接続には使えないため、bootstrap credential の管理が必要になる。
- default bootstrap credential が残るため、閉域 lab に限定し、risk scan／Manifest／verification へ警告を残す必要がある。
- 既存の boot-time 投入が必要な利用者は merge file で明示的に opt in できる。
