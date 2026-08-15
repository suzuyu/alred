# VNI Map Guide

## 1. 目的

VNI 一覧を作成・確認する方法と、正常性確認用の `vni-map.*`、既存 command 互換の
`vni_gateway_map.*` の違いを説明する。通常運用では `health-check` と `nxos-overlay` を使用する。

## 2. 推奨経路

```bash
alred health-check before \
  --collect \
  --hosts hosts.yaml \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --ask-pass
```

成功した phase には次を生成する。

| 成果物 | 用途 |
|---|---|
| `overlay-state.yaml` | 全 VNI、VRF、VLAN、SVI、NVE 状態と evidence の正本 |
| `vni-map.md` | L2VNI／L3VNI と正常性を確認する人間向け一覧 |
| `vni-map.csv` | 状態 field と全 address を含む機器単位一覧 |
| `vni_gateway_map.md` | 既存 VNI gateway map の人間向け互換表現 |
| `vni_gateway_map.csv` | `generate-vni-config` が受け付ける legacy schema |

`vni-map.md` の L2VNI 表と `vni_gateway_map.md`／CSV は `IPv6 link-local`／`ipv6_link_local` を表示する。
`ipv6 link-local <address>` が明示されていれば address、IPv6 SVI で明示されていなければ `auto`、
IPv4-only SVI または SVI なしは `-` または空欄となる。`auto` は実際の自動生成 address を推測した値ではない。
device 間で明示値と `auto`、または異なる明示値が混在する場合、Canonical `vni-map.*` は
`DEVICE_VARIANT` として表示する。

`vni_gateway_map.csv` の `ipv6_link_local` は optional な観測 field であり、従来の CSV は引き続き入力できる。
この field 単独の差分は legacy `generate-vni-config` の投入 config を生成しない。link-local を管理する場合は
Overlay ChangeSet を使用する。

最新の成功済み Operation は `operations/live/latest` から参照できる。機械処理では symbolic link だけを
信頼せず、対象 phase の `current.json`、Collection Manifest、Snapshot hash を確認する。

## 3. 既存 Operation の利用

既存 raw を新しい parser で再解析する場合は [Health Check Operations](02_HEALTH_CHECK_OPERATIONS.md) の
recheck 手順を使用する。新しい VNI 成果物は、固定済み source から新 attempt として生成する。

## 4. 外部 running config の利用

機器へ接続せず config transcript を使用する場合は、`health-check snapshot` と `nxos-overlay` を使用する。

```bash
alred health-check snapshot \
  --input transcripts/before \
  --input-format nxos-transcript \
  --phase before \
  --hosts hosts.yaml \
  --profile nxos-overlay
```

外部ログに必要な command 区間がない場合、該当 field は `UNKNOWN` となる。

## 5. Standalone 互換経路

running config だけから従来形式を作成する場合は `generate-vni-map` を使用する。

```bash
alred generate-vni-map --input raw
```

既定出力は `output/vni_gateway_map.md` と `output/vni_gateway_map.csv` である。この経路は
operational state、正常性、収束、投入可否を判定しない。

## 6. Legacy CSV の確認

field 順は次のとおりである。

```csv
l3vni,vrf,l2vni,gateway_ipv4,gateway_ipv6,device,vlan,vlan_name,ipv6_link_local
```

legacy CSV は SVI 中心であり、standalone L3VNI、複数 address、NVE state、conflict／unknown の詳細を
保持しない。`generate-vni-config` の target として使用する前に、同じ phase の `overlay-state.yaml`、
Checklist、`vni-map.md` で矛盾や証跡不足がないことを確認する。

## 7. Status の意味

`Status` は `vni-map.md`／`vni-map.csv` と `overlay-state.yaml` に出力される resource 単位の状態です。
`vni_gateway_map.md`／`vni_gateway_map.csv` は既存互換形式のため、`Status` field を持ちません。

| Status | 確認内容 |
|---|---|
| `CONSISTENT` | NVE membership と operational evidence があり、L2VNI の VLAN ID と IPv6 link-local mode／明示値が device 間で同じ。NVE `Up` を意味するとは限らない |
| `DEVICE_VARIANT` | 同じ L2VNI に複数の device-local VLAN ID、または IPv6 link-local mode／明示値がある。意図した差分なら許容可能 |
| `CONFLICT` | VNI／VRF 対応、VLAN name、NVE membership のいずれかに矛盾がある |
| `UNKNOWN` | operational state を取得できず、状態を確定できない |

`CONFLICT` の詳細は `vni-map.md` の `## Conflicts`、または `overlay-state.yaml` の
`spec.conflicts` で `reason` と `devices` を確認します。`UNKNOWN` は `spec.unknowns` と
`spec.evidence` を確認します。Status は構造と evidence の状態であり、正常性は NVE state と Checklist を
合わせて判断してください。

主な `reason`:

| reason | 意味 |
|---|---|
| `vni_maps_to_multiple_vrfs` | 同じ VNI が複数 VRF へ解決されている |
| `vlan_name_mismatch` | 同じ L2VNI の VLAN name が device 間で異なる |
| `nve_membership_missing` | L2 `member vni` または L3 `associate-vrf` が解決されていない |

具体的な config stanza、`show nve vni` の参照列、Traditional VLAN／SVI L3VNI の識別条件は
[VNI Map and Legacy CSV Design](../../design/network-ops/VNI_MAP_AND_LEGACY_CSV_DESIGN.md#103-canonical-overlaystate-の読み取り仕様)
を参照してください。

## 8. 構成図との関係

`topology_overlay_service.md` と Overlay Service Detail は service 間の関係、placement、route leak を
描画する。VNI の表形式 inventory は本手順の成果物を使用し、Topology diagram を一覧の正本にしない。

## 9. 制約

- legacy map は既存互換のため `nve1` と SVI 中心の表現である。
- primary IPv4／IPv6 は先頭 1 件へ縮退する。
- warning 付き record や conflict／unknown を正常な設定投入前提として扱わない。
- before／after の変更確認には `health/report/vni-map-diff.*` を使用する。
