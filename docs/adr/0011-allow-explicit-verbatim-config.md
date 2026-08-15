# ADR-0011: 保護環境向けpackageで明示承認された原文config収録を許可する

- Status: Accepted
- Date: 2026-08-09

## Context

ADR-0010では原文running configを公開鍵暗号化したsealed payloadとして収録する方針を採用した。しかし、
組織が承認した保護AIまたは隔離labでは、暗号化・復号運用を追加せず、収集したconfigを変更しないまま解析へ
使用する要件がある。通常のsanitizationを既定として維持しながら、誤操作で原文が一般共有されない境界が必要である。

## Decision

Evidence Packageのconfig選択を`--config-content sanitized|verbatim|exclude`とし、既定を`sanitized`とする。
`verbatim`は`digital-twin`または`ai-analysis`、`protected-preserve` preset、明示acknowledgement、有効な承認記録を
すべて満たす場合だけ許可する。原文configは暗号化を必須とせず、sourceと同一byte列でpackageへ格納する。

`verbatim` packageはarchive名へ`sensitive`を付け、permission、Manifest、CLI表示、promptで機密性を明示する。
sanitized configを必ず併載し、通常consumerの既定入力とする。Support Bundle、`pseudonymized`、`minimal`では
`verbatim`を禁止する。config以外のcredential、private key、禁止fileを含める許可にはしない。

## Consequences

- 保護環境で原文configの構文、値、byte同一性を保った解析ができる。
- 公開鍵管理と復号操作は不要になる。
- archiveを取得できる主体はconfig内secretを閲覧できるため、保存先、permission、搬送、期限、削除の統制が必要になる。
- CLI validation、承認記録、sensitive表示、secret scan、permission、通常consumerの入力選択testが必要になる。
- ADR-0010のsealed payloadを必須とする判断だけを本ADRで置き換え、その他のEvidence Package境界は維持する。

## References

- [Portable Evidence Package Design](../design/common/PORTABLE_EVIDENCE_PACKAGE_DESIGN.md)
- [ADR-0010](./0010-use-portable-evidence-package-boundary.md)
