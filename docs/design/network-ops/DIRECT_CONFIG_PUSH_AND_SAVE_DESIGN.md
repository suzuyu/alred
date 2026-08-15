# Direct Config Push and Save Design

## 1. 文書の目的

既存`push-config`、`push-config-dir`、`write-memory`の現行仕様、互換性、安全上の制約を定める。
これらは既存互換の直接投入commandであり、change-id、plan、approval、所有resource、rollback、after
Health Checkを持つmanaged Overlay operationの代替ではない。`Direct`はdeviceへ直接mutationを行う
責務を示し、deprecatedまたは廃止予定を意味しない。

managed apply／save／rollbackは
[Overlay Change Management Design](./OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)、共通transportは
[Inventory, Credentials, and Device Access Design](../common/INVENTORY_CREDENTIALS_AND_DEVICE_ACCESS_DESIGN.md)
を正本とする。解析根拠は[Existing Push Config As-Is](../../as-is/PUSH_CONFIG_AS_IS.md)を参照する。

## 2. 適用範囲

| command | 入力 | 動作 |
|---|---|---|
| `push-config` | 全target共通のconfig file | 同じline列を各deviceへ投入 |
| `push-config-dir` | deviceごとのconfig file | hostnameに対応するfileを各deviceへ投入 |
| `write-memory` | inventoryとtarget | config投入なしで保存commandだけを実行 |

次の用途ではDirect Config Pushを推奨しない。

- Overlay ChangeSetから生成した承認対象configの投入
- operation所有変更だけをrollbackする必要がある作業
- command単位の応答、hash、承認、before／after正常性を監査証跡として必要とする作業
- 失敗後のdevice状態を自動reconcileする必要がある作業

## 3. 入力とtarget

### 3.1 Config line

- UTF-8 textを行単位で読み、前後空白を除く。
- 空行と行頭`#`を除外する。
- device typeごとの除外prefixを適用する。NX-OSでは現在`!`、`version`、`copp`、`boot`から始まる
  lineを除外する。
- 除外後にlineがないdeviceは投入をskipする。

direct loaderはmanaged loaderの危険command denylist、regular file／symlink検査をすべて共有しない。
安全性を必要とする生成configはmanaged operationで使用する。

### 3.2 Directory mode

- exact modeでは`<hostname><suffix>`だけを対象fileとする。
- include modeではfilenameにhostnameを含み、指定suffixで終わるfileを候補とする。
- include modeで複数fileが一致したhostは曖昧としてskipする。
- fileがないhost、空configのhostはskipし、他hostの処理は継続する。

### 3.3 NX-OS 接続保護 filter

`push-config-dir` は、投入中に現在の SSH session と再接続経路を失わないよう、NX-OS config に次の
接続保護 filter を既定で適用する。login user は、対象 host への接続で実際に解決した username とする。

| rule ID | 除外対象 | 範囲 |
|---|---|---|
| `current_login_user` | `username <login-user> ...`、`no username <login-user>` | login username が大文字・小文字を含めて完全一致する top-level command。別 user は除外しない |
| `management_vrf` | `vrf context management`、`no vrf context management` | context header と配下の全 command。削除 command は単独で除外 |
| `management_interface` | `interface mgmt0`、`no interface mgmt0`、`default interface mgmt0` | interface header と配下の全 command。削除／初期化 command は単独で除外 |
| `line_vty` | `line vty`、`line vty <range>`、対応する `no`／`default` command | header と配下の全 command。削除／初期化 command は単独で除外 |

block は元 file のインデントと `!` 区切りを使用し、次の top-level command または `!` までを同じ section とする。
filter は section header と配下だけを除外するため、別 section の `logging source-interface mgmt0`、
`ntp source-interface mgmt0` など、`mgmt0` を参照する top-level command は保持する。
protected section の header 後に、インデントも明示的な `!` 境界もない command が続く入力は、block 範囲を
安全に確定できないため mutation 前に validation error とする。`--force` ではこの validation も明示解除される。

filter 適用後、mutation 確認 prompt より前に host 単位で rule ID、除外行数、secret を含まない代表 command を
表示し、同じ内容を log に記録する。`username` command は username だけを表示し、password、secret、hash など
後続 token を `<redacted>` とする。除外がない host は一覧へ表示しない。

`--force` を指定した場合はこの接続保護 filter を無効化し、上表の command も投入対象へ含める。`--force` は
既存の device type 別除外 prefix、strict CLI error 検出、connect check、対象表示、`yes` 確認を無効化しない。
実行前に警告を表示し、通常の `yes` 確認を要求する。

初期実装は NX-OS だけを対象とする。NX-OS 以外は platform 固有の block semantics を設計するまで、この filter を
推測適用しない。`clab-apply-config` は `clab-transform-config`、risk scan、post-apply credential 再接続、semantic
verification を持つため、内部で再利用する `push-config-dir` executor へ本 filter を重ねず、Containerlab workflow の
既存 gate を使用する。

### 3.4 Target と確認

- inventory、明示hostname、policy、connect checkの順でtargetを絞る。
- 接続可能な最終targetをhostname順で表示する。
- operatorが`yes`と完全一致する入力を行った場合だけmutationを開始する。
- `--skip-connect-check`は事前確認を省略するだけで、credential・投入中errorを成功に変換しない。

## 4. Config送信

- host間は`--workers`で並列実行する。
- `--fail-fast` の既定値は無効とする。指定した場合、最初の host failure を含む実行中 batch は完了させるが、未着手 host を
  新たに開始しない。`--workers 1 --fail-fast` では、失敗した host の次の host を開始しない。複数 worker では同時に開始済みの
  host だけが完了する。停止した host は `not_started_hosts` と summary に記録する。
- device内はconfig lineを1行ずつ`send_config_set([line])`で送る。
- 最初のlineでconfig modeへ入り、以降は同じsessionのconfig modeを維持する。
- transport例外が起きたlineで同一deviceの残りを停止し、他deviceは独立して継続する。
- config mode終了はbest effortとし、必ずsessionをdisconnectする。
- `push-config` と `push-config-dir` の CLI error 検出を default で有効にし、最初の未許可 error で対象 host の
  残りを停止する。他 host は独立して継続する。
- 許容済み error は`--allow-cli-error-pattern <yaml>`で限定し、rule ID、command、response pattern、判定を結果へ残す。
- `--ignore-all-cli-errors`は利用非推奨の緊急互換 option として提供する。検出自体は止めず、検出した error を
  `IGNORED_ERROR`として記録して投入を継続する。各 `IGNORED_ERROR` でも、直前に正常処理された最大 5 command と、
  該当 command の `line=<index>/<total>`、秘密値を除去した `command`、`error` を `WARNING` で表示する。host failure や
  `--fail-fast` の停止条件にはしない。transport error、timeout、session 切断は無視しない。
- 想定内の CLI error は Python Traceback を表示せず、`host`、送信対象内の `line=<index>/<total>`、秘密値を除去した
  `command`、`error` を 1 行の error log として標準出力および log file へ記録する。失敗 command の直前に正常処理された
  最大 5 command は、`PUSH CLI CONTEXT` として `host`、`line=<index>/<total>`、`status`、秘密値を除去した `command` を
  1 command ずつ記録する。response は context log へ出力せず、詳細 response は command evidence に残す。

`--allow-cli-error-pattern`と`--ignore-all-cli-errors`は同時指定を拒否する。`--ignore-all-cli-errors`と
`--write-memory`も同時指定を拒否し、error を無視した状態を startup config へ保存しない。利用時は通常の target
確認に加えて、CLI error を無視する旨の明示確認を要求し、summary と log に非推奨使用を記録する。

allowlist YAML は top-level の `rules` を持ち、各 rule に一意な `id`、anchored `command_pattern`、限定的な
`response_pattern` を指定する。両 pattern が同じ command response へ一致した場合だけ許可する。sample は
[`cli-error-allowlist.example.yaml`](../../../alred/sample_configs/cli-error-allowlist.example.yaml) を参照する。
汎用 `push-config`／`push-config-dir` は built-in allowlist を持たない。`clab-apply-config` が NX-OS 9000v bootstrap
互換のため内部追加する限定 rule は、Containerlab workflow だけに適用し、汎用 command へ継承しない。rule の定義は
[Containerlab Workflow Design の「6.7 Readiness、投入、検証」](../containerlab/CONTAINERLAB_WORKFLOW_DESIGN.md#67-readiness投入検証) を正本とする。

## 5. Save

- `push-config* --write-memory`はpushが例外なく完了したhostだけを別phaseで保存する。
- `write-memory`はpushせず、最終targetへ直接保存を行う。
- save commandはdevice type別mappingから取得する。
- NX-OSは`copy running-config startup-config`を使い、応答に`Copy complete.`が必要である。
- save timeoutは180秒とし、自動retryしない。
- markerが定義されていないdevice typeでは、transport例外がないことだけでsuccessとなる現行動作を
  維持する。対象deviceでの正確な成功判定は未検証事項とする。
- save失敗はpush済み状態を元に戻さない。失敗hostをsummaryへ表示する。

## 6. Failure semantics

| 状況 | Direct Config Pushの動作 | 注意 |
|---|---|---|
| connect check失敗 | hostをskip | mutationなし |
| send transport例外 | deviceの残りを停止 | command到達有無は不明の場合がある |
| 未許可のCLI error text | 対象 host の残りを停止 | default の strict 判定 |
| `--fail-fast` 指定後の最初の host failure | 未着手 host を開始しない | 実行開始済み host は完了。fail-fast 停止時は save しない |
| allowlist一致のCLI error | `WARN`として継続 | rule IDを記録 |
| `--ignore-all-cli-errors`で検出したerror | `IGNORED_ERROR`として継続 | 非推奨。save禁止 |
| config mode終了失敗 | best effort | post-checkなし |
| save marker欠落 | save失敗 | running configは変更済みの場合がある |
| operatorが`yes`以外 | 全投入を中止 | exit自体は正常return |
| 接続保護 filter に一致 | 該当 command／block を除外して継続 | 投入前に sanitized summary を表示。`--force` で明示解除 |

Direct Config Pushはattempt directory、immutable command evidence、current pointerを作成しない。
失敗後はrunning configを収集して状態を確認し、同じconfigを無条件に再送しない。

## 7. Managed operationとの共有境界

- 推奨責務境界ではCommon Config Session Executorがconnection、same-session show command、1行送信、save、
  disconnectを所有し、Managed Config OperationとDirect Config Pushは兄弟componentとしてこれを利用する。
- 現行実装は1行送信primitiveとsave command／markerを共有する。connection生成とManagedのsame-session
  precheckはCLI／Managed側に残っており、単一のSession Executor APIには未統合である。
- managed operationはCLI error検出、command別status、`UNKNOWN`、hash、approval、serial `1`、
  stop-on-first-error、before／after、rollback verificationを追加する。
- Direct Config Pushの並列defaultをmanaged operationへ継承しない。
- executorを別実装せず、共通primitiveのoptionと上位制御で挙動を分離する。

## 8. Security

- 実行前に対象host、config file、目的をoperatorが確認する。
- configとdevice応答にはsecretを含み得るため、そのままcommit・共有しない。
- debug logのcommand responseをsupport bundleへ直接含めない。
- secret、credential、実機raw logをtest fixtureにしない。

## 9. 実装状態と改善候補

- 1行送信、並列host処理、interactive confirmation、NX-OS保存markerは実装・mock test済みである。
- Common Config Session Executorとしてのconnection生成、same-session read-only command、session lifecycleの
  一元化は未実装である。
- Direct Config Pushのdefault CLI error本文検出、YAML error allowlist、非推奨`--ignore-all-cli-errors`、saveとの排他を
  実装済みとする。immutable command evidence schema、post-check、automatic rollbackは未実装である。
- `push-config-dir` の NX-OS 接続保護 filter、sanitized 投入前 summary、`--force`、曖昧な protected section の
  fail-closed validation は実装済みとする。`clab-apply-config` は独自の変換・risk scan・再接続検証を使用する。
- 安全性要件を追加する新規機能はDirect Config Pushを拡張するのではなく、managed operationを利用する。
