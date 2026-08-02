# NX-OS Fixtures

実機またはlab由来の出力を、認証情報と環境固有識別子を除去して保存する。

- `metadata/`: release、model、由来、sanitization、期待する観測値
- command名directory: parserへ渡すcommand単位のtext出力

fixtureのIP address、MAC address、hostname、serialは予約済みテスト値または明示的な
placeholderであり、原本値ではない。原本ログやcredentialをこのdirectoryへ保存しない。

`source_type: lab`は実際のlab出力から作成したことを示すが、縮約したtableを完全なraw
transcriptと同一とはみなさない。release/model capabilityはmetadataに列挙したcommandと
期待値の範囲だけを証明する。

`hardware_document_review/`は実機出力ではない。公式資料で確認した共通NX-OS構文を
synthetic before Snapshotから生成したfull golden configと、model別manifestを保持する。
`source_type: synthetic_document_review`および`apply_allowed: false`を必須とし、
Capability Registryの`APPLY_VERIFIED`証跡には使用しない。
