# Support Bundle Design

## 1. 文書の目的

正常性確認、設定投入、切り戻しで発生した事象を、運用者、開発者、またはAIへ安全かつ再現可能な形で引き渡すsupport bundleの仕様を定義する。

Support bundleは新しいログ収集機能ではない。既存の`operations/<change-id>/`に保存されたrawログ、Manifest、Snapshot、判定、plan、実行結果から、調査に必要な成果物だけを選択、redact、索引化、archive化する。

商用環境から隔離labまたはAI解析環境へ収集成果物を持ち出す共通形式と、用途から独立した開示levelは
[Portable Evidence Package Design](PORTABLE_EVIDENCE_PACKAGE_DESIGN.md)を正本とする。Support Bundleは
その障害解析用途profileとして位置付ける。既存CLIは共通基盤への移行が実装されるまで維持する。

本機能はOverlay作業に限定せず、共通Health Check Frameworkを使用する他作業でも利用可能とする。収集・Snapshot・判定の正本は[Health Check Framework Design](../network-ops/HEALTH_CHECK_FRAMEWORK_DESIGN.md)、Overlay固有成果物は[Overlay Change Management Design](../network-ops/OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)を参照する。

`support-bundle create/inspect/verify`、`split: none/phase/device`、device選択、
site固有redaction profileはPhase 9で実装済みである。

## 2. 設計原則

- bundle単位は`change-id`を基準とし、別operationを暗黙に混在させない
- before異常、after障害、rollback障害で必要なphaseを最小限に選ぶ
- 元のoperation directoryを直接tar化せず、allowlistでstagingを構築する
- `.env`、秘密鍵、credentialなどの禁止対象は設定にかかわらず含めない
- running-configやログはredaction後のコピーだけをarchiveへ格納する
- before / afterで同じ値を同じ仮名へ変換し、差分解析能力を維持する
- AI向けpromptは事実を自動記入し、症状と質問は利用者が追記できる
- Manifest、相対path、SHA-256により、どの原本から生成したか追跡可能にする
- raw、解析結果、推測を混同しない
- secret検出または入力世代の曖昧さが残る場合はbundleを完成扱いにしない

## 3. 利用シナリオとbundle範囲

### 3.1 before異常

設定投入前のため、原則としてbefore phaseだけを含める。

```text
metadata.yaml
health/resolved-profiles.yaml
health/execution-context.yaml
health/before/
overlay/                 # 存在する場合
```

目的は、作業前から存在する異常、作業開始可否、追加取得コマンド、`FAIL` / `WARN` / `UNKNOWN`判定の妥当性確認とする。

### 3.2 after障害

差分解析のためbeforeとafterを同じbundleへ含める。

```text
metadata.yaml
plan/
generated-config/        # redacted copy
apply/
health/resolved-profiles.yaml
health/execution-context.yaml
health/before/
health/after/
overlay/
```

plan、投入config、機器応答、before / after状態を対応付け、pre-existing異常とregression、設定失敗、収束未完了、parser問題を切り分ける。

### 3.3 rollback障害

```text
metadata.yaml
plan/
rollback-config/         # redacted copy
rollback/
health/before/
rollback-health/
```

rollbackコマンド失敗と状態復元失敗を分離し、before / rollback-after running-config差分、残存resource、消失した既存resource、driftを確認する。

### 3.4 全体bundle

全phaseが必要な重大障害または事後レビューだけで使用する。通常の一次切り分けではphase bundleを優先する。

## 4. bundle分割単位

既定は1 change-id、指定phaseを1 archiveへまとめる。

| 分割 | 用途 | 内容 |
|---|---|---|
| `none` | 容量が許容範囲 | common情報と全対象機器を1 archive |
| `phase` | 複数phaseを別々に渡す | before / after / rollbackごと |
| `device` | rawログが大きい、多数機器 | common archiveと機器別archive |

device分割時:

```text
CHG-2026-00123-after-common.tar.gz
CHG-2026-00123-after-leaf01.tar.gz
CHG-2026-00123-after-leaf02.tar.gz
```

common archiveにはmetadata、plan、profile、summary、Manifest、期待状態、全partの索引を格納する。機器別archiveには対象機器のraw、config、apply結果、diffを格納する。単純なbyte分割archiveは、単独partを解析できないため初期実装では使用しない。

既定の推奨上限は1 archiveあたり100 MiBとし、`--max-bundle-size-mib`で変更可能にする。上限超過時は暗黙にログを欠落させず、`BUNDLE_TOO_LARGE`で停止して`--split device`を案内する。

## 5. CLI

### 5.1 作成例

```bash
alred support-bundle create \
  --change-id CHG-2026-00123 \
  --phase after \
  --devices leaf01,leaf02 \
  --redact-profile support-redaction.yaml \
  --output support-bundles/
```

before異常:

```bash
alred support-bundle create \
  --change-id CHG-2026-00123 \
  --phase before \
  --output support-bundles/
```

rollback障害:

```bash
alred support-bundle create \
  --change-id CHG-2026-00123 \
  --phase rollback \
  --split device \
  --output support-bundles/
```

### 5.2 検査

```bash
alred support-bundle inspect \
  --bundle support-bundles/CHG-2026-00123-after.tar.gz

alred support-bundle verify \
  --manifest support-bundles/CHG-2026-00123-after.manifest.yaml
```

`inspect`は展開せずファイル一覧、phase、device、redaction結果、warningを表示する。`verify`はarchiveと内部・外部checksumを検証する。

### 5.3 オプション

| option | 内容 | 必須 | 既定値 |
|---|---|---:|---|
| `--change-id <ID>` | 入力operation | yes | なし |
| `--phase <before\|after\|rollback\|all>` | bundle対象phase | yes | なし |
| `--devices <LIST>` | 対象hostname。未指定ならphase Manifestの全対象 | no | 全対象 |
| `--split <none\|phase\|device>` | archive分割単位 | no | `none` |
| `--redact-profile <PATH>` | site固有redaction policy | no | 組み込みpolicy |
| `--max-bundle-size-mib <N>` | archive単位の上限 | no | `100` |
| `--[no-]include-generated-config` | after bundleへredacted forward configを含める | no | `true` |
| `--[no-]include-rollback-config` | rollback bundleへredacted rollback configを含める | no | `true` |
| `--[no-]include-raw-logging` | `show logging` rawを含める | no | `true` |
| `--prompt-language <ja\|en>` | AI向けprompt言語 | no | `ja` |
| `--symptom <TEXT>` | promptへ記載する症状 | no | 未記入欄 |
| `--question <TEXT>` | promptへ記載する質問。複数指定可 | no | phase別標準質問 |
| `--output <DIR>` | 出力先 | no | `support-bundles/` |

`--phase all`と`--split none`は容量と情報露出が最大になるためwarningを表示し、Manifestにも記録する。

## 6. 作成処理

```text
change-id / phase解決
    ↓
Collection Manifestとexecution metadata検証
    ↓
allowlistによるsource選択
    ↓
一時staging directory作成
    ↓
path traversal / symlink / special file拒否
    ↓
redactionと一貫したpseudonymization
    ↓
secret scan
    ↓
index / AI prompt / checksums生成
    ↓
archive生成
    ↓
外部Manifestとarchive SHA-256生成
    ↓
staging削除
```

stagingは一時directoryに作成し、元ファイルを変更しない。regular fileだけを対象とし、symlink、socket、device file、FIFO、operation root外を指すpathを拒否する。archive内pathは相対pathとし、`..`とabsolute pathを許可しない。

途中失敗時は完成名のarchiveを残さない。redaction前ファイルへfallbackせず、一時成果物を削除する。

## 7. allowlistと禁止対象

### 7.1 allowlist

- `metadata.yaml`
- `health/resolved-profiles.yaml`
- `health/execution-context.yaml`（password / secretを含まない固定済み実行条件）
- phaseのCollection Manifest、Snapshot、checklist、summary
- phase Manifestが参照するrawログ
- execution / rollback plan
- apply / rollbackのexecution JSON、summary、機器別command result
- qualificationのapproval、apply、rollback、復元検証、baseline saveのexecution JSONと
  機器別command/save log
- redacted generated / rollback config
- overlay expected / discovered changesとdiff
- rollback config diff

ファイル名だけでraw directoryを走査せず、原則としてCollection Manifestまたはexecution JSONから到達可能な成果物を選ぶ。参照切れは`BUNDLE_INCOMPLETE`とする。

### 7.2 常時禁止

- `.env`と環境変数dump
- SSH秘密鍵、証明書秘密鍵
- password、enable secret、API token
- credential cache、Git credential
- browser / shell history
- operation外のhome directory
- リポジトリ全体
- redaction前のhosts / inventoryでcredentialを含むもの
- pseudonymization対応表とsalt

禁止対象は利用者指定でincludeできない。必要なinventory情報はhostname、alias、role、platform、siteなどのsanitized copyを生成する。

## 8. redactionとpseudonymization

組み込みpolicyは、既知のpassword、secret、community、token、private key blockをmaskする。site固有policyでは追加のkey名、正規表現、IP prefix、hostname、VRF、tenant名を指定できる。

```yaml
api_version: alred/v1
kind: SupportBundleRedactionPolicy

metadata:
  name: site-a-support

spec:
  mask_keys:
    - password
    - secret
    - community
    - token

  pseudonymize:
    hostnames: true
    ip_addresses: true
    vrf_names: true

  preserve:
    - vni
    - vlan
    - interface_name
    - command_name
```

pseudonymizationはbundle単位で安定したIDを生成し、before / after / rollbackおよび全partで同じ原値を同じ仮名へ変換する。

```text
leaf01     → DEVICE-001
10.0.0.11 → IP-001
TENANT-A   → VRF-001
```

復元対応表とsaltはbundleへ含めない。prefix長、address family、同値関係、参照関係は可能な限り維持する。redactionによりparserやdiffが成立しない箇所はManifestへ`analysis_limitations`として記録する。

redaction後に[Secret Scan Rule Catalog](SECRET_SCAN_RULE_CATALOG.md)のscanを実行する。高信頼secret候補が残る場合は
`BUNDLE_BLOCKED_SECRET`でarchive生成を停止する。低信頼候補はpathとrule IDだけを表示し、値そのものを端末や
diagnosticへ出さない。

## 9. archiveと成果物

```text
support-bundles/
├── CHG-2026-00123-after.tar.gz
├── CHG-2026-00123-after.manifest.yaml
├── CHG-2026-00123-after.sha256
└── CHG-2026-00123-after-prompt.md
```

archive内部:

```text
support-bundle/
├── README.md
├── prompt.md
├── manifest.yaml
├── metadata.yaml
├── inventory-sanitized.yaml
├── plan/
├── config/
├── apply/
├── health/
├── rollback/
├── overlay/
└── checksums.sha256
```

内部`checksums.sha256`は、それ自身とarchiveを除く内部regular fileを対象にする。外部`.sha256`は完成archiveを対象にする。外部Manifestにはarchive名、archive SHA-256、part関係、作成時刻、tool version、schema version、redaction policy hashを記録する。

tar metadataのowner/groupは固定値、permissionは最小限、pathは相対、entry順は安定sortとする。出力archiveは既定で暗号化しないため、保存・転送先のaccess controlは利用者責任としてREADMEと端末へ警告する。

## 10. Manifest

```yaml
api_version: alred/v1
kind: SupportBundleManifest

metadata:
  change_id: CHG-2026-00123
  phase: after
  created_at: 2026-07-26T15:20:00+09:00
  timezone: Asia/Tokyo

spec:
  source_operation: operations/CHG-2026-00123
  devices:
    - DEVICE-001
    - DEVICE-002
  split: none
  redaction_policy_sha256: 0123456789abcdef

status:
  result: COMPLETE
  files_included: 84
  files_excluded: 7
  source_missing: []
  secret_scan:
    high_confidence: 0
    low_confidence: 0
  analysis_limitations: []
```

各file entryにはbundle path、source artifact ID、source SHA-256、redacted SHA-256、content type、phase、device、command ID、included / excluded理由を保存する。機微な元pathや原値は保存しない。

## 11. AI向けprompt

`prompt.md`はchange-id、phase、timezone、作業種別、対象device、期待変更、最初に失敗したcheck / command / timestamp、成果物の参照順、症状、質問、解析制約を自動記入する。

標準解析指示:

```text
1. 事実、推測、追加確認事項を分離する。
2. 各判断にbundle内の相対ファイルpathと根拠箇所を付ける。
3. beforeから存在する異常とafterで新規発生したregressionを分離する。
4. 収集失敗または証跡不足を正常とみなさずUNKNOWNとする。
5. ログにない事実を確定しない。
6. secretらしい値を回答へ転載しない。
7. 時刻はManifestのtimezoneで解釈する。
8. 追加取得が必要なら、対象device、NX-OS command、目的を示す。
```

phase別の標準質問:

| phase | 質問 |
|---|---|
| before | 作業前異常の事実と影響、作業開始可否、追加取得コマンド |
| after | beforeからのregression、設定失敗・収束・parser問題、rollback要否 |
| rollback | beforeへの復元、残存・消失設定、追加操作 |

## 12. 結果と失敗時動作

| result | 意味 |
|---|---|
| `COMPLETE` | 必須成果物、redaction、checksum、archive生成成功 |
| `COMPLETE_WITH_WARNINGS` | 任意成果物不足または低信頼secret候補あり |
| `BUNDLE_INCOMPLETE` | 必須Manifest / raw / execution成果物が不足 |
| `BUNDLE_TOO_LARGE` | 上限超過。device分割を要求 |
| `BUNDLE_BLOCKED_SECRET` | redaction後も高信頼secret候補が残存 |
| `BUNDLE_INVALID_SOURCE` | change-id、phase、Manifest世代、pathが不正 |
| `BUNDLE_CREATE_FAILED` | staging、archive、checksum生成失敗 |

`COMPLETE`または`COMPLETE_WITH_WARNINGS`以外は完成archiveとして引き渡さない。失敗を理由にredaction前ファイルをarchiveへfallbackしない。

## 13. 実装構成案

```text
alred/support_bundle/
├── selector.py
├── staging.py
├── redaction.py
├── pseudonymization.py
├── secret_scan.py
├── prompt.py
├── manifest.py
├── archive.py
└── verification.py
```

既存のCollection Manifest、operation metadata、Snapshot readerを再利用する。raw parserをsupport-bundle側へ再実装しない。

## 14. Test方針

- before / after / rollbackのallowlist
- phase間で必要な比較元が欠落しない
- change-id外path、symlink、path traversal、special fileの拒否
- `.env`、秘密鍵、credentialの常時除外
- structured / text / configのredaction
- before / after / split part間で一貫するpseudonymization
- secret残存時のfail closed
- device分割とcommon index
- deterministicなentry順と内部 / 外部checksum
- source file欠落、hash不一致、世代不一致
- archive上限超過時にファイルを黙って省略しない
- promptのphase別質問、根拠path、timezone
- inspect時にarchiveを展開せず危険pathを検出
- 元operationのファイルを変更しない

## 15. Phase 9実装状況

実装済み:

- phase別の固定allowlistとCollection Manifest参照からregular text fileだけを選択
- symlink、path traversal、non-file member、dot file、private key/credential名の拒否・除外
- hostname、IPv4 address、VRF名、home pathの一貫したpseudonymization
- password、secret、community、token、private key blockのmask
- site固有`SupportBundleRedactionPolicy`のschema validation、追加mask key/pattern
- redaction後のhigh-confidence secret scanとfail closed
- deterministic tar entry順、固定uid/gid/mtime/mode
- internal checksum、external archive checksum、external/internal manifest
- archiveを展開しないinspectとpath安全性検査
- external manifestとinternal checksumを検証するverify
- 日本語/英語AI prompt、phase別標準質問、症状・質問指定
- 100 MiB既定上限と超過時停止
- `--split phase/device`とpart index、全part共通pseudonym map
- `--devices`によるManifest host検証、structured documentとtextの対象外device除外
- generated/rollback config、raw loggingの個別include toggle
- Collection Manifestが参照するoperation内外rawのsource hash/line range検証

Phase 9の実装とoffline testは完了している。実データを外部へ渡す前には、site policyの
レビューと生成bundleの`inspect/verify`を運用手順として引き続き実施する。
