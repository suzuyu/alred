# Route Diff CLI・オフライン出力 実装計画

状態: **P6 まで実装。P7 は 1 万 route の代表ケース・wheel / glibc 2.17 binary を検証。0.2.0a13 は各時点 1 万 route まで。機種別受入は未完了**。2026-09-13 更新。
仕様の正本は [Route Diff 設計](../design/network-ops/ROUTE_DIFF_DESIGN.md)。本書は実装順、証跡、完了条件を追跡する。
Web UI は今回の実装・詳細設計から外し、Route Diff 以外の機能も含めて初回リリース後に検討する。
2026-09-13: 統合収集ログ・HMM・VXLAN・正常空、directory 入力・表示範囲の修正を実装。
修正の実装範囲と受入結果は下記 F1–F5 および第 12 節に記録する。

## 1. 初回の作業順

| ID | 作業 | 完了条件 | 現在 |
|---|---|---|---|
| P0 | 範囲・入力証跡 | README の対象機種、10.4(5)M 以降の対象 release、fixture 台帳、不足ケースが明確 | 範囲合意、詳細 route の release 付き fixture 不足 |
| P1 | schema / 共通契約 | 構造 schema、domain validation、Health profile 設定位置・Snapshot 参照・attempt 内配置を固定 | Policy / Source Map / RouteSnapshot / RouteDiff / RouteDiffReview の package schema と domain validator を実装。Health の設定・参照・attempt 配置を設計 18 節で固定 |
| P2 | terminal adapter / parser | raw byte hash、line mapping、複数 path、正常空・欠落・未知の区別を fixture で検証 | Python API を部分実装。合成 fixture で検証。release 固有 grammar の実証は未完了 |
| P3 | comparator / evaluator | 5 方式、件数式、期待変更、必須経路、UNKNOWN、policy hash を検証 | Python API を実装。5 方式・取得範囲・UNKNOWN・全 policy rule・hash・中断を合成 fixture と期待ケースで検証 |
| P4 | offline renderer | 全形式の同一結果、ページング、raw 仮想スクロール、レビュー保存・復元、外部通信なし | Python API を実装。全形式の同一比較結果、50 / 100 / 500 prefix のページング、raw 仮想スクロール、検索・証跡往復、レビュー保存・復元、外部通信なしを検証。実出力からマニュアル画像を更新 |
| P5 | standalone CLI | 入力 validation、進捗、中断、終了 code、atomic publish、任意 2 時点の再実行 | `route-diff-nxos` を実装。2 file / Source Map、AF / VRF、policy、review、元 bytes / Snapshot 保存、hash 検証、no-replace 公開、SIGINT、再実行を検証 |
| P6 | Health 統合 | 追加 profile、収集の重複排除、before 固定、after / compare / rollback、旧 consumer 回帰 | 追加 profile、固定設定、詳細 Snapshot 参照、取得証跡、before / after / rollback、atomic report 公開を実装。合成ログで検証 |
| P7 | 性能・配布・受入 | 実装版の性能測定、全自動テスト、wheel / 標準 binary、manual / help / status 整合 | [性能記録](ROUTE_DIFF_PERFORMANCE_REPORT.md)。1 万 route の代表 3 ケースを全出力・browser で検証。wheel / glibc 2.17 binary の standalone / Health smoke が成功。10 万 / 100 万は時間上限、機種別受入は未完了 |

P2–P3 は P1 の contract と合成 fixture を使って先行できるが、P0 の証跡不足を解消するまで release 対応済みとはしない。
P5 / P6 の収集・設定は既存経路を利用する。別の SSH executor は作らない。
本作業は version 採番、commit、push、PR、tag、Release 作成・公開を実行したことを意味しない。

### 1.1 利用マニュアルの作成順

[Route Diff 利用ガイド](../manual/network-ops/13_ROUTE_DIFF_GUIDE.md)のドラフトを P3 に先行して作成した。
入力準備、比較方式の選択、結果確認、UNKNOWN の対処を利用者の手順としてレビューし、
未実装 CLI の提案例と現在確認可能な UI モックを区別する。

以降は P3 の比較・判定、P4 の出力、P5 の CLI、P6 の Health 統合に合わせて該当節を更新する。
P5 では掲載 command の実行、生成物・終了 code の照合、P6 では profile と before／after の
操作例を確認する。P7 で対応対象、実出力例、性能の制約を反映し、正式マニュアルとして確定する。
ドラフトの作成だけで機能やリリースの受け入れを完了としない。

入力 parser `1.1` では default／指定／全 VRF の command 識別と取得範囲を追加した。
P3 で異なる取得範囲の未取得 VRF を UNKNOWN とすることを検証した。P6 で同じ契約を Health profile に接続した。
利用ガイドの 4 枚の画像は P4 の本番 renderer が生成した HTML で撮り直した。
CLI への接続と command 例の実行確認は P5 で完了した。

## 2. 入力証跡の確認結果

| 確認した資料 | 現在の証拠 | Route Diff で不足するもの |
|---|---|---|
| [C9300v 10.5(4) metadata](../../tests/fixtures/nxos/metadata/c9300v_10_5_4.yaml) | show version、route summary などの匿名化済み lab fixture | IPv4 / IPv6 の詳細 route command の登録がない |
| [既存 route parser](../../alred/health/parsers.py) | prefix / 単一 next_hop / protocol の解析 | 全 path、AD / Cost、品質、source mapping |
| [既存 route / role テスト](../../tests/test_health_roles.py) | inline の IPv4 / IPv6 route 例、IPv4-mapped next-hop と `%default:IPv4` 表記 | 取得元・release が明確な詳細 route fixture、空 / 多 path / 中断など |
| [UI 入力例](../design/network-ops/examples/route-diff-review/README.md) | 5 比較方式と境界条件の合成 model | 任意ログの production parser / evaluator の検証 |
| [現行 transcript importer](../../alred/health/transcript.py) | 既存入力形式の処理 | strict adapter 適用前の raw 検査、正確な元 byte / line mapping |

既存 Capability の apply 検証済み状態から、新機能の route parser 検証済み状態を継承しない。
必要な証跡は正本の [対応対象と fixture](../design/network-ops/ROUTE_DIFF_DESIGN.md#13-対応対象と-fixture-の受け入れ)で管理する。

## 3. P1 で実装前に固定する事項

- YAML は共通 envelope、JSON は schema_version。入力未知 field は拒否、同じ major の出力追加 field は reader で許容する。
- Snapshot は全 route を保持し、RouteDiff は差分と全 policy rule 結果、Review は確認記録を別に保存する。
- mode / UI filter と policy 照合を分離し、画面から見えない UNCHANGED の rule も評価する。
- profile に定義する AF / VRF / route policy と、standalone の引数を同じ解決済み比較要求へ写す。
- Health Snapshot の詳細 RouteSnapshot 参照、相対 path、hash、version、before / after / rollback の保存先を既存 resolver に沿って確定する。
- raw / normalized hash、parser / adapter version、採用区間の更新で旧レビューを誤継承しない。
- `user_asserted` を構文エラーの救済や必須 Health gate の PASS に使わない。

## 4. 性能測定計画

実装版で測定する。モックの生成時間を製品性能として扱わない。
2026-09-13 の合意により、`0.2.0a13` の性能対象は **各時点 1 万 route まで**。
全入力の host / VRF / AF ごとの prefix 件数の合計とする。10 万 / 100 万 route は将来拡張に移し、
今回の公開条件には含めない。時間・メモリは測定値を示し、一律の保証値とはしない。

| 軸 | ケース |
|---|---|
| 規模 | 各時点 1 万 / 10 万 / 100 万 prefix。両側の合計や path 数と混同しない |
| AF / scope | IPv4 / IPv6、単一 / 複数 VRF、複数 host |
| path | 1 / 4 path、path 属性対応交換、順序だけ変更 |
| 差分率 | 0 / 1 / 100%。完全な raw 文字列順序変更も含む |
| 計測対象 | 入力解決・解析・比較・出力の各時間、最大 RSS、成果物 size、初回表示、検索・mode 切替・jump 応答 |
| 記録条件 | CPU / RAM / OS / Python / browser / commit、生成 seed、入力 hash、測定回数 |

合否の必須条件は件数式の一致、証跡欠落なし、UNKNOWN の維持、中断と保存の整合。
応答時間・メモリの数値 budget は最初の測定で提案し、受入環境とともに確定する。
HTML の表示だけ高速でも全成果物生成や全文比較が未完了なら、その tier の合格としない。

## 5. 初回リリースの受け入れ checklist

- [ ] 対象 model / release / command ごとの evidence と未対応ケースを記録した。
- [ ] 10.4(5)M、10.5(4)、10.6(4)M を重点対象として詳細 route fixture と parser 試験の結果を示した。
- [x] schema 構造だけでなく、IP / AF、重複、policy 競合、hash / source 範囲、件数の domain validation を実装した。
- [x] 端末整形前 raw を保存し、正規化 route / path から元行・元 bytes に遡れる。
- [ ] 既存の全合意ケースを production parser / comparator / evaluator で検証した。
- [x] CLI と Health が同じ input / policy に対して同じ差分・理由・判定を生成する。
- [x] HTML / JSON / CSV / Markdown の件数・理由・UNKNOWN が一致する。
- [x] 大規模表示とレビュー記録の保存・復元を、外部通信なしで確認した（1 万 prefix の代表ケース）。
- [x] 中断、生成失敗、再実行、旧成功と新失敗 attempt の共存を確認した。
- [x] 既存 baseline count、Overlay Type-5 / role consumer、transcript import の回帰がない。
- [ ] 最小 tier の性能と配布形態の動作を検証し、上位 tier の結果・制約を記載した。
- [x] 通常の pytest（device 除外）、Ruff、CLI help、schema / resource、wheel / 標準 glibc 2.17 binary の確認が通った。
- [x] manual、sample、設計書、実装状況、リリース向けの未検証事項が一致した。

現時点では上記の production 受け入れは未完了。機器接続や未加工ログの取り込みは本作業では実行しない。

## 6. P4 の実装・検証記録（2026-09-13）

- [renderer](../../alred/route_diff/report.py) が検証済み Snapshot / RouteDiff と元 bytes を受け取り、
  5 方式の Markdown、全体 JSON / CSV / Markdown / checklist、各ホストの単独 HTML を生成する。
- [共通テンプレート](../../alred/j2/route_diff.html.j2) は外部通信なしでページング、CIDR 検索、
  raw 仮想スクロール、文字列 diff の中止、元行への往復、レビュー JSON の保存・復元を提供する。
- [出力テスト](../../tests/test_route_diff_report.py) 24 件で件数、ECMP 対応、UNKNOWN、元 bytes、
  不正なレビュー、HTML / Markdown / CSV の escape、hash 不整合、部分出力と再実行を検証した。
- [ブラウザ試験](../../tests/test_route_diff_report_browser.py) 8 件がローカル Chromium で成功。
  601 prefix の 50 / 100 / 500 件表示、ページをまたぐ差分移動、全 1,205 行への到達と DOM 行数を確認。
  この試験は大規模性能の認定ではない。
- `pytest -m "not device"`: 1,080 passed、ブラウザ用 opt-in module 1 skipped。
  上記ブラウザ試験は別途有効化して実施した。Ruff、CLI help、文書リンク、`git diff --check` も成功。
- wheel を build・別 directory へ install し、template / Review schema / 完了 manifest の生成を確認。
  PyInstaller の検証用実行ファイルでも同じ API を確認した。正式な標準 glibc 2.17 binary のリリース試験は P7 に残る。
- [実出力例](../manual/network-ops/examples/route-diff-core/README.md)と
  [画像付きマニュアル](../manual/network-ops/13_ROUTE_DIFF_GUIDE.md)を更新した。

P5 で `route-diff-nxos` CLI へ入力解決・進捗・終了 code・保存 lifecycle を接続した。
Health 統合、release 別の詳細 route fixture、1 万 / 10 万 / 100 万 route の性能受け入れは継続課題。

## 7. P5 の実装・検証記録（2026-09-13）

[standalone CLI](../../alred/route_diff/cli.py) を top-level `route-diff-nxos` へ接続した。
2 file / Source Map、6 種の取得 command、AF / VRF の対象解決、policy、表示ラベル、レビュー復元を実装。
元 bytes / Snapshot / 解決済み入力を保持し、全 file の hash を検証した report だけを no-replace rename で公開する。
既存出力、symlink、入力の重複・hard link、公開競合、不正 manifest、中断を検証した。

- 全体回帰: `pytest -m "not device"` で 1,114 passed、opt-in browser module 1 skipped。
- その後追加した manifest 破損・symlink 拒否 3 ケースを含め、[CLI 試験](../../tests/test_route_diff_cli.py)は 37 件成功。
- ブラウザ試験は別途有効化して 9 件成功。CLI の時点ラベルとレビュー初期状態も確認した。
- Ruff、top-level / command help、文書リンク、`git diff --check` が成功。
- wheel の別 directory への install と、PyInstaller 検証用実行ファイルの新 command から、
  オフライン report を生成・公開できることを確認した。正式な glibc 2.17 リリース試験は P7 に残る。
- マニュアルの 2 file / 3 host Source Map の command を実行し、COMPLETE / 0 と PARTIAL / 3 を確認した。

## 8. P6 の実装証跡

[Health adapter](../../alred/health/route_diff.py) と追加 profile を既存 collector、profile resolver、
Health evaluator、phase / rollback の保存処理へ接続した。baseline と既存 Overlay consumer は維持する。
正式な field と判定条件は [設計 18](../design/network-ops/ROUTE_DIFF_DESIGN.md#18-health-統合契約p6)に記載した。

- [Health Route 試験](../../tests/test_health_route_diff.py) 31 件で collect の完了証跡、端末ログ、
  6 command 形式、VRF の大小文字、Cost、必須経路、予定変更、rollback、欠落・改変、
  before / after CLI と profile 継承、公開中断後の既存結果保持を検証した。
- 全体回帰は 1,146 passed、opt-in browser module 1 skipped。
- 最終の report error 境界と rollback の公開先を追加検証し、Health Route / 旧 rollback / 文書の
  関連試験 55 件が成功。最終表示 metadata の変更後も parser / renderer 等の 151 件が成功した。
- ブラウザ試験 10 件が成功。rollback の FAIL が表示 filter を変更しても残ることを確認した。
- wheel を構築し、別 directory へ offline install。配布 package の追加 profile / schema / adapter と
  `health-check snapshot` を合成 transcript で実行し PASS を確認した。正式 binary の release 試験とは区別する。
- Ruff、CLI help、文書リンク、`git diff --check` が成功。
- [マニュアル](../manual/network-ops/13_ROUTE_DIFF_GUIDE.md)に profile 設定、保存先、
  rollback の判定方法と、実 renderer を撮影した 5 枚目の画像を追加した。

P6 完了時点では、大規模入力の性能、標準 glibc 2.17 配布形式、機種・release 別の詳細 route fixture の
受け入れを P7 に残した。Web UI と実機への接続・設定投入は実行していない。

## 9. P7 の途中検証記録

[性能・配布検証記録](ROUTE_DIFF_PERFORMANCE_REPORT.md)に実行環境、入力 hash、件数、時間、RSS、
成果物 size、browser 操作と未完了ケースを記録した。

- deterministic な合成入力と独立した期待件数を使う Linux benchmark runner を追加した。
- 内容 hash が一致する場合だけ同一実行内の schema / domain 検証を再利用し、改変拒否を維持した。
- 1 万 route の 1 path / 1%、4 path / 0%、4 path / 100% は全出力・hash 検証・公開が成功。
  それぞれ Chromium で 3 回、初回表示・全文比較・検索・証跡移動・レビュー復元を確認した。
- 10 万 / 100 万 route は 180 秒上限で停止し、未公開。4 path / 100% は 240 秒では未完了だったが、
  600 秒上限で再測定して約 337 秒で完了した。上限は runner の保護値で、製品の保証値ではない。
- 全体回帰 1,158 passed、opt-in browser module 1 skipped。別途 browser 回帰 10 件が成功。
- source / 別 directory に install した wheel / glibc 2.17 環境の標準 binary に同じ smoke runner を適用し、
  version `0.2.0a12`、standalone と Health の 5 方式の件数、判定、全 report hash の一致を確認した。

P7 は partial を維持する。固定負荷での反復測定、未測定の組み合わせ、上位 tier の完走、
機種・release 別 fixture と対応上限の合意が必要。version 採番や Release 作成・公開は行っていない。

## 10. HTML の長い証跡の折りたたみ

取得状態の詳細、scope に属さない診断、Policy、Sources、versions / fingerprint は初期状態で閉じる。
UNKNOWN の対象時点と理由、入力数、Policy の判定別件数は見出しに残す。
詳細 JSON は初回展開時に描画し、長い場合は枠内をスクロールする。scope の診断の重複表示を解消した。
本番 renderer の [サンプル](../manual/network-ops/examples/route-diff-core/route_diff/index.html)と
[操作画像](../manual/network-ops/images/route-diff/06-collapsed-evidence.png)を更新した。
browser 試験 12 件で、初期状態、UNKNOWN から該当項目だけの展開、keyboard 操作、
証跡全文の保持、scope に属さない UNKNOWN、Policy の判定件数と既存操作を確認した。
wheel / glibc 2.17 binary から更新済み HTML を生成し、standalone / Health の smoke と
report hash を確認した。既存回帰は 1,159 件成功。全体試験で画像生成前に失敗した文書リンク 1 件は、
画像生成後の再試験で成功した。Ruff、CLI help、サンプル manifest の hash 照合も成功した。

## 11. 全体収集ログの修正（実装済み）

正本は [修正設計](../design/network-ops/ROUTE_DIFF_COLLECTION_LOG_FIX_DESIGN.md)、
重要判断は [ADR-0023](../adr/0023-preserve-route-forwarding-attributes-and-completion-evidence.md)（Accepted）。
利用者の元ログと既存 report は保持する。設計時の文書・モックを保持し、合意後に実装と試験を追加した。

| 順序 | 変更予定 | 完了条件 | 状態 |
|---|---|---|---|
| F1 | 共通 section adapter、管理行と command 終端、診断の影響範囲 | 統合 collect / plain の正常・失敗・重複・切断、元 byte / 行証跡を検証 | 実装済み |
| F2 | HMM / VXLAN の解析、path schema、5 方式・Policy / rollback の tuple | 属性を捨てずに保持し、同じ IP の別 segment と ECMP の対応を検証 | 実装済み |
| F3 | 取得完了に基づく正常空、schema / version / 旧成果物の拒否 | EOF・凡例不足は UNKNOWN、正当な空だけ 0 件。旧 before / review を誤継承しない | 実装済み |
| F4 | standalone の directory 探索と複数ホストの入力解決 | 入力来歴の正式 field / version を確定し、F19–F22 と既存 2 file / Source Map の互換を検証 | 実装済み |
| F5 | CLI / Health / HTML / manual、匿名化 fixture と元入力の別出力先での再検証 | 設計の F01–F22、全形式、browser、source / wheel / glibc 2.17、既存回帰を確認 | 実装済み |

レビュー用 [入力・期待値](../design/network-ops/examples/route-diff-input-fix/README.md)では、
正常時に 2 scope COMPLETE、segment_id 変更で NextHop 2 方式だけ MODIFIED とする。
切断例では IPv6 のみ UNKNOWN、全体 PARTIAL とする。設計時は固定期待値であり、実装後は回帰試験でも確認した。
修正後も未対応の別行 VTEP grammar、model / release fixture の不足、上位性能 tier を完了扱いにしない。

設計時の確認では、文書リンクと既存の設計例 contract 試験 16 件が成功した。
合成 before / after の変更箇所と切断位置、期待値 JSON と静的 HTML の全 5 方式の件数を照合した。
Chromium で証跡の初期折りたたみ・展開、入力へのリンク、外部通信がないことを確認し、画面も目視した。
これは文書と表示案の検証であり、修正 parser の受入試験ではない。

追加の表示案として、ログ全文比較の「対象 route command 区間のみ / 入力ログ全体」を設計した。
対象区間を既定とし、区間内の全文と元行番号を保持する。切替モックは設計レビュー用として保持し、合意後に本番 renderer へ実装した。
追加後も文書関連 16 件が成功。Chromium で範囲切替と両側の全表示行を合成入力に照合し、
対象区間の元行番号、全体表示での全行保持、証跡の初期折りたたみを確認した。

directory 入力の [合成例](../design/network-ops/examples/route-diff-input-fix/directory-case/README.md)を追加した。
3 ホストのうち 2 ホストを file 名によらず対応付け、片側欠落の 1 ホストを UNKNOWN とする期待値を記録。
文書関連 16 件と、合成ログ内のホスト・file 数・HTML 対応表の照合が成功した。
ここまでの確認は設計段階の記録。実装後の検証は次節へ記録する。

## 12. 全体収集ログ・directory 入力の修正受入結果

2026-09-13。F1–F5 を実装し、修正設計の F01–F22 を関連試験と下記の実行で確認した。
parser `1.2`、normalizer `1.1`、section adapter `1.0`、comparator / evaluator / renderer `1.1`、
Health adapter / profile `1.1`。旧 Snapshot は新しい raw 解析結果と混在させず、両側の再解析を案内する。

| 検証 | 結果 |
|---|---|
| 全体 pytest（device を除外） | 1,202 件成功、任意 browser suite 1 件 skip |
| Chromium の独立 browser suite | 15 件成功。表示範囲、検索、証跡往復、片側欠落、折りたたみ、外部通信なし |
| Health / 収集ログ / benchmark の追加回帰 | 87 件成功。全体試験後に追加した segment / tunnel の rollback 復元漏れ 2 ケースを含む |
| source / wheel / glibc 2.17 binary | 各 10 回の CLI 呼び出しが期待終了状態と一致。directory、収集ログ、Health 比較、全成果物 hash を確認 |
| 元入力の再解析 | 新しい出力先へ保存。12 scope COMPLETE、UNKNOWN 0、全 5 方式で追加 1・削除 0・変更 0・共通 113。元ログと既存 report は保持 |
| 元入力の最終 HTML | 差分のみ既定、対象区間 / 全体切替、証跡の初期折りたたみ、JavaScript error / 外部通信なし |
| 1 万 route の代表ケース | 1 path / 差分 1%、全形式・hash 検証込み 56.18 秒、最大 RSS 499.17 MiB。期待件数と一致 |
| 1 万 route と多数の非 route command | 4 source × 各 300 非 route command、66.14 秒、最大 RSS 520.07 MiB。section 検出は計 4 回、全 5 方式の件数は元ケースと一致 |
| 1 万 route の HTML | 初回表示 2.92 秒、入力全体への切替 230 ms、末尾スクロール 99 ms。検索・文字列 diff・レビュー保存と復元も成功 |
| 文書・画像・静的検査 | マニュアルの実画面 8 枚と 2 種類の本番出力例を更新。sample manifest、文書リンク、CLI help、Ruff、diff の空白を確認 |

集計・配布 artifact / source hash は [修正受入 JSON](route-diff-performance/2026-09-13-collection-fix.json)に記録する。
性能は共有環境での単回測定であり、保証値ではない。多数コマンドのケースは、代表ケースの route 本文を
alred collect envelope に包み、IPv4 の前・AF 間・IPv6 の後へ各 100 個の合成非 route block を加えた。
directory 入力で実行し、解析回数と全方式の件数を独立期待値に照合した。

[利用ガイド](../manual/network-ops/13_ROUTE_DIFF_GUIDE.md)と
[全体収集ログ・複数ホストの実出力](../manual/network-ops/examples/route-diff-collection/README.md)から操作を確認できる。
元入力の再解析結果から、すべての対象機種 / NX-OS release を VERIFIED とはしない。
別行 VTEP grammar、機種・release 別 fixture、10 万 / 100 万 route の完走と性能上限合意は残課題。

## 13. 0.2.0a13 のリリース準備

各時点 1 万 route までを対象とする Pre-release。リリースノートは
[0.2.0a13](../releases/0.2.0a13.md)を参照する。10 万 / 100 万 route は将来拡張として残す。
機種・release ごとの詳細 route fixture が不足する組み合わせは未検証と明記する。
旧成果物の両側再解析、レビュー記録の非互換、配布 OS、メモリ・容量の実測条件を案内する。
公開には対象差分のレビュー・main への統合と、確定 commit に基づく配布物の再確認が必要。

ローカルの `0.2.0a13` 候補で固定依存の全体試験 1,204 件（任意 browser suite 1 件 skip）、
独立 browser 試験 15 件、packaging / 文書 / contract 21 件、Ruff、CLI help、lock 整合が成功した。
source / wheel / glibc 2.17 の Route Diff・Health smoke、既存 inventory / license parser、同梱 sample 生成も成功。
配布候補は `dist/0.2.0a13/` に分離し、既存 asset は保持する。
合成入力と hash 対象の生成例は `.gitattributes` で改行変換を防止する。
