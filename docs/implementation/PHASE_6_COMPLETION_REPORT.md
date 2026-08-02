# Phase 6 Completion Report

## 1. 結論

Phase 6「Overlay evaluatorと収束待ち」は2026-07-29に完了した。before / after Snapshotと
ChangeSetをoffline評価し、configuration、operational、impactを分離した
`OverlayHealthResult` JSONとMarkdown summaryを生成できる。

収集済みattemptの連続PASS判定は実装済みである。機器への再収集、sleep、timeout loopは
Phase 7のrunnerへ分離する。

## 2. Configuration checks

- device別VLAN / L2VNI mappingとVLAN name
- Gateway SVIのVRF、MTU、IPv4 / IPv6、link-local、anycast mode
- VRF / L3VNI mapping
- NVE L2 member / L3 associate-vrf
- running-config証跡不足を`UNKNOWN`
- 不一致または欠落を`FAIL`

## 3. Operational checks

- `show nve vni`のL2/L3種別、BD/VRF context、Up state
- 新規VNI行欠落またはparse証跡不足を`UNKNOWN`
- Down、種別/context不一致を`FAIL`
- multi-VTEP L2VNIでは`show nve vni ingress-replication`のremote VTEP証跡を条件付き確認
- 単一VTEP配置ではremote route不在だけを異常にしない

Type-5は広告対象prefixがない場合に不在を異常としない設計であり、Phase 6では宣言された
具体的prefix期待値がないため必須checkにしない。将来、prefix期待値をChangeSetへ追加した
時点で条件付きcheckを拡張する。

## 4. Impact checks

- beforeでUpだったNVE interfaceのafter悪化
- beforeでEstablishedだったEVPN BGP peerの消失・非Established化
- 新規VNIの判定と既存Fabric regressionを別checkとして保存

## 5. 総合結果

- declared / generated / importedで全必須check成功: `VERIFIED`
- discoveredで全必須check成功、warning/conflictなし: `OBSERVED_HEALTHY`
- warningまたは自動発見の制約: `WARN`
- 証跡不足: `UNKNOWN`
- configuration、operational、impactの異常: `FAIL`
- ChangeSet conflictまたは対象解決不能: `PLAN_ERROR`

## 6. Convergence

`assess_overlay_convergence()`はattempt順、各総合結果、連続成功回数、収束attemptを決定的に
記録する。途中のWARN/FAIL/UNKNOWNで連続回数を0へ戻す。既定は2回連続成功であり、profile
の`consecutive_passes`をPhase 7から渡す。

## 7. 検証範囲

pytestでVERIFIED、OBSERVED_HEALTHY、VNI Down、EVPN peer regression、運用証跡不足、
連続成功reset、NVE VNI / ingress-replication parser、Markdown出力を確認した。
Nexus 9000vの収束時間、remote VTEP数、release別表示差はPhase 10で検証する。
hardware 4機種は動作検証対象外とする。
