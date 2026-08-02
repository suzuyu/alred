# BUILD.md

`alred` の配布 binary を作成し、GitHub Releases へ公開するための開発者向けメモです。

## 目的

GitHub Releases やエアギャップ環境向け配布用に、PyInstaller で単体実行 binary を生成します。

## 前提

- 開発用マシンで Python 3.11 が利用できること
- このリポジトリを checkout 済みであること
- `uv` が利用できること

## セットアップ

通常の開発環境とbinary build用依存を、`uv.lock`から用意します。

```sh
uv sync --frozen --group dev --group build --python 3.11
```

PyInstallerは`build` dependency groupで固定する。個別の`uv pip install`は行わない。
依存を更新した場合は、Docker buildでも使用する固定requirementsを再生成する。

```sh
uv export \
  --frozen \
  --no-default-groups \
  --group build \
  --no-emit-project \
  --no-hashes \
  --output-file packaging/linux/requirements-build.lock
```

## build

単体 binary を `dist/` 配下へ出力する例です。

```sh
uv run --python 3.11 --group build --frozen pyinstaller \
  --clean \
  --noconfirm \
  alred.spec
```

生成物:

- Linux: `dist/alred`
- Windows: `dist/alred.exe`

補足:

- PyInstaller の中間生成物として `build/` や `*.spec` も作成されます
- これらは配布用成果物ではないため、通常は Git 管理しません
- `dist/` 配下は release asset の作業領域として扱う想定です
- `sample_configs/` や `j2/` などの package data は `alred.spec` で bundle しています
- SSH 収集で使う `netmiko` は dynamic import を含むため、`alred.spec` で `collect_submodules("netmiko")` を指定しています
- 直接コマンドライン引数で build する場合も、少なくとも `--collect-submodules netmiko` が必要です
- Linux Docker buildは`packaging/linux/requirements-build.lock`を共用し、runtime依存とPyInstallerのversionを`uv.lock`と一致させます

## Docker build for glibc variants

Linux binary を配布先の `glibc` に合わせて build したい場合は、対応する container で build します。

標準Releaseでは、互換範囲が最も広いglibc 2.17だけをbuildする。glibc 2.28／2.34の
Dockerfileとscriptは、配布先を限定したbinaryが必要な場合の明示オプションとして維持する。

このリポジトリでは次の3系統を用意している。

- `packaging/linux/Dockerfile.glibc217`: `quay.io/pypa/manylinux2014_x86_64`
- `packaging/linux/Dockerfile.glibc228`: `quay.io/pypa/manylinux_2_28_x86_64`
- `packaging/linux/Dockerfile.glibc234`: `quay.io/pypa/manylinux_2_34_x86_64`

共通 build script は次を実施します。

- 対応する `packaging/linux/Dockerfile.glibcXXX` から build image を作成
- image build 中に OpenSSL を build
- image build 中に shared library 付き Python 3.11 を作成
- container 内で `PyInstaller` により `alred.spec` を build
- 生成物をホスト側の `dist/` と `build/` に書き戻す
- 既存の `dist/alred-linux-x86_64-glibc217` など release 用 artifact は削除せず、`dist/alred` だけを更新する

各variantを個別にbuildする例:

```sh
./scripts/build_binary_glibc217.sh
./scripts/build_binary_glibc228.sh
./scripts/build_binary_glibc234.sh
```

共通 script を直接使う例:

```sh
./scripts/build_binary_glibc.sh glibc228
./scripts/build_binary_glibc.sh glibc234
```

script を使わずに直接実行する例:

```sh
docker build -f packaging/linux/Dockerfile.glibc228 -t alred-build-glibc228 .
docker run --rm \
  -v "$PWD:/work" \
  -w /work \
  alred-build-glibc228 \
  /bin/bash -lc '/opt/python-shared/cp311/bin/python3.11 -m PyInstaller --clean --noconfirm alred.spec'
```

配布前の確認例:

```sh
./dist/alred --version
ldd --version
```

補足:

- Linux binary は build 時の `glibc` 互換に影響されます
- CentOS / RHEL 8 などへ持ち込む用途では、この Docker build を推奨します
- さらに古い Linux を対象にする場合は、その対象に合わせて build 基盤を見直してください
- 初回 build では Python 本体の compile が入るため少し時間がかかります

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
- `alred-linux-x86_64-glibc217`
- `alred-linux-x86_64-glibc228`
- `alred-linux-x86_64-glibc234`
- `alred-linux-aarch64`
- `alred-windows-x86_64.exe`

Linux x86_64 の例:

```sh
cp dist/alred dist/alred-linux-x86_64
```

`glibc 2.17` build を区別したい場合の例:

```sh
cp dist/alred dist/alred-linux-x86_64-glibc217
```

`glibc 2.28` / `glibc 2.34` build を区別したい場合の例:

```sh
cp dist/alred dist/alred-linux-x86_64-glibc228
cp dist/alred dist/alred-linux-x86_64-glibc234
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
(cd dist && sha256sum alred-linux-x86_64 > alred-linux-x86_64.sha256)
```

```sh
(cd dist && sha256sum alred-linux-aarch64 > alred-linux-aarch64.sha256)
```

```sh
(cd dist && sha256sum alred-windows-x86_64.exe > alred-windows-x86_64.exe.sha256)
```

生成される checksum ファイル名の例:

- `alred-linux-x86_64.sha256`
- `alred-linux-x86_64-glibc217.sha256`
- `alred-linux-x86_64-glibc228.sha256`
- `alred-linux-x86_64-glibc234.sha256`
- `alred-linux-aarch64.sha256`
- `alred-windows-x86_64.exe.sha256`

## release artifact helper

`dist/alred` から release 用ファイル名と checksum をまとめて用意する helper script です。

標準Release用のglibc 2.17 binaryをbuildし、smoke test、release asset、checksumを作成する。

```sh
./scripts/build_release_artifacts_linux_x86_64.sh
```

glibc 2.28／2.34または全variantは明示指定する。

```sh
./scripts/build_release_artifacts_linux_x86_64.sh --variant glibc228
./scripts/build_release_artifacts_linux_x86_64.sh --variant glibc234
./scripts/build_release_artifacts_linux_x86_64.sh --all-variants
```

標準の `glibc 2.17` Linux x86_64 artifact を作る例:

```sh
./scripts/prepare_release_artifacts.sh
```

生成物:

- `dist/alred-linux-x86_64-glibc217`
- `dist/alred-linux-x86_64-glibc217.sha256`

`glibc 2.28` / `glibc 2.34` artifact を作る例:

```sh
./scripts/prepare_release_artifacts.sh dist/alred alred-linux-x86_64-glibc228
./scripts/prepare_release_artifacts.sh dist/alred alred-linux-x86_64-glibc234
```

入力 binary や出力名を明示する例:

```sh
./scripts/prepare_release_artifacts.sh dist/alred alred-linux-x86_64
```

## tag 名の付け方

GitHub Releases は Git tag と対応づけて管理する想定です。

例:

- `0.2.0a1`
- `0.2.0rc1`
- `0.2.0`

運用ルールの例:

- `pyproject.toml`のPEP 440 versionと完全一致させ、先頭に`v`を付けない
- alpha、beta、release candidateは`a`、`b`、`rc`で表す
- binary 配布を伴う公開単位ごとに tag を切る
- `a`、`b`、`rc`を含むGitHub ReleaseはPre-releaseにする

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

1. 標準のglibc 2.17 binaryをbuildする。追加variantは必要な場合だけ明示指定する
2. 生成した binary の動作を確認する
3. release 用のファイル名へ整形する
4. checksum を生成する
5. tag を作成して push する
6. GitHub Releases の新規 release を作成する
7. release note を記入する
8. binary と checksum を asset として添付する
9. 公開後にダウンロードと checksum 検証を確認する

Linux x86_64向けの標準Release例:

```sh
./scripts/build_release_artifacts_linux_x86_64.sh
./dist/alred --version
./dist/alred --help
(cd dist && sha256sum --check alred-linux-x86_64-glibc217.sha256)
git tag -a <tag> -m "Release <tag>"
git push origin <tag>
```

Releasesに添付する標準構成:

- `dist/alred-linux-x86_64-glibc217`
- `dist/alred-linux-x86_64-glibc217.sha256`

glibc 2.28／2.34は`--variant`または`--all-variants`を指定したReleaseだけに添付する。

## GitHub Releases 作成例

AgentまたはCLIで作成する場合は、tag push後にDraft Releaseを作成し、binaryとchecksumを
同時にアップロードする。`<version>`は`pyproject.toml`と一致させる。

```sh
gh release create <version> \
  --verify-tag \
  --draft \
  --title "<version>" \
  --notes-file <release-notes.md> \
  dist/alred-linux-x86_64-glibc217 \
  dist/alred-linux-x86_64-glibc217.sha256
```

alpha、beta、release candidateでは`--prerelease`も指定する。Draftの内容、asset、checksumを
確認し、人が明示的に承認した後だけ公開する。

```sh
gh release edit <version> --draft=false
```

既存Draftへassetを追加する場合は、既存asset名を確認してから`gh release upload`を使用する。

```sh
gh release view <version> --json assets,isDraft
gh release upload <version> \
  dist/alred-linux-x86_64-glibc217 \
  dist/alred-linux-x86_64-glibc217.sha256
```

### Web UIを使用する場合

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
  - dist/alred-linux-x86_64-glibc217
  - dist/alred-linux-x86_64-glibc217.sha256
```

複数 OS / アーキテクチャ向けに build している場合は、それぞれの binary と checksum も同様に添付します。

## 補足

- PyInstaller binary は build した OS / アーキテクチャに依存します
- 配布対象ごとに適切な環境で build してください
- Linux では `glibc` 差異の影響を受ける場合があります
- より古い環境まで含めて広く配布したい場合は `packaging/linux/Dockerfile.glibc217` を優先し、対象を限定して最適化したい場合は `glibc228` / `glibc234` を使い分けてください
