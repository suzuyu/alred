# Route Diff 性能・配布検証記録

2026-09-13。P7 の途中結果。仕様は [設計 19 節](../design/network-ops/ROUTE_DIFF_DESIGN.md#19-性能受入の計測契約p7)、
受入条件は [実装計画](ROUTE_DIFF_IMPLEMENTATION_PLAN.md)を正本とする。
合成ログによる検証であり、NX-OS の機種・release 別の対応実証ではない。

## 1. 測定条件

- Linux x86_64、glibc 2.34、Intel Core Ultra 7 155H、20 logical CPU、RAM 約 89.8 GiB。
- source 実行は Python 3.11.15、jsonschema 4.26.0、PyYAML 6.0.3、netmiko 4.6.0、ntc-templates 9.0.0。
- before / after **それぞれ**の prefix 数を記載する。2 host × 2 VRF × IPv4 / IPv6 の計 8 scope に分配。
- seed は 17。after は route と ECMP の順序を逆転し、経過時間も変える。
  変更対象には Cost 変更、NextHop 変更、prefix の置換を分配する。全 5 方式の期待件数を別計算で照合する。
- source 実行、CLI 入力解決から全形式の生成・hash 検証・公開までを計測する。
  入力合成時間は含めない。worker の仮想 address space 上限は 3,072 MiB（改善前だけ 4,096 MiB）。
  これは測定 runner の制限であり、製品の既定上限ではない。
- 各 CLI ケースは 1 回。ブラウザは fresh context で各 3 回。別の試験・build が同時に動く共有環境の値であり、
  安定した性能保証値、CPU を専有した比較、native binary の性能値ではない。
- 未コミットの source を含むため、HEAD だけでなく source / runner / 入力の hash を記録する。
  個々の結果と環境は [測定 JSON](route-diff-performance/2026-09-13.json)を参照する。

## 2. CLI と成果物

| 各時点 prefix | path | 差分率 | 状態 / 時間上限 | wall 秒 | 最大 RSS MiB | 全成果物 MiB | index HTML MiB |
|---:|---:|---:|---|---:|---:|---:|---:|
| 10,000 | 1 | 1% | PASS / 240 秒 | 67.4 | 475.8 | 226.9 | 46.3 |
| 10,000 | 4 | 0% | PASS / 240 秒 | 175.1 | 985.9 | 549.1 | 110.1 |
| 10,000 | 4 | 100% | TIMEOUT / 240 秒 | 240.3 | 1152.2 | 未公開 | — |
| 10,000 | 4 | 100% | PASS / 600 秒 | 336.5 | 2209.3 | 940.2 | 129.5 |
| 100,000 | 1 | 1% | TIMEOUT / 180 秒 | 180.3 | 1597.2 | 未公開 | — |
| 1,000,000 | 1 | 1% | TIMEOUT / 180 秒 | 180.5 | 2300.4 | 未公開 | — |

TIMEOUT は runner が worker を強制終了した結果。該当ケースでは公開先に完成レポートを作らず、
途中の evidence / stage / lock を保持した。製品の協調中断（SIGINT / 終了 code 130）とは区別する。
10 万 route は解析中、100 万 route は端末ログの正規化中に上限へ到達した。
この結果から両 tier を対応済みと判断しない。最小 tier も未測定の軸・組み合わせがあり、全面合格とはしない。

初回計測で同じ Snapshot の schema 検証の繰り返しが主な負荷と分かった。
`ProcessingControl` 内で検証済み文書の内容 hash を最大 8 件まで保持する改善を実装した。
毎回全内容を hash 化し、宣言された ID や fingerprint の一致だけでは再利用しない。
不正な schema、改変、JSON では同じ表現になる tuple などは従来どおり検証・拒否する。
改善前の 1 万 route・1 path・1% は約 104 秒、この節の測定時点のコードは約 67 秒だった。
実行時の負荷が異なるため、この比率を保証値として扱わない。

## 3. ブラウザ

Chromium 151.0.7922.34、headless、1440 × 1100。`file://` で production HTML を開き、
差分のみ既定、mode 切替、共通行表示、prefix 検索、元行への移動、全文検索、
最終行へのスクロール、文字列 diff 完了、レビュー JSON の保存・復元を測定する。
正規化 route の DOM は 100 件以下、raw の片側 DOM は 250 行未満であることを確認した。
JavaScript error / 外部 request がなく、各操作後も比較件数が変わらないことを検証する。

| 1 万 prefix のケース | 初回表示 秒（最小–最大） | mode 切替 ms 中央値 | prefix 検索 ms 中央値 | 元行へ移動 ms 中央値 | 文字列 diff ms 中央値 |
|---|---:|---:|---:|---:|---:|
| 1 path / 1% | 2.96–3.83 | 213 | 140 | 386 | 191 |
| 4 path / 0% | 6.45–6.66 | 99 | 137 | 333 | 303 |
| 4 path / 100% | 5.57–6.55 | 179 | 177 | 241 | 264 |

初回表示は page load と描画待ちを含む。各操作は Playwright の待ち時間を含み、
利用者の体感や JavaScript 関数単体の処理時間と同一ではない。
JSON の JS heap 値は CDP による計測であり、ブラウザ全体の RSS ではない。
独立した browser 回帰試験は 10 件成功した。
さらに 1% / 100% の 2 ケースで、保存後にチェックを解除してからレビュー JSON を読み込み、
チェックが復元されることを各 3 回確認した。追加試験は測定 JSON の `review_restore_checks` に保存した。

## 4. 配布形式と回帰

同じ [smoke runner](../../scripts/smoke_route_diff.py) を source、別 directory に offline install した wheel、
repository の `alred.spec` から作った Linux x86_64 glibc 2.17 binary に適用する。
合成 transcript から standalone / Health の before / after を比較し、5 方式の件数、profile / schema / template、
WARN 判定、全成果物 hash を確認する。詳細は測定 JSON に記録する。

binary は既存 image の Python 3.11.11 / PyInstaller 6.21.0 で network 無効、source 読み取り専用で build し、
glibc 2.17 の同じ image 内で実行する。実行者記録のため `USER` / `LOGNAME` を設定する。
初回は UID 1000 の passwd entry とユーザー名がなく Health の実行者記録で停止したため、
この環境設定を追加して新規出力先で再試験した。元の失敗証跡は保持した。
この節の検証時点の製品 version は `0.2.0a12`。検証 binary の作成は tag / Release / 公開の実施を意味しない。

全体回帰は `pytest -m "not device"` で **1,158 passed、1 skipped**。
skip は別途実行した opt-in browser module。改変拒否、期待件数、強制終了後の非公開を含む
[新規試験](../../tests/test_route_diff_benchmark.py)を追加した。その後、測定上限に `nan` / `inf` を拒否する
2 ケースを加え、最終の runner 関連 12 件が成功した。
Ruff、top-level / Route Diff / runner の help、文書リンクと contract 例の 16 件、`git diff --check` も成功した。

## 5. 再現手順

CLI benchmark は `/proc` と `resource.RLIMIT_AS` を使用する Linux 専用の開発用 script。
通常のテストには大規模ケースを含めず、小さい入力による正確性と上限処理を含める。
各出力先は未作成の directory / file を使う。既存測定結果を上書きしない。

```bash
uv run --frozen python scripts/benchmark_route_diff.py \
  --output /tmp/route-bench-single --routes 10000 --reverse-after \
  --timeout-seconds 240 --memory-mib 3072
uv run --frozen python scripts/benchmark_route_diff.py \
  --output /tmp/route-bench-ecmp --routes 10000 --paths 4 --diff-percent 100 \
  --reverse-after --timeout-seconds 600 --memory-mib 3072
uv run --frozen python scripts/benchmark_route_diff.py \
  --output /tmp/route-bench-large --routes 100000 1000000 --reverse-after \
  --timeout-seconds 180 --memory-mib 3072
```

root の `environment.json` / `results.json`、各 case の入力 hash / 独立した期待件数を持つ `case.json`、
`result.json`、`progress.jsonl`、stdout / stderr、完成 report または partial stage を保持する。
`api_inclusive_seconds` の renderer 時間には内部の再比較・検証を含む。各 API 区間の合計は
wall time と一致せず、親での上限監視・起動等も別に含まれる。最大 RSS は worker 単体である。

ブラウザ用は optional な Playwright とローカル Chromium を準備した環境で実行する。
runtime dependency には追加しない。以下は上の単一 path ケースを使う例。

```bash
python scripts/benchmark_route_diff_browser.py \
  --report /tmp/route-bench-single/routes-10000-paths-1-diff-1/route_diff \
  --output /tmp/route-browser-single.json --repeats 3
python scripts/smoke_route_diff.py \
  --command python alred.py --output /tmp/route-package-source
```

ブラウザ runner は HTML の manifest hash を照合する。測定 JSON とレビュー保存の JSON を残す。
生成ログ・全 report・binary は repository に追加せず、要約と hash だけを本書から参照する。

## 6. 統合収集ログ修正後の追加測定

parser `1.2` / renderer `1.1` で 1 万 route・1 path・1% を再測定し、56.18 秒、最大 RSS 499.17 MiB で成功した。
同じ route 本文を collect envelope に包み、4 source に各 300 非 route command を加えた directory 比較は
66.14 秒、最大 RSS 520.07 MiB。section 検出は各 source 1 回で、全 5 方式の件数は元ケースと一致した。
HTML の単回確認は初回表示 2.92 秒、入力全体への切替 230 ms、末尾移動 99 ms。
実行負荷と入力形式が異なるため、以前の値との比率を性能保証や改善率として扱わない。

source / wheel / glibc 2.17 binary の全体収集ログ・directory・Health smoke も再実行した。
詳細は [修正受入記録](ROUTE_DIFF_IMPLEMENTATION_PLAN.md#12-全体収集ログdirectory-入力の修正受入結果)と
[測定 JSON](route-diff-performance/2026-09-13-collection-fix.json)を参照する。

## 7. 残る受け入れ

2026-09-13 合意: `0.2.0a13` の性能対象は各時点 1 万 route まで。
10 万 / 100 万 route の完走は将来拡張であり、今回の公開条件から除外する。
以下の過去の未完了記録は保持し、未検証範囲を対応済みとはしない。

- README 対象機種と 10.4(5)M / 10.5(4) / 10.6(4)M の詳細 route fixture の収集・匿名化・検証。
- 専有または負荷条件を固定した環境での反復計測、未測定ケース、最大許容時間・メモリの合意。
- 10 万 / 100 万 route の端末正規化・解析の負荷を調べ、全出力生成まで完了させた後のブラウザ検証。
- 単独 HTML のデータ重複と、全変更時の大きい RouteDiff / schema 検証のコストの改善余地。

上位 tier や全機種対応を完了扱いにせず、P7 は partial を維持する。Web UI は今回の対象外。
