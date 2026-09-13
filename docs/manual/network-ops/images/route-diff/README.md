# Route Diff マニュアルの画面画像

2026-09-13 に [本番 renderer の HTML](../../examples/route-diff-core/route_diff/index.html)を
Chromium で実際に操作して撮影した画像。本番 parser・比較・renderer API が合成ログから生成した出力であり、実機検証や CLI 実行の証跡ではない。
[利用ガイド](../../13_ROUTE_DIFF_GUIDE.md#51-画像で確認する-cost-の変更を見つける)から参照する。

| 画像 | 操作状態 |
|---|---|
| [01-cost-diff.png](01-cost-diff.png) | leaf01／IPv4／Cost 込み比較／192.0.2.64/26／共通行 OFF |
| [02-common-ecmp.png](02-common-ecmp.png) | leaf01／IPv4／Prefix + AD + Cost + NextHop／198.51.100.128/25／共通行 ON |
| [03-full-log.png](03-full-log.png) | leaf01 の全文比較／経路基準で着色／[110/30] を検索 |
| [04-summary.png](04-summary.png) | 5 scope の方式別サマリーと UNKNOWN |
| [05-health-rollback.png](05-health-rollback.png) | Health の実 adapter / comparator / renderer で生成。Cost が復元されず Health Route が FAIL |
| [07-route-sections.png](07-route-sections.png) | 全体収集ログの対象区間表示、省略範囲、元行番号、VXLAN の変更 |
| [08-directory-hosts.png](08-directory-hosts.png) | 複数ホストの取得対応と after 欠落の UNKNOWN |
| [06-collapsed-evidence.png](06-collapsed-evidence.png) | 取得状態の要点を表示し、長い診断・Policy・Sources・比較条件を折りたたんだ初期状態 |

撮影時の viewport は 1440 × 1100、device scale factor は 1。
画面上の該当 panel／表を撮影し、画像の合成や表示値の差し替えは行っていない。
通常の利用では画像・HTML を開くだけでよい。以下はマニュアル保守用の手順。

開発環境に任意の Playwright Python package と Chromium がある場合、リポジトリのルートから実行する。

```bash
python docs/manual/network-ops/images/route-diff/capture_screenshots.py
```

script は 01–04 と 06–08 の 7 画像を更新する。生成画面の checkbox、検索結果、共通 path、UNKNOWN と証跡の折りたたみを確認し、
JavaScript error と外部通信がないことも検証する。画面画像には比較 API が計算した件数をそのまま使用する。

5 枚目は追加 Health profile の adapter で合成 collect 証跡を解析して撮影したもの。
rollback の収集や設定投入を実機で実施した証拠ではない。再生成は次の command で行う。

```bash
PYTHONPATH=. python docs/manual/network-ops/images/route-diff/capture_health_screenshot.py
```

一時 directory 内に合成 collect、詳細 Snapshot、rollback report を生成し、
表示された FAIL、Cost 20 / 30、判定根拠の展開を確認して撮影する。

07 / 08 は [全体収集ログの実出力](../../examples/route-diff-collection/route_diff/index.html)を撮影する。
`capture_screenshots.py` はこれらも更新する。
