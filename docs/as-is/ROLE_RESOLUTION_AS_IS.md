# Role Detection and Resolution As-Is

- Status: Reviewed
- Last reviewed: 2026-08-08
- Scope: `roles.yaml`、 hostname による role 検出、 topology/diagram、 role 別 show command

## Evidence

| 種別 | path または command | 確認内容 |
|---|---|---|
| Code | `alred/topology.py` | 単一 role と複数 role の検出順、未一致時の `other` |
| Code | `alred/cli.py` | show command、 underlay 描画における複数 role の利用 |
| Code | `alred/render.py` | containerlab の `group` と検出 role が異なる場合の priority fallback |
| Code | `alred/inventory.py` | Terraform provider group が単一 role を使用 |
| Code | `alred/constants.py` | built-in role detection の既定値 |
| Config | `roles.yaml`、 `alred/sample_configs/roles.example.yaml` | 現行 rule と配布 sample の role 名・ matcher |
| User doc | `CONFIG.md` | rule schema、複数 role、 role 別 show command の説明 |
| Test | `tests/test_design.py` | role 別 show command と生成 CLI の既存回帰確認 |

## Observed behavior

- `role_detection` 直下の key が role 名であり、固定語彙の schema validation はない。
- hostname は小文字化され、 `position_matches`、 `startswith`、 `endswith`、 `contains` の順で照合される。
- 単一 role API は最初に一致した role を返す。複数 role API は YAML 定義順ですべての一致を返す。未一致時はいずれも `other` を返す。
- containerlab の `group`、 link sort、 Terraform provider group などは単一 role を使用する。
- role 別 show command と underlay 対象 filter は複数 role を使用する。同一 hostname を `spine` と `underlay-route-reflector` の両方へ一致させる設定が配布 sample にある。
- underlay 描画は `underlay-route-reflector` 一致時に `(BGP-RR)` を表示するが、 address-family や実際の RR 設定は確認しない。
- repository 直下の `roles.yaml` は `bgw`、配布 sample と built-in default は `border-gateway` を使用する。 renderer はこのような group 名と role key の差を fallback で許容する。
- Capability Registry の `role: vpc_vtep_leaf` は、 hostname 検出 role とは別の適合性照合 key として使用される。

## Documented but not verified

- `CONFIG.md` は補助 role を追加し、同じ device へ複数 role の show command を適用できると説明している。
- `CONFIG.md` は `underlay-route-reflector` を underlay 図の BGP RR 表示にも使用すると説明している。

## Inferred behavior

- 現行の `underlay-route-reflector` は名前とは異なり、 EVPN address-family を含む「 BGP RR 一般」または表示上の RR tag として使われている可能性がある。
- 単一 role 利用機能の結果は priority ではなく YAML 定義順に影響されるため、補助 role を先に置くと topology group が変わる可能性がある。

## Unknowns and conflicts

- 現行の `underlay-route-reflector` が IPv4/IPv6 underlay RR、 L2VPN EVPN RR、または両方のどれを意図したかはコードから確定できない。
- 任意 role 名、 containerlab `group`、 Capability Registry の qualification role を同じ語彙として扱える保証がない。
- 排他的な topology role が複数一致した場合、現行実装は conflict を報告しない。
- hostname 規則と明示的な inventory 属性が食い違った場合の優先順位は定義されていない。

## Recommended design disposition

- 既存の flat な `role_detection` と複数一致を後方互換の入力として維持する。
- hostname の命名規則から topology role を解決し、その配下に VTEP/RR などの function policy を定義する。
- `evpn-route-reflector` と `underlay-route-reflector` を address-family 別に定義し、現行の曖昧な名前を黙って再解釈しない。
- 利用機能へ渡す前に topology role、function の期待状態と設定証跡、provenance、conflict を含む canonical resolution を生成する。
- role は check の選択・表示に利用してよいが、正常性の最終判定は config/show command の証跡に基づける。

## Integration

- Design document: [Role Definition and Resolution Design](../design/ROLE_DEFINITION_AND_RESOLUTION_DESIGN.md)
- ADR: [ADR-0008](../adr/0008-use-canonical-multi-role-resolution.md)
- Integrated date: 2026-08-08
