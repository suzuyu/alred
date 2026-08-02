# Phase 0 Progress Report

## 1. 判定

初回判定日は2026-07-26、最終確認日は2026-07-29（いずれもJST）。

Phase 0は2026-07-29に`implemented`と判定した。実機アクセスを伴わないlocal baseline、
Nexus 9000vのraw collection、repositoryへ登録可能なsanitized fixture、metadata、fixture
検査を完了した。

Phase 1のoffline schema/workspace実装へ進める。ただし、fixtureが証明する範囲はC9300v
10.5(4)の選択した7コマンドに限定し、release/model依存parser全体の対応済み判定や
`APPLY_VERIFIED`判定には使用しない。

## 2. 完了した作業

| 領域 | 成果 |
|---|---|
| test runner | pytestへ統一し、`device` markerを通常試験から除外 |
| dependency | pytestとRuffを`uv.lock`へ固定 |
| CI | Python 3.11/3.12で`uv sync --frozen`、pytest、Ruffを実行 |
| CLI | top-level command集合、help `0`、引数error `2`を回帰試験化 |
| VNI renderer | 現行CSV、add/delete Jinja2出力をgolden化 |
| collect | path、JSON優先、hostname/command境界をsynthetic fixture化 |
| NX-OS fixture | C9300v 10.5(4)の7コマンドをsanitized fixture化 |
| push/save | 1行送信、途中timeout、切断、NX-OS save markerをmock試験化 |
| As-Is | CLI、collect、VNI renderer、push/saveの観測結果と不明点を分離 |

## 3. 検証結果

```text
uv run --frozen pytest -m "not device"
49 passed

uv run --frozen ruff check .
All checks passed!

uv run --frozen python alred.py --help
exit code 0
```

実行環境ではPython 3.14.3を使用した。CIで宣言したPython 3.11/3.12の結果は、CI実行後に
別途確認する必要がある。

## 4. 取得証跡と継続課題

### 4.1 2026-07-29に確認したNexus 9000v collection

`/home/suzuyu/alred`直下で実行した`collect-all`は、期待する`raw/`配下へ保存されていた。

| 項目 | 確認結果 |
|---|---|
| generation | `20260729164224` |
| archive | `raw/collect-all-20260729-164224.tar.gz` |
| platform | `cisco Nexus9000 C9300v Chassis` |
| release | `10.5(4)` Maintenance Release |
| current show transcript | hostごとに37–48 section、`STATUS: OK`、非OK sectionなし |
| reload pending | 代表leafでpending commandなし |
| current/old mirror | 代表running configとshow transcriptはSHA-256一致 |

この証跡は「10.4(5)M以降の対応候補」である10.5(4)の証跡として扱う。初期対応下限
10.4(5)Mそのものの検証にはならないため、10.4(5)Mを検証済みとは表示しない。

`old/20260729164224`は今回generationの保存版、`old/`の他generationは過去取得である。
解析時はgenerationを明示し、current mirrorと過去generationを混在させない。

### 4.2 Archiveの注意事項

最新archiveは`old/`を含まないが、`raw/show_lists/<hostname>/`に残っていた過去取得のJSON
sidecarをcurrent artifactとして含む場合がある。実際に、今回のarchiveには2026-04-05更新の
JSON sidecarが含まれていた。一方、`<hostname>_shows.log`は2026-07-29の最新取得である。

したがって、現時点のarchive全体を単一generationのfixtureとしてそのまま採用しない。
sanitization時には`old/20260729164224/<hostname>_shows.log`、同generationの`config/`と
`lldp/`、またはtranscriptの`COLLECTED_AT`で今回取得と確認できる成果物だけを選択する。
sidecar世代管理とarchive allowlistの改善はcollectの残課題として扱う。

### 4.3 Sanitized fixture

取得済み10.5(4)ログから、次の7コマンドをcommand別fixtureとして登録した。

- `show version`
- `show processes cpu`
- `show system resources`
- `show system config reload-pending`
- `show vpc brief`
- `show nve interface`
- `show bgp l2vpn evpn summary`

管理IP、hostname、serial、MACは予約済みテスト値へ置換した。CPU process tableは判定に必要な
summaryを保持して縮約した。`show running-config`、`show logging`、`show inventory`は
fixtureから除外した。raw transcriptのrunning configにはpassword hashが含まれるため、
raw原本はgitignore対象のまま保持し、repositoryへ登録しない。

### 4.4 Hardware

次のmodelは文書確認対象として維持するが、実機または仮想labでの動作検証対象には含めない。

- Nexus 9336C-FX2
- Nexus 93180YC-FX3
- Nexus 9348GC-FX3
- Nexus 9364C-H1

開発中は共通NX-OS構文を9000vとgolden configで検証する。hardware固有差分はCisco公式資料に
根拠がある場合だけ機種別golden configへ反映する。hardwareは`PLAN_ONLY`以下とし、applyは
fail closedにする。Phase 10では公式資料とgolden configを確認し、hardwareのfixture収集、
plan/apply/save/rollback試験、`APPLY_VERIFIED`登録は行わない。

## 5. Phase 10または機能実装時の継続作業

1. Phase 2/3で7コマンドのparserと判定testを追加する。
2. 必要なcommandだけを同じsanitization規則で追加する。
3. config save、error、timeout、収束時間のlab証跡を追加する。
4. 9000vで10.4(5)Mを入手できた場合は対応下限のfixtureを追加する。
5. hardwareはPhase 10で文書確認状態と機種別golden configを更新する。

## 6. Phase 1着手の扱い

Phase 1のoperation workspace、schema、change-id、state/lockへ着手できる。一方、次は
必要なfixtureと試験が揃うまでfail closedとする。

- NX-OS 10.4(5)M parserを検証済みと表示すること
- 9000vの未検証model/releaseを`APPLY_VERIFIED`へ昇格すること
- hardwareの文書確認を実機apply/save/rollback試験の完了として扱うこと

追記: Phase 3で同じsanitization方針によりenvironment、IPv4 route summary、OSPF、
BGP IPv4の4 command fixtureを追加し、現在の登録数は11 commandである。Phase 0完了時点の
初期7 commandという記録は当時のbaselineを示す。
