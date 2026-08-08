# ADR-0008: canonical な複数 role 解決を利用機能間で共有する

- Status: Accepted
- Date: 2026-08-08

## Context

現行の `roles.yaml` は任意の role key と hostname matcher を持ち、単一 role を使う topology 利用機能と複数 role を使う show command/underlay 利用機能が併存する。配布 sample は同じ spine を `spine` と `underlay-route-reflector` へ一致させるが、後者が underlay BGP RR、L2VPN EVPN RR、または表示用の BGP RR 一般を意味するか確定できない。

EVPN RR は spine だけでなく super-spine にも配置できる。 `spine_rr` のように配置と機能を一つの名前へ結合すると role の組合せが増え、 Health Check、描画、収集で再び異なる語彙が生じる。一方、既存名を即時に読み替えると、利用者の underlay RR 設定を誤って EVPN RR として扱う危険がある。

## Decision

配置を示す排他的な topology role と、VTEP、vPC、address-family 別 RR を示す function を分離する。topology role は `roles.yaml` に記載した hostname の命名規則から解決する。function は topology role の配下へ確認方針として定義し、実在を hostname から推測しない。device ごとに 1 つの topology role、function の期待状態と running config による確認結果、provenance、conflict を持つ canonical resolution を生成し、利用機能間で共有する。

RR は配置から独立した `evpn-route-reflector` と `underlay-route-reflector` を canonical 名とする。現行の曖昧な `underlay-route-reflector` を EVPN RR へ黙って alias しない。既存利用機能では移行期間中も受理するが、設定証跡から AF を確定できない場合は ambiguous として扱い、AF 固有の正常性を推定しない。

既存の flat な `role_detection` と custom role は後方互換入力として維持する。 role は収集・ check 候補・表示の選択に使用できるが、 Health Check の最終適用と判定は同一 Snapshot の config/show command evidence で確定する。 Capability Registry の qualification role は別の語彙として維持し、明示 mapping なしに変換しない。

`network-baseline-nxos` は topology role にかかわらず NX-OS host 全体へ適用する。`nxos-overlay` は `leaf`、`border-gateway`、`spine`、`super-spine` だけへ適用する。`network-functions` と `server` は `nxos-overlay` を実行せず、`other` は read-only で `UNKNOWN`、compare、plan、apply で error とする。profile を実行しなかった host は Checklist の未実行ホスト一覧へ理由付きで残す。

## Consequences

- spine と super-spine のどちらにも同じ EVPN RR check を適用できる。
- 1 台が EVPN RR と underlay RR を兼ねる構成を表現できる。
- topology の単一 group と、収集・ Health Check の複数機能を混同しなくなる。
- 既存 `roles.yaml` と custom role は継続利用できるが、曖昧な legacy RR には warning と移行が必要になる。
- resolver 成果物、schema、hash 固定、conflict 処理、利用機能の移行実装が追加で必要になる。
- role だけを信頼して check を省略または PASS にしないため、安全性と既存 Health Check 原則を維持できる。

## References

- [Role Definition and Resolution Design](../design/ROLE_DEFINITION_AND_RESOLUTION_DESIGN.md)
- [Role Detection and Resolution As-Is](../as-is/ROLE_RESOLUTION_AS_IS.md)
- [Health Check Framework Design](../design/HEALTH_CHECK_FRAMEWORK_DESIGN.md)
- [ADR-0006](./0006-external-hierarchical-device-groups.md)
