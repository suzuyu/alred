# nxos-overlay Profile Guide

EVPN/VXLAN の正常性を確認する profile です。以下は組み込み
[nxos-overlay.yaml](../../../../alred/health/profiles/nxos-overlay.yaml) version `1.0` と
[evaluator](../../../../alred/health/evaluator.py) を照合した現行動作の要約です。
詳細仕様と設計済み・未実装の区別は
[Overlay Role Health Check Catalog](../../../design/network-ops/NXOS_OVERLAY_ROLE_HEALTH_CHECK_CATALOG.md)を参照してください。

## 1. 出力項目・目的・判定内容

組み込み profile の check は次の 9 項目です。role/function により実行対象と表示 ID が変わり、
2 節の check が追加される場合があります。すべての host に同じ件数を出力するとは限りません。
数値の負荷閾値ではなく、設定・状態・期待 resource の存在を主に確認します。

| Check ID | 目的・主な command | 現行の単体判定 | 前後比較での主な確認 |
|---|---|---|---|
| `nve_interface_health` | NVE interface の稼働。`show nve interface` | `Up` は `PASS`、それ以外は `FAIL`。未設定は `NOT_APPLICABLE` | Up からの Down、NVE 消失は `FAIL` |
| `evpn_bgp_health` | EVPN BGP 隣接。`show bgp l2vpn evpn summary` | peer が 1 件以上あり全件 `Established` なら `PASS`、非 Established または設定済みで peer 0 件なら `FAIL`。未設定は `NOT_APPLICABLE` | 正常 peer の消失・状態悪化を検出 |
| `nve_peer_regression` | 観測 NVE peer の状態。`show nve peers` | 観測 peer に非 Up があれば `FAIL`、なければ `PASS`。非適用は `NOT_APPLICABLE` | before の Up peer の消失・Down は `FAIL` |
| `nve_vni_health` | 観測 VNI の状態。`show nve vni` | 観測 VNI に非 Up があれば `FAIL`、なければ `PASS`。非適用は `NOT_APPLICABLE` | before の Up VNI の消失・Down は `FAIL` |
| `evpn_route_health` | EVPN route の観測。`show bgp l2vpn evpn` | route 数が正値なら `PASS`、0 件は `WARN`。EVPN 非適用は `NOT_APPLICABLE` | before の route key が消失し、after の route 数が 0 なら `FAIL`、残存 route があれば `WARN` |
| `type5_prefix_propagation` | 広報対象 connected prefix の伝搬。running config、EVPN route、VRF route | 期待 prefix の広報元・EVPN RR・受信対象 Leaf・VRF 導入を確認。必要 route の欠落は `FAIL`、証跡不足・policy 解釈不能は `UNKNOWN`、広報対象なしは `NOT_APPLICABLE` | after の期待値を再評価し、before の `PASS` からの悪化を regression として分類 |
| `vlan_operational_health` | VNI に対応する VLAN の稼働。running config、`show vlan brief` | 期待 VLAN がすべて存在し `active` なら `PASS`、欠落・非 active は `FAIL` | after の期待対象を再評価し、before の `PASS` からの悪化を分類 |
| `vrf_operational_health` | L3VNI や対象 SVI に対応する VRF の稼働。running config、`show vrf` | 期待 VRF がすべて存在し `Up` なら `PASS`、欠落・非 Up は `FAIL` | after の期待対象を再評価し、before の `PASS` からの悪化を分類 |
| `svi_operational_health` | Overlay 対象 SVI の稼働。running config、`show interface brief` | 期待 SVI が非 shutdown かつ admin / operational とも up なら `PASS`、shutdown・down・欠落は `FAIL` | after の期待対象を再評価し、before の `PASS` からの悪化を分類 |

VLAN／VRF／SVI は対象設定がなければ `NOT_APPLICABLE`、必要な設定・show 証跡がなければ
`UNKNOWN` とします。一括 show を取得できない場合と、取得済み show 内に期待 resource がない場合を区別します。

baseline の `interface_health` は admin-down を異常対象から除外しますが、
`svi_operational_health` は稼働を期待する Overlay SVI を対象とするため、設定の shutdown も `FAIL` です。

## 2. Role / function に応じた出力

`roles.yaml` の schema version `2` では、解決済み role/function に応じて次の出力を使用します。
function check は設定上の役割との一致確認であり、運用状態のチェックは 1 節や baseline が受け持ちます。

| Check ID | 目的・判定内容 |
|---|---|
| `vtep_function_expectation` | VTEP function の期待と NVE 設定の実在を照合 |
| `vpc_function_expectation` | vPC function の期待と vPC 設定の実在を照合 |
| `evpn_rr_config_health` | EVPN RR function の期待と RR 設定を照合。解決不能な BGP template は `UNKNOWN` |
| `underlay_rr_config_health` | underlay RR function の期待と RR 設定を照合。運用 neighbor は baseline で確認 |
| `evpn_rr_neighbor_health` | EVPN RR の EVPN neighbor。`evpn_bgp_health` の表示 ID を置き換える |
| `border_evpn_bgp_health` | border gateway の EVPN neighbor。EVPN RR の置換が適用されない場合に `evpn_bgp_health` の表示 ID を置き換える |

function の設定判定は、`required` なら存在で `PASS`・未設定で `FAIL`、`forbidden` なら存在で
`FAIL`・未設定で `PASS`、`optional` なら存在で `PASS`・未設定で `NOT_APPLICABLE` です。
設定が解釈不能なら `UNKNOWN` とします。前後比較で設定済み function が消失した場合は `FAIL` です。
role 対象外 host は check の `NOT_APPLICABLE` 件数へ混在させず、未実行ホストとして表示します。
詳細は [適用範囲と function expectation](../../../design/network-ops/NXOS_OVERLAY_ROLE_HEALTH_CHECK_CATALOG.md#2-適用範囲)を参照してください。

## 3. 閾値・制約と詳細設計

- この組み込み profile に CPU 利用率のような `spec.thresholds` はありません。EVPN route 0 件の
  `WARN` などは現行 evaluator の条件です。CPU、memory、interface error、logging は
  [baseline](./network-baseline-nxos.md)を併用して確認します。
- `spec.convergence` は `interval_seconds: 15`、`timeout_seconds: 300`、`consecutive_passes: 2` です。
  これは収束待ちの設定値であり、各 check の状態判定閾値ではありません。設定の存在だけで、
  すべての実行経路で自動再収集・待機が実装済みとは扱いません。
- `nve_peer_regression` / `nve_vni_health` の単体判定は観測行の状態確認です。解析済みの空集合は
  異常 peer / VNI がないため `PASS` になり、期待 peer / VNI の完全な充足を単独では保証しません。
- `evpn_route_health` の件数・route key 比較は Type-2/3/5 の期待値充足を保証しません。
  Type-5 の `full` mode は実装済みですが、`sampled` mode、`network` による広報の期待値導出などは未実装です。
- VLAN／VRF／SVI 比較は after の設定から期待対象を再導出します。設定から削除された resource の
  完全な追跡まで、この check の `PASS` だけで保証しません。

| 詳細を確認する対象 | 設計書・手順 |
|---|---|
| NVE、VNI、VLAN、VRF、SVI | [Leaf / VTEP check catalog](../../../design/network-ops/NXOS_OVERLAY_ROLE_HEALTH_CHECK_CATALOG.md#6-leaf--vtep) |
| Type-5 の期待 prefix と伝搬確認 | [Type-5 期待値の自動導出](../../../design/network-ops/NXOS_OVERLAY_ROLE_HEALTH_CHECK_CATALOG.md#63-type-5-期待値の自動導出) |
| 設計済みと実装済みの境界 | [Implementation Status](../../../implementation/IMPLEMENTATION_STATUS.md) |
| profile の指定・合成 | [共通 Profile Guide](../03_PROFILE_GUIDE.md) |
| before / after の実行手順と show command 一覧 | [NX-OS Overlay Health Check](../06_NXOS_OVERLAY_HEALTH_CHECK.md) |
