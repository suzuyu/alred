# Phase 2 Completion Report

## 1. 結論

Phase 2「rawログimportとSnapshot生成」は2026-07-29に完了した。既存collect成果物と外部NX-OS
CLI transcriptを共通Collection Manifestへ変換し、同じparserでCanonical Health Snapshotを
生成できる。処理はofflineであり、機器接続や設定変更を行わない。

## 2. 実装内容

- currentのnested show transcriptを優先し、`old/`世代を暗黙に混在させないcollect adapter
- running-configを内容展開せず、path、時刻、SHA-256 provenanceとしてmanifestへ固定
- 外部transcriptのANSI escape、backspace、paging marker正規化
- `hostname#`、`hostname>`、config mode prompt、FQDN、`-`、`_`の認識
- inventory hostname、short name、`aliases`の一意照合
- command正規化、`terminal length/width ;`と`| no-more`の安全な除去
- 元ファイル、SHA-256、command区間、output区間、confidenceの保存
- preamble、unknown host、重複command、空・破損・未知出力を推測せず追跡
- Snapshot生成時のsource SHA-256再検証
- parser / Snapshot Builder versionと値ごとのsource provenance
- offline `health-check snapshot` CLI

Phase 2の初期parserは次の7 commandを対象とする。

1. `show version`
2. `show processes cpu`
3. `show system resources`
4. `show system config reload-pending`
5. `show vpc brief`
6. `show nve interface`
7. `show bgp l2vpn evpn summary`

その他の取得済みcommandは削除せず`parse_status: unsupported`として保持する。必須commandの
不足と正常性判定はPhase 3で行う。

## 3. CLI

```bash
alred health-check snapshot \
  --input raw-before \
  --input-format alred-collect \
  --phase before \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos
```

```bash
alred health-check snapshot \
  --input external-before-logs \
  --input-format nxos-transcript \
  --hosts hosts.yaml \
  --phase before \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos
```

`--input-format`のauto検出は行わない。beforeで`--change-id`を省略した場合はPhase 1のJST既定
IDを採番する。afterは誤関連付け防止のため明示change-idを要求する。

## 4. 検証

- sanitized C9300v 10.5(4)の7 commandをparse
- collect形式と外部transcript形式から`common` / `profiles`が同一になることを確認
- alias衝突、重複command、unresolved preamble、source drift、空・error・未知出力を確認
- 取得済み`raw/`を読み取り専用で確認: 11 hosts、451 command、manifest host statusは全てsuccess
- 同rawのSnapshot生成確認: 60 parsed、391 unsupported。raw内容や秘密情報は出力していない

取得済みrawは開発時の適合確認であり、repository fixtureやhardware capability証跡へは
昇格していない。

## 5. Phase 3への引き継ぎ

- profileを解決して必須commandと適用条件を確定する。
- unsupported / missing / parse unknownをcheck単位の`UNKNOWN`へ変換する。
- CPU、memory、reload-pending、BGP、vPCなどのbefore単体判定とbefore/after比較を実装する。
- 未実装command parserが必要なcheckは、sanitized fixtureを追加してから実装する。
