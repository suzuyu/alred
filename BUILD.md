# BUILD.md

`alred` の配布 binary を作成し、GitHub Releases へ公開するための開発者向けメモです。

## 目的

GitHub Releases やエアギャップ環境向け配布用に、PyInstaller で単体実行 binary を生成します。

## 前提

- 開発用マシンで Python 3.11 以上が利用できること
- このリポジトリを checkout 済みであること
- `uv` が利用できること

## セットアップ

まず開発環境を用意します。

```sh
uv sync
```

PyInstaller が未導入の場合は、開発環境へ追加で導入します。

```sh
uv pip install pyinstaller
```

## build

単体 binary を `dist/` 配下へ出力する例です。

```sh
uv run pyinstaller \
  --onefile \
  --name alred \
  alred.py
```

生成物:

- Linux: `dist/alred`
- Windows: `dist/alred.exe`

補足:

- PyInstaller の中間生成物として `build/` や `*.spec` も作成されます
- これらは配布用成果物ではないため、通常は Git 管理しません
- `dist/` 配下は release asset の作業領域として扱う想定です

## 動作確認

最低限、生成した binary が起動することを確認します。

Linux 例:

```sh
./dist/alred --version
./dist/alred --help
```

必要に応じて、実際の配布先に近い OS / アーキテクチャ上でも動作確認してください。

## release 用ファイル名

GitHub Releases へそのまま載せやすいように、OS / アーキテクチャ入りのファイル名へ整形しておくと運用しやすくなります。

例:

- `alred-linux-x86_64`
- `alred-linux-aarch64`
- `alred-windows-x86_64.exe`

Linux x86_64 の例:

```sh
cp dist/alred dist/alred-linux-x86_64
```

Linux aarch64 の例:

```sh
cp dist/alred dist/alred-linux-aarch64
```

Windows x86_64 の例:

```sh
cp dist/alred.exe dist/alred-windows-x86_64.exe
```

## checksum

配布物とあわせて checksum を提示することを推奨します。

release 用ファイル名に合わせた例:

```sh
sha256sum dist/alred-linux-x86_64 > dist/alred-linux-x86_64.sha256
```

```sh
sha256sum dist/alred-linux-aarch64 > dist/alred-linux-aarch64.sha256
```

```sh
sha256sum dist/alred-windows-x86_64.exe > dist/alred-windows-x86_64.exe.sha256
```

生成される checksum ファイル名の例:

- `alred-linux-x86_64.sha256`
- `alred-linux-aarch64.sha256`
- `alred-windows-x86_64.exe.sha256`

## tag 名の付け方

GitHub Releases は Git tag と対応づけて管理する想定です。

例:

- `v0.1.0a1`
- `v0.1.0a2`
- `v0.1.0`

運用ルールの例:

- 先頭は `v` を付ける
- `major.minor.patch` 形式にする
- binary 配布を伴う公開単位ごとに tag を切る

tag 作成例:

```sh
git tag <tag>
git push origin <tag>
```

注釈付き tag を使う場合:

```sh
git tag -a <tag> -m "Release <tag>"
git push origin <tag>
```

## release note の書き方

release note には、利用者が見て判断しやすい内容を簡潔にまとめるのがおすすめです。

最低限あるとよい項目:

- この release で何ができるようになったか
- 破壊的変更の有無
- 配布 binary の対象 OS / アーキテクチャ
- checksum の有無
- 既知の制約や注意点

テンプレート例:

```md
## Summary

- containerlab 用の出力フローを改善
- `clab-set-cmds` を追加
- Mermaid underlay 出力を追加

## Artifacts

- `alred-linux-x86_64`
- `alred-linux-x86_64.sha256`
- `alred-linux-aarch64`
- `alred-linux-aarch64.sha256`

## Notes

- Linux binary は build 環境に依存します
- エアギャップ環境へ持ち込む場合は checksum をあわせて確認してください
```

短めの例:

```md
初回 binary 配布版です。

- Linux x86_64 / aarch64 向け binary を追加
- checksum を同梱
- `clab-set-cmds` を利用した基本フローを README に反映
```

## release 作業の流れ

GitHub Releases へ公開するまでの最小手順は次の通りです。

1. 対象 OS / アーキテクチャごとに build する
2. 生成した binary の動作を確認する
3. release 用のファイル名へ整形する
4. checksum を生成する
5. tag を作成して push する
6. GitHub Releases の新規 release を作成する
7. release note を記入する
8. binary と checksum を asset として添付する
9. 公開後にダウンロードと checksum 検証を確認する

Linux x86_64 向けの一連の例:

```sh
uv sync
uv pip install pyinstaller
uv run pyinstaller \
  --onefile \
  --name alred \
  alred.py
./dist/alred --version
./dist/alred --help
cp dist/alred dist/alred-linux-x86_64
sha256sum dist/alred-linux-x86_64 > dist/alred-linux-x86_64.sha256
git tag -a <tag> -m "Release <tag>"
git push origin <tag>
```

Releases に添付する最小構成の例:

- `dist/alred-linux-x86_64`
- `dist/alred-linux-x86_64.sha256`

## GitHub Releases 作成例

GitHub Web UI を使う場合の流れです。

1. GitHub の対象リポジトリを開く
2. `Releases` を開く
3. `Draft a new release` を選択する
4. 公開対象の tag を選ぶ、または新規 tag を作成する
5. Release title に `<tag>` のような名前を入力する
6. 本文に release note を記入する
7. `Attach binaries by dropping them here or selecting them` から asset を追加する
8. `Publish release` を実行する

入力イメージ:

```text
Tag: <tag>
Title: <tag>
Assets:
  - dist/alred-linux-x86_64
  - dist/alred-linux-x86_64.sha256
```

複数 OS / アーキテクチャ向けに build している場合は、それぞれの binary と checksum も同様に添付します。

## 補足

- PyInstaller binary は build した OS / アーキテクチャに依存します
- 配布対象ごとに適切な環境で build してください
- Linux では `glibc` 差異の影響を受ける場合があります
