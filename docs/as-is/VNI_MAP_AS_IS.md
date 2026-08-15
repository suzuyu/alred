# VNI Map As-Is

- Status: Reviewed
- Last reviewed: 2026-08-09
- Scope: `generate-vni-map`、running-config parser、VNI gateway CSV／Markdown

## Evidence

| 種別 | pathまたはcommand | 確認内容 |
|---|---|---|
| Code | `alred/cli.py:parse_vni_gateway_state_from_run` | VLAN、VRF、NVE、SVI解析 |
| Code | `alred/cli.py:cmd_generate_vni_map` | raw探索、hostname mapping、出力 |
| Code | `alred/cli.py:read_vni_gateway_csv` | CSV headerと正規化 |
| Test | `tests/test_phase0_vni_golden.py` | CSVからconfigへの現行golden |
| User doc | `README.md`、`CONFIG.md` | CLIとCSV field |

## Observed behavior

- input rootに`config/`があればそこを優先し、`*_run.txt|json`をdevice別に読む。同一suffixでは
  JSONを優先する。
- NX-OS running configから`vlan`の`name`／`vn-segment`、`vrf context`の`vni`、`interface nve1`
  のmember VNI、`interface Vlan<N>`のVRFと先頭primary IPv4／IPv6を抽出する。
- management VRF、VLAN-to-VNI欠落、L2VNIとL3VNIが同値のL3 SVIはmap recordから除外する。
- VRF L3VNIとNVE `associate-vrf`、L2VNIとNVE memberの不一致はwarningにするが、record生成を
  中止しない。
- device名へ`node_name_map`を適用し、L3VNI、VRF、L2VNI、device、VLANの順で安定sortする。
- CSV fieldは`l3vni,vrf,l2vni,gateway_ipv4,gateway_ipv6,device,vlan`で、`vlan_name`はoptionにより
  追加する。Markdownも同じrecordをtable化する。
- CSV readerは必須headerを検査するが、数値範囲、IP形式、VRF名を検証せず、値の前後空白を除く。
- config diffのentity keyは`device + vlan`で、重複を拒否する。

## Documented but not verified

- parserが対応するrunning config構文はREADME例とコードで確認したが、対象NX-OS全releaseの構文変種を
  網羅するfixtureはない。

## Inferred behavior

- VNI mapは網羅的なOverlay stateではなく、SVIから辿れるL2VNI gatewayの一覧を主目的とする。
- NVE不整合をwarningに留めるため、生成CSVだけから設定投入可否を判断する用途には不十分である。

## Unknowns and conflicts

- 複数primary IPv4／IPv6、secondary address、`nve2`以降、複数line VLAN宣言、indent変種は未対応または
  未確認である。
- malformedな数値・IPをCSVで受け付けた後に、renderer側のどのvalidationで拒否するかはlegacy経路で
  一律ではない。
- mapping後のdevice名衝突を検出しない。

## Recommended design disposition

- 現行CSVと出力順を後方互換入力として維持する。
- VNI mapを健康性や投入可否の証明として扱わず、canonical OverlayStateとevaluatorを利用する。
- legacy CSVはCanonical Render Modelへのadapterを経由させ、config生成を二重実装しない。

## Integration

- Design document: [VNI Map and Legacy CSV Design](../design/network-ops/VNI_MAP_AND_LEGACY_CSV_DESIGN.md)
- ADR: Not required
- Integrated date: 2026-08-09
