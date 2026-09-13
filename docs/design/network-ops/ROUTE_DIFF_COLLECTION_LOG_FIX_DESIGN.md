# Route Diff 全体収集ログ・HMM・VXLAN・空テーブルの修正設計

状態: **実装・修正受入試験完了**。2026-09-13。機種 / release 別 fixture と上位性能 tier の受入は別途継続する。
[Route Diff 設計](ROUTE_DIFF_DESIGN.md)の補足正本。本書が全体ログ・directory 入力・転送属性・表示範囲の現行仕様を定義する。
実装順と受入状況は [実装計画](../../implementation/ROUTE_DIFF_IMPLEMENTATION_PLAN.md)で管理する。

## 1. 問題と修正範囲

利用者が指定した既存レポートを読み取り確認した。report manifest と成果物 hash は一致し、
IPv4 / IPv6 の route command は識別できているが、全 12 scope が UNKNOWN、結果の終了 code は 3 だった。
入力ごとに収集管理行由来の `UNRESOLVED_SEGMENT` が 40 件、未対応 path が before 48 件 / after 49 件。
未対応 path は両側合計で `hmm` が 29 件、VXLAN suffix が 68 件だった。
さらに各入力で、経路行のない 4 scope に `EMPTY_UNCONFIRMED` が記録されていた。
これは当該入力の診断であり、すべてのログ・release に共通する件数ではない。
元ログ、既存レポート、レビュー記録は変更せず、実在 host・address・raw を本書や fixture に転載しない。

修正対象は次の 3 点と、その比較・証跡・互換性への影響。

1. alred の統合 `_shows.log` を command ごとの区間として認識する。
2. `hmm` と、今回観測した BGP の VXLAN suffix を正式な grammar として解析する。
3. 取得完了が確認でき、経路行のない VRF section を正常空と判定する。

Web UI、機器への再接続・設定投入、任意 protocol の許容、任意の折り返し復元、
structured NX-API JSON の直接解析、全属性比較 preset の追加は対象外。
対応予定の機種・release は [既存の対象範囲](ROUTE_DIFF_DESIGN.md#13-対応対象と-fixture-の受け入れ)を維持する。
今回のログで見つかった grammar の修正と、全対象機種・release の対応認定は別である。

## 2. 判断案

| 論点 | 採用仕様 | 理由・変更の影響 |
|---|---|---|
| 入力指定 | 既存 `nxos-transcript` で、plain transcript と構造が確認できる alred 収集形式を扱う | 今回の command を変更せず再実行できる。ファイル名による推測や新しい必須 option は追加しない |
| 管理行 | 構造を検証して本文から分離する | `###` 行を一括削除すると失敗状態・境界破損まで消えるため |
| 非 route command | 境界が確定した本文を比較対象外として保持する | 非 route の正常出力や pager を route の解析失敗にしない。境界不明の場合は限定しない |
| VXLAN 属性 | NextHop を含む 2 方式の比較に含める | 同じ IP next-hop のまま転送先 segment 等が変わる差分を見落とさない |
| HMM | `protocol: hmm` として保持する | direct / local に読み替えない。protocol 比較 preset は追加しない |
| 正常空 | heading・既知の凡例・区間終端・command 成功を検証する | `No routes` がない空出力を扱いつつ、途中で切れたログを 0 件にしない |
| 旧成果物 | そのまま保持し、両時点の元 bytes から新規出力へ再解析する | parser / 比較条件の変更後に旧レビューや旧判定を誤継承しない |

VXLAN 属性を NextHop 比較に含める点と正常空の認定条件は、利用者の実装・試験依頼に基づいて採用した。

## 3. 入力と section adapter

### 3.1 CLI と形式の識別

既存の `--before` / `--after` / `--input-format nxos-transcript` と Source Map の指定を維持する。
新しい `--input-format auto` や `--input-format alred-collect` は今回追加しない。
`nxos-route-text` は従来どおり 1 command の本文だけであり、統合ログを渡して救済する形式にしない。

`nxos-transcript` 内では次の構造を区別する。

- plain: host prompt、command、本文、次の prompt で区間が確定するもの。
- alred collect: `### COMMAND_LIST` または `### COMMAND:` から始まる既知の envelope。
  `COMMAND_LIST` は統合ファイルの冒頭だけ、command 別ファイルでは省略可能。
  宣言された command の一覧は入力本文ではなく計画として保持し、実行済みの証明にはしない。
- collect marker があるのに envelope が不正な入力は plain として再試行しない。
  ファイル先頭の未知 banner、plain / collect の未定義な混在を無条件に除去しない。

host は collect section の検証済み prompt から解決する。非 route command の本文中にある
prompt らしい文字列を host 候補として採用しない。単一ホストの 2 file 制約、
before / after の host 一致、Source Map による host 明示は維持する。
複数ホストの directory 入力は 3.5 に従い、単一ホストの 2 file 入力とは区別する。

### 3.2 alred collect の grammar

現行 writer は [Collection 設計](../common/COLLECTION_DESIGN.md)と `alred/cli.py` の収集処理を正本とする。
本修正では writer の形式を変えず、共通の読み取り adapter を追加する。

```text
### COMMAND: show ip route vrf all
### COLLECTED_AT: 2026-09-13T10:00:00+09:00
### STATUS: OK
### TRANSPORT: ssh
leaf01# show ip route vrf all
<NX-OS の本文>

### COMMAND: <次の command>
<次の section の metadata と prompt>
```

- 必須 metadata は `COMMAND`、timezone 付きの妥当な `COLLECTED_AT`、`STATUS`、`TRANSPORT`。
  各 key は 1 回だけ。宣言 command と prompt command は同じ実行要求でなければならない。
  VRF の大小文字を保持し、route command の比較には共通 resolver を使う。
- writer が出力する任意 key `OUTPUT_FORMAT`、`FALLBACK_FROM`、`ERROR` を位置・型付きで扱う。
  `STATUS: OK` と非空 `ERROR` の併存は成功としない。未知 key / 重複 / 必須欠落は診断を残す。
- 本文として受け付ける `OUTPUT_FORMAT` は未指定または `text`。`json` は本文として解析せず UNKNOWN。
  同 directory の JSON sidecar を暗黙に探索・採用しない。transport は記録し、成功の代用にしない。
- `COMMAND_LIST` がある場合、実行 section の command・順序と照合する。欠落・余分・重複を記録し、
  対象 route の欠落を未取得として残す。非 route の実行失敗は route 失敗に置き換えない。
  未実行の非 route command は `notices` に残し、既に閉じた route command の coverage は下げない。
  欠落した対象 route の VRF が特定できない場合は VRF を捏造せず、command 単位の未取得診断を残す。
  明示的な AF 選択の対象外は notice とし、対象内の未取得を全体 COMPLETE に集約しない。
- `### COMMAND:` だけでは境界確定にしない。後続 metadata と prompt が整合する位置を境界にする。
  本文の任意の `### ...` 行を削除しない。不正な境界候補の帰属が不明なら UNKNOWN を広げる。
- command block は header から次の header 直前まで。本文は prompt の次行から block 末尾まで。
  次の正常な block の metadata / prompt は直前 command の終端証拠として参照できる。
  最後の block の単なる EOF と `STATUS: OK` だけでは、正常空を認定しない。

### 3.3 責務と来歴

処理順は `元 bytes / hash 固定 → terminal adapter → section adapter → route parser → Snapshot`。
terminal adapter の文字除去規則は変更せず、同じ元 source の正規化と section 検出を 1 回だけ行う。
Health の `_parse_record` と standalone が共通 section / completion 検証を使い、
新しい SSH executor、別の HMM / VXLAN parser は作らない。
既存の汎用 Collection Manifest / transcript importer の他 consumer の意味は変えない。
Manifest の寛容な解析や decode 置換を、Route Diff の検証成功として流用しない。

新規出力では source に `container_format`（`plain-transcript` / `alred-collect` / `route-text`）を追加し、
各採用 command に次の `acquisition_evidence` を記録する案とする。

| field | 内容 |
|---|---|
| `header` / `prompt` / `body` | 元 source ID、1 始まりの行範囲、0 始まり・終端を含まない byte 範囲。存在しない header は null |
| `declared_status` / `collected_at` / `transport` | collect metadata。plain で不明な値は null |
| `completion_kind` | `next_prompt` / `next_collect_header` / `manifest_record` / `eof_unverified` |
| `completion_evidence` | 終端の prompt または検証した次 block の header～prompt。EOF は null |
| `manifest_record_sha256` | Health が検証した既存 Manifest record。standalone がその場で生成した記録で代用しない |

`completion_kind: manifest_record` は既存 Health の非空出力の証跡条件を継続するためのもの。
**今回追加する marker なし正常空には、実際の `next_prompt` / `next_collect_header` を必須**とする。
ログからその場で復元した Manifest と自己申告 status だけで、EOF の空出力を確定しない。
command 別 file が EOF で終わる既存 Health 入力では、この条件を満たさない空 scope は UNKNOWN のまま。
完了 footer 等を collector に追加する拡張は今回は行わない。

Source Map は採用する完全な command block を指定する。終端確認の lookahead は次 block の
header～prompt だけに限定し、`completion_evidence` として元 file 内の位置を保存する。
lookahead は次 command の採用・重複とは数えない。scope / route / path の evidence は採用本文内に限定する。
途中の本文だけを切り取った範囲、同じ route の複数時点、`vrf all` と個別 VRF の重複は従来どおり拒否する。

### 3.4 失敗の影響範囲

| 状態 | 影響 |
|---|---|
| 非 route の本文、pager、command 失敗。前後の境界は確定 | 対象外として source の `notices` に command・位置・理由を残す。route coverage は下げない |
| route の status 失敗、本文の未知行・control / pager | 該当 command、または帰属が明確な VRF を UNKNOWN |
| metadata / prompt / host / command の矛盾、control が境界を壊す | 影響を限定できる場合だけ限定する。不明なら source の全採用 scope を UNKNOWN または入力エラー |
| UTF-8 decode error、複数 host の曖昧さ、採用区間の重複 | 入力エラー。情報を捨てて続行しない |

`notices` は無視した原文の削除を意味しない。blocking な `diagnostics` と分け、
complete scope に無条件で source 全体の非 route 診断を伝播しないよう domain validator も更新する。
この限定は plain transcript の未知の接続メッセージを無条件に許容する変更ではない。

### 3.5 複数機器・ログの directory 入力

既存 `--before` / `--after` を拡張し、両側にそれぞれ directory を指定できるようにする。
既存の `--source-map` による明示対応を維持し、directory の自動探索を追加した。

```bash
alred route-diff-nxos \
  --before logs/before \
  --after logs/after \
  --input-format nxos-transcript \
  --output-dir review-directory/route_diff
```

| 項目 | 推奨仕様 |
|---|---|
| 入力形態 | file / file または directory / directory。混在は入力エラー |
| 探索 | 既定は直下の通常 file のみ。拡張子 `.log` / `.txt` は大小文字を区別しない |
| 子 directory | 新規 `--recursive` 指定時だけ探索。directory 入力専用、既定 OFF |
| 除外 | 隠し file / directory、対象外拡張子は除外理由と件数を記録。symlink は辿らず記録する |
| 入力形式 | directory 入力は `nxos-transcript` 必須。plain / collect は共通 section adapter で識別 |
| 併用制約 | `--source-map`、`--host`、`--command-id`、`--command-vrf`、`--completeness` と併用不可。AF / VRF / Policy 等は既存規則 |
| 出力先 | 両入力 directory の外側に新規出力。探索対象へ自己生成物を混ぜない |

before / after は利用者が指定した時点とし、mtime・取得時刻・file 名で左右を並べ替えない。
探索順は相対 path の文字列順で固定するが、ホストや時点の対応付けには使わない。
各 file の検証済み prompt からホストを解決し、**ホスト名の完全一致**で両側を対応付ける。
同名 file の対応付け、suffix 除去、大文字小文字の同一視、hostname 変更の推定はしない。
したがって file 名や分割数が before / after で異なっていても比較できる。

同じホスト・時点の複数ログは source 群として扱い、IPv4 / IPv6 や重ならない VRF を統合する。
同じ `(host, side, VRF, AF)` の重複、同じ command の再取得、`vrf all` と個別 VRF の重複は拒否する。
同じ内容 hash でも自動で 1 件へ潰さず、最新 file の自動採用もしない。
重複時は file 名・command・元行を示し、Source Map で採用 file / 区間を明示する導線を出す。
prompt のない本文や、1 file 内の複数ホストは自動入力では拒否し、明示 Source Map を使う。
Source Map でも hostname の矛盾を上書きしてよいという意味ではない。

対象ホストは両側で識別したホストの和集合とする。片側欠落は未取得 / UNKNOWN として残し、
反対側の全 prefix を ADDED / REMOVED としない。比較可能なホストは処理を継続する。
片側 directory が空の場合も、反対側で識別したホストの欠落として report を生成できる。
両側とも採用可能な route command がない場合は入力エラーとする。
対象拡張子の読み取り失敗、空 file、ホスト不明、複数ホスト、壊れた区間境界でホストを限定できない場合は
黙って除外せず入力エラー。ホストが確定した route command の取得・解析失敗は該当対象を UNKNOWN とする。
route command がない正常なログも、識別したホストと対象外理由を残す。
そのホストに別の有効 route source がなければ対象 command 未取得として UNKNOWN に残す。

ディレクトリ探索結果を固定し、各 file の元 bytes / hash を既存 capture 処理で確保してから共通 resolver へ渡す。
読み取り中の変更を検出した場合は入力エラーとし、収集中のログを一貫した時点の入力とみなさない。
探索後に増えた file は当該実行へ追加しない。既存の不変 evidence・atomic publish・再実行規則を継続する。
既存 `evidence/resolved-input.json` に、入力 root、探索条件、候補一覧、除外理由、host / side / source の
解決結果と欠落側を追跡できる `directory_discovery` を追加した。同じ内容を
`evidence/directory-discovery.json` に保存する。`schema_version: 1`、`kind: RouteDiffDirectoryDiscovery`、
`resolver_version: 1.0`、`roots`（before / after の絶対 path）、`recursive`、`extensions`、
`inventory`（side / 相対 path / status / reason または host）、`hosts`（host / before_count / after_count）を保持する。
Source Map は片側の source 配列を空にできるが、ホストの両側が空の指定は拒否する。空の側の Snapshot も
source / scope / route 配列を空で保存し、反対側の対象を UNKNOWN とする。
再現は保存済みの採用 source とその hash に基づき、可変の入力 directory を再探索して代用しない。

出力は既存の `route_diff/` 配下へ集約し、全体 checklist / JSON / Markdown / CSV とホスト別 HTML を生成する。
HTML と端末には「両側取得済み / before のみ / after のみ」のホスト数、source 数、UNKNOWN を表示する。
「両側取得済み」は正常解析の保証ではないため、取得対応と coverage を別に表示する。
各ホストの Sources は折りたたみ、ログ全文比較では選択したホストと source に 6.1 の表示範囲を適用する。
複数ホストを 1 個の巨大な raw pane に連結しない。
UNKNOWN を含む終了 code は既存どおり 3、入力不備は 2。Policy との優先順位も既存契約に従う。
この追加案は standalone の入口拡張であり、Health の固定 Manifest / attempt 選択は directory 再探索へ置き換えない。

## 4. HMM と VXLAN の解析・正規化

### 4.1 HMM

既知 protocol に小文字の `hmm` を追加する。`protocol` / `raw_protocol` は `hmm`、instance は null。
今回観測した IP address と interface を持つ HMM path は `kind: ip` とし、IP の AF、interface、
参照 VRF、AD、Cost、経過時間、元行を通常の path と同じ規則で保持する。
HMM だからといって AD / Cost を固定しない。`am` など別 protocol を一括して許容しない。
protocol だけの変更は既存 5 方式では差分にしないが、raw と Snapshot に残す。

### 4.2 VXLAN suffix

今回は BGP path の既知 suffix を次の形で追加する。IPv4 / IPv6 **prefix** の双方に適用する。

```text
segid[:] <decimal> [(Asymmetric)] [tunnelid: <hex>] encap: VXLAN
```

今回の観測と公式資料で確認できる 1 行形式を対象とし、順序は上記、区切り空白は複数可。
`segid` の直後のコロンは省略可能。実装時の元入力再検証で IPv6 のコロンなし表記も確認した。
IPv4-mapped IPv6 next-hop と `%default:IPv4` の参照を保つ合成回帰例を追加する。
tag 等の既存 comma 区切り属性の後ろで suffix を完全消費する。
未知 suffix、未消費文字、重複 key、不正値は UNKNOWN。単に `segid:` 以降を切り捨てない。
`tunnelid` のない形式、Asymmetric のない形式はそれぞれ fixture で確認する。
`VTEP:(... underlay_vrf: ...)`、`(evpn)` や複数行の別 grammar は今回の修正対象に自動追加しない。

| 新規 path field | 正規化案 |
|---|---|
| `encapsulation` | `vxlan` / null。`encap: VXLAN` の表記を対応付ける |
| `segment_id` | 10 進整数、1～16777215。未表示は null |
| `tunnel_id` | `0x` + 小文字の 16 進文字列、先頭の余分な 0 を除く。初期対応は 1～8 桁の hex 入力。未表示は null |
| `asymmetric` | `(Asymmetric)` が明示された場合 true、未表示は null。未表示を symmetric / false と推測しない |

suffix がない従来 path は 4 field とも null。suffix がある場合は `encapsulation` と `segment_id` が必須。
`tunnel_id` は識別子として保持し、IPv4 address に変換・置換しない。next-hop address と同じ値とも仮定しない。
IPv4-mapped IPv6、link-local interface、参照 VRF / table AF の既存規則は維持する。
元の hex 大小文字・桁・全文は raw evidence から追跡する。

### 4.3 比較・Policy・表示

新しい比較方式は追加せず、既存 NextHop tuple に上記 4 field を加える案とする。

| 方式 | VXLAN 属性だけが変わった場合 |
|---|---|
| Prefix / Prefix + AD / Prefix + AD + Cost | UNCHANGED |
| Prefix + AD + NextHop / Prefix + AD + Cost + NextHop | MODIFIED |

ECMP は拡張 tuple の集合で比較し、同じ IP / interface でも segment 等が異なる path を潰さない。
path の重複検証、表示上の対応付け、期待 path の完全一致、rollback 残存差分判定にも同じ tuple を使う。
Policy path の 4 field は optional、省略は null、wildcard にはしない。
VXLAN を持つ期待経路を指定する場合は実値を記述する。既存の非 VXLAN Policy は意味を維持する。

理由は既存 `NEXTHOP_CHANGED` に加え、変わった field に応じて
`ENCAPSULATION_CHANGED` / `SEGMENT_ID_CHANGED` / `TUNNEL_ID_CHANGED` / `ASYMMETRIC_CHANGED` を付ける。
field ごとの一意集合が同じでも組み合わせが違う場合は、拡張 tuple の差分で MODIFIED とし、
`PATH_ASSOCIATION_CHANGED` も付ける。set 同士を雑に対応させて変更 path を推測しない。
`field_summary.next_hops` にも 4 field を含め、5 方式の JSON / CSV / Markdown / HTML を同じ結果から作る。
理由を追加した場合は schema の enum と HTML の filter・label・field summary を同時に更新する。

## 5. 正常空の認定

従来の `No routes` による明示空は維持する。marker がない形式は次の **全条件** を満たす場合だけ追加認定する。

1. 対応する完全な route command である。summary / prefix 指定 / `include` 等ではない。
2. VRF heading が識別され、AF / VRF が command の取得範囲と整合する。
3. heading の後に AF ごとの既知の凡例が揃う。IPv4 は既存の 4 行、IPv6 は `%...VRF` の行を除く 3 行を必須とする。
   既知凡例の順序・空行は意味を変えない。省略形は別 fixture の確認なしに許容しない。
4. 当該 VRF に prefix / path / 未解析本文がない。制御文字・pager・CLI error・失敗 status がない。
5. 当該 VRF の終端と、**包含する command 全体の終端**が確定する。
   次の VRF heading だけでは command の取得完了を代用しない。
   collect では status / metadata の一致と検証済み次 block、plain では実際の次 prompt が必要。

判定できた場合は `coverage: COMPLETE`、prefix / path 数は 0。
新規 `empty_basis: closed_section` と `empty_evidence`（heading、凡例、VRF / command 終端参照）を記録する。
既存 `explicit_empty` は literal な `No routes` の有無を表すまま維持し、この新ケースでは false。
`No routes` は `empty_basis: explicit_marker`、非空・未確定は null とする。
Snapshot validator の「complete な 0 件は explicit_empty 必須」を、根拠を検証する 2 分岐に変更する。
新 field を付けただけで正常空を自己申告できないよう、元区間・command・verification の整合を検証する。

EOF、heading だけ、凡例不足、途中 path、同一 command の未解決終了、`nxos-route-text` の marker なし空は
`EMPTY_UNCONFIRMED` / UNKNOWN のまま。`completeness: asserted` を不明な空の救済に使わない。
片側が UNKNOWN なら反対側の経路を全件 ADDED / REMOVED としない。
両側が正常空なら全 5 方式で before / after 0、追加・削除・変更 0 とする。

## 6. 利用者向けの表示・ログ

既存の「長い証跡は折りたたむ」表示を維持する。上位の抽象的な `SCOPE_INCOMPLETE` だけでなく、
原因を分類して見出しに表示する。

```text
leaf01 / EMPTY-VRF / IPv6 — COMPLETE：正常空（取得完了を確認）
leaf01 / TENANT-A / IPv4 — UNKNOWN：after の経路属性が未対応（2 行）
Sources（2 入力）
  leaf01 / before — alred 収集形式、route 2 command、対象外 2 command
```

展開時に metadata、採用区間、終端証拠、正常空の根拠、原因の元行を表示する。
raw view は 6.1 の表示範囲を選べる。管理行も含めた全体ログ・元行番号を保持し、対象外 command を経路差分の赤・緑にしない。
VXLAN の差分例は `NextHop 203.0.113.1 / segment_id 19001 → 19002` のように該当値を見せる。
VNI 値だけの変更を IP next-hop が変わったと説明しない。

進捗に section 検出と command 単位の処理数を含める。最終 stdout / checklist には coverage、
UNKNOWN scope 数と主原因の集計、詳細レポートへの導線を出す。未解析の全文を端末へ大量に出さない。
終了 code は維持する。入力不備は 2、UNKNOWN は 3、出力失敗は 6、中断は 130。
差分ありでも Policy なしの完全比較は 0。Health 全体の終了規則は変更しない。

### 6.1 ログ全文比較の表示範囲

HTML の「ログ全文比較」に「表示範囲」を追加する。CLI の入力絞り込みとは別の表示 option とし、
新しい CLI option や成果物 file は追加しない。standalone / Health の共通 renderer に適用する。

| 選択肢 | 表示する行 | 推奨する既定 |
|---|---|---|
| 対象 route command 区間のみ | 比較入力として採用した route command の完全な区間。区間内の共通行・空行・未知行も表示 | ON |
| 入力ログ全体 | 選択した before / after source の全行。非 route command と収集管理行も表示 | OFF |

対象は `show ip route` / `show ipv6 route` と、それぞれの `vrf all` / `vrf <name>` の計 6 形式。
解析時の AF / VRF / Source Map 選択で採用した command を使い、renderer で prompt を再解析しない。
`vrf all` を採用した場合は command 全体を表示し、個別 VRF の本文だけに再分割しない。
正規化 view の AF / VRF / 検索条件と「差分行以外も表示」は引き継がない。
対象区間表示も区間内の全文なので、差分行だけの表示ではない。

collect では当該 block の管理行・prompt・本文、plain では command 付き prompt と本文を含める。
次 command の終端確認用 lookahead は表示区間に混ぜず、取得証跡から参照する。
本文のみの入力は、明示された採用区間全体を対象とする。
複数区間は元の順序で並べ、「対象外 Lx–Ly を省略」と区切りを表示する。
行番号は source の元番号を維持し、連番へ振り直さない。左右の異なる command を表示順だけで対応付けない。
各側の source 名、対象 command、表示行数 / 全行数を表示し、絞り込み中であることを常に示す。

区間が確定している UNKNOWN / ERROR の route 本文も表示対象に残す。
区間を確定できない場合は「対象区間を確定できません」と全体表示への導線を示し、正常空とは表示しない。
片側未取得の場合はその側に未取得を表示する。取得状態・UNKNOWN の件数と原因は表示範囲で隠さない。
証跡移動先が表示範囲外なら、通知を出して全体表示へ切り替え、該当元行へ移動する。

検索は現在の表示範囲を対象とし、一致行数に範囲を明記する。検索そのものでは行を隠さない。
文字列 diff は現在の範囲で再計算し、省略した別 command 区間をまたいで同一行を対応付けない。
区間は既存 resolver の command identity で対応付け、片側だけにある区間は追加 / 削除として表示する。
「入力ログ全体」では従来どおり source 全体の文字列 diff とする。
経路着色は既存の結果と元行 mapping を使い、表示範囲で再判定しない。
検索・文字列 diff・仮想スクロールは元行番号と表示位置の mapping を共有し、
範囲切替時に古い非同期計算を中止して結果を混在させない。

範囲選択は同じ HTML を開いている間の view 切替では保持する。新規表示・再読み込みは推奨既定へ戻す。
元 bytes / hash、Snapshot、差分件数、Health 判定、レビュー fingerprint は変えない。
従来の「ログ全文 view は入力全行を既定表示」から既定値を変更した。
更新済みの本番 renderer サンプルでも、対象 route command 区間が初期表示となる。

## 7. 互換性・再実行・実装境界

実装 version は parser `1.2`、normalizer `1.1`、section adapter `1.0`、comparator / evaluator / renderer `1.1`、
Health Route adapter / profile `1.1`。terminal adapter は `1.0` のまま。各定数と fixture・出力例を同時更新する。
schema major は 1 を維持する。追加 field と新規に認識する grammar であり、既存 field の型や
非 VXLAN の既存比較結果は変えない。`explicit_empty` の意味も変更しない。

ただし未知の転送属性を無視できる旧 reader と安全な比較互換があるとは扱わない。
新しい parser / comparator version は旧実装での比較を拒否し、更新後の実装も旧 Snapshot と新 Snapshot を
直接混ぜず、両側 raw を同じ version で再解析する。保存済み hash 対象文書を default 追加で書き換えない。
新 version により fingerprint が変わるため、旧レビュー記録は移植せず、不一致を説明する。
schema major を上げずに安全な拒否が実証できない reader が見つかった場合は、実装前に互換設計を再レビューする。

standalone は新規 output directory、Health は新しい attempt / operation を用い、
固定された旧 before / Policy / current を変更しない。新旧 parser の混在では再解析が必要と明示する。
新しい比較からの公開は既存の manifest 検証・atomic publish を継続する。
設定投入・rollback 操作はこの修正設計には含めない。Health rollback の経路比較には拡張 tuple を適用する。

変更予定の責務は section adapter と parser、Snapshot / Policy / Diff の schema・domain validator、
comparator / evaluator / renderer、Health adapter、入力解決、manual / sample / package 検証。
実装 code と package schema を更新し、元ログと利用者の既存 report は保持する。

## 8. 受け入れ条件とレビュー用入出力

[合成入力と期待出力](examples/route-diff-input-fix/README.md)を、今回のログとは独立して用意する。
設計用モックは固定期待表示として保持し、成功実績は実装計画と本番 renderer の出力例で区別する。

| ID | ケース | 必須の期待結果 |
|---|---|---|
| F01 | show version / interface 等を含む正常な統合収集ログ | route command だけを比較。元 bytes / 全行 / hash は保持 |
| F02 | COMMAND_LIST 内の route 名、本文中の prompt らしい文字列 | 二重実行や別 host と誤認しない |
| F03 | metadata 欠落・重複・command / host 不一致・不正日時 | エラーまたは UNKNOWN。管理行を消して成功にしない |
| F04 | 非 route の ERROR / pager、route の ERROR / pager、境界破損 | 3.4 の影響範囲に従い、無視した非 route 証跡も残す |
| F05 | HMM の IPv4 / IPv6、異なる AD / Cost、未知 protocol | HMM の値を保持し、未知 protocol は UNKNOWN |
| F06 | VXLAN 4 field 個別変更、未表示→表示、hex 大小文字・先頭 0 | NextHop 2 方式だけで所定の差分。等価 hex 表記は差分なし |
| F07 | 同一 IP で異なる segment の ECMP、順序変更、属性対応交換 | path を潰さず、一意な対応と件数を確認。順序だけは差分なし |
| F08 | 不正 segment / tunnel 値、未知 encap / suffix、未対応の複数行 | UNKNOWN。既知部分だけ採用して complete にしない |
| F09 | 6 command 形式、IPv4 4 行 / IPv6 3 行の凡例付き正常空 | 閉じた command のときだけ 0 件。元終端へ辿れる |
| F10 | heading だけ、途中 EOF、次 VRF はあるが command は EOF | UNKNOWN。明示 `No routes` と申告本文の既存ケースも回帰 |
| F11 | 同一 command 再出現、all / 個別 VRF の重複、Source Map 区間 | 自動で最後を選ばない。終端 lookahead と採用の重複を区別 |
| F12 | Policy、期待 path、rollback の segment / tunnel 残差 | CLI / Health で同じ比較結果。rollback 復元漏れを検出 |
| F13 | 旧 Snapshot / review、新旧 version 混在、改変 hash | 安全に拒否。元成果物・旧 current を変更しない |
| F14 | 解析中・公開前の中断と再実行 | partial を保持、新規出力で再実行、旧成功結果は維持 |
| F15 | HTML / JSON / CSV / Markdown、折りたたみ・元行移動 | 件数・理由が一致、UNKNOWN と正常空を区別、外部通信なし |
| F16 | 1 万 route と多数の非 route command | source ごとの正規化 / section 検出が 1 回。既存性能との比較を記録 |
| F17 | raw の対象区間 / 全体切替、複数区間・片側欠落・未知行 | 対象区間が既定、元行番号・省略表示・UNKNOWN を保持。判定件数は不変 |
| F18 | 範囲内検索・文字列 diff・証跡移動・仮想スクロール | 範囲外証跡への通知付き切替、区間をまたぐ誤対応なし、切替前の計算結果を破棄 |
| F19 | directory の複数ホスト・異なる file 名・AF 別複数 source | prompt のホストで対応。分割数・探索順によらず同じ結果 |
| F20 | 片側 file / ホスト / AF 欠落、片側空 directory | 欠落対象を UNKNOWN、比較可能なホストは継続。全件削除へ変換しない |
| F21 | 重複取得・同 hash・all / 個別 VRF の重複・複数ホスト file | 自動採用せず入力エラーと Source Map の案内 |
| F22 | 再帰 ON / OFF、隠し file、symlink、読取不能、読み取り中の変更 | 探索条件・除外を記録。曖昧な対象を黙って落とさず、固定入力を再現可能 |

匿名化した実例は grammar と値の関係を保つ。対応 model / release は元の取得証跡を別途確認し、
例を作っただけで fixture matrix を VERIFIED にしない。
元入力の再評価は新しい出力先で行い、未対応構文が残れば診断を示す。12 scope を必ず COMPLETE にするための
例外処理は入れない。source / wheel / 標準 glibc 2.17 binary と browser の受入を実装完了条件に含める。

## 9. 根拠と未対応形式

- 収集 envelope は既存 writer / Health adapter と、利用者が指定した保存済み出力の観測に基づく。
- [Cisco NX-OS 9.3(13) release notes](https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/93x/release/notes/cisco-nexus-9000-nxos-release-notes-9313.pdf)には
  HMM と Asymmetric / tunnelid を持つ route 表記例がある。grammar の補助資料であり、9.3 系を本機能の対象に追加しない。
- [Cisco NX-OS 10.5(x) VXLAN guide](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/105x/configuration/vxlan/cisco-nexus-9000-series-nx-os-vxlan-configuration-guide-release-105x/m_configuring_vxlan_bgp_evpn.html)には
  segment / tunnel / encapsulation を持つ表示例がある。すべての protocol / command 形式の対応を意味しない。
- [Cisco NX-OS 10.6(x) VXLANv6 guide](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/106x/configuration/vxlan/cisco-nexus-9000-series-nx-os-vxlan-configuration-guide-release-106x/m_configuring_vxlan_with_ipv6_in_the_underlay_vxlanv6.html)には
  別行の VTEP / underlay VRF 表記もある。この形式は今回の 1 行 grammar と分けて受入を設計する。

公式資料の確認日は 2026-09-13。正常空の認定は本書の保守的な判断案であり、
公式資料が任意の heading-only 出力を正常空と保証しているという主張ではない。
