# Documentation Instructions

## Scope

`docs/`、README、CONFIG、BUILD、manual、sample、ADR、実装計画、実装状況を変更するときに適用する。

## Rules

- 現行仕様は`docs/design/`、判断理由は`docs/adr/`、実装状況は`docs/implementation/`へ記録する。
- 利用者向けmanualは`common`、`network-ops`、`containerlab`、`topology`の利用目的で整理する。
- 同じ仕様を複数文書で再定義せず、正本へリンクする。例と既定値は正本と一致させる。
- As-Is、正式仕様、推測、未確認事項を分離し、未実装を実装済みと記載しない。
- command例はcopy-and-paste可能にし、promptや説明文をcode blockへ混在させない。
- Markdown link、見出し、sample参照、CLI option名をtestで検証する。
- 外部動作を変えない内部不具合修正では原則として仕様書を変更しない。不一致を発見した場合は更新する。
- 日本語と英数字の境界には、原則として半角スペースを入れる。command、option、file path、code、識別子は
  原表記を維持し、必要に応じて backtick で囲む。
- 句読点、括弧、記号の直前・直後には、意味のない半角スペースを追加しない。
- この表記規則は新規文書と変更箇所およびその周辺へ適用し、表記統一だけを目的とする既存文書の一括変更は行わない。

## Sources

- [Design index](../../docs/design/README.md)
- [ADR index](../../docs/adr/README.md)
- [Implementation Status](../../docs/implementation/IMPLEMENTATION_STATUS.md)
- [Existing Feature Documentation Status](../../docs/implementation/EXISTING_FEATURE_DOCUMENTATION_STATUS.md)
