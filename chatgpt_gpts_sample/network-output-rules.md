# Network Output Rules

この文書は、ネットワーク構成収集アーカイブから成果物を生成する際の詳細ルールを定義する。

## 共通ルール

- 新規行の追加は保守的に行う
- 明示的な根拠がない値は推測しない
- 同じ情報が複数箇所にある場合は、より具体的で整合するものを優先する
- 不明値は空欄または `unknown`
- 旧版と最新版の情報を混在させない

## 依頼判定

- `リンク構成` を含む依頼は normalize-links
- `構成図` を含む依頼は generate-mermaid
- `VNI` を含む依頼は generate-vni-map
- `不具合`, `レビュー`, `確認してください` を含む依頼は review-config-all
- `CSV` という語だけでは VNI 一覧表を選ばない

## review-config-all

### 目的

- `config-all-*.tar` 内の config, show, log 情報から不具合や構成上の懸念を確認する
- 通常の要約ではなく、レビューと異常検出を優先する

### 優先して確認する情報

- `show logging`
- `show interface status`
- `show interface description`
- `show port-channel summary`
- `show vpc brief`
- `show lldp neighbors`
- `show cdp neighbors`
- `show nve peers`
- `show nve vni`
- `show bgp l2vpn evpn summary`
- `show bgp l2vpn evpn`
- `show ip route vrf all`
- `show vlan`
- `show vrf`
- `show running-config`
- `show running-config interface`

`show logging` は raw/show_lists/<hostname>/<hostname>_shows.log の中にあります

### 確認観点

- shutdown, errdisable, link down, notconnect, suspend などの IF 異常
- port-channel の member 不整合、片系不通、suspended member
- vPC の不整合、peer-link/keepalive の異常
- LLDP/CDP 上の配線不一致や想定外隣接
- VLAN / VNI / VRF の不整合
- SVI の IP, VRF, VLAN の不整合
- NVE peer down, VNI down, EVPN neighbor down
- BGP/EVPN セッション異常
- 片系 leaf のみの設定存在
- ログ上の error, fail, flap, down, mismatch, duplicate, suspend など

### 出力ルール

- 問題がある場合は findings を先に出す
- findings には、可能な限り device, 対象, 問題内容, 根拠, 影響を含める
- 重大度順に並べる
- その後に 2 から 5 行程度の短いサマリーを書く
- 問題が見つからない場合は、重大な不具合は確認できなかったと明記する
- その場合でも、確認した範囲と未確認範囲を短く示す
- 推測で障害断定しない

## normalize-links

### 目的

- 物理接続、port-channel、L2/L3 接続情報を正規化した CSV を生成する
- VNI / VRF / gateway の一覧表を出力してはいけない

### 出力ヘッダ

`local_device,local_interface,peer_device,peer_interface,link_type,port_channel,mode,vlan_or_trunk,description,source`

### 参照優先順位

- 近隣判定:
  - `show lldp neighbors`
  - `show cdp neighbors`
  - `interface description`
- リンク属性:
  - `show running-config`
  - `show running-config interface`
  - `show interface status`
  - `show interface switchport`
  - `show port-channel summary`
  - `show vlan`
  - `show ip interface brief`

### show running-config で読む項目

- `interface Ethernet...`
- `interface Port-Channel...`
- `description`
- `switchport`
- `switchport mode access`
- `switchport mode trunk`
- `switchport access vlan`
- `switchport trunk allowed vlan`
- `channel-group`
- `no switchport`
- `ip address`
- shutdown の有無

### 解釈ルール

- LLDP/CDP がある場合は peer 判定の最優先根拠とする
- `channel-group` がある場合は port-channel 所属として扱う
- `interface port-channel` の設定と member interface を対応づける
- `switchport mode access` があれば `mode=access`
- `switchport mode trunk` があれば `mode=trunk`
- `no switchport` または L3 IP があれば `mode=routed`, `link_type=l3`
- `description` に対向機器名や対向 IF があれば補助根拠として使ってよい
- peer が不明でも local 側の属性が分かるなら行を出してよい
- VLAN 情報は running-config, interface status, vlan 情報を照合して決める
- trunk は allowed VLAN または trunk の旨を記載する
- 重複接続は 1 件に正規化する

## generate-mermaid

### 目的

- ネットワーク全体の物理構成図を Mermaid で生成する
- 論理構成図ではなく、観測できた物理接続を表現する

### ルール

- Mermaid コードブロックのみを返す
- `graph TD` または `graph LR`
- 必ず ```mermaid で始まる fenced code block で返す
- spine / leaf / border / server を可能な範囲で整理する
- 主要接続を優先し、冗長にしすぎない
- port-channel が分かる場合はラベルに含めてよい
- `%%` コメントは使わない
- 点線リンクや複雑なラベルは避ける
- 日本語ラベルは避け、短い英数字ラベルを優先する
- `subgraph` 名は単純な英数字を優先する
- ChatGPT で Mermaid 表示が不安定になりそうな場合は、ラベルを減らした簡略図を返す

### 物理構成図の優先事項

- spine と leaf の物理接続
- leaf と border の物理接続
- leaf と server の物理接続
- 両端インターフェース名
- 必要なら port-channel 番号を補助情報として付ける

### 省略してよいもの

- vPC peer-link
- VRF
- L3VNI
- L2VNI
- Gateway
- VLAN 一覧
- 論理セグメントノード

### 接続ラベルの原則

- 接続ラベルは、可能な限り両端インターフェースを表示する
- 推奨形式は `Eth1/1 - Eth1/10` のような `local_if - peer_if`
- 片側しか分からない場合は `Eth1/1 - unknown` としてよい
- Mermaid 互換性のため `<` `>` は使わない
- Po番号や VLAN 番号だけの要約ラベルは、両端インターフェースが不明な場合の補助としてのみ使う
- port-channel が分かる場合は、インターフェース情報の後ろに補助として付与してよい
  - 例: `Eth1/47 - Eth1/47 Po10`
- trunk VLAN や access VLAN は、必要なら補助情報として末尾に付けてよい
  - 例: `Eth1/31 - eth0 VLAN100`

### 描画方針

- 確認できた物理リンクは代表例にまとめず、接続ごとに描く
- spine-leaf 接続は簡略化禁止
- leaf-border 接続は簡略化禁止
- leaf-server 接続は簡略化禁止
- vPC peer-link は省略してよい
- 物理リンクが確認できないものは推測しない

## generate-vni-map

### 目的

- EVPN/VXLAN の VNI / VRF / Gateway / VLAN 対応一覧を生成する
- これは VRF の存在一覧ではなく、L2VNI を起点にした対応一覧である

### 出力列

`l3vni | vrf | l2vni | gateway_ipv4 | gateway_ipv6 | device | vlan | vlan_name`

### 基本方針

- まず L2VNI と VLAN の対応を特定する
- 次に、その L2VNI が属する VRF と L3VNI を特定する
- 最後に、そのセグメントに対応する tenant 向け SVI gateway を関連づける
- L2VNI が確認できた行を主対象とする
- `show nve vni` だけで不足する場合は、`show running-config` と `show running-config interface vlan` を使って補完してよい
- 行を作る前に、対象 device を先に確定する
- device を確定できない情報は、device 列に入れず補助根拠としてのみ使う

### 行を出力してよい条件

- `show nve vni` または `vn-segment` で L2VNI が明示されている
- または VLAN と L2VNI の対応が設定または show 出力で明示されている
- L3VNI だけで L2VNI / VLAN が確認できない場合は行を出力しない
- placeholder 行は作成しない

### 列ごとのルール

- `l2vni`:
  - `show nve vni` または `vn-segment` で明示された値のみ
- `vlan`, `vlan_name`:
  - L2VNI に対応づく VLAN のみ
  - VLAN ID を一意に確認できない場合、VLAN 1 を仮置きしない
  - `show vlan` または running-config の `vlan <id>` / `interface Vlan<id>` で確認できない VLAN は空欄にする
- `vrf`:
  - 設定、NVE、EVPN、VLAN 名、SVI 名などから一意に対応づけられる場合は記載してよい
  - `interface Vlan<id>` の `vrf member <vrf>` は強い根拠として扱う
- `l3vni`:
  - 対応する VRF の値が一意に判断できる場合は記載してよい
  - device ごとに直接見えなくても、同一 VRF に対応する値が一意なら採用してよい
- `gateway_ipv4`, `gateway_ipv6`:
  - tenant 向け SVI gateway と判断できる場合のみ
  - `interface Vlan<id>` の `ip address` と `ipv6 address` は強い根拠として扱う
  - `fabric forwarding mode anycast-gateway` がある場合は tenant 向け gateway の候補として扱ってよい
  - transit/p2p/underlay 用は採用しない
- `gateway_ipv6`:
  - `interface Vlan<id>` の `ipv6 address` を最優先の根拠として使う
  - IPv4 が確認できて IPv6 も同じ SVI に明示されている場合は、IPv6 も記載する
  - `fd..../64` などの IPv6 プレフィクスが running-config にある場合、未検出扱いにしない
- `device`:
  - device ごとに行を分ける
  - その device 上で該当 L2VNI または対応 VLAN の存在が確認できた場合のみ
  - `device` にはホスト名のみを入れる
  - `config`, `running-config`, `show`, `vlan`, `nve`, `evpn` などのファイル種別名やコマンド種別名を入れてはいけない
- `vlan_name`:
  - `show vlan` の VLAN 名を最優先で使う
  - `show vlan` がない場合は running-config の `vlan <id>` 配下の `name <vlan_name>` を使う
  - L2VNI と VLAN が結びついている場合、対応 VLAN の名前は可能な限り埋める
  - VLAN 名を確認できない場合だけ空欄にする

### device 判定ルール

- device は次のいずれかから取得する
  - アーカイブ内の機器ディレクトリ名
  - ファイルパス上のホスト名
  - `hostname` 設定
  - 機器ごとの show 出力の見出し
- device は `lfsw0101`, `spine01` のようなホスト名である必要がある
- 1 行の中で device が特定できない場合、その行は保留し、他の根拠で補強できなければ出力しない

### running-config から優先して読む項目

- `vlan <id>`
- `name <vlan_name>`
- `vn-segment <l2vni>`
- `interface Vlan<id>`
- `vrf member <vrf>`
- `ip address <gateway_ipv4>`
- `ipv6 address <gateway_ipv6>`
- `fabric forwarding mode anycast-gateway`

### running-config の解釈ルール

- 同じ VLAN に `vn-segment <l2vni>` があり、対応する `interface Vlan<id>` に `vrf member` がある場合、その VLAN と L2VNI をその VRF に対応づけてよい
- `interface Vlan<id>` に `ip address` または `ipv6 address` がある場合、その VLAN に対応する tenant 向け gateway として採用してよい
- `show nve vni` だけで vrf や gateway が不足する場合、running-config から `vlan`, `vn-segment`, `interface Vlan`, `vrf member`, `ip address`, `ipv6 address` を使って補完してよい
- `vlan_name` は `show vlan` に加えて running-config 上の VLAN 名から取得してよい
- VLAN, L2VNI, VRF, gateway の対応が running-config で一意に結びつく場合は、その値を表に反映してよい
- `vrf context <vrf>` と、その配下または関連設定にある `vni <l3vni>` は、VRF と L3VNI の強い根拠として扱ってよい
- `show running-config` にある VRF 名、VLAN 名、SVI 名が一致している場合は、保守的に関連づけてよい
- `interface Vlan<id>` に `ipv6 address` がある場合、`gateway_ipv6` を空欄にしてはいけない
- `show vlan` または `vlan <id>` に名前がある場合、`vlan_name` を空欄にしてはいけない

### 関連づけルール

- `l2vni -> vlan -> vlan_name -> svi -> vrf -> l3vni` の順に関連づける
- 同一 device 上でなくても、アーカイブ全体で一意に対応づけられるなら採用してよい
- 複数候補があって一意に決まらない場合は空欄にする
- `vrf -> l3vni` は、VRF 名から一意に決まるなら先に確定してよい
- `vlan -> l2vni` は、`vn-segment` または `show nve vni` の明示値を優先する
- `vlan -> gateway` は、その VLAN に対応する `interface Vlan<id>` がある場合のみ採用する
- `vlan 11` と `vlan 103` のように別 VLAN なら別行として扱い、異なる VLAN を1つの行にまとめない
- VLAN を確認できない場合、デフォルトの VLAN 1 を推測で入れてはいけない

### 列の厳格チェック

- `l3vni` は数値のみ
- `vrf` は VRF 名のみ
- `l2vni` は数値のみ
- `gateway_ipv4` は IPv4 プレフィクスのみ
- `gateway_ipv6` は IPv6 プレフィクスのみ
- `device` はホスト名のみ
- `vlan` は VLAN ID の数値のみ
- `vlan_name` は VLAN 名のみ
- 値を別列へ入れてはいけない
- 1 行を出力する前に、各列の値が列名に合っているか確認する
- `vrf` に数値だけを入れてはいけない
- `device` に IP アドレスや VLAN ID や設定種別名を入れてはいけない
- `gateway_ipv4` と `gateway_ipv6` が空欄なのに device や vlan に値がずれて入っていないか確認する
- `l3vni` と `l2vni` が逆転していないか確認する
- `vlan` が `1` の場合は、`show vlan` または running-config に明示根拠があるか再確認する

### 事前チェック

- 表を出す前に、各行について次を確認する
  - device はホスト名か
  - vrf は VRF 名か
  - l3vni と l2vni は数値か
  - gateway 列は IP プレフィクスか
  - vlan は数値か
- 上の条件を満たさない行は修正するか、修正不能なら出力しない

### 除外ルール

- `vn-segment` または `show nve vni` に対応がない VLAN は原則除外
- `/31`, `/127` など point-to-point / transit と考えられる gateway は、L2VNI 根拠がない限り除外
- underlay, uplink, transit, p2p, interconnect, loopback 用 VLAN/SVI は除外
- VLAN 名が tenant 名に似ていても、L2VNI 根拠がなければ採用しない
- 例: VLAN 3501 のような transit 用候補は除外

### 優先参照情報

- L2VNI:
  - `show nve vni`
  - `vn-segment`
- VRF / L3VNI:
  - `show vrf`
  - `show bgp l2vpn evpn summary`
  - `show bgp l2vpn evpn`
- VLAN:
  - `show vlan`
  - VLAN 設定情報
- Gateway:
  - `interface vlan` 設定
  - SVI 関連の show
  - `show ip interface vrf all`

### 不足時

- L2VNI は確認できるが VRF や gateway の関連づけが弱い場合は、その列だけ空欄にして行は残してよい
- 出力後に短く注記してよい
