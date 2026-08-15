# VNI Map and Legacy CSV Design

## 1. 文書の目的

既存`generate-vni-map`がrunning configから生成するVNI gateway mapと、`generate-vni-config`が
受け付けるlegacy CSVの互換仕様を定める。ChangeSet、Canonical Render Model、forward／rollback
configの新仕様は
[NX-OS Overlay Config Rendering Design](./NXOS_OVERLAY_CONFIG_RENDERING_DESIGN.md)を正本とする。

解析根拠は[VNI Map As-Is](../../as-is/VNI_MAP_AS_IS.md)と
[VNI Config Renderer As-Is](../../as-is/VNI_CONFIG_RENDERER_AS_IS.md)を参照する。

## 2. 責務

```text
collected running config
    ↓ legacy parser
VNI gateway records
    ├→ CSV / Markdown map
    └→ before / target diff
            ↓ legacy CSV adapter
       Canonical Render Model
            ↓ common renderer
       forward / rollback config
```

- VNI map parserは現在のSVI中心mappingを生成する。
- VNI mapは正常性、収束、投入可否を判定しない。
- legacy CSV adapterは入力互換を担当し、NX-OS config構文を独自に生成しない。
- Overlay全resourceのcanonical観測は`OverlayState`、判定はOverlay evaluatorを使用する。

## 3. Running config入力

- `--input`直下に`config/`があればそこをrunning config directoryとする。
- `<hostname>_run.json`と`.txt`が両方ある場合はJSONを優先する。
- NX-API JSONは既存loaderで表示相当textへ変換してからparserへ渡す。
- hostnameはfilenameから取得し、出力前に`node_name_map`を適用する。
- mapping後のhostname衝突は現在検出しないため、mapping定義側で一意性を確保する。

## 4. VNI gateway parser

### 4.1 抽出対象

| resource | NX-OS構文 | 抽出値 |
|---|---|---|
| VLAN | `vlan <id>` | VLAN ID、`name`、`vn-segment` |
| VRF | `vrf context <name>` | VRF名、`vni <id> [l3]` |
| NVE L2 | `interface nve1` | `member vni <id>` |
| NVE L3 | `interface nve1` | `member vni <id> associate-vrf` |
| SVI | `interface Vlan<id>` | `vrf member`、primary IPv4、先頭の通常 IPv6、明示的な `ipv6 link-local` |

parser は top-level stanza 開始と indent により context を切り替える。現在は `nve1`だけを対象とする。

### 4.2 Record生成

SVI ごとに次を満たす場合だけ record を生成する。

- VRF が設定され、`management`ではない。
- 同じ VLAN に`vn-segment`がある。
- VLAN の L2VNI が VRF の L3VNI と同値ではない。

record field は次とする。

| field | 値 |
|---|---|
| `l3vni` | SVI の VRF に対応する L3VNI。見つからない場合は空 |
| `vrf` | SVI の`vrf member` |
| `l2vni` | SVI VLANの`vn-segment` |
| `gateway_ipv4` | 最初のnon-secondary `ip address` |
| `gateway_ipv6` | `use-link-local-only`以外の最初の`ipv6 address` |
| `ipv6_link_local` | 明示的な `ipv6 link-local <address>`。IPv6 SVI で未設定の場合は `auto`、IPv4-only SVI は空 |
| `device` | input filename 由来 hostname へ mapping 適用後の値 |
| `vlan` | SVI VLAN ID |
| `vlan_name` | VLAN name。未設定時は空 |

VRF L3VNI と NVE L3 member、record の L2VNI と NVE L2 member に不一致がある場合は warning を出すが、
map 生成は継続する。

## 5. 出力

### 5.1 CSV

出力 field 順は次とする。`vlan_name` を無効にした場合だけ同 field を省略する。

```text
l3vni,vrf,l2vni,gateway_ipv4,gateway_ipv6,device,vlan[,vlan_name],ipv6_link_local
```

`ipv6_link_local` は観測 field である。明示的な address、`auto`、空のいずれかを出力する。record は次の
key で安定 sort する。

1. L3VNIの整数値
2. VRF名
3. L2VNIの整数値
4. device名
5. VLANの整数値

整数変換できない値はsort上`0`として扱うが、有効なVNI／VLANであることを保証しない。

### 5.2 Markdown

CSV と同じ field と record 順を Markdown table として出力する。Markdown は表示用であり、
再入力のcanonical形式にしない。

## 6. Legacy CSV入力

- 先頭の 7 header を必須とし、`vlan_name`と`ipv6_link_local`は optional とする。従来の 7 列または
  8 列 CSV を引き続き受け付ける。
- 各値をstringへ変換し、前後空白を除く。未指定optional値は空stringとする。
- entity keyは`device + vlan`とし、空keyと重複keyを拒否する。
- 同じentity keyでfieldが変わった場合はdelete oldとadd newへ展開する。
- add／delete CSVを入力するdirect modeと、before／targetを比較するdiff modeを維持する。
- before未指定でauto collectionを無効にした場合は、empty beforeに対するadd-onlyとして扱う。
- `ipv6_link_local` は観測用であり、legacy CSV の add／delete 差分および config 生成には使用しない。
  IPv6 link-local を設定変更する場合は Overlay ChangeSet の `svi.ipv6_link_local` を使用する。

legacy CSV reader自体はVNI／VLAN範囲、IP address、VRF名、device存在を完全検証しない。
config生成前にCanonical Render Model adapterとconflict validatorを通す。

## 7. Config成果物

- deviceごとのconfig fileとmerged configを生成する。
- device fileは`conf t`で始まり、body後に`end`を置く。
- merged fileは`### DEVICE: <hostname>`でdevice sectionを区切る。
- 差分がない場合、merged fileへ`### NO_DIFF`を出力する。
- forwardと逆方向のrecord集合からrollback成果物を生成する。
- 現行CSV adapterとChangeSet adapterは同じCanonical Render Modelとrendererを使用する。
- rollback ownership、安全なdelete、hash、template provenanceはNX-OS Overlay Config Rendering設計に従う。

## 8. Limitations

- VNI mapは複数primary address、全secondary address、`nve2`以降を表現しない。`auto`の場合に NX-OS が
  実際に生成した link-local address は推測しない。
- warning付きrecordを正常な投入前提として扱わない。
- CSVはOverlay ChangeSetの階層device group、mode、所有権、明示defaultをすべて表現できない。
- legacy map／CSVだけではbefore evidence freshness、operation approval、capabilityを証明しない。

## 9. 実装状態

- running config parser、CSV／Markdown、diff、per-device／merged出力は実装済みである。
- legacy CSV adapterのCanonical Render Model接続とgolden testは実装済みである。
- parserのrelease別fixture、mapping後hostname衝突検査、CSV単独の完全schema validationは未実装である。

## 10. Health Check 互換成果物

実効 profile に `nxos-overlay` が含まれる場合は、各 phase の Canonical `OverlayState` から
`vni_gateway_map.md` と `vni_gateway_map.csv` を自動生成する。抽出と sort は本書の既存
`generate-vni-map` 仕様へ合わせ、機器への追加収集や legacy parser の再実行は行わない。

- L2VNI、SVI、VRF、device-local VLAN が解決できる行を対象とする。
- standalone L3VNI は `vni-map.*` だけに掲載する。
- 複数 IPv4／IPv6 address は config 順の先頭を legacy field へ投影する。
- conflict／unknown を含む場合も観測一覧として生成するが、`generate-vni-config` の安全な target として
  使用する前に `overlay-state.yaml`、Checklist、`vni-map.md` を確認する。
- before／after の差分は `vni-map-diff.*` を使用し、legacy 専用 diff は生成しない。

### 10.1 Status の適用範囲

`Status` は Canonical `overlay-state.yaml` と、そこから生成する `vni-map.md`／`vni-map.csv` の resource 状態である。
既存互換の `vni_gateway_map.md`／`vni_gateway_map.csv` には `Status` field を持たせない。同じ phase の状態を
確認する場合は `vni-map.*` と `overlay-state.yaml` を参照する。

Status は resource の構造と evidence 完全性を表し、単独では正常性判定ではない。例えば NVE state が `Down` でも
値を取得できていれば `CONSISTENT` になる場合があるため、`operational_state` と Checklist を合わせて確認する。

| Status | 判定条件 | 運用上の意味 |
|---|---|---|
| `CONSISTENT` | 必要な NVE membership が全対象 device にあり、operational state を取得でき、L2VNI の device-local VLAN ID と IPv6 link-local mode／明示値がそれぞれ 1 種類以下 | Canonical resource として比較可能。`Up` や全 field の同値を保証しない |
| `DEVICE_VARIANT` | `CONFLICT`／`UNKNOWN` ではなく、同じ L2VNI に複数の device-local VLAN ID、または複数の IPv6 link-local mode／明示値がある | device ごとの VLAN または link-local 差分。設計どおりなら許容可能であり、異常とは限らない |
| `CONFLICT` | VNI の複数 VRF 対応、VLAN name 不一致、L2 `member vni` または L3 `associate-vrf` の欠落のいずれか | config の矛盾または分類不整合。`spec.conflicts[].reason` と対象 device を確認する |
| `UNKNOWN` | resource の operational state を取得できない | evidence 不足。未収集、parse 失敗、非対応 command を source まで確認する |

同一 resource に複数条件がある場合は、`CONFLICT`、`UNKNOWN`、`DEVICE_VARIANT`、`CONSISTENT` の順で優先する。
`vni-map.csv` では resource 単位の Status を device row ごとに繰り返して出力する。

### 10.2 Conflict reason

| reason | resource | 意味 |
|---|---|---|
| `vni_maps_to_multiple_vrfs` | L2VNI／L3VNI | 同じ VNI が複数 VRF へ解決された |
| `vlan_name_mismatch` | L2VNI | 同じ L2VNI の VLAN name が device 間で一致しない |
| `nve_membership_missing` | L2VNI／L3VNI | L2 `member vni` または L3 `member vni ... associate-vrf` が対象 device で解決されない |

Traditional VLAN／SVI を使う L3VNI は、`vrf context <vrf>` の L3VNI、同じ VNI の VLAN／SVI、`ip forward`、
NVE `associate-vrf` を 1 つの L3VNI resource として扱い、L2VNI resource へ重複登録しないことを正規仕様とする。

### 10.3 Canonical OverlayState の読み取り仕様

Health Check の `OverlayState` と `vni-map.*` は、同じ phase の `nxos-overlay` profile が正規化した
`show running-config` と `show nve vni` を使用する。`vni_gateway_map.*` はこの `OverlayState` から既存形式へ
投影し、別の config parser や追加の機器 access を使用しない。

#### 10.3.1 `show running-config`

次の top-level stanza と、その配下の indent された行を読む。明示されていない値を既定値から推測しない。

| config 箇所 | 読み取る構文 | 正規化する値 | VNI map での用途 |
|---|---|---|---|
| `vlan <vlan-id>` | `name <name>`、`vn-segment <vni>` | VLAN ID、VLAN name、VNI | L2VNI 候補と device-local VLAN を作る。Traditional VLAN／SVI L3VNI と判定した binding は L2VNI から除外する |
| `vrf context <vrf>` | `vni <vni>`、`vni <vni> l3` | VRF name、L3VNI | L3VNI identity と VNI／VRF 対応を作る |
| `vrf context <vrf>` | `rd <rd>`、`address-family ipv4/ipv6 unicast` 配下 | RD、address-family command | L3VNI の device-local detail として保持する。Status 判定には直接使用しない |
| `interface Vlan<vlan-id>` | `vrf member <vrf>`、`ip forward` | VLAN／VRF binding、L3 forwarding mode | Traditional VLAN／SVI L3VNI の識別に使用する |
| `interface Vlan<vlan-id>` | `mtu`、`ip address`、`ipv6 address`、`ipv6 link-local`、`ipv6 nd suppress-ra`、`fabric forwarding mode anycast-gateway`、`shutdown`／`no shutdown` | SVI address、MTU、IPv6、Anycast Gateway、admin state | L2VNI の gateway detail と legacy map への投影に使用する。IPv6 が有効で `ipv6 link-local` がない場合、表示上の mode を `auto` とするが address は補完しない |
| `interface nve<number>` | `member vni <vni>` | L2 NVE membership | L2VNI の `nve_member` と membership 欠落判定に使用する |
| `interface nve<number>` | `member vni <vni> associate-vrf` | L3 NVE membership | L3VNI の `nve_associate_vrf` と membership 欠落判定に使用する |
| `interface nve<number>` | L2 member 配下の `ingress-replication protocol`、`mcast-group` | L2 replication config | config evidence として保持する。現在の Status は `show nve vni` の replication 表示を使用する |
| `router bgp <asn>` | `vrf <vrf>` 配下 | local AS と VRF BGP config | L3VNI の device-local detail として保持する。Status 判定には直接使用しない |

Traditional VLAN／SVI L3VNI は device ごとに次の全条件で識別する。

1. `vlan <vlan-id>` の `vn-segment <vni>` がある。
2. `interface Vlan<vlan-id>` に `vrf member <vrf>` と `ip forward` がある。
3. 同じ `vrf context <vrf>` の `vni` が `<vni>` と一致する。

この 3 条件を満たす VLAN／VNI binding は L3VNI の構成要素であり、L2VNI へ登録しない。
`member vni <vni> associate-vrf` は mode 識別の条件に含めず、識別後の L3 NVE membership 検査に使用する。
したがって `associate-vrf` が欠落した場合も、誤って L2VNI に分類せず、該当 L3VNI を
`nve_membership_missing` の `CONFLICT` とする。上記 3 条件に該当する VLAN／SVI がない L3VNI は
New L3VNI mode として扱う。

#### 10.3.2 `show nve vni`

各 VNI 行から次の列を読み取る。NX-OS の heading 表記ではなく、行の並びを parser 契約とする。

```text
<interface> <vni> <replication> <state> <mode> <L2|L3> [<bd-or-vrf>] [flags...]
```

例:

```text
nve1      10010    UnicastBGP        Up    CP   L2 [10]            SA
nve1      50001    n/a               Up    CP   L3 [TENANT-A]
```

| 表示値 | 正規化 field | 現在の VNI map での用途 |
|---|---|---|
| `<vni>` | VNI key | config から作った L2VNI／L3VNI と同じ VNI を対応付ける |
| `<state>` | `operational_state` | 値を取得できたかを Status 判定に使用し、値自体も出力する。`Up`／`Down` の正常性判定は Checklist の責務とする |
| `<replication>` | `replication` | L2VNI の device-local detail として出力する |
| `<interface>`、`<mode>`、`<L2|L3>`、`<bd-or-vrf>`、flags | parser の正規化結果 | parser は保持するが、現行 `build_overlay_state` の Status 判定には使用しない |

`show nve vni` に該当 VNI 行がない、command 未収集、または parse できない場合は
`operational_state` を解決できないため `UNKNOWN` とする。一方、NVE membership の `CONFLICT` は
`show nve vni` の行有無ではなく、`show running-config` の `member vni`／`associate-vrf` から判定する。
