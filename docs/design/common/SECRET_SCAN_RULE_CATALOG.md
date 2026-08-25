# Secret Scan Rule Catalog

## 1. 文書の目的

Support BundleとPortable Evidence Packageがtext／NX-OS configへ適用するsecret検出rule、confidence、
検出後動作、Manifest記録を定義する。redaction／開示変換は検出前の処理、secret scanは変換漏れを検出する
独立した安全gateとし、同じ正規表現を両責務へ重複実装しない。

本catalogは値を収集、表示、保存するための仕様ではない。検出結果にはrule ID、confidence、artifact ID、
相対path、line／block位置、件数だけを記録し、一致値、部分値、元の長さ、値のhashを含めない。

## 2. 適用時点と結果

```text
source text
    ↓ content type / platform判定
structured redaction or generic sanitization
    ↓
secret scan
    ├── sanitized: high confidence 1件以上 → fail closed
    ├── sanitized: low confidenceのみ   → warning + Manifest
    └── verbatim: 全findingを記録       → 明示承認時だけ継続
```

- `sanitized`は変換後の全 content text memberをscanする。高信頼候補は`BUNDLE_BLOCKED_SECRET`または
  `EVIDENCE_BLOCKED_SECRET`とし、完成archiveを公開しない。
- `verbatim`はpackage格納前の原文running configをscanする。高信頼候補が存在しても
  [Portable Evidence Package Design](PORTABLE_EVIDENCE_PACKAGE_DESIGN.md#55-原文configの例外的なverbatim収録)の
  acknowledgementと承認条件を満たす場合だけ継続し、結果を`ACKNOWLEDGED_SENSITIVE`とする。
- binary、文字code不明、上限超過でscanできないfileを`clean`とみなさない。profileで任意なら除外と制約を記録し、
  必須ならpackage生成を失敗させる。
- redaction placeholder、comment marker、NX-OSが表示する既知の省略表現はruleごとのsafe formに完全一致する場合だけ
  検出対象外とする。類似文字列を広く除外しない。
- Portable Evidence の`package-manifest.yaml`は scan 結果を内包するため再帰 scan の対象外とし、schema validation、
  member hash、再 scan 結果との完全一致で検証する。`checksums.sha256`も hash 一覧のため content scan 対象外とする。
  `raw/`、inventory、Collection Manifest、README、AI 向け構造説明／prompt は content scan 対象に含める。

結果statusは`CLEAN`、`LOW_CONFIDENCE_FINDINGS`、`BLOCKED`、`ACKNOWLEDGED_SENSITIVE`、`NOT_SCANNED`とする。

## 3. 組み込み共通rule

| Rule ID | Confidence | 対象 | safe form／除外 | 動作 |
|---|---|---|---|---|
| `SECRET_PEM_PRIVATE_KEY` | high | PEM／OpenSSH private key block | なし | sanitizedをblock |
| `SECRET_GENERIC_KEY_VALUE` | high | `password`、`secret`、`token`、`api_key`、`client_secret`、`community`を key とする`key: value`／`key=value`形式の assignment | `<redacted:TYPE>`、`***REDACTED***`への完全一致 | sanitized を block |
| `SECRET_AUTHORIZATION_HEADER` | high | Bearer、Basic、token形式のAuthorization header | redaction marker | sanitizedをblock |
| `SECRET_URI_USERINFO` | high | URI内の`user:password@host` | password部分がredaction marker | sanitizedをblock |
| `SECRET_SUSPICIOUS_ENTROPY` | low | secret関連keyの近傍にある長いopaque文字列 | public hash／checksum field | warning |
| `SECRET_KEYWORD_ONLY` | low | secret関連keywordはあるが値を確定できないline | comment／説明文と判定済み | warning |

checksum、source SHA-256、archive SHA-256、public key、certificate本文は、それだけを理由にentropy ruleへ一致させない。
ただしprivate key markerや秘密fieldの値として出現した場合は高信頼ruleを優先する。

汎用 rule は keyword 検索で line 全体を判定せず、定義済み key の assignment 形式へ positive match した場合だけ
高信頼 finding とする。空白区切りの CLI command は汎用 rule へ含めず、platform rule が定義する command path と
secret field の組み合わせへ positive match した場合だけ検出する。未分類 command を keyword だけで mask しない。

`community`を含むという理由だけで line 全体を secret と判定しない。NX-OS の
`send-community`、`send-community extended`、`send-community both`、BGP community attribute、
`match community`、`set community`、`set extcommunity`、community list は routing policy／capability であり、
credential community ではないため保持する。
汎用 rule の`community`は`community: <value>`または`community=<value>`の assignment に限定する。
NX-OS running config では、`snmp-server community <value>`など platform rule が定義する
credential-bearing context を優先する。

## 4. NX-OS config rule

NX-OS の階層と command token を解析し、comment、banner 本文、command echo と実 config を区別して判定する。
暗号化済み／type 付きの値も認証に利用できる secret として扱い、平文だけに限定しない。

### 4.1 Portable Evidence で現在処理する構文

次の表は代表例ではなく、現在の Portable Evidence sanitizer と scanner が positive match する
全構文を示す。`<name>`、`<value>`、`<token>` は空白を含まない 1 token、`<remainder...>` は 0 個以上の
後続 token を表す。先頭の空白と英字の大文字／小文字は無視する。一致した行は秘密値だけを部分置換せず、
行全体を `! REDACTED <rule-id>` へ置換する。`!`／`#`で始まる comment と redaction marker は scan 対象外とする。

| 処理区分 | 実際に対象となる構文 | 現在の一致条件 |
|---|---|---|
| local user credential | `username <name> <remainder...> password <remainder...>` | `username` と name の後ろに word boundary で区切られた `password` がある行 |
| local user credential | `username <name> <remainder...> secret <remainder...>` | `username` と name の後ろに word boundary で区切られた `secret` がある行 |
| local user 従属 policy | `username <name> <remainder...> passphrase <remainder...>` | `username` と name の後ろに word boundary で区切られた `passphrase` がある行。`username <name> passphrase lifetime <days> [warntime <days>] [gracetime <days>]` を含む |
| enable credential | `enable password <value> <remainder...>` | `password` 直後に 1 token 以上ある行 |
| enable credential | `enable secret <value> <remainder...>` | `secret` 直後に 1 token 以上ある行 |
| SNMP community | `snmp-server community <value> <remainder...>` | `community` 直後に 1 token 以上ある行 |
| SNMP v1／v2c trap host community | `snmp-server host <host> traps version 1 <community> <remainder...>`、`snmp-server host <host> traps version 2c <community> <remainder...>` | `traps version 1` または `traps version 2c` の直後に community token がある行 |
| SNMP v1／v2c inform host community | `snmp-server host <host> informs version 1 <community> <remainder...>`、`snmp-server host <host> informs version 2c <community> <remainder...>` | `informs version 1` または `informs version 2c` の直後に community token がある行。`version 3` の user 名はこの rule の対象外 |
| SNMP user auth／priv | `snmp-server user <remainder...> auth <token> <remainder...>` | 独立 token の `auth` 直後に 1 token 以上ある行 |
| SNMP user auth／priv | `snmp-server user <remainder...> priv <token> <remainder...>` | 独立 token の `priv` 直後に 1 token 以上ある行 |
| RADIUS shared key | `radius-server <remainder...> key <value> <remainder...>` | 独立 token の `key` 直後に 1 token 以上ある行。`radius-server key ...` と `radius-server host ... key ...` を含む |
| TACACS+ shared key | `tacacs-server <remainder...> key <value> <remainder...>` | 独立 token の `key` 直後に 1 token 以上ある行。`tacacs-server key ...` と `tacacs-server host ... key ...` を含む |
| LDAP bind／test password | `ldap-server host <host> rootDN <dn> password [7] <value> <remainder...>`、`ldap-server host <host> test rootDN <dn> <remainder...> password [7] <value> <remainder...>` | `ldap-server host`の`rootDN`または`test rootDN`形式で、`password`直後の optional type `7`と値を確認する |
| BGP neighbor password | `neighbor <peer> password [0|3|5|7] <value> <remainder...>` | peer 直後の`password`と値がある行 |
| BGP peer／neighbor 階層内 password | `password [0|3|5|7] <value> <remainder...>` | 親階層に`router bgp <asn>`または`template peer <name>`がある場合だけ処理する。親がない同形行は high confidence にしない |
| key chain material | `key chain <name>`／`key <id>`配下の`key-string <value> <remainder...>` | 親階層に`key chain`または`key`がある場合だけ処理する。親がない`key-string`行は high confidence にしない |

local user の `passphrase` 行は秘密値そのものではない場合があるが、対応する credential 行だけを除去して
従属 policy を残すと lab 投入が失敗するため、同じ credential group として必ず除去する。
`password strength-check`、`password secure-mode`、`password required`と、それぞれの`no`形式は credential 値を
持たない policy command として high／low confidence から除外する。

上表に加え、text 内の次の assignment を処理する。key の直前は行頭、空白、`,`、`{` のいずれか、key は
single quote／double quote で囲まれていてもよい。key の大文字／小文字は無視する。separator は `:` または
`=`、値は 1 token 以上とする。

```text
password: <value>
password=<value>
secret: <value>
secret=<value>
token: <value>
token=<value>
api_key: <value>
api_key=<value>
api-key: <value>
api-key=<value>
apikey: <value>
apikey=<value>
client_secret: <value>
client_secret=<value>
client-secret: <value>
client-secret=<value>
clientsecret: <value>
clientsecret=<value>
community: <value>
community=<value>
```

private key は`-----BEGIN [<TYPE> ...] PRIVATE KEY-----`から、対応する
`-----END [<TYPE> ...] PRIVATE KEY-----`までを block 単位で除去する。marker は大文字／小文字を区別する。
開始 marker が閉じていない場合は file 末尾までを除去する。現在 test で固定する形式は次のとおりであり、同じ
marker 文法の`ENCRYPTED`なども対象となる。

```text
-----BEGIN PRIVATE KEY-----
-----BEGIN OPENSSH PRIVATE KEY-----
-----BEGIN RSA PRIVATE KEY-----
-----BEGIN EC PRIVATE KEY-----
-----BEGIN ENCRYPTED PRIVATE KEY-----

-----END PRIVATE KEY-----
-----END OPENSSH PRIVATE KEY-----
-----END RSA PRIVATE KEY-----
-----END EC PRIVATE KEY-----
-----END ENCRYPTED PRIVATE KEY-----
```

`password strength-check`、`send-community`、`match community`、`set community`、
`set extcommunity`、`ip community-list` は上記 positive match に含まれず、原文を保持する。

### 4.2 Rule ID と実装動作

| Rule ID | Confidence | 対象構文／context | sanitized 時の動作 |
|---|---|---|---|
| `NXOS_USERNAME_PASSWORD` | high | `username`行の`password`、`secret`、および同じ user の`passphrase`従属 policy | command 全体を除外 |
| `NXOS_ENABLE_SECRET` | high | `enable secret`、`enable password` | command 全体を除外 |
| `NXOS_SNMP_COMMUNITY` | high | `snmp-server community`、`snmp-server host ... traps|informs version 1|2c <community>` | command 全体を除外 |
| `NXOS_SNMP_USER_AUTH_PRIV` | high | `snmp-server user`行の`auth`または`priv` | 安全な値単位分離を仮定せず command 全体を除外 |
| `NXOS_RADIUS_SHARED_SECRET` | high | `radius-server`行の`key` | command 全体を除外 |
| `NXOS_TACACS_SHARED_SECRET` | high | `tacacs-server`行の`key` | command 全体を除外 |
| `NXOS_LDAP_PASSWORD` | high | `ldap-server host`の`rootDN ... password`／`test rootDN ... password` | command 全体を除外 |
| `NXOS_BGP_NEIGHBOR_PASSWORD` | high | 直接 neighbor 行の`password`、BGP／peer template 階層配下の`password` | command 全体を除外 |
| `NXOS_KEY_CHAIN_MATERIAL` | high | `key chain`／`key`配下の`key-string` | `key-string` command を除外し、親 block は保持 |
| `SECRET_GENERIC_KEY_VALUE` | high | NX-API／HTTP token、client secret を含む定義済み assignment | 該当 line を除外 |
| `SECRET_PEM_PRIVATE_KEY` | high | PEM／OpenSSH／RSA／EC／encrypted private key material | block 全体を除外 |
| `NXOS_BANNER_SECRET_CANDIDATE` | low | banner 本文の secret keyword。明示 assignment は共通 high rule を優先 | 書き換えず warning と finding を記録 |

release差異や省略構文でtoken位置を一意に解釈できない場合は、値を推測して一部だけmaskせず、該当command／blockを
除外する。`verbatim`では書き換えずfindingだけを記録する。

### 4.3 公式構文確認で採用しなかった候補

- `aaa group server`配下は server reference を構成し、shared key は`radius-server [host] key`または
  `tacacs-server [host] key`で設定するため、独立した`NXOS_AAA_SERVER_KEY`は定義しない。対象構文は既存の
  RADIUS／TACACS rule へ集約する。
- NX-OS 10.5 の`peer-keepalive` command は destination、source、VRF、interval、timeout、precedence、UDP port
  を受け取り、password／key field を持たないため、`NXOS_VPC_KEEPALIVE_PASSWORD`は定義しない。
- Nexus 9000 NX-OS 10.4／10.5 の現在の対応範囲で IPsec／IKE pre-shared key の対象 command path を公式資料から
  確定できていないため、推測による`NXOS_IPSEC_IKE_KEY`は実装しない。対象 platform／release の対応を追加する際に、
  公式 command reference と positive／negative fixture をそろえて追加する。

確認根拠は Cisco の
[AAA Configuration Guide 10.4(x)](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/104x/configuration/security/cisco-nexus-9000-series-nx-os-security-configuration-guide-release-104x/m-configuring-aaa.html)、
[vPC Configuration Guide 10.5(x)](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/105x/configuration/interfaces/cisco-nexus-9000-series-nx-os-interfaces-configuration-guide-release-105x/m_configuring_vpcs_9x.html)、
[NX-OS Command Reference 10.5(x)](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/105x/command-reference/config/b_n9k_config_commands_1051/m_p_cmds.html)、
[LDAP command reference](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/101x/command-reference/config/b_n9k_config_commands_101x/m_l_cmds.html)
とする。

## 5. Secret Scan拡張rule

組み込みruleで不足する検出条件は、rule ID、対象content type／platform、pattern、confidence、説明を追加できる。
用途や管理単位は限定せず、特定の機器構文、独自command、追加のtext形式などへ使用する。組み込みhigh ruleの
無効化、confidence低下、safe form拡張は許可しない。patternは長さ、件数、compile時間、scan対象sizeに上限を設け、
不正patternや処理budget超過をscan成功として扱わない。

```yaml
secret_scan:
  additional_rules:
    - id: CUSTOM_RADIUS_TOKEN
      platforms: [nxos]
      content_types: [running-config, cli-output]
      confidence: high
      pattern: '(?im)^\s*custom-radius-token\s+\S+'
```

replacementはredaction policyの責務であり、scan ruleには指定しない。

## 6. Manifest記録

```yaml
secret_scan:
  catalog_version: 1
  catalog_sha256: sha256:...
  status: BLOCKED
  files_scanned: 12
  files_not_scanned: 0
  high_confidence: 1
  low_confidence: 0
  findings:
    - rule_id: NXOS_SNMP_COMMUNITY
      confidence: high
      artifact_id: collection:leaf01:running_config
      path: raw/sanitized/leaf01-running-config.txt
      location:
        line: 142
      count: 1
```

複数一致を一つへ集約する場合もdevice、artifact、rule、位置の追跡能力を失わない。端末と`inspect`はsummaryだけを
既定表示し、詳細表示でも一致値を出さない。

## 7. 実装状態とtest

Portable Evidence は共通 scanner、4.1 の NX-OS context rule、private key block、共通 assignment／Authorization／URI
rule、conservative entropy／keyword low rule を実装済みとする。sanitizer が処理した source finding は file entry の
`redaction_count`へ集計し、独立した変換後 scan の finding を`secret_scan`へ記録する。`verbatim`は原文を変更せずに
scan し、明示承認済み package を`ACKNOWLEDGED_SENSITIVE`とする。Manifest は catalog version／hash、status、
high／low 件数、値を含まない finding を保持し、`create`と`verify`の双方が high confidence を fail closed にする。
`inspect`／`verify`の既定出力は status と high／low 件数だけを表示する。
catalog導入前の Portable Evidence Manifestは、`secret_scan_declared: false`を表示して現在のcatalogで再scanする。
高信頼findingがない旧packageだけを互換読込みし、旧Manifestの`CLEAN`を推測または追記しない。
catalog version が対応範囲内でも `catalog_sha256` が現在値と異なる package は、archive／member／Manifest の checksum を
先に検証した上で現在の catalog により全対象 member を再 scan する。sanitized member に high confidence finding があれば
拒否し、通過した場合だけ `secret_scan_catalog_match: false` と現在の catalog hash を verify result および import record に
記録して互換読込みする。旧 catalog の finding 集合と現在の finding 集合が同一であるとは推測しない。

既存 Support Bundle は private key block と行頭の `password`、`secret`、`community`、`token` を高信頼として
検出し、追加 mask pattern を redaction へ使用する。Support Bundle への 4.1 の NX-OS line selector 統合、
共通 rule 拡張、low confidence、catalog version／hash は未実装である。

Portable Evidence の test は rule ごとの positive／negative fixture、routing community、policy command、親 context、
banner、redaction placeholder、private key、sanitizer 変換漏れ時の独立 gate、非 UTF-8 fail closed、値が Manifest／
finding へ出ないことを確認する。fixture へ実 secret を使用せず、明確な synthetic 値を使用する。

追加 pattern の user 定義、複数 release の全構文 fixture、Support Bundle との scanner 共通化は未実装とする。

sanitizer の test は、定義済み secret-bearing command／assignment が除去されることと、pattern に一致しない
非 secret command が原文のまま保持されることを同じ fixture で確認する。CLI の positive pattern は secret 値の
token 位置まで定義し、`password strength-check`のように keyword が同じ policy command を含めない。
